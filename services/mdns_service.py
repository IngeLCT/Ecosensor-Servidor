import atexit
import socket
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf

from config import MDNS_HOSTNAME, MDNS_SERVICE_TYPE, UI_PORT

_zeroconf: Optional[Zeroconf] = None
_service_info: Optional[ServiceInfo] = None
PRINT_MDNS_STATUS = False  # Debug temporal: silenciar consola.


def _get_lan_ip() -> str:
    """Return the preferred LAN IPv4 address without requiring external traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return '127.0.0.1'
    finally:
        sock.close()


def start_mdns_service() -> None:
    """Advertise the NiceGUI HTTP server as ecosensor-servidor.local."""
    global _zeroconf, _service_info

    if _zeroconf is not None:
        return

    ip = _get_lan_ip()
    service_name = f'{MDNS_HOSTNAME}.{MDNS_SERVICE_TYPE}'
    server_name = f'{MDNS_HOSTNAME}.local.'

    _service_info = ServiceInfo(
        MDNS_SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(ip)],
        port=UI_PORT,
        properties={
            'path': '/',
            'name': 'EcoSensor Servidor',
        },
        server=server_name,
    )
    _zeroconf = Zeroconf()
    _zeroconf.register_service(_service_info)
    if PRINT_MDNS_STATUS:
        print(f'mDNS activo: http://{MDNS_HOSTNAME}.local:{UI_PORT}/ ({ip})')


def stop_mdns_service() -> None:
    global _zeroconf, _service_info

    if _zeroconf is None or _service_info is None:
        return

    try:
        _zeroconf.unregister_service(_service_info)
    finally:
        _zeroconf.close()
        _zeroconf = None
        _service_info = None


atexit.register(stop_mdns_service)
