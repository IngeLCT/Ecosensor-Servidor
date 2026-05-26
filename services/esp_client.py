import asyncio
import json
import socket
from datetime import datetime
from typing import Any

from config import UI_PORT
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def normalize_host_input(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''

    if '://' not in value:
        value = f'http://{value}'

    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    host = host.strip().rstrip('/')

    if '/' in host:
        host = host.split('/')[0]

    return host


def build_base_url(host: str) -> str:
    return f'http://{host}' if host else ''


def build_endpoints(host: str) -> dict[str, str]:
    base_url = build_base_url(host)
    return {
        'base_url': base_url,
        'status': f'{base_url}/status' if base_url else '',
        'lecturas': f'{base_url}/lecturas' if base_url else '',
        'lecturas_since': f'{base_url}/lecturas/since' if base_url else '',
        'lecturas_range': f'{base_url}/lecturas/range' if base_url else '',
        'lecturas_recent': f'{base_url}/lecturas/recent' if base_url else '',
        'config': f'{base_url}/config' if base_url else '',
        'time': f'{base_url}/time' if base_url else '',
        'diagnostics': f'{base_url}/diagnostics' if base_url else '',
        'ota_update': f'{base_url}/ota/update' if base_url else '',
        'ota_status': f'{base_url}/ota/status' if base_url else '',
        'wifi_clear': f'{base_url}/wifi/clear' if base_url else '',
        'readings_clear': f'{base_url}/lecturas/clear' if base_url else '',
    }


def fetch_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'})
    return request_json_sync(request, url, timeout)


def delete_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'}, method='DELETE')
    return request_json_sync(request, url, timeout)


def post_json_sync(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    request = Request(
        url,
        data=body,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
        method='POST',
    )
    return request_json_sync(request, url, timeout)


def request_json_sync(request: Request, url: str, timeout: float = 8.0) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', errors='replace')
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
            return {'ok': 200 <= response.status < 300, 'status': response.status, 'url': url, 'data': data}
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
        return {'ok': False, 'status': exc.code, 'url': url, 'data': raw}
    except (TimeoutError, URLError, OSError) as exc:
        return {'ok': False, 'status': 0, 'url': url, 'data': str(exc)}


async def fetch_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_json_sync, url, timeout)


async def post_json(url: str, payload: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(post_json_sync, url, payload, timeout)


async def delete_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    return await asyncio.to_thread(delete_json_sync, url, timeout)


async def start_ota_update(host: str, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['ota_update']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    return await post_json(endpoints['ota_update'], payload, timeout=timeout)


async def fetch_ota_status(host: str, timeout: float = 3.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['ota_status']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    return await fetch_json(endpoints['ota_status'], timeout=timeout)


def candidate_hosts(saved_host: str, default_host: str) -> list[str]:
    hosts: list[str] = []
    for host in (saved_host, default_host):
        normalized = normalize_host_input(host)
        if normalized and normalized not in hosts:
            hosts.append(normalized)
    return hosts


def _local_ip_for_target(target_host: str) -> str | None:
    clean_host = normalize_host_input(target_host).split(':', 1)[0]
    if not clean_host:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect((clean_host, 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def sync_time_if_needed_sync(host: str, timeout: float = 4.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    status = fetch_json_sync(endpoints['status'], timeout=timeout)
    if not status.get('ok') or not isinstance(status.get('data'), dict):
        return {'ok': False, 'host': host, 'status': status, 'synced': False}

    status_data = status['data']
    needs_sync = bool(status_data.get('needs_time_sync', not status_data.get('time_valid', False)))
    if not needs_sync:
        return {'ok': True, 'host': host, 'status': status, 'synced': False}

    payload = system_datetime_payload(host)
    sync_response = post_json_sync(endpoints['time'], payload, timeout=timeout)
    if not sync_response.get('ok'):
        sync_response = post_json_sync(endpoints['config'], payload, timeout=timeout)

    sync_data = sync_response.get('data')
    synced = bool(sync_response.get('ok') and isinstance(sync_data, dict) and sync_data.get('time_valid'))
    return {'ok': synced, 'host': host, 'status': status, 'sync': sync_response, 'synced': synced}


async def sync_time_if_needed(host: str, timeout: float = 4.0) -> dict[str, Any]:
    return await asyncio.to_thread(sync_time_if_needed_sync, host, timeout)




def push_host_payload(target_host: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    server_ip = _local_ip_for_target(target_host)
    if server_ip:
        payload['push_host'] = server_ip
    return payload

def configure_push_host_sync(host: str, timeout: float = 4.0) -> dict[str, Any]:
    payload = system_datetime_payload(host)
    if 'push_host' not in payload:
        return {'ok': False, 'host': host, 'data': 'server_ip_unavailable'}
    endpoints = build_endpoints(host)
    sync_response = post_json_sync(endpoints['time'], payload, timeout=timeout)
    if not sync_response.get('ok'):
        sync_response = post_json_sync(endpoints['config'], payload, timeout=timeout)
    return {'ok': bool(sync_response.get('ok')), 'host': host, 'sync': sync_response, 'push_host': payload.get('push_host')}


async def configure_push_host(host: str, timeout: float = 4.0) -> dict[str, Any]:
    return await asyncio.to_thread(configure_push_host_sync, host, timeout)

async def fetch_readings_since(host: str, after_id: int, limit: int = 25, timeout: float = 20.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_since']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'after': max(0, int(after_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 1000)),
    })
    return await fetch_json(f"{endpoints['lecturas_since']}?{query}", timeout=timeout)


async def fetch_readings_range(host: str, from_id: int, to_id: int, limit: int = 25, timeout: float = 30.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_range']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'from': max(1, int(from_id)),
        'to': max(1, int(to_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 1000)),
    })
    return await fetch_json(f"{endpoints['lecturas_range']}?{query}", timeout=timeout)


async def fetch_recent_readings(host: str, after_id: int, before_id: int = 0, limit: int = 25, timeout: float = 4.0) -> dict[str, Any]:
    endpoints = build_endpoints(host)
    if not endpoints['lecturas_recent']:
        return {'ok': False, 'status': 0, 'url': '', 'data': 'missing host'}
    query = urlencode({
        'after': max(0, int(after_id)),
        'before': max(0, int(before_id)),
        'limit': max(1, int(limit)),
        'timeout_ms': max(250, int(timeout * 800)),
    })
    return await fetch_json(f"{endpoints['lecturas_recent']}?{query}", timeout=timeout)


async def autoconnect_and_sync(saved_host: str, default_host: str) -> dict[str, Any]:
    last_result: dict[str, Any] = {'ok': False, 'host': '', 'synced': False}
    for host in candidate_hosts(saved_host, default_host):
        result = await sync_time_if_needed(host)
        if result.get('ok'):
            return result
        last_result = result
    return last_result


def system_datetime_payload(target_host: str | None = None) -> dict[str, str]:
    now = datetime.now().astimezone()
    payload = {
        'date': now.strftime('%d-%m-%Y'),
        'time': now.strftime('%H:%M:%S'),
    }
    if target_host:
        server_ip = _local_ip_for_target(target_host)
        if server_ip:
            payload['push_host'] = server_ip
    return payload
