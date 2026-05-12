import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.esp_client import autoconnect_and_sync, build_endpoints, fetch_json, fetch_readings_since
from shared.formatters import row_from_payload
from storage.measurements_store import get_latest_measurement, latest_source_id, save_measurement
from storage.settings_store import load_settings, save_settings


def _iso_local(dt: datetime) -> str:
    """Devuelve fecha/hora local del servidor, sin marcarla como UTC.

    El ESP32 recibe hora local desde este servidor; para que gráficas y CSV no muestren
    horas adelantadas, los timestamps estimados también se guardan en hora local.
    """
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


async def sync_latest_measurements() -> dict[str, Any] | None:
    """Sincroniza silenciosamente el ESP32 con SQLite y devuelve la última medición conocida."""
    settings_now = load_settings()
    saved_host = settings_now.get('esp_host', DEFAULT_ESP_HOST)
    connection = await autoconnect_and_sync(saved_host, DEFAULT_ESP_HOST)
    host_now = connection.get('host') if connection.get('ok') else saved_host

    if connection.get('ok') and host_now != settings_now.get('esp_host'):
        settings_now['esp_host'] = host_now
        save_settings(settings_now)

    endpoints_now = build_endpoints(host_now)
    row = None

    if connection.get('ok') and endpoints_now['lecturas']:
        last_id = await asyncio.to_thread(latest_source_id, display_host(host_now))
        missing = await fetch_readings_since(host_now, last_id)
        missing_data = missing.get('data') if missing.get('ok') else None
        if isinstance(missing_data, dict) and isinstance(missing_data.get('rows'), list):
            server_now = datetime.now().astimezone()
            current_uptime_s = missing_data.get('current_uptime_s')
            current_boot_id = missing_data.get('boot_id')
            last_estimated: datetime | None = None
            for item in missing_data['rows']:
                if isinstance(item, dict):
                    source_id = item.get('measurement_id') or item.get('id')
                    item['device_id'] = item.get('device_id') or display_host(host_now)
                    item['id'] = item.get('device_id')
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

        lecturas = await fetch_json(endpoints_now['lecturas'])
        data = lecturas.get('data') if lecturas.get('ok') else None
        if isinstance(data, dict) and data.get('valid'):
            row = row_from_payload(data)
            if row:
                _enrich_time_metadata(row, data.get('current_uptime_s'), datetime.now().astimezone(), data.get('boot_id'))
                await asyncio.to_thread(save_measurement, host_now, row)

    if not row:
        row = await asyncio.to_thread(get_latest_measurement)

    return row
