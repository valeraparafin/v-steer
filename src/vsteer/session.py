"""One ride: pick the remote if needed, advertise to Zwift, steer, and report through Events.

The console and the tray are two Events implementations over the same Session.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from . import config, net, update
from .core import Core, Status
from .vs200 import SCAN_S, InputState, Vs200Input, _bleak_find, pick_remote
from .zwift.ride import EmulatorState, RideEmulator

log = logging.getLogger("vsteer")

HINT_AFTER_S = 60
PICK_TIMEOUT_S = 120
RELEASE_AFTER_S = 600  # no Zwift this long: let the remote sleep (#2)
RELEASE_CHECK_S = 5
ASLEEP_AFTER_S = 30  # a released remote unseen this long has gone to sleep (#39)
WAKE_PAUSE_S = 1


class Events:
    """What a Session reports. The base does nothing; the console and the tray override what they show."""

    def status(self, s: Status) -> None:
        pass

    def pick_started(self) -> None:
        pass

    def picked(self, address: str, device: str) -> None:
        """`device` is the name to pair in Zwift."""

    def update_available(self, tag: str) -> None:
        pass

    def fatal(self, reason: str) -> None:
        pass


class HintTimer:
    """Fires once after Zwift has been away for `after_s`, counted from when it went away."""

    def __init__(self, after_s: float = HINT_AFTER_S) -> None:
        self.after_s = after_s
        self._away_since: float | None = None
        self._hinted = False
        self.was_connected = False  # Zwift had paired before: the hint is about re-pairing, not setup

    def update(self, state: EmulatorState, now: float) -> bool:
        if state is not EmulatorState.ADVERTISING:
            self._away_since, self._hinted = None, False
            self.was_connected = self.was_connected or state is not EmulatorState.STOPPED
            return False
        if self._away_since is None:
            self._away_since = now
        if self._hinted or now - self._away_since < self.after_s:
            return False
        self._hinted = True
        return True


def zwift_connected(state: EmulatorState) -> bool:
    return state in (EmulatorState.CONNECTED, EmulatorState.READY)


class ReleaseTimer:
    """Fires once after Zwift has not been connected for `after_s`; a held remote never sleeps."""

    def __init__(self, after_s: float = RELEASE_AFTER_S) -> None:
        self.after_s = after_s
        self._away_since: float | None = None
        self._fired = False

    def update(self, state: EmulatorState, now: float) -> bool:
        if zwift_connected(state):
            self._away_since, self._fired = None, False
            return False
        if self._away_since is None:
            self._away_since = now
        if self._fired or now - self._away_since < self.after_s:
            return False
        self._fired = True
        return True


class WakeWatch:
    """Tells a remote woken by a button press from one still awake after its release.

    It fires once, on the first sighting after the remote has been unseen for `asleep_after_s`:
    reconnecting before it slept would keep it awake, which the release is there to stop.
    """

    def __init__(self, asleep_after_s: float = ASLEEP_AFTER_S) -> None:
        self.asleep_after_s = asleep_after_s
        self._last_seen: float | None = None
        self._asleep = False

    @property
    def asleep(self) -> bool:
        return self._asleep

    def update(self, seen: bool, now: float) -> bool:
        if self._last_seen is None:  # just released: it was connected a moment ago
            self._last_seen = now
        if not seen:
            self._asleep = self._asleep or now - self._last_seen >= self.asleep_after_s
            return False
        self._last_seen = now
        woken, self._asleep = self._asleep, False
        return woken


async def _hint_loop(emulator: RideEmulator) -> None:
    loop, timer = asyncio.get_running_loop(), HintTimer()
    while True:
        await asyncio.sleep(5)
        if not timer.update(emulator.state, loop.time()):
            continue
        if timer.was_connected:
            log.warning("Zwift disconnected. To steer again: in Zwift, Paired Devices -> Controls -> pair '%s'.",
                        emulator.advertised_name)
        else:
            log.warning(
                "Zwift has not connected yet. In Zwift: Paired Devices -> Controls -> pair '%s'. "
                "If it is not listed: allow V-Steer/Python through Windows Firewall, "
                "check the PC and Zwift are on the same network, or set [network] address in the config.",
                emulator.advertised_name,
            )


class Session:
    def __init__(self, cfg: config.Config, cfg_path: Path, events: Events, *, pick=pick_remote,
                 input_factory=Vs200Input, emulator_factory=RideEmulator, lan: str | None = None,
                 check_update=update.check_for_update, find_device=None) -> None:
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.events = events
        self._pick = pick
        self._input_factory = input_factory
        self._emulator_factory = emulator_factory
        self._lan = lan
        self._check_update = check_update
        self._find_device = find_device or _bleak_find
        self._stop_requested = asyncio.Event()
        self._done = asyncio.Event()
        self._running = False
        self._picking = False
        self._core: Core | None = None
        self._emulator = None
        self._input_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._crashed: asyncio.Future | None = None
        self._released = False
        self.release_after_s = RELEASE_AFTER_S
        self.release_check_s = RELEASE_CHECK_S
        self.asleep_after_s = ASLEEP_AFTER_S
        self.wake_pause_s = WAKE_PAUSE_S
        self.wake_scan_s = SCAN_S
        self._wake_task: asyncio.Task | None = None

    # --- lifecycle -------------------------------------------------------------

    async def run(self) -> int:
        """Ride until stop() (returns 0) or a fatal error (returns 2). Unexpected errors propagate."""
        self._running = True
        self._done.clear()
        loop = asyncio.get_running_loop()
        self._crashed = loop.create_future()
        updates = asyncio.create_task(self._announce_update()) if self.cfg.check_updates else None
        ride = asyncio.create_task(self._ride())
        stopper = asyncio.create_task(self._stop_requested.wait())
        try:
            await asyncio.wait({ride, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if ride.done():
                return ride.result()
            return 0
        finally:
            for task in (ride, stopper, updates):
                if task and not task.done():
                    task.cancel()
            # Wait for the ride's own cleanup: remote released, mDNS unregistered, port closed.
            await asyncio.gather(ride, stopper, *(t for t in (updates,) if t), return_exceptions=True)
            self._running = False
            self._done.set()

    @property
    def released(self) -> bool:
        """The remote is let go so it can sleep (#2); it is searched again when Zwift connects."""
        return self._released

    async def stop(self) -> None:
        """Make run() return; safe during a pick or a connect."""
        self._stop_requested.set()
        if self._running:
            await self._done.wait()

    async def _ride(self) -> int:
        cfg = self.cfg
        address = None  # a first-run pick; announced once Zwift has a name to list
        if not cfg.vs200_address:
            log.info("First run: wake the VS200 you want to steer with and press any button on it ...")
            address = await self._pick_remote()
            if not address:
                log.error("No VS200 was pressed within 2 minutes. Is it awake and not connected to the trainer?")
                self.events.fatal("No VS200 was pressed within 2 minutes")
                return 2

        lan = cfg.network_address or (self._lan if self._lan is not None
                                      else net.pick_address(net.list_adapters(), net.default_route_ip()))
        if not lan:
            log.error("No LAN address found to advertise on. Set [network] address in %s", self.cfg_path)
            self.events.fatal("No LAN address found")
            return 2

        emulator = self._emulator_factory(lan, device_name=cfg.device_name)
        core = Core(cfg, emulator)
        core.subscribe(self.events.status)
        emulator.on_state_change = core.on_emulator_state
        try:
            await emulator.start()
        except Exception as exc:  # noqa: BLE001 - port taken or mDNS failed: steering cannot work
            log.error("Zwift link could not start: %s", exc)
            self.events.fatal(f"Zwift link could not start: {exc}")
            return 2
        self._emulator, self._core = emulator, core
        if address:  # named now: a taken mDNS name makes Zwift list "... 2"
            self.events.picked(address, emulator.advertised_name)
        log.info("Advertising '%s' on %s:%d. In Zwift: Paired Devices -> Controls -> pair it.",
                 emulator.advertised_name, lan, emulator.bound_port)
        hint = self._spawn(_hint_loop(emulator))
        self._spawn(self._release_loop(emulator))
        self._start_input()
        try:
            await self._crashed  # raises if a background job failed unexpectedly; else until cancelled
        finally:
            self._core = None
            hint.cancel()
            for task in [*self._tasks, self._input_task]:
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*self._tasks, *(t for t in (self._input_task,) if t), return_exceptions=True)
            await emulator.stop()
        return 0

    # --- actions from the UI -----------------------------------------------------

    async def pick_another(self) -> None:
        """Pick a new remote; ignored before the ride starts and while a pick runs."""
        if self._picking or self._core is None:
            return
        self._picking = True
        try:
            # A job of the ride: stop() cancels it with the rest.
            await asyncio.wait({self._spawn(self._repick())})
        finally:
            self._picking = False

    def set_swap(self, on: bool) -> None:
        self.cfg.swap = on  # Core.map_tap reads it on the next tap
        log.info("Swap + and -: %s", "on" if on else "off")
        self._save()

    # --- internals -------------------------------------------------------------

    async def _repick(self) -> None:
        if self._input_task:
            self._input_task.cancel()
            await asyncio.gather(self._input_task, return_exceptions=True)
        if self._core:
            self._core.on_input_state(InputState.SEARCHING)
        await self._stop_wake_watch()  # one scanner at a time: the pick scans next
        self._released = False
        log.info("Pick another remote: press any button on the VS200 you want to steer with ...")
        address = await self._pick_remote()
        if address:
            self.events.picked(address, self._emulator.advertised_name)
        else:
            log.warning("No VS200 was pressed within 2 minutes; keeping %s", self.cfg.vs200_address)
        self._start_input()

    async def _release_loop(self, emulator) -> None:
        loop, timer = asyncio.get_running_loop(), ReleaseTimer(self.release_after_s)
        while True:
            await asyncio.sleep(self.release_check_s)
            if self._picking:  # a pick owns the input; it starts the search itself
                continue
            if self._released and zwift_connected(emulator.state):
                await self._stop_wake_watch()
                self._released = False
                self._start_input()
            elif timer.update(emulator.state, loop.time()) and not self._released:
                await self._release()

    async def _release(self) -> None:
        if self._input_task:
            self._input_task.cancel()
            await asyncio.gather(self._input_task, return_exceptions=True)
        self._released = True
        if self._core:
            self._core.on_input_state(InputState.ASLEEP)
        log.info("VS200 released: Zwift not connected for %d min, so the remote can sleep. "
                 "Press a button on it, or connect Zwift, to use it again.", round(self.release_after_s / 60))
        self._wake_task = self._spawn(self._wake_watch())

    async def _stop_wake_watch(self) -> None:
        task, self._wake_task = self._wake_task, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _wake_watch(self) -> None:
        """Scan for the released remote; connect once it was asleep and a button woke it (#39)."""
        loop, watch = asyncio.get_running_loop(), WakeWatch(self.asleep_after_s)
        while True:
            try:
                seen = await self._find_device(self.cfg.vs200_address, self.wake_scan_s) is not None
            except Exception as exc:  # noqa: BLE001 - radio off: counts as not seen, try again
                log.debug("wake watch scan failed: %s", exc)
                seen = False
            if watch.update(seen, loop.time()):
                log.info("VS200 woken by a button press: connecting")
                self._wake_task, self._released = None, False
                self._start_input()
                return
            await asyncio.sleep(self.wake_pause_s)

    async def _pick_remote(self) -> str | None:
        self.events.pick_started()
        address = await self._pick(timeout=PICK_TIMEOUT_S)
        if not address:
            return None
        self.cfg.vs200_address = address
        self._save()
        log.info("Saved VS200 %s to %s", address, self.cfg_path)
        return address

    def _save(self) -> None:
        try:
            config.save(self.cfg, self.cfg_path)
        except OSError as exc:  # read-only file, antivirus lock: the setting still applies to this run
            log.warning("Could not save %s: %s", self.cfg_path, exc)

    def _start_input(self) -> None:
        core = self._core
        if core is None:
            return
        core.status = Status(core.status.vs200, core.status.zwift, self.cfg.vs200_address)
        vs200 = self._input_factory(self.cfg.vs200_address, on_tap=core.on_tap, on_state=core.on_input_state,
                                    on_battery=core.on_battery)
        self._input_task = asyncio.create_task(vs200.run())
        self._input_task.add_done_callback(self._report_crash)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._report_crash)
        return task

    def _report_crash(self, task: asyncio.Task) -> None:
        if task.cancelled() or task.exception() is None:
            return
        if self._crashed and not self._crashed.done():
            self._crashed.set_exception(task.exception())

    async def _announce_update(self) -> None:
        tag = await self._check_update()
        if tag:
            log.warning("New version %s is available: %s", tag, update.RELEASES_PAGE)
            self.events.update_available(tag)
