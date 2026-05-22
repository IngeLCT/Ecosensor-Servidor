"""Captura temporal de muestras temp/hum para calcular offsets.

Se alimenta desde /api/debug/temp-hum-sample y guarda un CSV por EcoSensor.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR

OFFSET_CAPTURE_SAMPLE_COUNT = 241
OFFSET_CAPTURE_DIR = DATA_DIR / 'offset_captures'

CSV_FIELDS = [
    'index',
    'captured_at',
    'device_id',
    'sample_slot',
    'scd40_temp',
    'scd40_hum',
    'sen55_temp',
    'sen55_hum',
    'scd40_offset_valid',
    'scd40_offset',
    'scd40_offset_raw',
    'sen55_offset_valid',
    'sen55_offset',
    'sen55_offset_raw',
]


def _canonical_device_id(device_id: str | None) -> str:
    return str(device_id or '').strip().lower() or 'unknown'


def _display_device_id(device_id: str) -> str:
    canonical = _canonical_device_id(device_id)
    if canonical.startswith('ecosensor'):
        suffix = canonical.removeprefix('ecosensor')
        return f'EcoSensor{suffix}'
    return canonical


def _csv_path(device_id: str) -> Path:
    OFFSET_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    return OFFSET_CAPTURE_DIR / f'{_display_device_id(device_id)}_offset.csv'


@dataclass
class OffsetCaptureState:
    active: bool = False
    complete: bool = False
    device_id: str = ''
    count: int = 0
    target: int = OFFSET_CAPTURE_SAMPLE_COUNT
    filename: str = ''
    path: str = ''
    started_at: str = ''
    completed_at: str = ''
    last_error: str = ''
    _seen_download: bool = field(default=False, repr=False)


_state = OffsetCaptureState()


def start_capture(device_id: str) -> dict[str, Any]:
    """Inicia una captura nueva para device_id, sobrescribiendo CSV anterior."""
    canonical = _canonical_device_id(device_id)
    path = _csv_path(canonical)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()

    global _state
    now = datetime.now(timezone.utc).isoformat()
    _state = OffsetCaptureState(
        active=True,
        complete=False,
        device_id=canonical,
        count=0,
        target=OFFSET_CAPTURE_SAMPLE_COUNT,
        filename=path.name,
        path=str(path),
        started_at=now,
        completed_at='',
        last_error='',
    )
    return snapshot()


def add_sample(payload: dict[str, Any]) -> dict[str, Any]:
    """Agrega una muestra si hay captura activa para ese device_id."""
    if not _state.active or _state.complete:
        return snapshot()

    device_id = _canonical_device_id(str(payload.get('device_id') or ''))
    if device_id != _state.device_id:
        return snapshot()

    if _state.count >= _state.target:
        _state.active = False
        _state.complete = True
        _state.completed_at = datetime.now(timezone.utc).isoformat()
        return snapshot()

    index = _state.count + 1
    row = {
        'index': index,
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'device_id': device_id,
        'sample_slot': payload.get('sample_slot'),
        'scd40_temp': payload.get('scd_temp'),
        'scd40_hum': payload.get('scd_hum'),
        'sen55_temp': payload.get('sen_temp'),
        'sen55_hum': payload.get('sen_hum'),
        'scd40_offset_valid': payload.get('scd_temp_offset_valid'),
        'scd40_offset': payload.get('scd_temp_offset'),
        'scd40_offset_raw': payload.get('scd_temp_offset_raw'),
        'sen55_offset_valid': payload.get('sen55_offset_valid'),
        'sen55_offset': payload.get('sen55_offset'),
        'sen55_offset_raw': payload.get('sen55_offset_raw'),
    }

    try:
        with Path(_state.path).open('a', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writerow(row)
        _state.count = index
        _state.last_error = ''
    except Exception as exc:  # pragma: no cover - protección runtime
        _state.last_error = str(exc)
        return snapshot()

    if _state.count >= _state.target:
        _state.active = False
        _state.complete = True
        _state.completed_at = datetime.now(timezone.utc).isoformat()

    return snapshot()


def snapshot() -> dict[str, Any]:
    progress = (_state.count / _state.target) if _state.target else 0.0
    return {
        'active': _state.active,
        'complete': _state.complete,
        'device_id': _state.device_id,
        'count': _state.count,
        'target': _state.target,
        'progress': progress,
        'filename': _state.filename,
        'path': _state.path,
        'started_at': _state.started_at,
        'completed_at': _state.completed_at,
        'last_error': _state.last_error,
        'download_url': f'/api/debug/offset-capture/download?device_id={_state.device_id}' if _state.filename else '',
    }


def file_path_for(device_id: str) -> Path:
    path = _csv_path(_canonical_device_id(device_id))
    if not path.exists():
        raise FileNotFoundError(path)
    return path
