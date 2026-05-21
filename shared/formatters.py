from typing import Any

from config import DEVICE_ID


def device_display_name(device_id: str = DEVICE_ID) -> str:
    suffix = ''.join(ch for ch in device_id if ch.isdigit())
    return f'EcoSensor{suffix or "01"}'


def row_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        'id': payload.get('device_id', DEVICE_ID),
        'measurement_id': payload.get('measurement_id') or payload.get('id'),
        'boot_id': payload.get('boot_id'),
        'uptime_s': payload.get('uptime_s'),
        'time_valid': payload.get('time_valid'),
        'time_source': payload.get('time_source'),
        'timestamp': payload.get('timestamp'),
        'pm1p0': payload.get('pm1p0'),
        'pm2p5': payload.get('pm2p5'),
        'pm4p0': payload.get('pm4p0'),
        'pm10p0': payload.get('pm10p0'),
        'voc': payload.get('voc'),
        'nox': payload.get('nox'),
        'co2': payload.get('co2'),
        'temp': payload.get('temp'),
        'hum': payload.get('hum'),
        'scd_temp': payload.get('scd_temp'),
        'scd_hum': payload.get('scd_hum'),
        'sen_temp': payload.get('sen_temp'),
        'sen_hum': payload.get('sen_hum'),
        'window_s': payload.get('window_s'),
    }


def format_value(value: Any, decimals: int = 2) -> str:
    if value is None:
        return '0'
    if isinstance(value, float):
        return f'{value:.{decimals}f}'
    return str(value)
