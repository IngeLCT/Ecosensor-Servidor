import asyncio
from datetime import datetime, timedelta
from time import monotonic
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
from services.esp_client import build_endpoints, fetch_json, fetch_readings_range, sync_time_if_needed
from services.sync_debug import record_sync_event, summarize_response
from shared.formatters import row_from_payload
from storage.measurements_store import get_latest_measurement, latest_source_id, missing_source_id_ranges, save_measurement

_sync_locks: dict[str, asyncio.Lock] = {}
_synced_notice_printed: set[str] = set()
SYNC_CHUNK_SIZE = 25
SYNC_MAX_BATCHES_PER_CYCLE = 300
SYNC_PROGRESS_INTERVAL_SECONDS = 60.0


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


async def sync_sensor_measurements(device_id: str | None = None, *, fetch_latest: bool = True, sync_history: bool = True) -> dict[str, Any] | None:
    """Sincroniza un EcoSensor concreto y devuelve su última medición conocida.

    Cuando ``fetch_latest`` es False no consulta ``/lecturas``. Cuando
    ``sync_history`` es False solo deja listo el estado rápido del sensor
    (vida/hora/última medición) y no recupera histórico desde SD.
    """
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
        total_inserted = 0
        total_received = 0
        batches = 0
        sync_started_printed = False
        suppress_zero_sync_log = False
        last_progress_print = monotonic()

        if endpoints_now['lecturas']:
            completed_history_sync = False
            local_floor_id = await asyncio.to_thread(latest_source_id, selected_device_id)

            latest_inserted = False
            latest_remote_id = 0
            latest_valid = False

            if fetch_latest:
                # Prioridad 1: pedir primero la última medición. Esto mantiene
                # compatibilidad con pantallas/flujos que aún no dependen solo
                # del push del ESP32.
                lecturas = await fetch_json(endpoints_now['lecturas'], timeout=3.0)
                data = lecturas.get('data') if lecturas.get('ok') else None
                if isinstance(data, dict) and data.get('valid'):
                    row = row_from_payload(data)
                    if row:
                        row['device_id'] = selected_device_id
                        row['id'] = selected_device_id
                        _enrich_time_metadata(row, data.get('current_uptime_s'), datetime.now().astimezone(), data.get('boot_id'))
                        if row.get('time_source') == 'esp':
                            row['time_source'] = 'esp_live'
                        try:
                            latest_remote_id = int(row.get('measurement_id') or 0)
                        except (TypeError, ValueError):
                            latest_remote_id = 0
                        latest_inserted = await asyncio.to_thread(save_measurement, host_now, row)
                latest_valid = bool(isinstance(data, dict) and data.get('valid'))
                response_summary = summarize_response(lecturas)
            else:
                status_data = active.get('status') if isinstance(active.get('status'), dict) else {}
                try:
                    latest_remote_id = int(status_data.get('last_measurement_id') or 0)
                except (TypeError, ValueError):
                    latest_remote_id = 0
                response_summary = 'skipped_fetch_latest'

            record_sync_event(
                selected_device_id,
                'fetch_latest',
                host=host_now,
                ok=True,
                valid=latest_valid,
                inserted=latest_inserted,
                local_floor_id=local_floor_id,
                latest_remote_id=latest_remote_id,
                response=response_summary,
            )

            if latest_inserted:
                total_inserted += 1

            if not sync_history:
                missing_ranges = []
                pending_count = 0
                completed_history_sync = True
                record_sync_event(
                    selected_device_id,
                    'fetch_history_skipped',
                    host=host_now,
                    reason='quick_sync_only',
                    latest_remote_id=latest_remote_id,
                )
            else:
                missing_ranges = await asyncio.to_thread(missing_source_id_ranges, selected_device_id, latest_remote_id)
                pending_count = sum((end_id - start_id + 1) for start_id, end_id in missing_ranges)

            if latest_remote_id > 0:
                if missing_ranges:
                    _synced_notice_printed.discard(selected_device_id)
                    ranges_preview = ','.join(
                        f"{start_id}-{end_id}" if start_id != end_id else str(start_id)
                        for start_id, end_id in missing_ranges[-4:]
                    )
                    print(
                        f"[measurement_sync] inicio sincronizacion {selected_device_id}: "
                        f"{pending_count} datos por sincronizar; rangos={ranges_preview}",
                        flush=True,
                    )
                    sync_started_printed = True
                else:
                    suppress_zero_sync_log = True
                    if sync_history and selected_device_id not in _synced_notice_printed:
                        print(
                            f"[measurement_sync] {selected_device_id}: sincronizado; 0 datos pendientes",
                            flush=True,
                        )
                        _synced_notice_printed.add(selected_device_id)
            else:
                print(f"[measurement_sync] inicio sincronizacion {selected_device_id}", flush=True)
                sync_started_printed = True

            # Recuperación de histórico por rangos faltantes concretos.
            # Se recorre de IDs altos a bajos para rellenar primero lo más reciente.
            if missing_ranges:
                for range_start, range_end in reversed(missing_ranges):
                    chunk_to = range_end
                    while chunk_to >= range_start and batches < SYNC_MAX_BATCHES_PER_CYCLE:
                        chunk_from = max(range_start, chunk_to - SYNC_CHUNK_SIZE + 1)
                        missing = await fetch_readings_range(
                            host_now,
                            from_id=chunk_from,
                            to_id=chunk_to,
                            limit=SYNC_CHUNK_SIZE,
                            timeout=30.0,
                        )
                        missing_data = missing.get('data') if isinstance(missing.get('data'), dict) else None
                        rows = missing_data.get('rows') if isinstance(missing_data, dict) else None
                        rows = rows if isinstance(rows, list) else []
                        inserted_count = 0
                        min_seen_source_id = 0
                        max_seen_source_id = 0
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

                        batches += 1
                        ok = bool(missing.get('ok'))
                        record_sync_event(
                            selected_device_id,
                            'fetch_range_batch',
                            host=host_now,
                            batch=batches,
                            from_id=chunk_from,
                            to_id=chunk_to,
                            limit=SYNC_CHUNK_SIZE,
                            ok=ok,
                            rows=len(rows),
                            inserted=inserted_count,
                            min_seen_source_id=min_seen_source_id,
                            max_seen_source_id=max_seen_source_id,
                            response=summarize_response(missing),
                        )

                        now_progress = monotonic()
                        if pending_count > 0 and now_progress - last_progress_print >= SYNC_PROGRESS_INTERVAL_SECONDS:
                            synced_so_far = min(total_received, pending_count)
                            remaining = max(0, pending_count - synced_so_far)
                            print(
                                f"[measurement_sync] progreso {selected_device_id}: "
                                f"{synced_so_far}/{pending_count} recibidos, "
                                f"{total_inserted} insertados, faltan {remaining}, "
                                f"lotes={batches}, ultimo_rango={chunk_from}-{chunk_to}",
                                flush=True,
                            )
                            last_progress_print = now_progress

                        if not ok and not rows:
                            print(
                                f"[measurement_sync] {selected_device_id}: bloque sin progreso "
                                f"range={chunk_from}-{chunk_to} response={summarize_response(missing)}",
                                flush=True,
                            )
                            break
                        chunk_to = chunk_from - 1

                    if batches >= SYNC_MAX_BATCHES_PER_CYCLE:
                        break

                completed_history_sync = batches < SYNC_MAX_BATCHES_PER_CYCLE
                record_sync_event(
                    selected_device_id,
                    'fetch_range_summary',
                    host=host_now,
                    batches=batches,
                    chunk_size=SYNC_CHUNK_SIZE,
                    rows=total_received,
                    inserted=total_inserted,
                    complete=completed_history_sync,
                    ranges=len(missing_ranges),
                    pending=pending_count,
                    latest_remote_id=latest_remote_id,
                )
            else:
                completed_history_sync = True
                record_sync_event(
                    selected_device_id,
                    'fetch_history_skipped',
                    host=host_now,
                    reason='no_missing_ranges',
                    latest_remote_id=latest_remote_id,
                )

        if not sync_started_printed:
            print(f"[measurement_sync] inicio sincronizacion {selected_device_id}", flush=True)

        if not row:
            row = await asyncio.to_thread(get_latest_measurement, selected_device_id)

        if not suppress_zero_sync_log:
            if sync_history and sync_started_printed:
                final_remaining = max(0, pending_count - min(total_received, pending_count)) if 'pending_count' in locals() else 0
                if final_remaining > 0:
                    print(
                        f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                        f"{total_inserted} datos sincronizados; faltan {final_remaining}",
                        flush=True,
                    )
                else:
                    print(
                        f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                        f"{total_inserted} datos sincronizados",
                        flush=True,
                    )
            else:
                print(
                    f"[measurement_sync] fin sincronizacion {selected_device_id}: "
                    f"{total_inserted} datos sincronizados",
                    flush=True,
                )

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


async def background_sync_loop(interval_seconds: float = 300.0) -> None:
    print(
        f"[measurement_sync] backend iniciado: sincronizacion automatica cada {interval_seconds:.0f}s",
        flush=True,
    )
    while True:
        try:
            await sync_all_active_measurements()
        except Exception as exc:
            record_sync_event('background', 'loop_error', error=str(exc)[:220])
            # El loop debe sobrevivir caídas puntuales de red/ESP32.
            pass
        await asyncio.sleep(interval_seconds)
