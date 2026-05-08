import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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
        'config': f'{base_url}/config' if base_url else '',
    }


def fetch_json_sync(url: str, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers={'Accept': 'application/json'})
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


async def fetch_json(url: str) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_json_sync, url)


async def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(post_json_sync, url, payload)


def system_datetime_payload() -> dict[str, str]:
    now = datetime.now().astimezone()
    return {
        'date': now.strftime('%d-%m-%Y'),
        'time': now.strftime('%H:%M:%S'),
    }
