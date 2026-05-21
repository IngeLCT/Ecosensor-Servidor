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
from services.esp_client import build_endpoints, fetch_json, fetch_readings_since, fetch_recent_readings, sync_time_if_needed
from services.sensor_diagnostics import log_co2_diagnostics_if_needed, log_temp_humidity_sources_if_needed
from services.sync_debug import record_sync_event, summarize_response, sync_debug_snapshot
from shared.formatters import row_from_payload
from storage.measurements_store import get_latest_measurement, latest_source_id, measurement_debug_summary, save_measurement

_sync_locks: dict[str, asyncio.Lock] = {}
SYNC_CHUNK_SIZE = 25
SYNC_MAX_BATCHES_PER_CYCLE = 40


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


async def _save_remote_rows(
    host: str,
    device_id: str,
    rows: list[Any],
    current_uptime_s: Any,
    current_boot_id: Any,
) -> tuple[int, int, int]:
    """Guarda filas remotas y devuelve (insertadas, min_source_id, max_source_id)."""
    inserted_count = 0
    min_seen_source_id = 0
    max_seen_source_id = 0
    server_now = datetime.now().astimezone()
    last_estimated: datetime | None = None

    for item in rows:
        if not isinstance(item, dict):
            continue
        source_id = item.get('measurement_id') or item.get('id')
        try:
            source_id_int = int(source_id or 0)
        except (TypeError, ValueError):
            source_id_int = 0
        if source_id_int > 0:
            min_seen_source_id = source_id_int if min_seen_source_id == 0 else min(min_seen_source_id, source_id_int)
            max_seen_source_id = max(max_seen_source_id, source_id_int)

        item['device_id'] = device_id
        item['id'] = device_id
        item['measurement_id'] = source_id
        _enrich_time_metadata(item, current_uptime_s, server_now, current_boot_id)
        if not item.get('timestamp'):
            window_s = item.get('window_s') or 300
            try:
                step = max(1, int(window_s))
            except (TypeError, ValueError):
                step = 300
            if last_estimated is None:
                last_estimated = server_now - timedelta(seconds=step * max(1, len(rows)))
            else:
                last_estimated = last_estimated + timedelta(seconds=step)
            if last_estimated > server_now:
                last_estimated = server_now
            item['timestamp'] = _iso_local(last_estimated)
            item['time_source'] = 'estimated_sequence'
        if await asyncio.to_thread(save_measurement, host, item):
            inserted_count += 1

    return inserted_count, min_seen_source_id, max_seen_source_id


async def sync_sensor_measurements(device_id: str | None = None) -> dict[str, Any] | None:
    """Sincroniza un EcoSensor concreto y devuelve su última medición conocida."""
    active = await ensure_device_active(device_id)
    if not active:
        target_id = (device_id or DEVICE_ID).strip().lower() or DEVICE_ID
        record_sync_event(target_id, 'inactive', reason='no_active_device')
        return await asyncio.to_thread(get_latest_measurement, target_id)

    selected_device_id = str(active['device_id'])
    host_now = str(active['host'])

    async with _lock_for(selected_device_id):
        record_sync_event(
            selected_device_id,
            'start',
            host=host_now,
            last_seen=active.get('last_seen'),
            status_time_valid=(active.get('status') or {}).get('time_valid'),
            status_needs_time_sync=(active.get('status') or {}).get('needs_time_sync'),
        )

        # La sincronización de hora es útil, pero no debe bloquear la lectura de
        # mediciones: el ESP32 puede estar activo y con datos aunque /time falle.
        connection = await sync_time_if_needed(host_now, timeout=2.0)
        record_sync_event(
            selected_device_id,
            'time_sync',
            host=host_now,
            ok=bool(connection.get('ok')),
            synced=bool(connection.get('synced')),
            status=summarize_response(connection.get('status')),
            sync=summarize_response(connection.get('sync')) if connection.get('sync') else None,
        )
        if connection.get('ok'):
            host_now = str(connection.get('host') or host_now)

        endpoints_now = build_endpoints(host_now)
        row = None

        if endpoints_now['lecturas']:
            total_inserted = 0
            total_received = 0
            batches = 0
            completed_history_sync = False
            local_floor_id = await asyncio.to_thread(latest_source_id, selected_device_id)

            # Prioridad 1: pedir primero la última medición. Esto mantiene el
            # dashboard y las gráficas de tiempo real frescas aunque falte
            # rellenar histórico de SD.
            lecturas = await fetch_json(endpoints_now['lecturas'], timeout=3.0)
            data = lecturas.get('data') if lecturas.get('ok') else None
            latest_inserted = False
            latest_remote_id = 0
            if isinstance(data, dict) and data.get('valid'):
                row = row_from_payload(data)
                if row:
                    row['device_id'] = selected_device_id
                    row['id'] = selected_device_id
                    _enrich_time_metadata(row, data.get('current_uptime_s'), datetime.now().astimezone(), data.get('boot_id'))
                    try:
                        latest_remote_id = int(row.get('measurement_id') or 0)
                    except (TypeError, ValueError):
                        latest_remote_id = 0
                    latest_inserted = await asyncio.to_thread(save_measurement, host_now, row)
                    log_temp_humidity_sources_if_needed(selected_device_id, data)
            latest_valid = bool(isinstance(data, dict) and data.get('valid'))
            record_sync_event(
                selected_device_id,
                'fetch_latest',
                host=host_now,
                ok=bool(lecturas.get('ok')),
                valid=latest_valid,
                inserted=latest_inserted,
                local_floor_id=local_floor_id,
                latest_remote_id=latest_remote_id,
                response=summarize_response(lecturas),
            )

            latest_co2 = None
            if isinstance(data, dict):
                try:
                    latest_co2 = int(data.get('co2') or 0)
                except (TypeError, ValueError):
                    latest_co2 = None
            if selected_device_id == 'ecosensor02' or latest_co2 == 0 or not latest_valid:
                try:
                    await log_co2_diagnostics_if_needed(selected_device_id, host_now, data if isinstance(data, dict) else None)
                except Exception as exc:
                    record_sync_event(selected_device_id, 'co2_diagnostics_error', error=str(exc)[:180])

            # Prioridad 2: si el firmware nuevo está disponible, rellenar hacia
            # atrás desde lo más reciente. Así las gráficas obtienen primero los
            # puntos cercanos al tiempo real y no dependen de una recuperación
            # completa desde el ID viejo.
            if latest_remote_id > local_floor_id and endpoints_now.get('lecturas_recent'):
                before_id = latest_remote_id
                for batch_index in range(1, SYNC_MAX_BATCHES_PER_CYCLE + 1):
                    recent = await fetch_recent_readings(
                        host_now,
                        after_id=local_floor_id,
                        before_id=before_id,
                        limit=SYNC_CHUNK_SIZE,
                        timeout=4.0,
                    )
                    recent_data = recent.get('data') if recent.get('ok') else None
                    rows = recent_data.get('rows') if isinstance(recent_data, dict) else None
                    rows = rows if isinstance(rows, list) else []
                    inserted_count = 0
                    min_seen_source_id = 0
                    max_seen_source_id = 0
                    if rows:
                        inserted_count, min_seen_source_id, max_seen_source_id = await _save_remote_rows(
                            host_now,
                            selected_device_id,
                            rows,
                            recent_data.get('current_uptime_s') if isinstance(recent_data, dict) else None,
                            recent_data.get('boot_id') if isinstance(recent_data, dict) else None,
                        )
                        total_inserted += inserted_count
                        total_received += len(rows)

                    batches = batch_index
                    record_sync_event(
                        selected_device_id,
                        'fetch_recent_batch',
                        host=host_now,
                        batch=batch_index,
                        after_id=local_floor_id,
                        before_id=before_id,
                        limit=SYNC_CHUNK_SIZE,
                        ok=bool(recent.get('ok')),
                        rows=len(rows),
                        inserted=inserted_count,
                        min_seen_source_id=min_seen_source_id,
                        max_seen_source_id=max_seen_source_id,
                        response=summarize_response(recent),
                    )

                    if not recent.get('ok'):
                        break
                    if not rows:
                        completed_history_sync = True
                        break
                    if min_seen_source_id <= local_floor_id + 1:
                        completed_history_sync = True
                        break
                    if min_seen_source_id <= 0 or min_seen_source_id >= before_id:
                        record_sync_event(
                            selected_device_id,
                            'fetch_recent_stalled',
                            host=host_now,
                            after_id=local_floor_id,
                            before_id=before_id,
                            min_seen_source_id=min_seen_source_id,
                        )
                        break
                    before_id = min_seen_source_id
                    if len(rows) < SYNC_CHUNK_SIZE:
                        completed_history_sync = True
                        break

                record_sync_event(
                    selected_device_id,
                    'fetch_recent_summary',
                    host=host_now,
                    batches=batches,
                    chunk_size=SYNC_CHUNK_SIZE,
                    rows=total_received,
                    inserted=total_inserted,
                    complete=completed_history_sync,
                    local_floor_id=local_floor_id,
                    latest_remote_id=latest_remote_id,
                )

            # Compatibilidad/fallback: para firmware viejo sin /lecturas/recent,
            # seguir usando /lecturas/since, pero desde el ID anterior al último
            # guardado antes de insertar la medición fresca.
            elif latest_remote_id <= local_floor_id:
                completed_history_sync = True
                record_sync_event(
                    selected_device_id,
                    'fetch_history_skipped',
                    host=host_now,
                    reason='latest_not_newer',
                    local_floor_id=local_floor_id,
                    latest_remote_id=latest_remote_id,
                )
            else:
                last_id = local_floor_id
                for batch_index in range(1, SYNC_MAX_BATCHES_PER_CYCLE + 1):
                    batch_after_id = last_id
                    missing = await fetch_readings_since(
                        host_now,
                        batch_after_id,
                        limit=SYNC_CHUNK_SIZE,
                        timeout=4.0,
                    )
                    missing_data = missing.get('data') if missing.get('ok') else None
                    rows = missing_data.get('rows') if isinstance(missing_data, dict) else None
                    rows = rows if isinstance(rows, list) else []
                    inserted_count = 0
                    min_seen_source_id = 0
                    max_seen_source_id = batch_after_id
                    if rows:
                        inserted_count, min_seen_source_id, max_seen_source_id = await _save_remote_rows(
                            host_now,
                            selected_device_id,
                            rows,
                            missing_data.get('current_uptime_s') if isinstance(missing_data, dict) else None,
                            missing_data.get('boot_id') if isinstance(missing_data, dict) else None,
                        )
                        total_inserted += inserted_count
                        total_received += len(rows)

                    batches = batch_index
                    record_sync_event(
                        selected_device_id,
                        'fetch_since_batch',
                        host=host_now,
                        batch=batch_index,
                        after_id=batch_after_id,
                        limit=SYNC_CHUNK_SIZE,
                        ok=bool(missing.get('ok')),
                        rows=len(rows),
                        inserted=inserted_count,
                        response=summarize_response(missing),
                    )

                    if not missing.get('ok'):
                        break
                    if not rows:
                        completed_history_sync = True
                        break
                    if max_seen_source_id <= batch_after_id:
                        record_sync_event(
                            selected_device_id,
                            'fetch_since_stalled',
                            host=host_now,
                            after_id=batch_after_id,
                            max_seen_source_id=max_seen_source_id,
                        )
                        break
                    last_id = max_seen_source_id
                    if len(rows) < SYNC_CHUNK_SIZE:
                        completed_history_sync = True
                        break

                record_sync_event(
                    selected_device_id,
                    'fetch_since_summary',
                    host=host_now,
                    batches=batches,
                    chunk_size=SYNC_CHUNK_SIZE,
                    rows=total_received,
                    inserted=total_inserted,
                    complete=completed_history_sync,
                    latest_after_id=last_id,
                )

        if not row:
            row = await asyncio.to_thread(get_latest_measurement, selected_device_id)

        record_sync_event(
            selected_device_id,
            'done',
            host=host_now,
            latest_timestamp=(row or {}).get('timestamp'),
            latest_received_at=(row or {}).get('received_at'),
            latest_measurement_id=(row or {}).get('measurement_id'),
            latest_time_valid=(row or {}).get('time_valid'),
            latest_time_source=(row or {}).get('time_source'),
        )
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
        except Exception as exc:
            record_sync_event('background', 'loop_error', error=str(exc)[:220])
            # El loop debe sobrevivir caídas puntuales de red/ESP32.
            pass
        await asyncio.sleep(interval_seconds)


async def debug_device_snapshot(device_id: str | None = None) -> dict[str, Any]:
    """Diagnóstico bajo demanda para consola/API; no modifica la UI."""
    target_id = (device_id or DEVICE_ID).strip().lower() or DEVICE_ID
    active = await ensure_device_active(target_id)
    host = str((active or {}).get('host') or host_for_device(target_id))
    endpoints = build_endpoints(host)
    latest_source = await asyncio.to_thread(latest_source_id, target_id)

    status = await fetch_json(endpoints['status'], timeout=3.0) if endpoints['status'] else {'ok': False, 'data': 'missing status endpoint'}
    lecturas = await fetch_json(endpoints['lecturas'], timeout=4.0) if endpoints['lecturas'] else {'ok': False, 'data': 'missing lecturas endpoint'}
    diagnostics = await fetch_json(endpoints['diagnostics'], timeout=4.0) if endpoints.get('diagnostics') else {'ok': False, 'data': 'missing diagnostics endpoint'}
    since = await fetch_readings_since(host, latest_source, limit=20, timeout=5.0) if host else {'ok': False, 'data': 'missing host'}

    since_data = since.get('data') if since.get('ok') else None
    rows = since_data.get('rows') if isinstance(since_data, dict) else None

    return {
        'ok': True,
        'device_id': target_id,
        'host': host,
        'active_entry': active,
        'local_storage': await asyncio.to_thread(measurement_debug_summary, target_id),
        'latest_local_source_id': latest_source,
        'remote': {
            'status': summarize_response(status),
            'lecturas': summarize_response(lecturas),
            'diagnostics': diagnostics.get('data') if diagnostics.get('ok') and isinstance(diagnostics.get('data'), dict) else summarize_response(diagnostics),
            'lecturas_since': {
                **summarize_response(since),
                'rows_preview': rows[:3] if isinstance(rows, list) else None,
            },
        },
        'sync_events': sync_debug_snapshot(target_id),
    }


def host_for_selected_device(device_id: str | None) -> str:
    return host_for_device(device_id or DEVICE_ID)
