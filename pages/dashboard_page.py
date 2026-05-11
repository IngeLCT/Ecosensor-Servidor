from typing import Any

from nicegui import ui

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.esp_client import autoconnect_and_sync, build_endpoints, fetch_json
from shared.formatters import format_value, row_from_payload
from shared.styles import add_styles
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
        id_label = ui.label('').classes('text-xl font-bold min-h-[32px]')

        with ui.element('section').classes('pollutant-card w-full mt-4'):
            ui.label('Información sobre contaminantes').classes('text-lg font-bold')
            ui.label(
                'Referencia visual de los contaminantes monitoreados por el EcoSensor.'
            ).classes('text-base')
            with ui.element('div').classes('thumbs mt-3'):
                for filename, label in (
                    ('pm.png', 'PM2.5'),
                    ('co2.png', 'CO2'),
                    ('voc.png', 'VOC'),
                    ('nox.png', 'NOx'),
                ):
                    with ui.element('div').classes('thumb'):
                        ui.image(f'/static/{filename}')
                        ui.label(label)

        table = ui.html('').classes('w-full')
        date_info = ui.label('').classes('status-line mt-6')
        time_info = ui.label('').classes('status-line')
        connection_info = ui.label('').classes('status-line mt-3')

    def render_table(row: dict[str, Any] | None) -> None:
        if not row:
            table.set_content(
                '<div style="margin:20px 0;font-size:32px;font-weight:700;">Esperando Datos...</div>'
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

    def split_timestamp(timestamp: str) -> tuple[str, str]:
        value = (timestamp or '').strip()
        if not value:
            return '', ''
        if 'T' in value:
            date_part, time_part = value.split('T', 1)
            return date_part, time_part.rstrip('Z').split('+', 1)[0].split('-', 1)[0]
        if ' ' in value:
            date_part, time_part = value.split(' ', 1)
            return date_part, time_part.rstrip('Z')
        return value, ''

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

        if not connection.get('ok'):
            render_table(None)
            id_label.set_text(f"ID: {display_host(saved_host or DEFAULT_ESP_HOST)}")
            date_info.set_text('')
            time_info.set_text('')
            connection_info.set_text('Reconectando automaticamente. Si no aparece, revisa que el ESP32 este encendido y en la misma red.')
            return

        render_table(row)
        id_label.set_text(f"ID: {display_host(host_now)}")
        timestamp = (row or {}).get('timestamp') or ''
        date_part, time_part = split_timestamp(timestamp)
        date_info.set_text(f"Fecha ultima medicion: {date_part}" if date_part else '')
        time_info.set_text(f"Hora ultima medicion: {time_part}" if time_part else '')
        connection_info.set_text('')

    ui.timer(8.0, refresh)
    ui.timer(0.1, refresh, once=True)
