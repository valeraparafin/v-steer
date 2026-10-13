"""ThinkRider VS200 input: one BLE notification per press on 0xFEA1, no repeat, no release."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from enum import Enum

from .events import Tap

log = logging.getLogger("vs200steer")

NAME_PREFIX = "THINK VS"
FEA1_UUID = "0000fea1-0000-1000-8000-00805f9b34fb"
_PACKETS = {
    bytes.fromhex("f3050301fc"): Tap.RIGHT,  # "+" button
    bytes.fromhex("f3050300fb"): Tap.LEFT,   # "-" button
}
_BLE_ERRORS: tuple[type[BaseException], ...] = (OSError, asyncio.TimeoutError)
try:  # bleak is a runtime dependency; tests inject fakes but bleak is installed anyway
    from bleak.exc import BleakError

    _BLE_ERRORS = (*_BLE_ERRORS, BleakError)
except ImportError:  # pragma: no cover
    pass


def parse_packet(data: bytes) -> Tap | None:
    return _PACKETS.get(bytes(data))


class InputState(Enum):
    SEARCHING = "searching"
    CONNECTED = "connected"


async def _bleak_find(address: str, timeout: float):
    from bleak import BleakScanner

    return await BleakScanner.find_device_by_address(address, timeout=timeout)


async def _bleak_scan(timeout: float):
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=timeout)
    return [d for d in devices if (d.name or "").upper().startswith(NAME_PREFIX)]


def _bleak_client(device, disconnected_callback):
    from bleak import BleakClient

    return BleakClient(device, disconnected_callback=disconnected_callback)


async def pick_remote(timeout: float = 120.0, *, scan=None, client_factory=None) -> str | None:
    """Connect to every VS200 in range and return the address of the first one pressed."""
    scan = scan or _bleak_scan
    client_factory = client_factory or _bleak_client
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    chosen: asyncio.Future[str] = loop.create_future()
    clients, seen = [], set()

    def make_handler(address: str):
        def handler(_sender, data) -> None:
            if not chosen.done() and parse_packet(bytes(data)) is not None:
                chosen.set_result(address)
        return handler

    try:
        while not chosen.done() and loop.time() < deadline:
            for device in await scan(5.0):
                if device.address in seen:
                    continue
                seen.add(device.address)
                log.info("Found %s (%s) - press a button on it to use it", device.name, device.address)
                client = client_factory(device, disconnected_callback=lambda _c: None)
                try:
                    await client.connect()
                    await client.start_notify(FEA1_UUID, make_handler(device.address))
                    clients.append(client)
                except _BLE_ERRORS as exc:
                    log.info("Could not connect to %s: %s", device.address, exc)
                    seen.discard(device.address)
            if not chosen.done():
                try:
                    await asyncio.wait_for(asyncio.shield(chosen), min(1.0, max(0.0, deadline - loop.time())))
                except TimeoutError:
                    pass
        return chosen.result() if chosen.done() else None
    finally:
        for client in clients:
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001 - best effort
                log.debug("disconnect during pick failed: %s", exc)


class Vs200Input:
    def __init__(self, address: str, on_tap: Callable[[Tap], None],
                 on_state: Callable[[InputState], None] | None = None, *, find_device=None,
                 client_factory=None, retry_s: float = 3.0, max_retry_s: float = 15.0) -> None:
        self.address = address
        self.on_tap = on_tap
        self.on_state = on_state
        self._find = find_device or _bleak_find
        self._client_factory = client_factory or _bleak_client
        self.retry_s = retry_s
        self.max_retry_s = max_retry_s
        self._state: InputState | None = None

    @property
    def state(self) -> InputState | None:
        return self._state

    def _set_state(self, state: InputState) -> None:
        if state is not self._state:
            self._state = state
            log.info("VS200 %s: %s", self.address, state.value)
            if self.on_state:
                self.on_state(state)

    def _on_notify(self, _sender, data) -> None:
        tap = parse_packet(bytes(data))
        if tap is None:
            log.debug("VS200 unknown packet %s", bytes(data).hex())
            return
        self.on_tap(tap)

    async def run(self) -> None:
        delay = self.retry_s
        while True:
            self._set_state(InputState.SEARCHING)
            device = await self._find(self.address, 10.0)
            if device is None:
                await asyncio.sleep(delay)  # asleep or out of range: press a button to wake it
                delay = min(delay * 2, self.max_retry_s)
                continue
            delay = self.retry_s
            disconnected = asyncio.Event()
            # Bind this link's own event: Windows may report an old link's disconnect late,
            # and that must not tear down the link made after it.
            client = self._client_factory(
                device, disconnected_callback=lambda _c, link_down=disconnected: link_down.set()
            )
            try:
                await client.connect()
                await client.start_notify(FEA1_UUID, self._on_notify)
                self._set_state(InputState.CONNECTED)
                await disconnected.wait()
            except _BLE_ERRORS as exc:
                log.info("VS200 connection failed: %s", exc)
            finally:
                try:
                    await client.disconnect()
                except Exception as exc:  # noqa: BLE001 - already gone
                    log.debug("VS200 disconnect failed: %s", exc)
            await asyncio.sleep(self.retry_s)
