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


_DEFAULTS = Config()


class ConfigError(Exception):
    pass


APP_DIR_NAME = "V-Steer"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home())))


def default_path() -> Path:
    return _appdata() / APP_DIR_NAME / "config.toml"


@dataclass(frozen=True)
class Setting:
    """One line of config.toml: where it lives, which Config field it fills, and its comment."""

    section: str
    key: str
    field: str
    comment: str = ""

    @property
    def kind(self) -> type:
        """The type a value must have: the Config field's default type, so the two can't disagree."""
        return type(getattr(_DEFAULTS, self.field))


# The one list of settings (#22): it writes the file, reads it, and tells typos from missing keys.
SETTINGS: tuple[Setting, ...] = (
    Setting("vs200", "address", "vs200_address", "filled on first run"),
    Setting("vs200", "swap", "swap", "false: + = right, - = left"),
    Setting("steer", "pulse_ms", "pulse_ms", f"how long one tap holds the D-pad ({PULSE_MIN_MS}..{PULSE_MAX_MS})"),
    Setting("zwift", "device_name", "device_name"),
    Setting("network", "address", "network_address", "empty = auto"),
    Setting("updates", "check", "check_updates", "look for a new version on GitHub at start"),
)


def by_section(settings: tuple[Setting, ...]) -> dict[str, list[Setting]]:
    """Settings per section, in first-seen order; a section's settings need not be adjacent."""
    grouped: dict[str, list[Setting]] = {}
    for s in settings:
        grouped.setdefault(s.section, []).append(s)
    return grouped


# Every key the file holds: anything else in it is a typo or left over.
KNOWN_KEYS: dict[str, set[str]] = {section: {s.key for s in group} for section, group in by_section(SETTINGS).items()}


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


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _toml_str(value) if isinstance(value, str) else str(value)


def _render(cfg: Config) -> str:
    def line(s: Setting) -> str:
        text = f"{s.key} = {_toml_value(getattr(cfg, s.field))}"
        return f"{text}  # {s.comment}" if s.comment else text

    blocks = ([f"[{section}]", *map(line, group)] for section, group in by_section(SETTINGS).items())
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def save(cfg: Config, path: Path) -> None:
    """Write via a temp file and an atomic replace: a crash mid-write keeps the old config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        _render(cfg),
        encoding="utf-8",
    )
    os.replace(tmp, path)


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
        raise ConfigError(
            f"{path}: {exc}. Fix that line in Notepad, or delete config.toml to start over "
            "(you will pick the remote again)."
        ) from exc
    defaults = Config()
    cfg = Config(**{
        st.field: _get(data, st.section, st.key, st.kind, getattr(defaults, st.field), path) for st in SETTINGS
    })
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
    unknown = _unknown_keys(data)
    for key in unknown:
        log.warning("%s: unknown setting %s is ignored (typo?)", path, key)
    # Show settings added by newer versions, but never while a typo is in the file: the rewrite
    # would delete the line the warning above points at.
    if _missing_keys(data) and not unknown:
        try:  # values come from the file or the defaults
            save(cfg, path)
        except OSError as exc:
            log.debug("could not add new settings to %s: %s", path, exc)
    return cfg
