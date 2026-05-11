import csv
import io
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
    source_id INTEGER,
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
'''


def ensure_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(measurements)')}
        if 'source_id' not in columns:
            conn.execute('ALTER TABLE measurements ADD COLUMN source_id INTEGER')
        conn.execute(
            '''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_device_timestamp
            ON measurements(device_id, device_timestamp)
            WHERE source_id IS NULL AND device_timestamp IS NOT NULL AND device_timestamp != ''
            '''
        )
        conn.execute(
            '''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_measurements_device_source_id
            ON measurements(device_id, source_id)
            WHERE source_id IS NOT NULL
            '''
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_measurements_received_at ON measurements(received_at)')


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


def _source_id_from_row(row: dict[str, Any]) -> int | None:
    return _int_or_none(row.get('measurement_id') or row.get('source_id'))


def _measurement_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'id': row['device_id'],
        'host': row['host'],
        'timestamp': row['device_timestamp'],
        'received_at': row['received_at'],
        'measurement_id': row['source_id'],
        'pm1p0': row['pm1p0'],
        'pm2p5': row['pm2p5'],
        'pm4p0': row['pm4p0'],
        'pm10p0': row['pm10p0'],
        'voc': row['voc'],
        'nox': row['nox'],
        'co2': row['co2'],
        'temp': row['temp'],
        'hum': row['hum'],
        'window_s': row['window_s'],
    }


def get_latest_measurement() -> dict[str, Any] | None:
    ensure_db()
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT device_id, host, device_timestamp, received_at, source_id,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum, window_s
            FROM measurements
            ORDER BY COALESCE(source_id, id) DESC, id DESC
            LIMIT 1
            '''
        ).fetchone()
    return _measurement_row_to_dict(row) if row else None


def latest_source_id(device_id: str = 'ecosensor01') -> int:
    ensure_db()
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        value = conn.execute(
            'SELECT COALESCE(MAX(source_id), 0) FROM measurements WHERE device_id = ?',
            (device_id,),
        ).fetchone()[0]
    return int(value or 0)


def _split_device_timestamp(timestamp: str | None) -> tuple[str, str]:
    value = (timestamp or '').strip()
    if not value:
        return '', ''
    if 'T' in value:
        date_part, time_part = value.split('T', 1)
        return date_part, time_part.rstrip('Z').split('+', 1)[0].split('-', 1)[0]
    if ' ' in value:
        date_part, time_part = value.split(' ', 1)
        return date_part, time_part.rstrip('Z')
    return value, ''


def _graph_row(row: sqlite3.Row) -> dict[str, Any]:
    fecha, hora = _split_device_timestamp(row['device_timestamp'])
    return {
        '_row_id': row['source_id'] if row['source_id'] is not None else row['id'],
        'id': row['device_id'],
        'device_id': row['device_id'],
        'fecha': fecha,
        'hora': hora,
        'pm1p0': row['pm1p0'],
        'pm2p5': row['pm2p5'],
        'pm4p0': row['pm4p0'],
        'pm10p0': row['pm10p0'],
        'voc': row['voc'],
        'nox': row['nox'],
        'co2': row['co2'],
        'temp': row['temp'],
        'hum': row['hum'],
    }


def graph_latest_row() -> dict[str, Any] | None:
    ensure_db()
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM measurements
            ORDER BY COALESCE(source_id, id) DESC, id DESC
            LIMIT 1
            '''
        ).fetchone()
    return _graph_row(row) if row else None


def graph_rows_history(limit: int = 5000) -> list[dict[str, Any]]:
    ensure_db()
    limit = max(1, min(20000, int(limit)))
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM (
                SELECT id, source_id, device_id, device_timestamp,
                       pm1p0, pm2p5, pm4p0, pm10p0,
                       voc, nox, co2, temp, hum
                FROM measurements
                ORDER BY COALESCE(source_id, id) DESC, id DESC
                LIMIT ?
            ) t
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            ''',
            (limit,),
        ).fetchall()
    return [_graph_row(row) for row in rows]


def graph_rows_since(row_id: int, limit: int = 500) -> list[dict[str, Any]]:
    ensure_db()
    row_id = max(0, int(row_id))
    limit = max(1, min(20000, int(limit)))
    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM measurements
            WHERE COALESCE(source_id, id) > ?
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            LIMIT ?
            ''',
            (row_id, limit),
        ).fetchall()
    return [_graph_row(row) for row in rows]


def measurements_csv_text() -> str:
    ensure_db()
    output = io.StringIO()
    fieldnames = [
        'id', 'device_id', 'Fecha de medicion', 'Hora de medicion',
        'PM1.0', 'PM2.5', 'PM4.0', 'PM10.0',
        'VOC', 'NOx', 'CO2', 'Temperatura', 'Humedad',
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    with sqlite3.connect(MEASUREMENTS_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''
            SELECT id, source_id, device_id, device_timestamp,
                   pm1p0, pm2p5, pm4p0, pm10p0,
                   voc, nox, co2, temp, hum
            FROM measurements
            ORDER BY COALESCE(source_id, id) ASC, id ASC
            '''
        )
        for row in rows:
            date_part, time_part = _split_device_timestamp(row['device_timestamp'])
            writer.writerow({
                'id': row['source_id'] if row['source_id'] is not None else row['id'],
                'device_id': row['device_id'],
                'Fecha de medicion': date_part,
                'Hora de medicion': time_part,
                'PM1.0': row['pm1p0'],
                'PM2.5': row['pm2p5'],
                'PM4.0': row['pm4p0'],
                'PM10.0': row['pm10p0'],
                'VOC': row['voc'],
                'NOx': row['nox'],
                'CO2': row['co2'],
                'Temperatura': row['temp'],
                'Humedad': row['hum'],
            })

    return output.getvalue()


def save_measurement(host: str, row: dict[str, Any]) -> bool:
    """Guarda una medición válida. Devuelve True si insertó una fila nueva."""
    ensure_db()
    received_at = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    device_id = str(row.get('id') or row.get('device_id') or '').strip() or 'ecosensor01'
    device_timestamp = row.get('timestamp') or None
    source_id = _source_id_from_row(row)

    values = {
        'device_id': device_id,
        'host': host,
        'device_timestamp': device_timestamp,
        'received_at': received_at,
        'source_id': source_id,
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
                device_id, host, device_timestamp, received_at, source_id,
                pm1p0, pm2p5, pm4p0, pm10p0,
                voc, nox, co2, temp, hum, window_s
            ) VALUES (
                :device_id, :host, :device_timestamp, :received_at, :source_id,
                :pm1p0, :pm2p5, :pm4p0, :pm10p0,
                :voc, :nox, :co2, :temp, :hum, :window_s
            )
            ''',
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
