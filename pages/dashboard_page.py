import asyncio
from typing import Any

from nicegui import ui

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.esp_client import autoconnect_and_sync, build_endpoints, fetch_json
from shared.formatters import format_value, row_from_payload
from shared.styles import add_styles
from pages.pollutants_modal import pollutants_info_card
from storage.measurements_store import get_latest_measurement, save_measurement
from storage.settings_store import load_settings, save_settings


@ui.page('/dashboard')
def dashboard() -> None:
    ui.page_title('EcoSensor Mediciones')
    add_styles()
    load_settings()

    with ui.element('div').classes('dashboard'):
        with ui.element('nav').classes('top-nav'):
            ui.link('Mediciones', '/dashboard')

        with ui.column().classes('items-center justify-center gap-3'):
            ui.label('LCT Didacticos').classes('brand-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')

        ui.label('Mediciones Ambientales').classes('section-title')
        id_label = ui.label('').classes('section-title')

        pollutants_info_card()

        table = ui.html('').classes('w-full')
        date_info = ui.html('').classes('status-line mt-6')
        time_info = ui.html('').classes('status-line')
        connection_info = ui.label('').classes('status-line mt-3')
        with ui.row().classes('justify-center gap-3 mt-4'):
            ui.button('Descargar CSV', on_click=lambda: ui.navigate.to('/api/measurements.csv')).props('unelevated')

    def render_table(row: dict[str, Any] | None) -> None:
        if not row:
            table.set_content(
                '<table class="measure-table"><tr><th>Mediciones</th><th>Valor</th><th>Unidad</th></tr></table>'
            )
            return

        rows = [
            ('PM1.0', format_value(row.get('pm1p0')), 'ug/m3'),
            ('PM2.5', format_value(row.get('pm2p5')), 'ug/m3'),
            ('PM4.0', format_value(row.get('pm4p0')), 'ug/m3'),
            ('PM10.0', format_value(row.get('pm10p0')), 'ug/m3'),
            ('VOC', format_value(row.get('voc'), 1), 'Index'),
            ('NOx', format_value(row.get('nox'), 1), 'Index'),
            ('CO2', format_value(row.get('co2'), 0), 'ppm'),
            ('Temperatura', format_value(row.get('temp')), 'C'),
            ('Humedad Relativa', format_value(row.get('hum'), 0), '%'),
        ]
        html_rows = ''.join(f'<tr><td>{name}</td><td>{value}</td><td>{unit}</td></tr>' for name, value, unit in rows)
        table.set_content(
            '<table class="measure-table">'
            '<tr><th>Mediciones</th><th>Valor</th><th>Unidad</th></tr>'
            f'{html_rows}'
            '</table>'
        )

    def display_host(host: str) -> str:
        clean = (host or DEVICE_ID).strip()
        if clean.endswith('.local'):
            clean = clean[:-6]
        return clean or DEVICE_ID

    def format_date_dd_mm_yyyy(date_value: str) -> str:
        value = (date_value or '').strip()
        if not value:
            return ''

        # Acepta fechas tipo:
        # 2026-05-11
        # 2026.05.11
        # 2026/05/11
        normalized = value.replace('.', '-').replace('/', '-')
        parts = normalized.split('-')

        if len(parts) >= 3 and len(parts[0]) == 4:
            year = parts[0]
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f'{day}-{month}-{year}'

        return value

    def clean_time(time_value: str) -> str:
        value = (time_value or '').strip()
        if not value:
            return ''

        value = value.rstrip('Z')

        if '+' in value:
            value = value.split('+', 1)[0]

        # Para casos tipo 12:23:19-06:00
        if len(value) >= 8 and value[2] == ':' and value[5] == ':':
            return value[:8]

        return value

    def split_timestamp(timestamp: str) -> tuple[str, str]:
        value = (timestamp or '').strip()
        if not value:
            return '', ''

        if 'T' in value:
            date_part, time_part = value.split('T', 1)
            return format_date_dd_mm_yyyy(date_part), clean_time(time_part)

        if ' ' in value:
            date_part, time_part = value.split(' ', 1)
            return format_date_dd_mm_yyyy(date_part), clean_time(time_part)

        return format_date_dd_mm_yyyy(value), ''

    async def refresh() -> None:
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
            lecturas = await fetch_json(endpoints_now['lecturas'])
            data = lecturas.get('data') if lecturas.get('ok') else None
            if isinstance(data, dict) and data.get('valid'):
                row = row_from_payload(data)
                if row:
                    await asyncio.to_thread(save_measurement, host_now, row)

        if not row:
            row = await asyncio.to_thread(get_latest_measurement)

        render_table(row)
        id_label.set_text(f"ID: {display_host((row or {}).get('host') or host_now)}")
        timestamp = (row or {}).get('timestamp') or ''
        date_part, time_part = split_timestamp(timestamp)
        date_info.set_content(
            f'<strong>Fecha última medición:</strong> {date_part}' if date_part else ''
        )
        time_info.set_content(
            f'<strong>Hora última medición:</strong> {time_part}' if time_part else ''
        )
        connection_info.set_text('')

    ui.timer(8.0, refresh)
    ui.timer(0.1, refresh, once=True)
