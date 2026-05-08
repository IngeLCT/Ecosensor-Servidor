import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Body
from nicegui import app, ui

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / 'data'
SETTINGS_FILE = DATA_DIR / 'settings.json'
DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '8765'))
DEFAULT_SETTINGS = {
    'esp_host': '',
    'device_id': DEVICE_ID,
    'read_interval_s': 5,
    'upload_interval_s': 60,
    'time_required': True,
}
LATEST_INGEST: dict[str, Any] = {
    'received': False,
    'payload': None,
    'received_at': None,
}


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
    }


def pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)


def current_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


async def fetch_json(url: str) -> dict[str, Any]:
    return await ui.run_javascript(
        f'''
        return fetch({url!r})
            .then(async response => {{
                const text = await response.text();
                let data = null;
                try {{
                    data = JSON.parse(text);
                }} catch (error) {{
                    data = text;
                }}
                return {{
                    ok: response.ok,
                    status: response.status,
                    url: {url!r},
                    data,
                }};
            }})
            .catch(error => ({{
                ok: false,
                status: 0,
                url: {url!r},
                data: String(error),
            }}));
        ''',
        timeout=30,
    )


@app.get('/api/v1/device/{device_id}/config')
def api_get_config(device_id: str):
    settings = load_settings()
    return {
        'ok': True,
        'device_id': device_id,
        'read_interval_s': settings['read_interval_s'],
        'upload_interval_s': settings['upload_interval_s'],
        'time_required': settings['time_required'],
    }


@app.get('/api/v1/device/{device_id}/time')
def api_get_time(device_id: str):
    return {
        'ok': True,
        'device_id': device_id,
        'timestamp': current_utc_iso(),
        'valid': True,
    }


@app.post('/api/v1/ingest')
async def api_post_ingest(payload: dict = Body(...)):
    LATEST_INGEST['received'] = True
    LATEST_INGEST['payload'] = payload
    LATEST_INGEST['received_at'] = current_utc_iso()
    return {
        'ok': True,
        'device_id': payload.get('device_id', DEVICE_ID),
        'server_time': LATEST_INGEST['received_at'],
    }


@ui.page('/')
def index() -> None:
    ui.page_title('EcoSensor Servidor')
    settings = load_settings()
    current = {
        'host': settings.get('esp_host', ''),
        'endpoints': build_endpoints(settings.get('esp_host', '')),
    }

    with ui.column().classes('w-full max-w-5xl mx-auto p-6 gap-4'):
        ui.label('EcoSensor Servidor').classes('text-3xl font-bold')
        ui.label(
            'Escribe la IP o el mDNS del ESP32. '
            'No necesitas poner endpoints; el servidor resolverá automáticamente /status y /lecturas.'
        ).classes('text-base text-gray-700')

        with ui.card().classes('w-full gap-3'):
            ui.label('Conexión con el ESP').classes('text-lg font-semibold')
            host_input = ui.input(
                label='IP o mDNS del ESP32',
                placeholder='Ejemplo: 192.168.1.50 o ecosensor01.local',
                value=current['host'],
            ).classes('w-full')
            helper = ui.label().classes('text-sm text-gray-600')

            with ui.row().classes('gap-2 flex-wrap'):
                save_button = ui.button('Guardar host y resolver endpoints')
                test_status_button = ui.button('Probar /status')
                test_lecturas_button = ui.button('Probar /lecturas')

            with ui.column().classes('gap-1'):
                base_url_label = ui.label().classes('font-mono text-sm')
                status_url_label = ui.label().classes('font-mono text-sm')
                lecturas_url_label = ui.label().classes('font-mono text-sm')

        with ui.grid(columns=2).classes('w-full gap-4'):
            with ui.card().classes('w-full'):
                ui.label('Respuesta de /status').classes('text-lg font-semibold')
                status_result = ui.codemirror(language='JSON', value='').classes('w-full h-72')
            with ui.card().classes('w-full'):
                ui.label('Respuesta de /lecturas').classes('text-lg font-semibold')
                lecturas_result = ui.codemirror(language='JSON', value='').classes('w-full h-72')

        with ui.card().classes('w-full gap-3'):
            ui.label('Servidor central (base)').classes('text-lg font-semibold')
            ui.label('Endpoints iniciales ya expuestos por esta app:').classes('text-sm text-gray-700')
            ui.label('POST /api/v1/ingest').classes('font-mono text-sm')
            ui.label(f'GET /api/v1/device/{DEVICE_ID}/config').classes('font-mono text-sm')
            ui.label(f'GET /api/v1/device/{DEVICE_ID}/time').classes('font-mono text-sm')
            latest_ingest_view = ui.codemirror(language='JSON', value='').classes('w-full h-72')

        def refresh_labels() -> None:
            endpoints = current['endpoints']
            base_url_label.set_text(f"Base URL: {endpoints['base_url'] or '-'}")
            status_url_label.set_text(f"/status: {endpoints['status'] or '-'}")
            lecturas_url_label.set_text(f"/lecturas: {endpoints['lecturas'] or '-'}")
            helper.set_text(
                f"Host guardado: {current['host']}" if current['host'] else 'Aún no hay host guardado.'
            )

        def refresh_ingest_view() -> None:
            latest_ingest_view.set_value(pretty_json(LATEST_INGEST))

        def resolve_and_store_host() -> bool:
            host = normalize_host_input(host_input.value)
            if not host:
                ui.notify('Escribe una IP o mDNS válido', color='negative')
                return False

            current['host'] = host
            current['endpoints'] = build_endpoints(host)
            settings['esp_host'] = host
            save_settings(settings)
            refresh_labels()
            ui.notify(f'Host guardado y endpoints resueltos para {host}', color='positive')
            return True

        async def test_status() -> None:
            if not current['host'] and not resolve_and_store_host():
                return
            result = await fetch_json(current['endpoints']['status'])
            status_result.set_value(pretty_json(result))
            ui.notify(
                'Consulta /status completada' if result.get('ok') else 'Falló consulta /status',
                color='positive' if result.get('ok') else 'negative',
            )

        async def test_lecturas() -> None:
            if not current['host'] and not resolve_and_store_host():
                return
            result = await fetch_json(current['endpoints']['lecturas'])
            lecturas_result.set_value(pretty_json(result))
            ui.notify(
                'Consulta /lecturas completada' if result.get('ok') else 'Falló consulta /lecturas',
                color='positive' if result.get('ok') else 'negative',
            )

        save_button.on('click', resolve_and_store_host)
        test_status_button.on('click', test_status)
        test_lecturas_button.on('click', test_lecturas)

        refresh_labels()
        refresh_ingest_view()


ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False)
