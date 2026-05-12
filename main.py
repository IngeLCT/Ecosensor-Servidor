"""Punto de entrada para EcoSensor Servidor.

La aplicación queda organizada por módulos:
- pages/: pantallas NiceGUI
- services/: comunicación HTTP con el ESP32
- storage/: persistencia local
- shared/: estilos y utilidades de presentación
"""

import asyncio

from fastapi import Query
from fastapi.responses import JSONResponse, Response
from nicegui import app, ui

from config import STATIC_DIR, UI_HOST, UI_PORT
from services.measurement_sync import background_sync_loop
from services.mdns_service import start_mdns_service
from storage.measurements_store import graph_latest_row, graph_rows_history, graph_rows_since, measurements_csv_text
import pages.connect_page  # registra / y /config
import pages.dashboard_page  # registra /dashboard
import pages.graphs_page  # registra /graficas/*

app.add_static_files('/static', STATIC_DIR)

_background_sync_task: asyncio.Task | None = None


def _start_background_sync() -> None:
    global _background_sync_task
    if _background_sync_task is None or _background_sync_task.done():
        _background_sync_task = asyncio.create_task(background_sync_loop())


app.on_startup(_start_background_sync)


@app.get('/api/measurements.csv')
def download_measurements_csv(device_id: str | None = Query(default=None)) -> Response:
    filename_id = (device_id or 'ecosensor01').strip() or 'ecosensor01'
    return Response(
        content=measurements_csv_text(device_id),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="ecosensor_mediciones_{filename_id}.csv"'},
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

ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False)
