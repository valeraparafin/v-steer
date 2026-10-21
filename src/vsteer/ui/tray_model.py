"""What the tray shows, as plain data: icon state, tooltip, status line, notification texts."""

from __future__ import annotations

from collections.abc import Callable

from ..core import Status
from ..vs200 import InputState
from ..zwift.ride import EmulatorState
from .icon import IconState

LOW_BATTERY = 15  # % at which the remote's battery is worth a warning (#36)
TOOLTIP_MAX = 127  # Windows cuts the tray tooltip (szTip holds 128 characters with the terminator)

MESSAGES = {
    "pick": "Press a button on the VS200 you want to steer with.",
    "picked": "Remote saved. In Zwift: Paired Devices → Controls → {device}.",
    "update": "V-Steer {tag} is out. Download it from the V-Steer menu.",
    "battery": "The steering remote's battery is at {level}%. Replace it soon.",
    "error": "V-Steer can't steer: {reason}. Open the log from the V-Steer menu.",
}


def _remote_ok(status: Status) -> bool:
    return status.vs200 is InputState.CONNECTED


def _zwift_ok(status: Status) -> bool:
    return status.zwift is EmulatorState.READY  # TCP open but not subscribed does not steer yet


def icon_state(status: Status, error: str | None) -> IconState:
    if error:
        return IconState.ERROR
    connected = _remote_ok(status) + _zwift_ok(status)
    return (IconState.IDLE, IconState.PARTIAL, IconState.READY)[connected]


def status_line(status: Status) -> str:
    if status.vs200 is InputState.ASLEEP:
        remote = "asleep, press a button to wake"
    else:
        remote = "connected" if _remote_ok(status) else "searching"
        if _remote_ok(status) and status.battery is not None:
            remote += f" {status.battery}%"
    zwift = "ready" if _zwift_ok(status) else "waiting"
    return f"Remote: {remote} · Zwift: {zwift}"


def battery_low(status: Status) -> bool:
    return status.battery is not None and status.battery <= LOW_BATTERY


def tooltip(version: str, status: Status, error: str | None) -> str:
    text = f"V-Steer {version} · Error: {error}" if error else f"V-Steer {version} · {status_line(status)}"
    return text if len(text) <= TOOLTIP_MAX else text[:TOOLTIP_MAX - 1] + "…"


class Notifier:
    """Sends each kind of notification at most once per run."""

    def __init__(self, send: Callable[[str], None]) -> None:
        self._send = send
        self._shown: set[str] = set()

    def once(self, kind: str, **fmt) -> bool:
        if kind in self._shown:
            return False
        self._shown.add(kind)
        self._send(MESSAGES[kind].format(**fmt))
        return True

    def rearm(self, *kinds: str) -> None:
        self._shown.difference_update(kinds)
