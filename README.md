# EcoSensor Servidor

Servidor NiceGUI para visualizar mediciones del ESP32 EcoSensor.

## Estado actual

Esta versión incluye:

- acceso de usuarios directo al dashboard en `/`
- dashboard público en `/dashboard`
- configuración local protegida en `/config`, accesible solo desde el equipo servidor
- anuncio mDNS como `ecosensor-servidor.local:8765`
- consulta automática al ESP32 por estos endpoints:
  - `GET /status`
  - `GET /lecturas`
  - `POST /config`
  - `POST /ota/update`
  - `GET /ota/status`
- envío interno de fecha y hora del sistema al ESP32 cuando `/status` responde `time_valid: false`
- OTA local sin hosting externo: el servidor almacena y sirve `.bin` por `device_id`
- guardado local del host del ESP en `data/settings.json`

## Estructura del proyecto

```text
main.py                 # punto de entrada NiceGUI
config.py               # rutas, host/puerto, mDNS y constantes globales
pages/                  # pantallas NiceGUI
  connect_page.py       # redirección / y configuración local /config
  dashboard_page.py     # dashboard de mediciones
services/
  esp_client.py         # cliente HTTP hacia endpoints del ESP32
  mdns_service.py       # anuncio mDNS del servidor
storage/
  settings_store.py     # carga/guardado de data/settings.json
shared/
  formatters.py         # formato de datos para UI
  styles.py             # CSS compartido
static/                 # imágenes usadas por la interfaz
firmware/               # binarios OTA por device_id
  ecosensor02/
    manifest.json
    ecosensor02_v1.0.1.bin
data/                   # configuración local generada en runtime
```

## Arquitectura

El ESP32 expone los endpoints HTTP.
El servidor no espera que el ESP32 le mande datos ni que consulte endpoints del servidor.

Flujo normal:

1. Windows corre `Ecosensor-Servidor`.
2. El servidor anuncia `ecosensor-servidor.local:8765`.
3. Celulares/PCs entran a `http://ecosensor-servidor.local:8765/`.
4. `/` redirige directo a `/dashboard`.
5. El dashboard lee el ESP configurado en `data/settings.json`.
6. Solo el equipo servidor abre `http://localhost:8765/config` para cambiar el ESP, por ejemplo `ecosensor01.local`.

## Configuración del ESP

Desde el equipo servidor:

```text
http://localhost:8765/config
```

El usuario escribe por ejemplo:

- `192.168.1.50`
- `ecosensor01.local`

La aplicación construye automáticamente:

- `http://<host>/status`
- `http://<host>/lecturas`
- `http://<host>/config`

Si `time_valid` es `false`, el servidor envía:

- `POST http://<host>/config`
- payload: `{"date":"DD-MM-YYYY","time":"HH:MM:SS"}`

## Arranque

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Opcionalmente se puede configurar host, puerto y nombre mDNS:

```bash
ECOSENSOR_SERVER_HOST=0.0.0.0 ECOSENSOR_SERVER_PORT=8765 ECOSENSOR_MDNS_HOSTNAME=ecosensor-servidor python3 main.py
```

## OTA local

La OTA local funciona sin hosting externo:

1. El servidor detecta EcoSensores activos.
2. Para cada `device_id`, busca firmware en `firmware/<device_id>/manifest.json`.
3. Desde `http://localhost:8765/config`, la sección **Actualización OTA local** muestra:
   - `device_id`
   - host/IP
   - versión actual reportada por el ESP32
   - versión disponible en manifest
   - estado/progreso OTA
   - botón **Actualizar** cuando aplica
4. Al actualizar, el servidor envía al ESP32:
   - `POST http://<host_esp>/ota/update`
   - JSON con `device_id`, `version`, `firmware_url` y `sha256`
5. El `firmware_url` apunta al propio servidor usando una IP LAN accesible desde el ESP32.
6. El ESP32 descarga el `.bin`, lo escribe en la partición OTA libre y reinicia.

### Estructura de firmware

Cada EcoSensor tiene su propio directorio:

```text
firmware/
  ecosensor01/
    manifest.json
    ecosensor01_v1.0.1.bin
  ecosensor02/
    manifest.json
    ecosensor02_v1.0.1.bin
```

Manifest ejemplo:

```json
{
  "device_id": "ecosensor02",
  "version": "1.0.1",
  "filename": "ecosensor02_v1.0.1.bin",
  "enabled": true,
  "sha256": "...",
  "release_date": "2026-05-20"
}
```

Para publicar una nueva versión basta con copiar el `.bin` al directorio del `device_id` y actualizar `manifest.json`.

### Rutas OTA del servidor

- `GET /firmware/<device_id>/manifest.json`
- `GET /firmware/<device_id>/<archivo.bin>`
- `GET /api/ota/devices`
- `POST /api/ota/update?device_id=<device_id>`

### Requisito inicial importante

Un EcoSensor con firmware antiguo de partición **Single App Large** no puede actualizarse por OTA hasta flashearse una primera vez por USB/cable con la nueva tabla OTA (`ota_0`, `ota_1`, `otadata`). Después de esa migración, las siguientes actualizaciones pueden hacerse desde la interfaz local.

## Persistencia local

El host del ESP queda guardado en:

- `data/settings.json`

## Próximos pasos sugeridos

- persistir lecturas en base de datos
- soportar múltiples dispositivos
- agregar historial de mediciones
