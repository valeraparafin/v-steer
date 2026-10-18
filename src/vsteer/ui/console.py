"""Console mode (--console): one log line per status change; everything else is already logged."""

from __future__ import annotations

import logging

from ..core import Status
from ..session import Events

log = logging.getLogger("vsteer")


def format_status(status: Status) -> str:
    return f"VS200 {status.vs200_address}: {status.vs200.value} | Zwift: {status.zwift.value}"


class ConsoleUI:
    def on_status(self, status: Status) -> None:
        log.info("== %s", format_status(status))


class ConsoleEvents(Events):
    """The Session already logs picks, updates and errors; the console adds the status line."""

    def __init__(self) -> None:
        self._ui = ConsoleUI()

    def status(self, s: Status) -> None:
        self._ui.on_status(s)
