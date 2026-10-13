"""v0.1 UI: one log line per status change. v0.2 adds a tray icon next to this."""

from __future__ import annotations

import logging

from ..core import Status

log = logging.getLogger("vs200steer")


def format_status(status: Status) -> str:
    return f"VS200 {status.vs200_address}: {status.vs200.value} | Zwift: {status.zwift.value}"


class ConsoleUI:
    def on_status(self, status: Status) -> None:
        log.info("== %s", format_status(status))
