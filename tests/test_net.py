from vs200steer.net import Adapter, pick_address

# The author's real adapter list on 2026-10-13 (VPN up, Hyper-V, Bluetooth PAN).
REAL = [
    Adapter("Bluetooth Device (Personal Area Network)", ["169.254.179.195"]),
    Adapter("Hyper-V Virtual Ethernet Adapter", ["172.25.144.1"]),
    Adapter("TAP-Windows Adapter V9 #3", ["172.16.10.11"]),
    Adapter("RZ616 Wi-Fi 6E 160MHz", ["192.168.1.140"]),
    Adapter("Software Loopback Interface 1", ["127.0.0.1"]),
]


def test_picks_wifi_even_when_default_route_is_the_vpn():
    assert pick_address(REAL, route_ip="172.16.10.11") == "192.168.1.140"


def test_prefers_default_route_when_it_is_a_real_lan():
    adapters = [Adapter("Intel Ethernet", ["10.0.0.5"]), Adapter("Realtek Wi-Fi", ["192.168.0.20"])]
    assert pick_address(adapters, route_ip="192.168.0.20") == "192.168.0.20"


def test_falls_back_to_first_private_lan_address():
    adapters = [Adapter("Intel Ethernet", ["10.0.0.5"]), Adapter("Realtek Wi-Fi", ["192.168.0.20"])]
    assert pick_address(adapters, route_ip=None) == "10.0.0.5"


def test_none_when_only_virtual_or_link_local():
    adapters = [Adapter("WireGuard Tunnel", ["10.8.0.2"]), Adapter("Ethernet", ["169.254.1.2"])]
    assert pick_address(adapters, route_ip="10.8.0.2") is None
