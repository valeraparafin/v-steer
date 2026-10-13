"""Pick the LAN IPv4 address Zwift can reach us on (skip VPN, virtual and link-local adapters)."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass

_VIRTUAL = re.compile(
    r"vpn|tap|tun|wireguard|wintun|hyper-v|vethernet|virtual|bluetooth|loopback|wsl|docker|vmware|"
    r"virtualbox|zerotier|tailscale|npcap",
    re.IGNORECASE,
)


@dataclass
class Adapter:
    name: str
    ips: list[str]


def list_adapters() -> list[Adapter]:
    import ifaddr

    return [
        Adapter(a.nice_name, [ip.ip for ip in a.ips if isinstance(ip.ip, str)])
        for a in ifaddr.get_adapters()
    ]


def default_route_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # no packet is sent; this only consults the routing table
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _usable(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.version == 4 and addr.is_private and not addr.is_loopback and not addr.is_link_local


def pick_address(adapters: list[Adapter], route_ip: str | None) -> str | None:
    candidates = [ip for a in adapters if not _VIRTUAL.search(a.name) for ip in a.ips if _usable(ip)]
    if route_ip in candidates:
        return route_ip
    return candidates[0] if candidates else None
