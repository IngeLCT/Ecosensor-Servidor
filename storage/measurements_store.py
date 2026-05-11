import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, MEASUREMENTS_DB_FILE


SCHEMA = '''
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    host TEXT NOT NULL,
    device_timestamp TEXT,
    received_at TEXT NOT NULL,
    pm1p0 REAL,
    pm2p5 REAL,
    pm4p0 REAL,
    pm10p0 REAL,
    voc REAL,
    nox REAL,
    co2 REAL,
    temp REAL,
    hum REAL,
    window_s INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_device_timestamp
ON measurements(device_id, device_timestamp)
WHERE device_timestamp IS NOT NULL AND device_timestamp != '';

CREATE INDEX IF NOT EXISTS idx_measurements_received_at
ON measurements(received_at);
'''


def ensure_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.executescript(SCHEMA)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def save_measurement(host: str, row: dict[str, Any]) -> bool:
    """Guarda una medición válida. Devuelve True si insertó una fila nueva."""
    ensure_db()
    received_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    device_id = str(row.get('id') or '').strip() or 'ecosensor01'
    device_timestamp = row.get('timestamp') or None

    values = {
        'device_id': device_id,
        'host': host,
        'device_timestamp': device_timestamp,
        'received_at': received_at,
        'pm1p0': _float_or_none(row.get('pm1p0')),
        'pm2p5': _float_or_none(row.get('pm2p5')),
        'pm4p0': _float_or_none(row.get('pm4p0')),
        'pm10p0': _float_or_none(row.get('pm10p0')),
        'voc': _float_or_none(row.get('voc')),
        'nox': _float_or_none(row.get('nox')),
        'co2': _float_or_none(row.get('co2')),
        'temp': _float_or_none(row.get('temp')),
        'hum': _float_or_none(row.get('hum')),
        'window_s': _int_or_none(row.get('window_s')),
    }

    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        cursor = conn.execute(
            '''
            INSERT OR IGNORE INTO measurements (
                device_id, host, device_timestamp, received_at,
                pm1p0, pm2p5, pm4p0, pm10p0,
                voc, nox, co2, temp, hum, window_s
            ) VALUES (
                :device_id, :host, :device_timestamp, :received_at,
                :pm1p0, :pm2p5, :pm4p0, :pm10p0,
                :voc, :nox, :co2, :temp, :hum, :window_s
            )
            ''',
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
