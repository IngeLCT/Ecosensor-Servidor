from nicegui import ui

from services.esp_client import build_endpoints, fetch_json, normalize_host_input, post_json, system_datetime_payload
from shared.formatters import device_display_name
from shared.styles import add_styles
from storage.settings_store import load_settings, save_settings


@ui.page('/')
def index() -> None:
    ui.page_title('EcoSensor Servidor')
    add_styles()
    settings = load_settings()
    with ui.element('div').classes('connect-shell'):
        with ui.element('div').classes('connect-card'):
            ui.label('LCT Didacticos').classes('connect-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
            ui.label(device_display_name()).classes('connect-subtitle')
            with ui.element('div').classes('connect-box'):
                ui.label('Ingrese la direccion IP o Nombre del EcoSensor').classes('connect-label')
                host_input = ui.input(
                    placeholder='ecosensor01.local',
                    value=settings.get('esp_host', ''),
                ).props('outlined dense autofocus').classes('w-full connect-input')
                connect_button = ui.button('Conectar').props('unelevated').classes('connect-button')

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
