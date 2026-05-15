import asyncio
from datetime import datetime, timedelta
from typing import Any

from config import DEVICE_ID
from services.device_registry import (
    active_devices,
    device_id_from_host,
    ensure_active_devices,
    ensure_device_active,
    host_for_device,
    refresh_active_devices,
)
from services.esp_client import build_endpoints, fetch_json, fetch_readings_since, sync_time_if_needed
from shared.formatters import row_from_payload
from storage.measurements_store import get_latest_measurement, latest_source_id, save_measurement

_sync_locks: dict[str, asyncio.Lock] = {}


def _lock_for(device_id: str) -> asyncio.Lock:
    if device_id not in _sync_locks:
        _sync_locks[device_id] = asyncio.Lock()
    return _sync_locks[device_id]


def _iso_local(dt: datetime) -> str:
    """Devuelve fecha/hora local del servidor, sin marcarla como UTC."""
    return dt.astimezone().replace(tzinfo=None).isoformat(timespec='seconds')


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
    return bool(value)


def _enrich_time_metadata(item: dict[str, Any], current_uptime_s: Any, server_now: datetime, current_boot_id: Any = None) -> None:
    parsed_time_valid = _bool_or_none(item.get('time_valid'))
    time_valid = bool(parsed_time_valid) or (parsed_time_valid is None and bool(item.get('timestamp')))
    item['time_valid'] = time_valid
    item['time_source'] = 'esp' if time_valid else 'estimated'

    if time_valid and item.get('timestamp'):
        return

    same_boot = str(item.get('boot_id') or '') == str(current_boot_id or '') if current_boot_id is not None else True
    if not same_boot:
        return

    try:
        current_uptime = float(current_uptime_s)
        measurement_uptime = float(item.get('uptime_s'))
    except (TypeError, ValueError):
        return

    elapsed_since_measurement = max(0.0, current_uptime - measurement_uptime)
    estimated = server_now - timedelta(seconds=elapsed_since_measurement)
    if estimated > server_now:
        estimated = server_now
    item['timestamp'] = _iso_local(estimated)


def display_host(host: str) -> str:
    clean = (host or DEVICE_ID).strip()
    if clean.endswith('.local'):
        clean = clean[:-6]
    return clean or DEVICE_ID


async def sync_sensor_measurements(device_id: str | None = None) -> dict[str, Any] | None:
    """Sincroniza un EcoSensor concreto y devuelve su última medición conocida."""
    active = await ensure_device_active(device_id)
    if not active:
        target_id = (device_id or DEVICE_ID).strip().lower() or DEVICE_ID
        return await asyncio.to_thread(get_latest_measurement, target_id)

    selected_device_id = str(active['device_id'])
    host_now = str(active['host'])

    async with _lock_for(selected_device_id):
        # La sincronización de hora es útil, pero no debe bloquear la lectura de
        # mediciones: el ESP32 puede estar activo y con datos aunque /time falle.
        connection = await sync_time_if_needed(host_now, timeout=2.0)
        if connection.get('ok'):
            host_now = str(connection.get('host') or host_now)

        endpoints_now = build_endpoints(host_now)
        row = None

        if endpoints_now['lecturas']:
            last_id = await asyncio.to_thread(latest_source_id, selected_device_id)
            missing = await fetch_readings_since(host_now, last_id, timeout=5.0)
            missing_data = missing.get('data') if missing.get('ok') else None
            if isinstance(missing_data, dict) and isinstance(missing_data.get('rows'), list):
                server_now = datetime.now().astimezone()
                current_uptime_s = missing_data.get('current_uptime_s')
                current_boot_id = missing_data.get('boot_id')
                last_estimated: datetime | None = None
                for item in missing_data['rows']:
                    if isinstance(item, dict):
                        source_id = item.get('measurement_id') or item.get('id')
                        item['device_id'] = selected_device_id
                        item['id'] = selected_device_id
                        item['measurement_id'] = source_id
                        _enrich_time_metadata(item, current_uptime_s, server_now, current_boot_id)
                        if not item.get('timestamp'):
                            window_s = item.get('window_s') or 300
                            try:
                                step = max(1, int(window_s))
                            except (TypeError, ValueError):
                                step = 300
                            if last_estimated is None:
                                last_estimated = server_now - timedelta(seconds=step * max(1, len(missing_data['rows'])))
                            else:
                                last_estimated = last_estimated + timedelta(seconds=step)
                            if last_estimated > server_now:
                                last_estimated = server_now
                            item['timestamp'] = _iso_local(last_estimated)
                            item['time_source'] = 'estimated_sequence'
                        await asyncio.to_thread(save_measurement, host_now, item)

            lecturas = await fetch_json(endpoints_now['lecturas'], timeout=4.0)
            data = lecturas.get('data') if lecturas.get('ok') else None
            if isinstance(data, dict) and data.get('valid'):
                row = row_from_payload(data)
                if row:
                    row['device_id'] = selected_device_id
                    row['id'] = selected_device_id
                    _enrich_time_metadata(row, data.get('current_uptime_s'), datetime.now().astimezone(), data.get('boot_id'))
                    await asyncio.to_thread(save_measurement, host_now, row)

        if not row:
            row = await asyncio.to_thread(get_latest_measurement, selected_device_id)

        return row


async def sync_latest_measurements(device_id: str | None = None) -> dict[str, Any] | None:
    """Compatibilidad: sincroniza el sensor seleccionado o el primer activo."""
    if device_id:
        return await sync_sensor_measurements(device_id)
    devices = await ensure_active_devices()
    selected = devices[0]['device_id'] if devices else DEVICE_ID
    return await sync_sensor_measurements(selected)


async def sync_all_active_measurements() -> list[dict[str, Any] | None]:
    """Sincroniza todos los EcoSensor activos sin depender de que haya UI abierta."""
    await refresh_active_devices()
    devices = active_devices()
    if not devices:
        return []
    return await asyncio.gather(
        *(sync_sensor_measurements(str(item['device_id'])) for item in devices),
        return_exceptions=False,
    )


async def background_sync_loop(interval_seconds: float = 60.0) -> None:
    while True:
        try:
            await sync_all_active_measurements()
        except Exception:
            # El loop debe sobrevivir caídas puntuales de red/ESP32.
            pass
        await asyncio.sleep(interval_seconds)


def host_for_selected_device(device_id: str | None) -> str:
    return host_for_device(device_id or DEVICE_ID)
