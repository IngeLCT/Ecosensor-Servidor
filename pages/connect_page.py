from typing import Any

from fastapi import Request
from nicegui import Client, app, ui

from services.device_registry import active_device_options, ensure_active_devices, ensure_device_active, forget_device, host_for_device, probe_host, registry_revision, remember_host
from services.esp_client import sync_time_if_needed
from services.main_window import register_main_window
from services.measurement_sync import coordinated_clear_history
from services.ota_manager import ota_snapshot, start_device_ota, start_device_web_assets_update
from services.wifi_manager import clear_device_wifi
from shared.formatters import device_display_name
from shared.styles import add_styles

LOCAL_CLIENTS = {'127.0.0.1', '::1', 'localhost'}


def is_local_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ''
    return client_host in LOCAL_CLIENTS


@ui.page('/')
async def index(request: Request, client: Client) -> None:
    await register_main_window(request, client)
    ui.navigate.to('/dashboard')


@ui.page('/config')
async def config_page(request: Request, client: Client) -> None:
    await register_main_window(request, client)
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
    seen_registry_revision = {'value': registry_revision()}

    with ui.element('div').classes('connect-shell'):
        with ui.element('div').classes('connect-card'):
            with ui.element('div').classes('brand-header'):
                ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
                ui.label('EcoSensor®').classes('brand-name')
            with ui.element('div').classes('connect-box'):
                ui.label('Seleccione el EcoSensor a configurar').classes('connect-label')
                sensor_select = ui.select({}, value=None).props('outlined dense').classes('w-full connect-input device-select')
                selected_host_info = ui.label('').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    refresh_button = ui.button('Actualizar lista').props('unelevated no-caps').classes('secondary-button action-button')
                    connect_button = ui.button('Sincronizar hora').props('unelevated no-caps').classes('connect-button action-button')
                ui.button('Ir al dashboard', on_click=lambda: ui.navigate.to('/dashboard')).props('flat no-caps').classes('dashboard-link')


            with ui.element('div').classes('connect-box'):
                ui.label('Mantenimiento').classes('connect-label')
                ui.label('Acciones disponibles solo desde el equipo servidor. Úsalas con cuidado.').classes('connect-label')
                with ui.row().classes('justify-center gap-3'):
                    clear_wifi_button = ui.button('Borrar datos de WiFi').props('unelevated color=negative text-color=white no-caps').classes('danger-outline-button action-button')
                    clear_history_button = ui.button('Borrar historial de mediciones').props('unelevated color=negative text-color=white no-caps').classes('danger-button action-button')

            with ui.element('div').classes('connect-box'):
                ui.label('Actualización OTA local').classes('connect-label')
                ota_toggle_button = ui.button('Mostrar opciones OTA', icon='system_update_alt').props('unelevated no-caps').classes('ota-toggle-button action-button')
                ota_panel = ui.column().classes('w-full gap-3 ota-panel')
                ota_panel.visible = False
                with ota_panel:
                    ui.label('El servidor ordena al EcoSensor descargar su .bin desde esta red local.').classes('connect-label')
                    refresh_ota_button = ui.button('Actualizar estado OTA').props('unelevated no-caps').classes('secondary-button action-button w-full')
                    ota_auto_info = ui.label('').classes('connect-label ota-auto-info')
                    ota_container = ui.column().classes('w-full gap-2')

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

        display_name = device_display_name(device_id)
        detected = await probe_host(host, timeout=1.5)
        if not detected:
            ui.notify(f'No se pudo conectar a {display_name}. Revisa red/mDNS.', color='negative')
            return

        detected_host = str(detected.get('host') or host)
        result = await sync_time_if_needed(detected_host, timeout=3.0)
        if result.get('synced'):
            ui.notify(f'{display_name} conectado y fecha/hora sincronizada.', color='positive')
        elif result.get('ok'):
            ui.notify(f'{display_name} conectado con fecha/hora válida.', color='positive')
        else:
            ui.notify(f'{display_name} conectado; la hora no se pudo sincronizar, pero se guardó para mediciones.', color='warning')

        remember_host(detected_host, str(detected.get('device_id') or device_id))
        app.storage.user['selected_device_id'] = str(detected.get('device_id') or device_id)
        await refresh_sensor_options()

    async def clear_wifi() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        display_name = device_display_name(device_id)
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar credenciales WiFi de {display_name}?')
            ui.label(f'{display_name} reiniciará y volverá al modo de configuración WiFi.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await clear_device_wifi(device_id, host)
                    if result.get('ok'):
                        forget_device(device_id)
                        if app.storage.user.get('selected_device_id') == device_id:
                            app.storage.user.pop('selected_device_id', None)
                        if result.get('confirmed'):
                            ui.notify(f'Credenciales WiFi borradas en {device_display_name(device_id)}. Quitado de las listas activas.', color='positive')
                        else:
                            ui.notify(
                                f'Orden de borrado enviada a {device_display_name(device_id)}. '
                                'El equipo cortó la conexión al reiniciarse; verifica que aparezca su red de configuración.',
                                color='warning',
                            )
                        await refresh_sensor_options()
                        await refresh_ota_status(rebuild=True)
                    else:
                        ui.notify(f'No se pudo borrar WiFi: {result.get("message") or result.get("error")}', color='negative')

                ui.button('Borrar WiFi', on_click=confirm).props('unelevated color=negative')
        dialog.open()

    async def clear_history() -> None:
        device_id, host = await selected_host()
        if not device_id or not host:
            return
        display_name = device_display_name(device_id)
        with ui.dialog() as dialog, ui.card():
            ui.label(f'¿Borrar TODO el historial de mediciones de {display_name}?')
            ui.label(f'Se borrará el CSV de la SD de {display_name} y su base local SQLite del servidor.')
            with ui.row().classes('justify-end gap-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')

                async def confirm() -> None:
                    dialog.close()
                    result = await coordinated_clear_history(device_id)
                    if not result.get('ok'):
                        ui.notify(f'No se pudo completar el borrado coordinado de {display_name}: {result.get("error")}', color='negative')
                        return
                    target_device_id = str(result.get('device_id') or device_id)
                    deleted = int(result.get('deleted') or 0)
                    ui.notify(f'Historial de {device_display_name(target_device_id)} borrado. Filas locales eliminadas: {deleted}.', color='positive')
                    await refresh_sensor_options()

                ui.button('Borrar historial', on_click=confirm).props('unelevated color=negative')
        dialog.open()


    ota_auto_refresh = {'remaining': 0, 'device_id': ''}
    ota_cards: dict[str, dict[str, Any]] = {}

    def _ota_state_text(item: dict[str, Any]) -> str:
        state_data = item.get('ota_status') if isinstance(item.get('ota_status'), dict) else {}
        state = str(state_data.get('state') or 'sin respuesta')
        progress = state_data.get('progress_pct')
        progress_text = f' | {float(progress):.0f}%' if isinstance(progress, (int, float)) else ''
        return f'Estado OTA: {state}{progress_text}'

    def _ota_note_text(item: dict[str, Any]) -> str:
        if item.get('version_newer') == 0:
            return 'La versión disponible es igual a la actual; no se actualiza por defecto.'
        if item.get('version_newer') == -1:
            return 'La versión disponible es menor que la actual; no se actualiza por defecto.'
        if not item.get('manifest_ok'):
            return 'No hay firmware OTA disponible para este dispositivo.'
        return ''

    def _update_ota_card_values(item: dict[str, Any]) -> None:
        device_id = str(item.get('device_id') or '-')
        refs = ota_cards.get(device_id)
        if not refs:
            return
        manifest_text = item.get('available_version') or item.get('manifest_error') or 'sin manifest'
        current = item.get('current_version') or 'desconocida'
        host = item.get('host') or '-'
        refs['title'].set_text(f'{device_display_name(device_id)}  |  host: {host}')
        refs['version'].set_text(f'Versión actual: {current}  |  OTA disponible: {manifest_text}')
        refs['state'].set_text(_ota_state_text(item))
        refs['note'].set_text(_ota_note_text(item))
        button = refs['button']
        if item.get('can_update'):
            button.enable()
        else:
            button.disable()
        button.set_text('Actualizar')

    async def refresh_ota_status(*, rebuild: bool = True, only_device_id: str | None = None) -> dict[str, Any]:
        snapshot = await ota_snapshot()
        devices = snapshot.get('devices') if isinstance(snapshot, dict) else []
        if not isinstance(devices, list):
            devices = []

        if not rebuild:
            target = (only_device_id or '').strip().lower()
            for item in devices:
                if not isinstance(item, dict):
                    continue
                item_device_id = str(item.get('device_id') or '').strip().lower()
                if target and item_device_id != target:
                    continue
                _update_ota_card_values(item)
            return snapshot

        ota_container.clear()
        ota_cards.clear()
        if not devices:
            with ota_container:
                ui.label('No hay EcoSensores activos detectados.').classes('connect-label')
            return snapshot

        with ota_container:
            for item in devices:
                if not isinstance(item, dict):
                    continue
                device_id = str(item.get('device_id') or '-')

                async def update_device(did: str = device_id) -> None:
                    result = await start_device_ota(did)
                    if result.get('ok'):
                        ui.notify(f'OTA iniciada para {did}.', color='positive')
                        start_ota_auto_refresh(did)
                    else:
                        ui.notify(f'No se pudo iniciar OTA para {did}: {result.get("error")}', color='negative')
                    await refresh_ota_status(rebuild=False, only_device_id=did)

                async def update_web_assets(did: str = device_id) -> None:
                    result = await start_device_web_assets_update(did)
                    if result.get('ok'):
                        response = result.get('response') if isinstance(result.get('response'), dict) else {}
                        saved = response.get('saved') if isinstance(response, dict) else None
                        total = response.get('total') if isinstance(response, dict) else None
                        detail = f' ({saved}/{total})' if saved is not None and total is not None else ''
                        ui.notify(f'Archivos web enviados a {did}{detail}.', color='positive')
                    else:
                        ui.notify(f'No se pudieron enviar archivos web a {did}: {result.get("error")}', color='negative')
                    await refresh_ota_status(rebuild=False, only_device_id=did)

                with ui.card().classes('w-full'):
                    title_label = ui.label('').classes('connect-label')
                    version_label = ui.label('').classes('connect-label')
                    state_label = ui.label('').classes('connect-label')
                    note_label = ui.label('').classes('connect-label')
                    with ui.row().classes('gap-2 items-center'):
                        update_button = ui.button('Actualizar', on_click=update_device).props('unelevated no-caps')
                        ui.button('Actualizar web', on_click=update_web_assets).props('unelevated no-caps').classes('secondary-button')
                    ota_cards[device_id] = {
                        'title': title_label,
                        'version': version_label,
                        'state': state_label,
                        'note': note_label,
                        'button': update_button,
                    }
                    _update_ota_card_values(item)

    async def on_sensor_change(event: Any) -> None:
        nonlocal selected_device_id
        selected_device_id = str(event.value or '') or None
        if selected_device_id:
            app.storage.user['selected_device_id'] = selected_device_id
        else:
            app.storage.user.pop('selected_device_id', None)
        await refresh_sensor_options()

    def start_ota_auto_refresh(device_id: str) -> None:
        ota_auto_refresh['remaining'] = 60
        ota_auto_refresh['device_id'] = device_id
        ota_auto_info.set_text(f'Actualizando estado OTA de {device_display_name(device_id)} automáticamente cada 2 s...')
        if not ota_panel.visible:
            ota_panel.visible = True
            ota_panel.update()
            ota_toggle_button.set_text('Ocultar opciones OTA')
        ota_auto_timer.activate()

    async def auto_refresh_ota_status() -> None:
        remaining = int(ota_auto_refresh.get('remaining') or 0)
        device_id = str(ota_auto_refresh.get('device_id') or '')
        if remaining <= 0:
            ota_auto_timer.deactivate()
            ota_auto_info.set_text('')
            return
        if not ota_panel.visible:
            ota_auto_timer.deactivate()
            return

        snapshot = await refresh_ota_status(rebuild=False, only_device_id=device_id)
        devices = snapshot.get('devices') if isinstance(snapshot, dict) else []
        target = next((item for item in devices if isinstance(item, dict) and item.get('device_id') == device_id), None)
        state_data = target.get('ota_status') if isinstance(target, dict) and isinstance(target.get('ota_status'), dict) else {}
        version_newer = target.get('version_newer') if isinstance(target, dict) else None
        ota_state = str(state_data.get('state') or '')
        if version_newer == 0 or ota_state in {'success', 'idle'} and version_newer == 0:
            ota_auto_timer.deactivate()
            ota_auto_refresh['remaining'] = 0
            ota_auto_info.set_text(f'{device_display_name(device_id)} ya está actualizado. Actualización automática detenida.')
            return

        remaining -= 1
        ota_auto_refresh['remaining'] = remaining
        if remaining <= 0:
            ota_auto_timer.deactivate()
            ota_auto_info.set_text('')
        else:
            seconds_left = remaining * 2
            ota_auto_info.set_text(f'Actualizando solo estado OTA de {device_display_name(device_id)} cada 2 s ({seconds_left} s restantes)...')

    ota_auto_timer = ui.timer(2.0, auto_refresh_ota_status, active=False)

    async def refresh_options_if_registry_changed() -> None:
        current = registry_revision()
        if current != seen_registry_revision['value']:
            seen_registry_revision['value'] = current
            await refresh_sensor_options()
            if ota_panel.visible:
                await refresh_ota_status(rebuild=True)

    sensor_select.on_value_change(on_sensor_change)
    async def toggle_ota_panel() -> None:
        ota_panel.visible = not ota_panel.visible
        ota_panel.update()
        ota_toggle_button.set_text('Ocultar opciones OTA' if ota_panel.visible else 'Mostrar opciones OTA')
        if ota_panel.visible:
            await refresh_ota_status()

    refresh_button.on('click', refresh_sensor_options)
    refresh_ota_button.on('click', refresh_ota_status)
    ota_toggle_button.on('click', toggle_ota_panel)
    connect_button.on('click', connect)
    clear_wifi_button.on('click', clear_wifi)
    clear_history_button.on('click', clear_history)
    ui.timer(1.0, refresh_options_if_registry_changed)
    ui.timer(0.1, refresh_sensor_options, once=True)
