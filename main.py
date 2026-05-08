"""Punto de entrada para EcoSensor Servidor.

La aplicación queda organizada por módulos:
- pages/: pantallas NiceGUI
- services/: comunicación HTTP con el ESP32
- storage/: persistencia local
- shared/: estilos y utilidades de presentación
"""

from nicegui import app, ui

from config import STATIC_DIR, UI_HOST, UI_PORT
from services.mdns_service import start_mdns_service
import pages.connect_page  # registra / y /config
import pages.dashboard_page  # registra /dashboard

app.add_static_files('/static', STATIC_DIR)
start_mdns_service()

ui.run(host=UI_HOST, port=UI_PORT, title='EcoSensor Servidor', reload=False)
