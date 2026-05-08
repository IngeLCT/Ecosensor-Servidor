import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / 'data'
STATIC_DIR = APP_DIR / 'static'
SETTINGS_FILE = DATA_DIR / 'settings.json'

DEVICE_ID = 'ecosensor01'
UI_HOST = os.getenv('ECOSENSOR_SERVER_HOST', '0.0.0.0')
UI_PORT = int(os.getenv('ECOSENSOR_SERVER_PORT', '8765'))

DEFAULT_SETTINGS = {
    'esp_host': '',
    'device_id': DEVICE_ID,
}
