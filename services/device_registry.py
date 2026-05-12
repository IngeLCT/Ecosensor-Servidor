import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from config import DEFAULT_ESP_HOST, DEVICE_ID
from services.esp_client import normalize_host_input, sync_time_if_needed_sync
from storage.settings_store import load_settings, save_settings

ACTIVE_TTL_SECONDS = 180
DISCOVERY_MAX_DEVICE_NUMBER = 12
_DEVICE_RE = re.compile(r'^(ecosensor\d+)(?:\.local)?(?::\d+)?$', re.IGNORECASE)

_active_devices: dict[str, dict[str, Any]] = {}
_probe_lock = asyncio.Lock()


def device_id_from_host(host: str) -> str:
    clean = normalize_host_input(host)
    if not clean:
        return DEVICE_ID
    base = clean.split(':', 1)[0]
    match = _DEVICE_RE.match(base)
    if match:
        return match.group(1).lower()
    if base.endswith('.local'):
        base = base[:-6]
    return base.lower() or DEVICE_ID


def host_for_device(device_id: str) -> str:
    device_id = (device_id or DEVICE_ID).strip().lower()
    settings = load_settings()
    for host in configured_hosts():
        if device_id_from_host(host) == device_id:
            return host
    return f'{device_id}.local'


def configured_hosts() -> list[str]:
    settings = load_settings()
    hosts: list[str] = []
    raw_hosts = settings.get('esp_hosts')
    if isinstance(raw_hosts, list):
        for item in raw_hosts:
            host = normalize_host_input(str(item))
            if host and host not in hosts:
                hosts.append(host)
    legacy = normalize_host_input(str(settings.get('esp_host') or DEFAULT_ESP_HOST))
    if legacy and legacy not in hosts:
        hosts.append(legacy)
    default = normalize_host_input(DEFAULT_ESP_HOST)
    if default and default not in hosts:
        hosts.append(default)
    return hosts


def discovery_hosts() -> list[str]:
    hosts = configured_hosts()
    for number in range(1, DISCOVERY_MAX_DEVICE_NUMBER + 1):
        host = f'ecosensor{number:02d}.local'
        if host not in hosts:
            hosts.append(host)
    return hosts


def remember_host(host: str) -> None:
    host = normalize_host_input(host)
    if not host:
        return
    settings = load_settings()
    hosts = []
    raw_hosts = settings.get('esp_hosts')
    if isinstance(raw_hosts, list):
        hosts = [normalize_host_input(str(item)) for item in raw_hosts]
        hosts = [item for item in hosts if item]
    legacy = normalize_host_input(str(settings.get('esp_host') or ''))
    if legacy and legacy not in hosts:
        hosts.append(legacy)
    if host not in hosts:
        hosts.append(host)
    settings['esp_host'] = host
    settings['esp_hosts'] = hosts
    settings['device_id'] = device_id_from_host(host)
    save_settings(settings)


def _mark_active(host: str, status_data: dict[str, Any] | None = None) -> dict[str, Any]:
    host = normalize_host_input(host)
    device_id = device_id_from_host(host)
    entry = {
        'device_id': device_id,
        'host': host,
        'label': device_id,
        'last_seen': datetime.now().isoformat(timespec='seconds'),
        'status': status_data or {},
    }
    _active_devices[device_id] = entry
    return entry


def _prune_expired() -> None:
    now = datetime.now()
    expired: list[str] = []
    for device_id, entry in _active_devices.items():
        try:
            last_seen = datetime.fromisoformat(str(entry.get('last_seen') or ''))
        except ValueError:
            expired.append(device_id)
            continue
        if now - last_seen > timedelta(seconds=ACTIVE_TTL_SECONDS):
            expired.append(device_id)
    for device_id in expired:
        _active_devices.pop(device_id, None)


def active_devices() -> list[dict[str, Any]]:
    _prune_expired()
    return sorted(_active_devices.values(), key=lambda item: item.get('device_id') or '')


def active_device_options() -> dict[str, str]:
    return {item['device_id']: item['label'] for item in active_devices()}


async def probe_host(host: str) -> dict[str, Any] | None:
    host = normalize_host_input(host)
    if not host:
        return None
    result = await asyncio.to_thread(sync_time_if_needed_sync, host, 0.8)
    if not result.get('ok'):
        return None
    status = result.get('status', {}).get('data')
    entry = _mark_active(str(result.get('host') or host), status if isinstance(status, dict) else None)
    remember_host(entry['host'])
    return entry


async def refresh_active_devices() -> list[dict[str, Any]]:
    async with _probe_lock:
        semaphore = asyncio.Semaphore(4)

        async def limited_probe(host: str) -> None:
            async with semaphore:
                await probe_host(host)

        await asyncio.gather(*(limited_probe(host) for host in discovery_hosts()))
        _prune_expired()
        return active_devices()


async def ensure_active_devices() -> list[dict[str, Any]]:
    devices = active_devices()
    if devices:
        return devices
    return await refresh_active_devices()


async def ensure_device_active(device_id: str | None) -> dict[str, Any] | None:
    target = (device_id or '').strip().lower()
    if target:
        for item in active_devices():
            if item['device_id'] == target:
                return item
        return await probe_host(host_for_device(target))
    devices = await ensure_active_devices()
    return devices[0] if devices else None
