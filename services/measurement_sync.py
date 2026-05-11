import asyncio
from typing import Any

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.esp_client import autoconnect_and_sync, build_endpoints, fetch_json, fetch_readings_since
from shared.formatters import row_from_payload
from storage.measurements_store import get_latest_measurement, latest_source_id, save_measurement
from storage.settings_store import load_settings, save_settings


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
            for item in missing_data['rows']:
                if isinstance(item, dict):
                    source_id = item.get('measurement_id') or item.get('id')
                    item['device_id'] = item.get('device_id') or display_host(host_now)
                    item['id'] = item.get('device_id')
                    item['measurement_id'] = source_id
                    await asyncio.to_thread(save_measurement, host_now, item)

        lecturas = await fetch_json(endpoints_now['lecturas'])
        data = lecturas.get('data') if lecturas.get('ok') else None
        if isinstance(data, dict) and data.get('valid'):
            row = row_from_payload(data)
            if row:
                await asyncio.to_thread(save_measurement, host_now, row)

    if not row:
        row = await asyncio.to_thread(get_latest_measurement)

    return row
