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
- envío interno de fecha y hora del sistema al ESP32 cuando `/status` responde `time_valid: false`
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

## Persistencia local

El host del ESP queda guardado en:

- `data/settings.json`

## Próximos pasos sugeridos

- persistir lecturas en base de datos
- soportar múltiples dispositivos
- agregar historial de mediciones
