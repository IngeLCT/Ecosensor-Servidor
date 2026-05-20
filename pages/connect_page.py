from typing import Any

from fastapi import Request
from nicegui import app, ui

from services.device_registry import active_device_options, ensure_active_devices, ensure_device_active, host_for_device, probe_host, remember_host
from services.esp_client import build_endpoints, delete_json, sync_time_if_needed
from shared.formatters import device_display_name
from shared.styles import add_styles
from storage.measurements_store import clear_measurements

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

    selected_device_id: str | None = str(app.storage.user.get('selected_device_id') or '') or None

    with ui.element('div').classes('connect-shell'):
        with ui.element('div').classes('connect-card'):
            ui.label('LCT Didacticos').classes('connect-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
            ui.label(device_display_name()).classes('connect-subtitle')
            with ui.element('div').classes('connect-box'):
                ui.label('Seleccione el EcoSensor a configurar').classes('connect-label')
                sensor_select = ui.select({}, value=None).props('outlined dense').classes('w-full connect-input device-select')
                selected_host_info = ui.label('').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    refresh_button = ui.button('Actualizar lista').props('outline no-caps')
                    connect_button = ui.button('Conectar / sincronizar hora').props('unelevated no-caps').classes('connect-button')
                ui.button('Ir al dashboard', on_click=lambda: ui.navigate.to('/dashboard')).props('flat')

            with ui.element('div').classes('connect-box'):
                ui.label('Mantenimiento').classes('connect-label')
                ui.label('Acciones disponibles solo desde el equipo servidor. Úsalas con cuidado.').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    clear_wifi_button = ui.button('Borrar datos de WiFi').props('outline color=negative no-caps')
                    clear_history_button = ui.button('Borrar historial de mediciones').props('unelevated color=negative no-caps')

    async def refresh_sensor_options() -> None:
        nonlocal selected_device_id
        devices = await ensure_active_devices()
        options = active_device_options()
        stored_device_id = str(app.storage.user.get('selected_device_id') or '') or None
        if stored_device_id in options:
            selected_device_id = stored_device_id
        elif selected_device_id not in options:
            selected_device_id = next(iter(options)) if options else None

        sensor_select.options = options
        sensor_select.value = selected_device_id
        sensor_select.update()

        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
            active = next((item for item in devices if item.get('device_id') == selected_device_id), None)
            selected_host = str((active or {}).get('host') or host_for_device(selected_device_id))
            selected_host_info.set_text(f'Host detectado: {selected_host}')
        else:
            app.storage.user.pop('selected_device_id', None)
            selected_host_info.set_text('No hay EcoSensores activos detectados todavía.')

    async def selected_host() -> tuple[str | None, str | None]:
        if not selected_device_id:
            await refresh_sensor_options()
        if not selected_device_id:
            ui.notify('No hay EcoSensor seleccionado.', color='negative')
            return None, None

        active = await ensure_device_active(selected_device_id)
        host = str((active or {}).get('host') or host_for_device(selected_device_id))
        if not host:
            ui.notify('No se encontró el host del EcoSensor seleccionado.', color='negative')
            return selected_device_id, None
        return selected_device_id, host

    async def connect() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return

        detected = await probe_host(host, timeout=1.5)
        if not detected:
            ui.notify(f'No se pudo conectar a {device_id}. Revisa red/mDNS.', color='negative')
            return

        detected_host = str(detected.get('host') or host)
        result = await sync_time_if_needed(detected_host, timeout=3.0)
        if result.get('synced'):
            ui.notify(f'{device_id} conectado y fecha/hora sincronizada.', color='positive')
        elif result.get('ok'):
            ui.notify(f'{device_id} conectado con fecha/hora válida.', color='positive')
        else:
            ui.notify(f'{device_id} conectado; la hora no se pudo sincronizar, pero se guardó para mediciones.', color='warning')

        remember_host(detected_host, str(detected.get('device_id') or device_id))
        app.storage.user['selected_device_id'] = str(detected.get('device_id') or device_id)
        await refresh_sensor_options()

    async def clear_wifi() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar credenciales WiFi de {device_id}?')
            ui.label('El ESP32 reiniciará y volverá al modo de configuración WiFi.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await delete_json(build_endpoints(host)['wifi_clear'])
                    if result.get('ok'):
                        ui.notify(f'Credenciales WiFi borradas en {device_id}.', color='positive')
                    else:
                        ui.notify(f'No se pudo borrar WiFi: {result.get("data")}', color='negative')

                ui.button('Borrar WiFi', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def clear_history() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar TODO el historial de mediciones de {device_id}?')
            ui.label('Se borrará el CSV de la SD del ESP32 seleccionado y su base local SQLite del servidor.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await delete_json(build_endpoints(host)['readings_clear'])
                    if not result.get('ok'):
                        ui.notify(f'No se pudo borrar CSV del ESP32: {result.get("data")}', color='negative')
                        return
                    detected = await probe_host(host, timeout=1.5)
                    target_device_id = str((detected or {}).get('device_id') or device_id)
                    deleted = clear_measurements(target_device_id)
                    ui.notify(f'Historial de {target_device_id} borrado. Filas locales eliminadas: {deleted}.', color='positive')
                    await refresh_sensor_options()

                ui.button('Borrar historial', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def on_sensor_change(event: Any) -> None:
        nonlocal selected_device_id
        selected_device_id = str(event.value or '') or None
        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
        else:
            app.storage.user.pop('selected_device_id', None)
        await refresh_sensor_options()

    sensor_select.on_value_change(on_sensor_change)
    refresh_button.on('click', refresh_sensor_options)
    connect_button.on('click', connect)
    clear_wifi_button.on('click', clear_wifi)
    clear_history_button.on('click', clear_history)
    ui.timer(0.1, refresh_sensor_options, once=True)
