"""%APPDATA%\\vs200-steer\\config.toml — read with tomllib, written from a fixed template."""

from __future__ import annotations

import ipaddress
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .zwift.protocol import DEFAULT_DEVICE_NAME

PULSE_MIN_MS, PULSE_MAX_MS = 50, 2000
MDNS_NAME_MAX_BYTES = 63  # one DNS label


@dataclass
class Config:
    vs200_address: str = ""
    swap: bool = False
    pulse_ms: int = 200
    device_name: str = DEFAULT_DEVICE_NAME
    network_address: str = ""


class ConfigError(Exception):
    pass


def default_path() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "vs200-steer" / "config.toml"


_TEMPLATE = """\
[vs200]
address = {vs200_address}   # filled on first run
swap = {swap}               # false: + = right, - = left

[steer]
pulse_ms = {pulse_ms}       # how long one tap holds the D-pad ({min}..{max})

[zwift]
device_name = {device_name}

[network]
address = {network_address}   # empty = auto
"""


def save(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TEMPLATE.format(
            vs200_address=json.dumps(cfg.vs200_address),
            swap="true" if cfg.swap else "false",
            pulse_ms=cfg.pulse_ms,
            min=PULSE_MIN_MS,
            max=PULSE_MAX_MS,
            device_name=json.dumps(cfg.device_name),
            network_address=json.dumps(cfg.network_address),
        ),
        encoding="utf-8",
    )


def _get(data: dict, section: str, key: str, kind: type, default, path: Path):
    table = data.get(section, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [{section}] must be a section, got {section} = {table!r}")
    value = table.get(key, default)
    if kind is int and isinstance(value, bool) or not isinstance(value, kind):
        raise ConfigError(f"{path}: {section}.{key} must be {kind.__name__}, got {value!r}")
    return value


def load(path: Path) -> Config:
    if not path.exists():
        cfg = Config()
        save(cfg, path)
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    defaults = Config()
    cfg = Config(
        vs200_address=_get(data, "vs200", "address", str, defaults.vs200_address, path),
        swap=_get(data, "vs200", "swap", bool, defaults.swap, path),
        pulse_ms=_get(data, "steer", "pulse_ms", int, defaults.pulse_ms, path),
        device_name=_get(data, "zwift", "device_name", str, defaults.device_name, path),
        network_address=_get(data, "network", "address", str, defaults.network_address, path),
    )
    if not PULSE_MIN_MS <= cfg.pulse_ms <= PULSE_MAX_MS:
        raise ConfigError(f"{path}: steer.pulse_ms must be {PULSE_MIN_MS}..{PULSE_MAX_MS}, got {cfg.pulse_ms}")
    if not 1 <= len(cfg.device_name.encode("utf-8")) <= MDNS_NAME_MAX_BYTES:
        raise ConfigError(
            f"{path}: zwift.device_name must be 1..{MDNS_NAME_MAX_BYTES} bytes, got {cfg.device_name!r}"
        )
    if cfg.network_address:
        try:
            ipaddress.IPv4Address(cfg.network_address)
        except ValueError as exc:
            raise ConfigError(
                f"{path}: network.address must be an IPv4 address like 192.168.1.10 (no port), "
                f"got {cfg.network_address!r}"
            ) from exc
    return cfg
