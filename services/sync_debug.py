from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_EVENTS = 80
PRINT_SYNC_EVENTS = False  # Debug temporal: mantener consola limpia; /api/debug/sync conserva eventos.

_sync_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_last_by_device: dict[str, dict[str, Any]] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def summarize_response(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {'ok': False, 'error': 'sin respuesta'}
    data = response.get('data')
    summary: dict[str, Any] = {
        'ok': bool(response.get('ok')),
        'status': response.get('status'),
        'url': response.get('url'),
    }
    if isinstance(data, dict):
        summary['data_keys'] = sorted(str(key) for key in data.keys())
        for key in (
            'device_id', 'id', 'valid', 'time_valid', 'needs_time_sync',
            'current_datetime', 'last_measurement_id', 'last_measurement_timestamp',
            'last_measurement_uptime_s', 'measurement_id', 'boot_id',
            'current_uptime_s', 'uptime_s', 'sd_ready', 'sd_last_id',
            'state', 'sensors', 'rows',
        ):
            if key in data:
                value = data[key]
                summary[key] = len(value) if key == 'rows' and isinstance(value, list) else value
    else:
        text = str(data or '').strip()
        summary['data'] = text[:180]
    return summary


def _should_print_sync_event(event: str, details: dict[str, Any]) -> bool:
    """Mantiene historial completo en memoria, pero reduce ruido en consola."""
    if event in {'loop_error', 'co2_diagnostics_error', 'fetch_recent_stalled', 'fetch_since_stalled'}:
        return True
    if event == 'inactive':
        return True
    if event == 'time_sync':
        return not bool(details.get('ok'))
    if event == 'fetch_latest':
        return (not bool(details.get('ok'))) or (not bool(details.get('valid')))
    if event in {'fetch_recent_summary', 'fetch_since_summary'}:
        rows = int(details.get('rows') or 0)
        inserted = int(details.get('inserted') or 0)
        complete = bool(details.get('complete'))
        return rows > 0 or inserted > 0 or not complete
    return False


def record_sync_event(device_id: str, event: str, **details: Any) -> dict[str, Any]:
    clean_device_id = (device_id or 'unknown').strip().lower() or 'unknown'
    payload: dict[str, Any] = {
        'ts': utc_now_iso(),
        'device_id': clean_device_id,
        'event': event,
        **details,
    }
    _sync_events.append(payload)
    _last_by_device[clean_device_id] = payload

    # Debug operativo: queda en la consola del servidor, no en la UI.
    # Se imprime solo lo esencial; /api/debug/sync conserva los eventos recientes.
    if PRINT_SYNC_EVENTS and _should_print_sync_event(event, details):
        compact = ' '.join(
            f'{key}={value}'
            for key, value in payload.items()
            if key not in {'ts', 'device_id', 'event'} and value is not None
        )
        print(f"[ecosensor-sync] {payload['ts']} {clean_device_id} {event} {compact}".rstrip(), flush=True)
    return payload


def sync_debug_snapshot(device_id: str | None = None) -> dict[str, Any]:
    clean_device_id = (device_id or '').strip().lower()
    events = list(_sync_events)
    if clean_device_id:
        events = [item for item in events if item.get('device_id') == clean_device_id]
    return {
        'ok': True,
        'generated_at': utc_now_iso(),
        'device_id': clean_device_id or None,
        'last': _last_by_device.get(clean_device_id) if clean_device_id else dict(_last_by_device),
        'events': events[-30:],
    }


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
