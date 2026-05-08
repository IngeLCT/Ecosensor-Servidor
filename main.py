import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from nicegui import app, ui

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / 'data'
STATIC_DIR = APP_DIR / 'static'
SETTINGS_FILE = DATA_DIR / 'settings.json'
DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '8765'))
DEFAULT_SETTINGS = {
    'esp_host': '',
    'device_id': DEVICE_ID,
}

app.add_static_files('/static', STATIC_DIR)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_data_dir()
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return deepcopy(DEFAULT_SETTINGS)

    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        stored = {}

    settings = deepcopy(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in stored.items() if k in settings})
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    ensure_data_dir()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')


def normalize_host_input(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''

    if '://' not in value:
        value = f'http://{value}'

    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    host = host.strip().rstrip('/')

    if '/' in host:
        host = host.split('/')[0]

    return host


def build_base_url(host: str) -> str:
    return f'http://{host}' if host else ''


def build_endpoints(host: str) -> dict[str, str]:
    base_url = build_base_url(host)
    return {
        'base_url': base_url,
        'status': f'{base_url}/status' if base_url else '',
        'lecturas': f'{base_url}/lecturas' if base_url else '',
        'config': f'{base_url}/config' if base_url else '',
    }


def fetch_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'})
    return request_json_sync(request, url, timeout)


def post_json_sync(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    request = Request(
        url,
        data=body,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
        method='POST',
    )
    return request_json_sync(request, url, timeout)


def request_json_sync(request: Request, url: str, timeout: float = 8.0) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', errors='replace')
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
            return {'ok': 200 <= response.status < 300, 'status': response.status, 'url': url, 'data': data}
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
        return {'ok': False, 'status': exc.code, 'url': url, 'data': raw}
    except (TimeoutError, URLError, OSError) as exc:
        return {'ok': False, 'status': 0, 'url': url, 'data': str(exc)}


async def fetch_json(url: str) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_json_sync, url)


async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(post_json_sync, url, payload)


def system_datetime_payload() -> dict[str, str]:
    now = datetime.now().astimezone()
    return {
        'date': now.strftime('%d-%m-%Y'),
        'time': now.strftime('%H:%M:%S'),
    }


def row_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        'id': payload.get('device_id', DEVICE_ID),
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
        'window_s': payload.get('window_s'),
    }


def format_value(value: Any, decimals: int = 2) -> str:
    if value is None:
        return '0'
    if isinstance(value, float):
        return f'{value:.{decimals}f}'
    return str(value)


def add_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        body { background: #cce5dc; color: #101820; }
        .connect-shell {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .connect-box {
            width: min(520px, 100%);
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 12px;
            align-items: start;
        }
        .dashboard {
            width: min(1180px, 100%);
            margin: 0 auto;
            padding: 28px 18px 44px;
            text-align: center;
            font-family: "Arial Narrow", Arial, sans-serif;
        }
        .top-nav {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 10px 18px;
            margin-bottom: 18px;
            font-size: 18px;
            font-weight: 700;
        }
        .brand-title { color: rgb(4, 87, 9); font-size: 28px; font-weight: 700; }
        .section-title {
            color: rgb(4, 4, 52);
            font-size: 26px;
            font-weight: 700;
            text-decoration: underline;
        }
        .pollutant-card {
            background: rgba(255, 255, 255, .52);
            border: 1px solid rgba(0, 0, 0, .12);
            border-radius: 8px;
            padding: 16px;
        }
        .thumbs {
            display: grid;
            grid-template-columns: repeat(4, minmax(110px, 1fr));
            gap: 12px;
        }
        .thumb {
            background: #fff;
            border: 1px solid rgba(0, 0, 0, .14);
            border-radius: 8px;
            padding: 8px;
            font-weight: 700;
        }
        .thumb img {
            width: 100%;
            height: 84px;
            object-fit: contain;
        }
        .measure-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 20px;
        }
        .measure-table th,
        .measure-table td {
            font-size: 24px;
            text-align: center;
            border: 1px solid black;
            padding: 10px;
        }
        .measure-table th { background: #80ffd4; }
        .status-line {
            min-height: 28px;
            font-size: 19px;
            color: #1d332a;
        }
        @media (max-width: 760px) {
            .connect-box { grid-template-columns: 1fr; }
            .thumbs { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
            .measure-table th,
            .measure-table td { font-size: 18px; }
        }
        </style>
        '''
    )


@ui.page('/')
def index() -> None:
    ui.page_title('EcoSensor Servidor')
    add_styles()
    settings = load_settings()

    with ui.element('div').classes('connect-shell'):
        with ui.element('div').classes('connect-box'):
            host_input = ui.input(
                placeholder='IP o mDNS del ESP32',
                value=settings.get('esp_host', ''),
            ).props('outlined dense autofocus').classes('w-full')
            connect_button = ui.button('Conectar').props('unelevated color=primary')

    async def connect() -> None:
        host = normalize_host_input(host_input.value)
        if not host:
            ui.notify('Escribe la IP o mDNS del ESP32', color='negative')
            return

        endpoints = build_endpoints(host)
        status = await fetch_json(endpoints['status'])
        if not status.get('ok'):
            ui.notify('No se pudo leer /status del ESP32. Revisa IP/mDNS y red.', color='negative')
            return

        status_data = status.get('data')
        if not isinstance(status_data, dict):
            ui.notify('Respuesta inválida desde /status del ESP32.', color='negative')
            return

        if not status_data.get('time_valid', False):
            config_payload = system_datetime_payload()
            config_response = await post_json(endpoints['config'], config_payload)
            config_data = config_response.get('data')
            if not config_response.get('ok') or not (isinstance(config_data, dict) and config_data.get('time_valid')):
                ui.notify('No se pudo configurar fecha/hora en el ESP32.', color='negative')
                return
            ui.notify('Fecha/hora enviada al ESP32. Sensores habilitados.', color='positive')
        else:
            ui.notify('ESP32 conectado con fecha/hora válida.', color='positive')

        settings['esp_host'] = host
        save_settings(settings)
        ui.navigate.to('/dashboard')

    connect_button.on('click', connect)
    host_input.on('keydown.enter', connect)


@ui.page('/dashboard')
def dashboard() -> None:
    ui.page_title('EcoSensor Mediciones')
    add_styles()
    settings = load_settings()
    host = settings.get('esp_host', '')
    endpoints = build_endpoints(host)

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
            reconnect_button = ui.button('Cambiar conexión', on_click=lambda: ui.navigate.to('/'))

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


ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False)
