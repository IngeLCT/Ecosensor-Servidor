"""Punto de entrada para EcoSensor Servidor.

La aplicación queda organizada por módulos:
- pages/: pantallas NiceGUI
- services/: comunicación HTTP con el ESP32
- storage/: persistencia local
- shared/: estilos y utilidades de presentación
"""

from fastapi import Query
from fastapi.responses import JSONResponse, Response
from nicegui import app, ui

from config import STATIC_DIR, UI_HOST, UI_PORT
from services.mdns_service import start_mdns_service
from storage.measurements_store import graph_latest_row, graph_rows_history, graph_rows_since, measurements_csv_text
import pages.connect_page  # registra / y /config
import pages.dashboard_page  # registra /dashboard
import pages.graphs_page  # registra /graficas/*

app.add_static_files('/static', STATIC_DIR)


@app.get('/api/measurements.csv')
def download_measurements_csv() -> Response:
    return Response(
        content=measurements_csv_text(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="ecosensor_mediciones.csv"'},
    )


@app.get('/api/graph_read')
def graph_read(
    op: str = Query(default='history'),
    id: int = Query(default=0),
    limit: int = Query(default=5000),
) -> JSONResponse:
    if op == 'latest':
        return JSONResponse({'ok': True, 'row': graph_latest_row()})
    if op == 'history':
        return JSONResponse({'ok': True, 'rows': graph_rows_history(limit)})
    if op == 'since':
        return JSONResponse({'ok': True, 'rows': graph_rows_since(id, limit)})
    return JSONResponse({'ok': False, 'error': 'unknown_op', 'allowed': 'latest|history|since'}, status_code=400)


start_mdns_service()

ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False)
