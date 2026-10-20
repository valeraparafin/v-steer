"""Wires VS200 taps to Zwift pulses and keeps the status the UI shows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from .config import Config
from .events import Tap
from .vs200 import InputState
from .zwift.ride import EmulatorState

log = logging.getLogger("vsteer")


@dataclass(frozen=True)
class Status:
    vs200: InputState = InputState.SEARCHING
    zwift: EmulatorState = EmulatorState.STOPPED
    vs200_address: str = ""
    battery: int | None = None  # the remote's level while connected (#36)


class Core:
    def __init__(self, cfg: Config, emulator) -> None:
        self.cfg = cfg
        self.emulator = emulator
        self.status = Status(vs200_address=cfg.vs200_address)
        self._listeners: list[Callable[[Status], None]] = []
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, listener: Callable[[Status], None]) -> None:
        self._listeners.append(listener)
        listener(self.status)

    def map_tap(self, tap: Tap) -> Tap:
        if not self.cfg.swap:
            return tap
        return Tap.LEFT if tap is Tap.RIGHT else Tap.RIGHT

    def on_tap(self, tap: Tap) -> None:
        task = asyncio.get_running_loop().create_task(self._steer(self.map_tap(tap)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _steer(self, direction: Tap) -> None:
        delivered = await self.emulator.pulse(direction, self.cfg.pulse_ms)
        if delivered:
            log.info("steer %s", direction.value)
        else:
            log.info("steer %s dropped: Zwift is not connected", direction.value)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks))

    def on_input_state(self, state: InputState) -> None:
        if state is InputState.CONNECTED:
            self._update(vs200=state)
        else:
            self._update(vs200=state, battery=None)

    def on_battery(self, level: int) -> None:
        if not 0 <= level <= 100 or self.status.vs200 is not InputState.CONNECTED:
            return  # a broken read, or a late one after the remote dropped
        self.emulator.set_battery(level)
        self._update(battery=level)

    def on_emulator_state(self, state: EmulatorState) -> None:
        self._update(zwift=state)

    def _update(self, **changes) -> None:
        new = replace(self.status, **changes)
        if new != self.status:
            self.status = new
            for listener in self._listeners:
                listener(new)
