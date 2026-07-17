import hashlib
import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import FIRMWARE_DIR, UI_PORT
from services.device_registry import active_devices, ensure_active_devices, ensure_device_active
from services.esp_client import fetch_ota_status, start_ota_update, start_web_assets_update


class OtaError(ValueError):
    pass

WEB_ASSET_FILENAMES = {'in.htm', 'sc.js', 'st.css', 'lct.png'}


def _server_port() -> int:
    try:
        return int(os.getenv('ECOSENSOR_ACTIVE_PORT', str(UI_PORT)))
    except ValueError:
        return UI_PORT


def web_asset_dir(device_id: str | None = None) -> Path:
    # Los assets de /tabla son compartidos por todos los EcoSensor.
    # Se conserva device_id en la firma para compatibilidad con rutas existentes.
    if device_id:
        _clean_device_id(device_id)
    return FIRMWARE_DIR / 'web'


def web_asset_file_path(device_id: str, filename: str) -> Path:
    _clean_device_id(device_id)
    clean_filename = (filename or '').strip()
    if clean_filename not in WEB_ASSET_FILENAMES:
        raise OtaError('archivo web inválido')
    path = web_asset_dir(device_id) / clean_filename
    if not path.exists() or not path.is_file():
        raise OtaError('archivo web compartido no encontrado')
    return path


def web_assets_payload_for_device(device_id: str, esp_host: str) -> dict[str, Any]:
    device_id = _clean_device_id(device_id)
    server_ip = _local_ip_for_target(esp_host)
    base_url = f'http://{server_ip}:{_server_port()}/firmware/{quote(device_id)}/web'
    files = []
    for name in ('in.htm', 'st.css', 'sc.js', 'lct.png'):
        path = web_asset_file_path(device_id, name)
        files.append({
            'name': name,
            'url': f'{base_url}/{quote(name)}',
            'size_bytes': path.stat().st_size,
            'sha256': _sha256_file(path).upper(),
        })
    return {'device_id': device_id, 'base_url': base_url, 'files': files}


async def start_device_web_assets_update(device_id: str) -> dict[str, Any]:
    print(f'[web_assets] solicitud recibida device_id={device_id}', flush=True)
    active = await ensure_device_active(device_id)
    if not active:
        print(f'[web_assets] dispositivo no activo device_id={device_id}', flush=True)
        return {'ok': False, 'error': 'dispositivo no activo'}
    device_id = str(active['device_id'])
    host = str(active['host'])
    status = active.get('status') if isinstance(active.get('status'), dict) else {}
    print(
        f'[web_assets] activo device_id={device_id} host={host} '
        f'wifi={status.get("wifi")} sd_ready={status.get("sd_ready")} '
        f'firmware={status.get("firmware_version")}',
        flush=True,
    )
    try:
        payload = web_assets_payload_for_device(device_id, host)
    except OtaError as exc:
        print(f'[web_assets] error preparando payload device_id={device_id}: {exc}', flush=True)
        return {'ok': False, 'error': str(exc)}

    print(f'[web_assets] base_url={payload.get("base_url")}', flush=True)
    for file_info in payload.get('files', []):
        print(
            '[web_assets] archivo '
            f'name={file_info.get("name")} size={file_info.get("size_bytes")} '
            f'sha256={file_info.get("sha256")} url={file_info.get("url")}',
            flush=True,
        )

    timeout_s = 90.0
    print(f'[web_assets] enviando POST /web/update host={host} timeout={timeout_s}s', flush=True)
    result = await start_web_assets_update(host, payload, timeout=timeout_s)
    print(
        f'[web_assets] respuesta host={host} ok={result.get("ok")} '
        f'status={result.get("status")} url={result.get("url")} data={result.get("data")!r}',
        flush=True,
    )
    return {
        'ok': bool(result.get('ok')),
        'device_id': device_id,
        'host': host,
        'payload': payload,
        'response': result.get('data'),
        'status': result.get('status'),
        'error': None if result.get('ok') else result.get('data'),
    }


def _clean_device_id(device_id: str) -> str:
    clean = (device_id or '').strip().lower()
    if not clean or '/' in clean or '\\' in clean or '..' in clean:
        raise OtaError('device_id inválido')
    return clean


def _device_dir(device_id: str) -> Path:
    return FIRMWARE_DIR / _clean_device_id(device_id)


def _manifest_path(device_id: str) -> Path:
    return _device_dir(device_id) / 'manifest.json'


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(device_id: str) -> dict[str, Any]:
    device_id = _clean_device_id(device_id)
    path = _manifest_path(device_id)
    if not path.exists():
        raise OtaError('manifest no encontrado')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise OtaError(f'manifest inválido: {exc}') from exc
    if not isinstance(data, dict):
        raise OtaError('manifest debe ser JSON object')
    if str(data.get('device_id') or '').strip().lower() != device_id:
        raise OtaError('manifest device_id no coincide')
    if not data.get('enabled', True):
        raise OtaError('firmware deshabilitado')
    version = str(data.get('version') or '').strip()
    filename = str(data.get('filename') or '').strip()
    if not version:
        raise OtaError('manifest sin version')
    if not filename or '/' in filename or '\\' in filename or not filename.endswith('.bin'):
        raise OtaError('manifest filename inválido')
    bin_path = _device_dir(device_id) / filename
    if not bin_path.exists() or not bin_path.is_file():
        raise OtaError('archivo .bin no encontrado')
    out = dict(data)
    out['device_id'] = device_id
    out['version'] = version
    out['filename'] = filename
    out['size_bytes'] = bin_path.stat().st_size
    out['sha256'] = str(out.get('sha256') or '').strip() or _sha256_file(bin_path)
    return out


def firmware_file_path(device_id: str, filename: str) -> Path:
    device_id = _clean_device_id(device_id)
    clean_filename = (filename or '').strip()
    if not clean_filename or '/' in clean_filename or '\\' in clean_filename or not clean_filename.endswith('.bin'):
        raise OtaError('filename inválido')
    path = _device_dir(device_id) / clean_filename
    manifest = load_manifest(device_id)
    if manifest['filename'] != clean_filename:
        raise OtaError('archivo no corresponde al manifest activo')
    return path


def _local_ip_for_target(target_host: str) -> str:
    host = (target_host or '').split(':', 1)[0]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect((host, 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return '127.0.0.1'


def firmware_url_for_device(device_id: str, esp_host: str) -> str:
    manifest = load_manifest(device_id)
    server_ip = _local_ip_for_target(esp_host)
    return (
        f'http://{server_ip}:{_server_port()}/firmware/'
        f'{quote(manifest["device_id"])}/{quote(manifest["filename"])}'
    )


def compare_versions(current: str | None, available: str | None) -> int | None:
    if not current or not available:
        return None

    def parts(value: str) -> list[Any]:
        normalized = str(value).strip().lstrip('vV').replace('-', '.')
        out: list[Any] = []
        for item in normalized.split('.'):
            if item.isdigit():
                out.append(int(item))
            else:
                out.append(item)
        return out

    a = parts(current)
    b = parts(available)
    try:
        return (b > a) - (b < a)
    except TypeError:
        return None


async def ota_snapshot() -> dict[str, Any]:
    devices = await ensure_active_devices()
    rows: list[dict[str, Any]] = []
    for item in devices:
        device_id = str(item.get('device_id') or '')
        host = str(item.get('host') or '')
        status_data = item.get('status') if isinstance(item.get('status'), dict) else {}
        current_version = str(status_data.get('firmware_version') or status_data.get('version') or '')
        row: dict[str, Any] = {
            'device_id': device_id,
            'host': host,
            'current_version': current_version,
            'manifest_ok': False,
            'available_version': '',
            'can_update': False,
            'version_newer': None,
            'manifest_error': '',
            'ota_status': None,
        }
        try:
            manifest = load_manifest(device_id)
            cmp_value = compare_versions(current_version, manifest['version'])
            row.update({
                'manifest_ok': True,
                'available_version': manifest['version'],
                'filename': manifest['filename'],
                'size_bytes': manifest['size_bytes'],
                'sha256': manifest['sha256'],
                'release_date': manifest.get('release_date', ''),
                'version_newer': cmp_value,
                'can_update': cmp_value is None or cmp_value > 0,
            })
        except OtaError as exc:
            row['manifest_error'] = str(exc)

        ota_status = await fetch_ota_status(host, timeout=1.2) if host else {'ok': False, 'data': 'sin host'}
        row['ota_status'] = ota_status.get('data') if ota_status.get('ok') else {'ok': False, 'error': ota_status.get('data')}
        if isinstance(row['ota_status'], dict) and row['ota_status'].get('state') in {'queued', 'downloading', 'writing', 'rebooting'}:
            row['can_update'] = False
        rows.append(row)
    return {'ok': True, 'generated_at': datetime.now().isoformat(timespec='seconds'), 'devices': rows}


async def start_device_ota(device_id: str, force: bool = False) -> dict[str, Any]:
    active = await ensure_device_active(device_id)
    if not active:
        return {'ok': False, 'error': 'dispositivo no activo'}
    device_id = str(active['device_id'])
    host = str(active['host'])
    try:
        manifest = load_manifest(device_id)
    except OtaError as exc:
        return {'ok': False, 'error': str(exc)}

    current_version = str((active.get('status') or {}).get('firmware_version') or '')
    cmp_value = compare_versions(current_version, manifest['version'])
    if not force and cmp_value is not None and cmp_value <= 0:
        return {'ok': False, 'error': 'la versión disponible no es mayor que la actual', 'current_version': current_version, 'available_version': manifest['version']}

    firmware_url = firmware_url_for_device(device_id, host)
    payload = {
        'device_id': device_id,
        'version': manifest['version'],
        'firmware_url': firmware_url,
        'sha256': manifest.get('sha256', ''),
    }
    result = await start_ota_update(host, payload, timeout=5.0)
    return {
        'ok': bool(result.get('ok')),
        'device_id': device_id,
        'host': host,
        'payload': payload,
        'response': result.get('data'),
        'status': result.get('status'),
        'error': None if result.get('ok') else result.get('data'),
    }
