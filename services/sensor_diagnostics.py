from __future__ import annotations

import time
from typing import Any

from services.esp_client import build_endpoints, fetch_json

_CO2_LOG_MIN_INTERVAL_S = 60.0
_last_co2_log: dict[str, tuple[float, str]] = {}

SENSOR_DIAG_LABELS = {
    0: 'OK',
    1: 'CRC_INVALIDO',
    2: 'TIMEOUT',
    3: 'FUERA_DE_RANGO',
    4: 'I2C_TX',
    5: 'I2C_RX',
    99: 'OTRO',
}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _diag_label(value: Any) -> str:
    code = _int_or_none(value)
    if code is None:
        return 'DESCONOCIDO'
    return SENSOR_DIAG_LABELS.get(code, f'DESCONOCIDO_{code}')


def _co2_problem_reason(co2: int | None, scd40_ret: int | None, scd40_diag: int | None, valid: bool) -> str | None:
    if scd40_ret not in (None, 0):
        return f'scd40_ret={scd40_ret}'
    if scd40_diag not in (None, 0):
        return f'scd40_diag={_diag_label(scd40_diag)}'
    if co2 == 0:
        return 'co2=0'
    if not valid:
        return 'lectura_no_valida'
    return None


def _recent_event_summary(events: Any) -> str:
    if not isinstance(events, list):
        return 'sin_eventos'
    useful: list[str] = []
    for item in events[-6:]:
        if not isinstance(item, dict):
            continue
        event = str(item.get('event') or '').strip()
        detail = str(item.get('detail') or '').strip()
        uptime = item.get('uptime_s')
        if event:
            useful.append(f'{uptime}s:{event}{"/" + detail if detail else ""}')
    return ' | '.join(useful[-4:]) or 'sin_eventos'


def _should_print(device_id: str, signature: str, force: bool) -> bool:
    if force:
        return True
    now = time.monotonic()
    last_ts, last_signature = _last_co2_log.get(device_id, (0.0, ''))
    if signature != last_signature or (now - last_ts) >= _CO2_LOG_MIN_INTERVAL_S:
        _last_co2_log[device_id] = (now, signature)
        return True
    return False


async def log_co2_diagnostics_if_needed(
    device_id: str,
    host: str,
    latest_payload: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Consulta /diagnostics y escribe en consola solo si hay indicios de problema CO2/SCD40."""
    clean_device_id = (device_id or 'unknown').strip().lower() or 'unknown'
    endpoints = build_endpoints(host)
    if not endpoints.get('diagnostics'):
        return {'ok': False, 'printed': False, 'reason': 'missing_host'}

    diagnostics = await fetch_json(endpoints['diagnostics'], timeout=3.0)
    data = diagnostics.get('data') if diagnostics.get('ok') else None
    if not isinstance(data, dict):
        if force:
            print(f"[ecosensor-co2] {clean_device_id} ERROR diagnostics_ok={diagnostics.get('ok')} status={diagnostics.get('status')} data={str(diagnostics.get('data'))[:180]}", flush=True)
        return {'ok': False, 'printed': force, 'reason': 'diagnostics_unavailable', 'diagnostics': diagnostics}

    last_reading = data.get('last_reading') if isinstance(data.get('last_reading'), dict) else {}
    sensor_debug = data.get('sensor_debug') if isinstance(data.get('sensor_debug'), dict) else {}
    source = latest_payload if isinstance(latest_payload, dict) else last_reading

    co2 = _int_or_none(source.get('co2'))
    valid = bool(source.get('valid', last_reading.get('valid', False)))
    scd40_ret = _int_or_none(sensor_debug.get('scd40_ret'))
    scd40_diag = _int_or_none(sensor_debug.get('scd40_diag'))
    reason = _co2_problem_reason(co2, scd40_ret, scd40_diag, valid)
    if not force and reason is None:
        return {'ok': True, 'printed': False, 'reason': 'co2_ok', 'diagnostics': data}

    signature = f'{reason}|co2={co2}|ret={scd40_ret}|diag={scd40_diag}|sample={sensor_debug.get("sample_slot")}|id={last_reading.get("measurement_id")}'
    if _should_print(clean_device_id, signature, force):
        print(
            '[ecosensor-co2] '
            f'{clean_device_id} {"FORZADO" if force else "ALERTA"} '
            f'reason={reason or "consulta_manual"} '
            f'co2={co2} valid={valid} '
            f'scd40_ret={scd40_ret} scd40_diag={scd40_diag}:{_diag_label(scd40_diag)} '
            f'sample={sensor_debug.get("sample_slot")}/{sensor_debug.get("samples_per_window")} '
            f'scd40_ok={sensor_debug.get("scd40_ok_count")} '
            f'sensores={sensor_debug.get("sensors_state")} '
            f'uptime={data.get("current_uptime_s")} '
            f'last_sample_uptime={sensor_debug.get("last_sample_uptime_s")} '
            f'last_measurement_id={last_reading.get("measurement_id")} '
            f'events={_recent_event_summary(data.get("events"))}',
            flush=True,
        )
        return {'ok': True, 'printed': True, 'reason': reason or 'manual', 'diagnostics': data}

    return {'ok': True, 'printed': False, 'reason': 'throttled', 'diagnostics': data}
