from typing import Any

from nicegui import ui

from config import DEVICE_ID
from services.esp_client import build_endpoints, fetch_json
from shared.formatters import format_value, row_from_payload
from shared.styles import add_styles
from storage.settings_store import load_settings


@ui.page('/dashboard')
def dashboard() -> None:
    ui.page_title('EcoSensor Mediciones')
    add_styles()
    settings = load_settings()
    host = settings.get('esp_host', '')

    with ui.element('div').classes('dashboard'):
        with ui.element('nav').classes('top-nav'):
            ui.link('Conexión', '/')
            ui.link('Mediciones', '/dashboard')

        with ui.row().classes('items-center justify-center gap-3'):
            ui.label('LCT Didacticos').classes('brand-title')
            ui.image('/static/LCT_SF.png').classes('w-[90px] h-[90px]')

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
        start_info = ui.label('').classes('status-line mt-6')
        time_info = ui.label('').classes('status-line')
        connection_info = ui.label('').classes('status-line mt-3')

        with ui.row().classes('justify-center gap-3 mt-4'):
            refresh_button = ui.button('Actualizar')
            ui.button('Cambiar conexión', on_click=lambda: ui.navigate.to('/'))

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

    async def refresh() -> None:
        host_now = load_settings().get('esp_host', '')
        endpoints_now = build_endpoints(host_now)
        row = None
        source = 'ESP32 sin lecturas válidas'

        if endpoints_now['lecturas']:
            lecturas = await fetch_json(endpoints_now['lecturas'])
            data = lecturas.get('data') if lecturas.get('ok') else None
            if isinstance(data, dict) and data.get('valid'):
                row = row_from_payload(data)
                source = 'ESP32'

        render_table(row)
        id_label.set_text(f"ID: {(row or {}).get('id', DEVICE_ID)}")
        timestamp = (row or {}).get('timestamp') or ''
        start_info.set_text(f"Host conectado: {host_now or '-'}")
        time_info.set_text(f"Fecha ultima medicion: {timestamp}" if timestamp else '')
        connection_info.set_text(f"Fuente de datos: {source}. El servidor consulta endpoints del ESP32.")

    refresh_button.on('click', refresh)
    ui.timer(8.0, refresh)
    ui.timer(0.1, refresh, once=True)
