"""%APPDATA%\\V-Steer\\config.toml — read with tomllib, written from a fixed template."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .zwift.protocol import DEFAULT_DEVICE_NAME

log = logging.getLogger("vsteer")

PULSE_MIN_MS, PULSE_MAX_MS = 50, 2000
MDNS_NAME_MAX_BYTES = 63  # one DNS label


@dataclass
class Config:
    vs200_address: str = ""
    swap: bool = False
    pulse_ms: int = 200
    device_name: str = DEFAULT_DEVICE_NAME
    network_address: str = ""
    check_updates: bool = True


class ConfigError(Exception):
    pass


APP_DIR_NAME = "V-Steer"
LEGACY_DIR_NAME = "vs200-steer"  # the app's name before v0.1.0


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home())))


def default_path() -> Path:
    return _appdata() / APP_DIR_NAME / "config.toml"


def migrate_legacy_config(appdata: Path | None = None) -> Path | None:
    """Move config.toml from the pre-rename folder if the new folder has none; return the old path.

    Only the config moves: it is never held open, unlike the old logs, which stay behind.
    """
    appdata = appdata or _appdata()
    old, new = appdata / LEGACY_DIR_NAME / "config.toml", appdata / APP_DIR_NAME / "config.toml"
    if not old.is_file() or new.exists():
        return None
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new)
    except OSError:  # unexpected lock or permissions: start with fresh settings rather than fail
        return None
    return old


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

[updates]
check = {check_updates}        # look for a new version on GitHub at start
"""


def _toml_str(value: str) -> str:
    """A TOML basic string. Unlike json.dumps, emoji stay as they are (no surrogate pairs)."""
    out = []
    for ch in value:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def save(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TEMPLATE.format(
            vs200_address=_toml_str(cfg.vs200_address),
            swap="true" if cfg.swap else "false",
            pulse_ms=cfg.pulse_ms,
            min=PULSE_MIN_MS,
            max=PULSE_MAX_MS,
            device_name=_toml_str(cfg.device_name),
            network_address=_toml_str(cfg.network_address),
            check_updates="true" if cfg.check_updates else "false",
        ),
        encoding="utf-8",
    )


# Every key the template writes: anything else in the file is a typo or left over.
KNOWN_KEYS = {
    "vs200": {"address", "swap"},
    "steer": {"pulse_ms"},
    "zwift": {"device_name"},
    "network": {"address"},
    "updates": {"check"},
}
_BLUETOOTH_ADDRESS = re.compile(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}")


def _unknown_keys(data: dict) -> list[str]:
    unknown = []
    for section, table in data.items():
        if section not in KNOWN_KEYS:
            unknown.append(f"[{section}]")
        elif isinstance(table, dict):
            unknown += [f"{section}.{key}" for key in table if key not in KNOWN_KEYS[section]]
    return unknown


def _missing_keys(data: dict) -> bool:
    return any(not isinstance(data.get(s), dict) or not keys <= data[s].keys() for s, keys in KNOWN_KEYS.items())


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
        check_updates=_get(data, "updates", "check", bool, defaults.check_updates, path),
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
    if cfg.vs200_address and not _BLUETOOTH_ADDRESS.fullmatch(cfg.vs200_address):
        raise ConfigError(
            f"{path}: vs200.address must look like D3:F7:DD:C8:6A:69 (or \"\" to pick the remote again), "
            f"got {cfg.vs200_address!r}"
        )
    for key in _unknown_keys(data):
        log.warning("%s: unknown setting %s is ignored (typo?)", path, key)
    if _missing_keys(data):
        try:  # show settings added by newer versions; values come from the file or the defaults
            save(cfg, path)
        except OSError as exc:
            log.debug("could not add new settings to %s: %s", path, exc)
    return cfg
