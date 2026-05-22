"""Punto de entrada para EcoSensor Servidor.

La aplicación queda organizada por módulos:
- pages/: pantallas NiceGUI
- services/: comunicación HTTP con el ESP32
- storage/: persistencia local
- shared/: estilos y utilidades de presentación
"""

import asyncio
import importlib

from services.windows_asyncio import install_connection_reset_filter, install_windows_selector_policy

install_windows_selector_policy()

from fastapi import Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from nicegui import app, ui

from config import STATIC_DIR, UI_HOST, UI_PORT
from services.device_registry import active_devices, probe_failures
from services.measurement_sync import background_sync_loop, debug_device_snapshot
from services.ota_manager import OtaError, firmware_file_path, load_manifest, ota_snapshot, start_device_ota
from services.sensor_diagnostics import log_co2_diagnostics_if_needed, run_scd40_debug_action
from services.sync_debug import sync_debug_snapshot
from services.mdns_service import start_mdns_service
from storage.measurements_store import graph_latest_row, graph_rows_history, graph_rows_since, measurements_csv_text


def _register_pages() -> None:
    """Carga módulos de páginas NiceGUI que registran rutas al importarse."""
    for module_name in ('pages.connect_page', 'pages.dashboard_page', 'pages.graphs_page'):
        importlib.import_module(module_name)


_register_pages()

app.add_static_files('/static', STATIC_DIR)

_background_sync_task: asyncio.Task | None = None


def _start_background_sync() -> None:
    global _background_sync_task
    install_connection_reset_filter()
    if _background_sync_task is None or _background_sync_task.done():
        _background_sync_task = asyncio.create_task(background_sync_loop())


app.on_startup(_start_background_sync)


@app.get('/api/devices')
def devices_status() -> JSONResponse:
    return JSONResponse({'ok': True, 'active': active_devices(), 'failures': probe_failures()})


@app.get('/api/debug/sync')
def debug_sync_events(device_id: str | None = Query(default=None)) -> JSONResponse:
    return JSONResponse(sync_debug_snapshot(device_id))


@app.get('/api/debug/device')
async def debug_device(device_id: str | None = Query(default=None)) -> JSONResponse:
    return JSONResponse(await debug_device_snapshot(device_id))


@app.get('/api/debug/co2')
async def debug_co2(device_id: str = Query(default='ecosensor02')) -> JSONResponse:
    target = (device_id or 'ecosensor02').strip().lower() or 'ecosensor02'
    host = next((item['host'] for item in active_devices() if item.get('device_id') == target), f'{target}.local')
    result = await log_co2_diagnostics_if_needed(target, str(host), force=True)
    return JSONResponse({
        'ok': bool(result.get('ok')),
        'printed': bool(result.get('printed')),
        'device_id': target,
        'host': host,
        'reason': result.get('reason'),
    })


@app.get('/api/debug/scd40')
async def debug_scd40(
    device_id: str = Query(default='ecosensor02'),
    action: str = Query(default='status'),
    offset: float | None = Query(default=None),
) -> JSONResponse:
    target = (device_id or 'ecosensor02').strip().lower() or 'ecosensor02'
    host = next((item['host'] for item in active_devices() if item.get('device_id') == target), f'{target}.local')
    result = await run_scd40_debug_action(target, str(host), action, offset)
    return JSONResponse({
        'ok': bool(result.get('ok')),
        'printed': bool(result.get('printed')),
        'device_id': target,
        'host': host,
        'action': action,
        'diagnostics': result.get('diagnostics'),
        'error': result.get('reason') or result.get('response'),
    })


@app.post('/api/debug/temp-hum-sample')
async def debug_temp_hum_sample(request: Request) -> JSONResponse:
    """Endpoint temporal de debug: recibe una muestra cruda del ESP32 y solo la imprime.

    No guarda en SQLite ni participa en las gráficas. Retirar cuando termine el diagnóstico
    de temperatura/humedad SCD40 vs SEN55.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': f'invalid_json: {exc}'}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({'ok': False, 'error': 'json_object_required'}, status_code=400)

    device_id = str(payload.get('device_id') or 'unknown').strip().lower() or 'unknown'
    print(
        '[ecosensor-temp-hum-sample] '
        f'{device_id} '
        f'sample={payload.get("sample_slot")} '
        f'scd40_temp={payload.get("scd_temp")} scd40_hum={payload.get("scd_hum")} '
        f'sen55_temp={payload.get("sen_temp")} sen55_hum={payload.get("sen_hum")} '
        f'scd40_offset_valid={payload.get("scd_temp_offset_valid")} '
        f'scd40_offset={payload.get("scd_temp_offset")} '
        f'scd40_offset_raw={payload.get("scd_temp_offset_raw")} '
        f'sen55_offset_valid={payload.get("sen55_offset_valid")} '
        f'sen55_offset={payload.get("sen55_offset")} '
        f'sen55_offset_raw={payload.get("sen55_offset_raw")}',
        flush=True,
    )
    return JSONResponse({'ok': True, 'debug': 'temp_hum_sample_printed'})


@app.get('/api/ota/devices')
async def api_ota_devices() -> JSONResponse:
    return JSONResponse(await ota_snapshot())


@app.post('/api/ota/update')
async def api_ota_update(device_id: str = Query(...), force: bool = Query(default=False)) -> JSONResponse:
    result = await start_device_ota(device_id, force=force)
    return JSONResponse(result, status_code=200 if result.get('ok') else 400)


@app.get('/firmware/{device_id}/manifest.json')
def firmware_manifest(device_id: str) -> JSONResponse:
    try:
        return JSONResponse(load_manifest(device_id))
    except OtaError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=404)


@app.get('/firmware/{device_id}/{filename}', response_model=None)
def firmware_binary(device_id: str, filename: str):
    try:
        path = firmware_file_path(device_id, filename)
    except OtaError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=404)
    return FileResponse(path, media_type='application/octet-stream', filename=filename)


@app.get('/api/measurements.csv')
def download_measurements_csv(device_id: str | None = Query(default=None)) -> Response:
    filename_id = (device_id or 'ecosensor01').strip() or 'ecosensor01'
    return Response(
        content=measurements_csv_text(device_id),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename_id}_mediciones.csv"'},
    )


@app.get('/api/graph_read')
def graph_read(
    op: str = Query(default='history'),
    id: int = Query(default=0),
    limit: int = Query(default=5000),
    device_id: str | None = Query(default=None),
) -> JSONResponse:
    if op == 'latest':
        return JSONResponse({'ok': True, 'row': graph_latest_row(device_id)})
    if op == 'history':
        return JSONResponse({'ok': True, 'rows': graph_rows_history(limit, device_id)})
    if op == 'since':
        return JSONResponse({'ok': True, 'rows': graph_rows_since(id, limit, device_id)})
    return JSONResponse({'ok': False, 'error': 'unknown_op', 'allowed': 'latest|history|since'}, status_code=400)


start_mdns_service()

ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False, storage_secret='ecosensor-servidor-local')
