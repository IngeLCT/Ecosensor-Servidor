from fastapi import Request
from nicegui import ui

from services.esp_client import normalize_host_input, sync_time_if_needed
from shared.formatters import device_display_name
from shared.styles import add_styles
from storage.settings_store import load_settings, save_settings

LOCAL_CLIENTS = {'127.0.0.1', '::1', 'localhost'}


def is_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ''
    return client_host in LOCAL_CLIENTS


@ui.page('/')
def index() -> None:
    ui.navigate.to('/dashboard')


@ui.page('/config')
def config_page(request: Request) -> None:
    ui.page_title('Configurar EcoSensor Servidor')
    add_styles()

    if not is_local_request(request):
        with ui.element('div').classes('connect-shell'):
            with ui.element('div').classes('connect-card'):
                ui.label('Acceso restringido').classes('connect-title')
                ui.label('Esta configuración solo se puede abrir desde el equipo servidor.').classes('connect-label')
                ui.label('Usa: http://localhost:8765/config').classes('connect-label')
        return

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
                ui.button('Ir al dashboard', on_click=lambda: ui.navigate.to('/dashboard')).props('flat')

    async def connect() -> None:
        host = normalize_host_input(host_input.value)
        if not host:
            ui.notify('Escribe la IP o mDNS del ESP32', color='negative')
            return

        result = await sync_time_if_needed(host)
        if not result.get('ok'):
            ui.notify('No se pudo conectar/sincronizar el ESP32. Revisa IP/mDNS y red.', color='negative')
            return

        if result.get('synced'):
            ui.notify('ESP32 conectado y fecha/hora sincronizada.', color='positive')
        else:
            ui.notify('ESP32 conectado con fecha/hora válida.', color='positive')

        settings['esp_host'] = host
        save_settings(settings)
        ui.navigate.to('/dashboard')

    connect_button.on('click', connect)
    host_input.on('keydown.enter', connect)
