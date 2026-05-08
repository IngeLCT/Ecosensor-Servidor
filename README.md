# EcoSensor Servidor

Base inicial del servidor en NiceGUI para interactuar con dispositivos ESP32 EcoSensor.

## Estado actual

Esta versión ya incluye:

- página principal mínima en NiceGUI con solo IP/mDNS y botón **Conectar**
- resolución automática de endpoints locales del dispositivo
  - `/status`
  - `/lecturas`
- pantalla `/dashboard` para visualizar mediciones con estilo basado en `web/EcoSensor01`
- guardado local del host del ESP en `data/settings.json`
- estructura inicial del servidor central
  - `POST /api/v1/ingest`
  - `GET /api/v1/device/{device_id}/config`
  - `GET /api/v1/device/{device_id}/time`

## Uso esperado

El usuario escribe por ejemplo:

- `192.168.1.50`
- `ecosensor01.local`

Al presionar **Conectar**, la aplicación guarda el host, verifica `/status` si está disponible,
deja lista la configuración que consulta el ESP32 desde el servidor y abre `/dashboard`.

La aplicación construye automáticamente:

- `http://<host>/status`
- `http://<host>/lecturas`

La configuración que requiere el ESP32 queda disponible en:

- `GET /api/v1/device/ecosensor01/config`
- `GET /api/v1/device/ecosensor01/time`

## Arranque

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Persistencia local

El host del ESP y parámetros base del servidor quedan guardados en:

- `data/settings.json`

## Endpoints centrales actuales

### `POST /api/v1/ingest`
Recibe el payload enviado por el ESP32 y conserva en memoria la última recepción.

### `GET /api/v1/device/ecosensor01/config`
Devuelve una configuración básica inicial:

- `read_interval_s`
- `upload_interval_s`
- `time_required`

### `GET /api/v1/device/ecosensor01/time`
Devuelve hora UTC actual del servidor en formato ISO8601.

## Próximos pasos sugeridos

- persistir lecturas en base de datos
- soportar múltiples dispositivos
- separar UI, servicios y API
- agregar historial de ingest y panel de monitoreo
- implementar validación del payload recibido por `/api/v1/ingest`
