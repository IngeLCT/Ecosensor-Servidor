from fastapi import Request
from nicegui import ui

from services.device_registry import device_id_from_host, remember_host
from services.esp_client import build_endpoints, delete_json, normalize_host_input, sync_time_if_needed
from shared.formatters import device_display_name
from shared.styles import add_styles
from storage.measurements_store import clear_measurements
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

            with ui.element('div').classes('connect-box'):
                ui.label('Mantenimiento').classes('connect-label')
                ui.label('Acciones disponibles solo desde el equipo servidor. Úsalas con cuidado.').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    clear_wifi_button = ui.button('Borrar datos de WiFi').props('outline color=negative no-caps')
                    clear_history_button = ui.button('Borrar historial de mediciones').props('unelevated color=negative no-caps')

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

        remember_host(host)
        ui.navigate.to('/dashboard')

    async def clear_wifi() -> None:
        host = normalize_host_input(host_input.value or settings.get('esp_host', ''))
        if not host:
            ui.notify('Escribe la IP o mDNS del ESP32 antes de borrar WiFi.', color='negative')
            return
        with ui.dialog() as dialog, ui.card():
            ui.label('¿Borrar credenciales WiFi del ESP32?')
            ui.label('El ESP32 reiniciará y volverá al modo de configuración WiFi.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await delete_json(build_endpoints(host)['wifi_clear'])
                    if result.get('ok'):
                        ui.notify('Credenciales WiFi borradas en el ESP32.', color='positive')
                    else:
                        ui.notify(f'No se pudo borrar WiFi: {result.get("data")}', color='negative')

                ui.button('Borrar WiFi', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def clear_history() -> None:
        host = normalize_host_input(host_input.value or settings.get('esp_host', ''))
        if not host:
            ui.notify('Escribe la IP o mDNS del ESP32 antes de borrar historial.', color='negative')
            return
        with ui.dialog() as dialog, ui.card():
            ui.label('¿Borrar TODO el historial de mediciones?')
            ui.label('Se borrará el CSV de la SD del ESP32 y la base local SQLite del servidor.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await delete_json(build_endpoints(host)['readings_clear'])
                    if not result.get('ok'):
                        ui.notify(f'No se pudo borrar CSV del ESP32: {result.get("data")}', color='negative')
                        return
                    deleted = clear_measurements(device_id_from_host(host))
                    ui.notify(f'Historial borrado. Filas locales eliminadas: {deleted}.', color='positive')

                ui.button('Borrar historial', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    connect_button.on('click', connect)
    host_input.on('keydown.enter', connect)
    clear_wifi_button.on('click', clear_wifi)
    clear_history_button.on('click', clear_history)
