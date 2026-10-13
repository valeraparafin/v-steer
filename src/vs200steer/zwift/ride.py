"""Emulate a Zwift Ride controller over DirCon so Zwift pairs with it under Controls."""

from __future__ import annotations

import asyncio
import logging
import math
import socket
from collections.abc import Callable
from enum import Enum

from ..events import Tap
from . import dircon
from . import protocol as P

log = logging.getLogger("vs200steer")

PORT_RANGE = 10
NAME_ATTEMPTS = 5


class EmulatorState(Enum):
    STOPPED = "stopped"
    ADVERTISING = "advertising"
    CONNECTED = "connected"
    READY = "ready"


class RideEmulator:
    def __init__(self, address: str, port: int = 36866, device_name: str = P.DEFAULT_DEVICE_NAME, *,
                 advertise: bool = True, keepalive_s: float = 20.0, repeat_s: float = 0.05,
                 gap_s: float = 0.05) -> None:
        self.address = address
        self.port = port
        self.device_name = device_name
        self.advertise = advertise
        self.keepalive_s = keepalive_s
        self.repeat_s = repeat_s
        self.gap_s = gap_s
        self.bound_port: int | None = None
        self.advertised_name: str | None = None
        self.on_state_change: Callable[[EmulatorState], None] | None = None
        self._state = EmulatorState.STOPPED
        self._server: asyncio.AbstractServer | None = None
        self._zeroconf = None
        self._service_info = None
        self._keepalive_task: asyncio.Task | None = None
        self._pulse_lock = asyncio.Lock()
        self._background: set[asyncio.Task] = set()
        self.dircon = dircon.DirconServer(
            dircon.Service(P.RIDE_SERVICE_UUID, [
                dircon.Characteristic(P.SYNC_RX_CHAR_UUID, P.DIRCON_PROP_WRITE, on_write=self._on_sync_write),
                dircon.Characteristic(P.ASYNC_CHAR_UUID, P.DIRCON_PROP_NOTIFY, on_read=lambda: P.RELEASED_FRAME),
                dircon.Characteristic(P.SYNC_TX_CHAR_UUID, P.DIRCON_PROP_NOTIFY),
            ]),
            on_client_change=lambda _message: self._refresh_state(),
        )

    # --- state ---------------------------------------------------------------

    @property
    def state(self) -> EmulatorState:
        return self._state

    def _refresh_state(self) -> None:
        if self._server is None:
            new = EmulatorState.STOPPED
        elif self.dircon.subscribers(P.ASYNC_CHAR_UUID):
            new = EmulatorState.READY
        elif self.dircon.clients:
            new = EmulatorState.CONNECTED
        else:
            new = EmulatorState.ADVERTISING
        if new is not self._state:
            self._state = new
            log.info("Zwift link: %s", new.value)
            if self.on_state_change:
                self.on_state_change(new)

    # --- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        ports = [0] if self.port == 0 else range(self.port, self.port + PORT_RANGE)
        last_error: OSError | None = None
        for port in ports:
            try:
                self._server = await asyncio.start_server(self.dircon.handle_client, "0.0.0.0", port)
                break
            except OSError as exc:
                last_error = exc
        if self._server is None:
            raise last_error or OSError("no free DirCon port")
        self.bound_port = self._server.sockets[0].getsockname()[1]
        try:
            if self.advertise:
                await self._advertise()
        except BaseException:
            # Bad address, name clashes or Ctrl+C during the mDNS probe: release the port and mDNS.
            await self.stop()
            raise
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        self._refresh_state()

    async def _advertise(self) -> None:
        from zeroconf import NonUniqueNameException, ServiceInfo
        from zeroconf.asyncio import AsyncZeroconf

        self._zeroconf = AsyncZeroconf()
        for attempt in range(NAME_ATTEMPTS):
            name = self.device_name if attempt == 0 else f"{self.device_name} {attempt + 1}"
            label = "".join(c if c.isalnum() else "-" for c in name).strip("-").lower() or "vs200-steer"
            info = ServiceInfo(
                P.MDNS_SERVICE_TYPE,
                f"{name}.{P.MDNS_SERVICE_TYPE}",
                addresses=[socket.inet_aton(self.address)],
                port=self.bound_port,
                properties=P.MDNS_TXT,
                server=f"{label}.local.",
            )
            try:
                await self._zeroconf.async_register_service(info, strict=False)
            except NonUniqueNameException:
                log.info("mDNS name '%s' is taken, trying another", name)
                continue
            self._service_info = info
            self.advertised_name = name
            return
        raise RuntimeError(f"could not register an mDNS name based on '{self.device_name}'")

    async def stop(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        if self._zeroconf:
            if self._service_info:
                try:
                    await self._zeroconf.async_unregister_service(self._service_info)
                except Exception as exc:  # noqa: BLE001 - teardown must not raise
                    log.debug("mDNS unregister failed: %s", exc)
            await self._zeroconf.async_close()
            self._zeroconf = None
            self._service_info = None
        await self.dircon.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._refresh_state()

    # --- Zwift -> us ---------------------------------------------------------

    def _on_sync_write(self, value: bytes) -> None:
        if value.startswith(P.RIDE_ON):
            log.debug("RideOn from Zwift")
            self._spawn(self._send(P.SYNC_TX_CHAR_UUID, P.RIDE_ON_REPLY))
            return
        object_id = P.parse_get(value)
        if object_id is None:
            log.debug("ignored SYNC_RX write %s", value.hex())
            return
        reply = P.GET_REPLIES.get(object_id)
        if reply is None:
            log.info("Zwift asked for data object %d, not served", object_id)
            return
        log.debug("GET %d answered", object_id)
        self._spawn(self._send(P.SYNC_TX_CHAR_UUID, reply))

    async def _send(self, char_uuid: str, value: bytes) -> int:
        """notify() that never raises: a half-dead Zwift socket must not kill a pulse or the keepalive."""
        try:
            return await self.dircon.notify(char_uuid, value)
        except (ConnectionError, OSError) as exc:
            log.info("Zwift link write failed: %s", exc)
            return 0

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # --- us -> Zwift ---------------------------------------------------------

    async def pulse(self, direction: Tap, ms: int) -> bool:
        """Hold the D-pad `direction` for `ms`, then release. Pulses run one at a time, in order."""
        async with self._pulse_lock:
            if self._state is not EmulatorState.READY:
                return False
            frame = P.keypad_frame(direction)
            # A fixed number of sends: Windows' ~15 ms timer makes short sleeps return at once,
            # and a clock-driven loop would then flood Zwift until the deadline passed.
            repeat_ms = max(1, round(self.repeat_s * 1000))
            sends = max(1, math.ceil(ms / repeat_ms))  # integer ms: 200 / 50 is exactly 4 sends
            for i in range(sends):
                await self._send(P.ASYNC_CHAR_UUID, frame)
                await asyncio.sleep(min(repeat_ms, ms - i * repeat_ms) / 1000)
            await self._send(P.ASYNC_CHAR_UUID, P.RELEASED_FRAME)
            await asyncio.sleep(self.gap_s)
            return True

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(self.keepalive_s)
            if self._state is EmulatorState.READY and not self._pulse_lock.locked():
                await self._send(P.ASYNC_CHAR_UUID, P.RELEASED_FRAME)
