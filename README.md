# EcoSensor Servidor

Servidor NiceGUI para visualizar mediciones del ESP32 EcoSensor.

## Estado actual

Esta versión incluye:

- pantalla inicial con IP/mDNS y botón **Conectar**
- consulta automática al ESP32 por estos endpoints:
  - `GET /status`
  - `GET /lecturas`
  - `POST /config`
- envío interno de fecha y hora del sistema al ESP32 cuando `/status` responde `time_valid: false`
- pantalla `/dashboard` para visualizar mediciones con estilo basado en `web/EcoSensor01`
- guardado local del host del ESP en `data/settings.json`

## Estructura del proyecto

```text
main.py                 # punto de entrada NiceGUI
config.py               # rutas, host/puerto y constantes globales
pages/                  # pantallas NiceGUI
  connect_page.py       # pantalla inicial de conexión
  dashboard_page.py     # dashboard de mediciones
services/
  esp_client.py         # cliente HTTP hacia endpoints del ESP32
storage/
  settings_store.py     # carga/guardado de data/settings.json
shared/
  formatters.py         # formato de datos para UI
  styles.py             # CSS compartido
static/                 # imágenes usadas por la interfaz
data/                   # configuración local generada en runtime
```

## Arquitectura

El ESP32 expone los endpoints HTTP.
El servidor no espera que el ESP32 le mande datos ni que consulte endpoints del servidor.

Flujo normal:

1. El usuario escribe `ecosensor01.local` o la IP del ESP32.
2. El servidor consulta `http://<host>/status`.
3. Si `time_valid` es `false`, el servidor envía:
   - `POST http://<host>/config`
   - payload: `{"date":"DD-MM-YYYY","time":"HH:MM:SS"}`
4. Si el ESP32 confirma `time_valid: true`, se abre `/dashboard`.
5. El dashboard consulta `http://<host>/lecturas` periódicamente.

## Uso esperado

El usuario escribe por ejemplo:

- `192.168.1.50`
- `ecosensor01.local`

La aplicación construye automáticamente:

- `http://<host>/status`
- `http://<host>/lecturas`
- `http://<host>/config`

## Arranque

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Opcionalmente se puede configurar host y puerto del servidor NiceGUI:

```bash
ECOSENSOR_SERVER_HOST=0.0.0.0 ECOSENSOR_SERVER_PORT=8765 python3 main.py
```

## Persistencia local

El host del ESP queda guardado en:

- `data/settings.json`

## Próximos pasos sugeridos

- persistir lecturas en base de datos
- soportar múltiples dispositivos
- agregar historial de mediciones
