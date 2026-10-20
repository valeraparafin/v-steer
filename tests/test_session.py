import asyncio
import logging
from typing import ClassVar

import pytest

from vsteer import config
from vsteer.config import Config
from vsteer.session import Events, HintTimer, ReleaseTimer, Session
from vsteer.update import RELEASES_PAGE
from vsteer.vs200 import InputState
from vsteer.zwift.ride import EmulatorState


class RecordingEvents(Events):
    def __init__(self):
        self.calls = []

    def status(self, s):
        self.calls.append(("status", s))

    def pick_started(self):
        self.calls.append("pick_started")

    def picked(self, address, device):
        self.calls.append(("picked", address, device))

    def update_available(self, tag):
        self.calls.append(("update", tag))

    def fatal(self, reason):
        self.calls.append(("fatal", reason))

    def named(self, name):
        return [c for c in self.calls if c == name or (isinstance(c, tuple) and c[0] == name)]


class FakeEmulator:
    instances: ClassVar[list] = []

    def __init__(self, address, device_name="KICKR BIKE PRO 1337", fail=None):
        self.address, self.device_name = address, device_name
        self.advertised_name = None
        self.bound_port = 36866
        self.state = EmulatorState.STOPPED
        self.on_state_change = None
        self.started = self.stopped = False
        self.fail = fail
        FakeEmulator.instances.append(self)

    async def start(self):
        if self.fail:
            raise self.fail
        self.started = True
        self.advertised_name = self.device_name
        self.state = EmulatorState.ADVERTISING

    async def stop(self):
        self.stopped = True

    async def pulse(self, direction, ms):
        return True


class FakeInput:
    instances: ClassVar[list] = []

    def __init__(self, address, on_tap, on_state=None):
        self.address, self.on_tap, self.on_state = address, on_tap, on_state
        self.cancelled = False
        FakeInput.instances.append(self)

    async def run(self):
        try:
            if self.on_state:
                self.on_state(InputState.SEARCHING)
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def until(condition, timeout=1.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        if loop.time() > end:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.005)


async def _no_update():
    return None


def _session(tmp_path, cfg=None, *, pick=None, lan="192.168.1.140", events=None, emulator_factory=None,
             check_update=_no_update):
    FakeEmulator.instances, FakeInput.instances = [], []

    async def never_pick(timeout):
        await asyncio.Event().wait()

    events = events or RecordingEvents()
    session = Session(cfg or Config(vs200_address="AA:AA:AA:AA:AA:AA"), tmp_path / "config.toml", events,
                      pick=pick or never_pick, input_factory=FakeInput,
                      emulator_factory=emulator_factory or FakeEmulator, lan=lan, check_update=check_update)
    return session, events


def _picks(*addresses):
    queue = list(addresses)

    async def pick(timeout):
        return queue.pop(0)
    return pick


async def test_first_run_reports_pick_and_saves_the_remote(tmp_path):
    session, events = _session(tmp_path, Config(), pick=_picks("A1:A1:A1:A1:A1:A1"))
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    assert events.calls[0] == "pick_started"
    assert events.named("picked") == [("picked", "A1:A1:A1:A1:A1:A1", "KICKR BIKE PRO 1337")]
    assert config.load(tmp_path / "config.toml").vs200_address == "A1:A1:A1:A1:A1:A1"
    assert FakeInput.instances[0].address == "A1:A1:A1:A1:A1:A1"
    await session.stop()
    assert await task == 0


async def test_no_press_on_first_run_is_fatal(tmp_path):
    session, events = _session(tmp_path, Config(), pick=_picks(None))
    assert await session.run() == 2
    assert events.named("fatal") == [("fatal", "No VS200 was pressed within 2 minutes")]


async def test_no_lan_address_is_fatal_once(tmp_path):
    session, events = _session(tmp_path, lan="")
    assert await session.run() == 2
    assert events.named("fatal") == [("fatal", "No LAN address found")]


async def test_a_taken_port_is_fatal(tmp_path):
    def broken(address, device_name):
        return FakeEmulator(address, device_name, fail=OSError("port 36866 in use"))

    session, events = _session(tmp_path, emulator_factory=broken)
    assert await session.run() == 2
    assert events.named("fatal") == [("fatal", "Zwift link could not start: port 36866 in use")]


async def test_status_reaches_events(tmp_path):
    session, events = _session(tmp_path)
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    FakeInput.instances[0].on_state(InputState.CONNECTED)
    assert events.named("status")[-1][1].vs200 is InputState.CONNECTED
    await session.stop()
    await task


async def test_stop_ends_run_and_stops_the_emulator(tmp_path):
    session, _ = _session(tmp_path)
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    await session.stop()
    assert await asyncio.wait_for(task, 1) == 0
    assert FakeEmulator.instances[0].stopped and FakeInput.instances[0].cancelled


async def test_stop_during_a_pick_returns_quickly(tmp_path):
    session, _ = _session(tmp_path, Config())  # first run: the pick waits forever
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.05)
    await asyncio.wait_for(session.stop(), 1)
    assert await asyncio.wait_for(task, 1) == 0
    assert not FakeEmulator.instances  # never started, nothing to stop


async def test_stop_before_run_makes_run_return_at_once(tmp_path):
    session, _ = _session(tmp_path)
    await session.stop()
    assert await asyncio.wait_for(session.run(), 1) == 0


async def test_pick_another_restarts_the_input_with_the_new_remote(tmp_path):
    session, events = _session(tmp_path, pick=_picks("B2:B2:B2:B2:B2:B2"))
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    await session.pick_another()
    assert FakeInput.instances[0].cancelled
    assert FakeInput.instances[-1].address == "B2:B2:B2:B2:B2:B2"
    assert events.named("pick_started") and events.named("picked")[-1][1] == "B2:B2:B2:B2:B2:B2"
    assert config.load(tmp_path / "config.toml").vs200_address == "B2:B2:B2:B2:B2:B2"
    await session.stop()
    await task


async def test_pick_another_without_a_press_keeps_the_old_remote(tmp_path):
    session, events = _session(tmp_path, pick=_picks(None))
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    await session.pick_another()
    assert FakeInput.instances[-1].address == "AA:AA:AA:AA:AA:AA" and len(FakeInput.instances) == 2
    assert not events.named("fatal") and not events.named("picked")
    await session.stop()
    assert await task == 0


async def test_a_second_pick_another_while_picking_is_ignored(tmp_path):
    started = []

    async def slow_pick(timeout):
        started.append(1)
        await asyncio.Event().wait()

    session, _ = _session(tmp_path, pick=slow_pick)
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    first = asyncio.create_task(session.pick_another())
    await until(lambda: started)
    await asyncio.wait_for(session.pick_another(), 1)  # returns at once, no second scan
    assert len(started) == 1
    await asyncio.wait_for(session.stop(), 1)  # Review Focus 1: quitting during a pick
    assert await asyncio.wait_for(task, 1) == 0
    await asyncio.wait_for(first, 1)


async def test_pick_another_before_the_ride_starts_is_ignored(tmp_path):
    session, events = _session(tmp_path)
    await session.pick_another()
    assert events.calls == []


def test_set_swap_saves_and_applies(tmp_path):
    cfg = Config(vs200_address="AA:AA:AA:AA:AA:AA")
    session, _ = _session(tmp_path, cfg)
    session.set_swap(True)
    assert cfg.swap is True and config.load(tmp_path / "config.toml").swap is True


def test_set_swap_survives_a_read_only_config(tmp_path, monkeypatch, caplog):
    cfg = Config(vs200_address="AA:AA:AA:AA:AA:AA")
    session, _ = _session(tmp_path, cfg)

    def locked(cfg, path):
        raise PermissionError("read-only")

    monkeypatch.setattr(config, "save", locked)
    with caplog.at_level(logging.WARNING, logger="vsteer"):
        session.set_swap(True)
    assert cfg.swap is True and "read-only" in caplog.text


async def test_a_newer_release_reaches_events(tmp_path, caplog):
    async def newer():
        return "v0.2.1"

    session, events = _session(tmp_path, check_update=newer)
    with caplog.at_level(logging.INFO, logger="vsteer"):
        task = asyncio.create_task(session.run())
        await until(lambda: events.named("update"))
    assert events.named("update") == [("update", "v0.2.1")]
    assert "v0.2.1" in caplog.text and RELEASES_PAGE in caplog.text
    await session.stop()
    await task


async def test_no_update_check_when_turned_off(tmp_path):
    asked = []

    async def check():
        asked.append(1)
        return "v9.9.9"

    session, events = _session(tmp_path, Config(vs200_address="AA:AA:AA:AA:AA:AA", check_updates=False),
                               check_update=check)
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    await asyncio.sleep(0.02)
    assert not asked and not events.named("update")
    await session.stop()
    await task


async def test_a_crash_in_the_input_ends_run_with_the_error(tmp_path):
    class Broken(FakeInput):
        async def run(self):
            raise RuntimeError("bluetooth stack exploded")

    session, _ = _session(tmp_path)
    session._input_factory = Broken
    with pytest.raises(RuntimeError, match="exploded"):
        await asyncio.wait_for(session.run(), 1)
    assert FakeEmulator.instances[0].stopped


# Moved from test_app.py with the code they test.

def test_hint_counts_from_when_zwift_went_away():
    """#9: the firewall hint waits 60 s of no Zwift, measured from the disconnect, not from app start."""
    t = HintTimer(after_s=60)
    assert not t.update(EmulatorState.ADVERTISING, 0)
    assert not t.update(EmulatorState.ADVERTISING, 59)
    assert t.update(EmulatorState.ADVERTISING, 60)
    assert not t.update(EmulatorState.ADVERTISING, 61)  # once per wait
    assert not t.update(EmulatorState.READY, 70)
    assert not t.update(EmulatorState.ADVERTISING, 100)  # Zwift closed at 100 s
    assert not t.update(EmulatorState.ADVERTISING, 104)  # was: hinted here, 4 s after the close
    assert t.update(EmulatorState.ADVERTISING, 160)


def test_hint_knows_zwift_had_been_connected():
    """Review of #9: after a Zwift restart the hint is about re-pairing, not the firewall."""
    t = HintTimer(after_s=60)
    t.update(EmulatorState.ADVERTISING, 0)
    assert t.was_connected is False
    t.update(EmulatorState.READY, 10)
    t.update(EmulatorState.ADVERTISING, 20)
    assert t.was_connected is True


async def test_nothing_is_announced_when_up_to_date(tmp_path, caplog):
    session, events = _session(tmp_path)
    with caplog.at_level(logging.INFO, logger="vsteer"):
        task = asyncio.create_task(session.run())
        await until(lambda: FakeInput.instances)
        await asyncio.sleep(0.02)
    assert "New version" not in caplog.text and not events.named("update")
    await session.stop()
    await task


async def test_first_run_names_the_device_zwift_will_list(tmp_path):
    """Review: with the mDNS name taken, Zwift lists 'KICKR BIKE PRO 1337 2'; the picked
    notification must name that, not the configured name."""
    class Renamed(FakeEmulator):
        async def start(self):
            await super().start()
            self.advertised_name = f"{self.device_name} 2"

    session, events = _session(tmp_path, Config(), pick=_picks("A1:A1:A1:A1:A1:A1"), emulator_factory=Renamed)
    task = asyncio.create_task(session.run())
    await until(lambda: FakeInput.instances)
    assert events.named("picked") == [("picked", "A1:A1:A1:A1:A1:A1", "KICKR BIKE PRO 1337 2")]
    await session.stop()
    await task


def test_release_timer_fires_once_after_ten_minutes_away():
    """#2: the remote is let go after 10 min without Zwift, once per away period."""
    t = ReleaseTimer(after_s=600)
    assert not t.update(EmulatorState.ADVERTISING, 0)
    assert not t.update(EmulatorState.ADVERTISING, 599)
    assert t.update(EmulatorState.ADVERTISING, 600)
    assert not t.update(EmulatorState.ADVERTISING, 700)


def test_release_timer_restarts_when_zwift_comes_back():
    t = ReleaseTimer(after_s=600)
    t.update(EmulatorState.ADVERTISING, 0)
    assert not t.update(EmulatorState.READY, 500)
    assert not t.update(EmulatorState.ADVERTISING, 550)
    assert not t.update(EmulatorState.ADVERTISING, 1100)
    assert t.update(EmulatorState.STOPPED, 1150)  # STOPPED counts as away


def _quick_release(session):
    session.release_after_s, session.release_check_s = 0.05, 0.01
    return session


async def test_the_remote_is_released_when_zwift_stays_away(tmp_path, caplog):
    caplog.set_level(logging.INFO, "vsteer")
    session, events = _session(tmp_path)
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: session.released)
    assert FakeInput.instances[0].cancelled
    assert events.named("status")[-1][1].vs200 is InputState.ASLEEP
    assert "so the remote can sleep" in caplog.text
    await session.stop()
    await task


async def test_the_remote_is_searched_again_when_zwift_connects(tmp_path):
    session, _ = _session(tmp_path)
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: session.released)
    FakeEmulator.instances[0].state = EmulatorState.READY
    await until(lambda: len(FakeInput.instances) == 2 and not session.released)
    assert not FakeInput.instances[1].cancelled
    await session.stop()
    await task


async def test_the_remote_is_kept_while_zwift_is_connected(tmp_path):
    def connected_emulator(*a, **kw):
        emulator = FakeEmulator(*a, **kw)
        emulator.start = lambda: _set_ready(emulator)
        return emulator

    session, _ = _session(tmp_path, emulator_factory=connected_emulator)
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: FakeInput.instances)
    await asyncio.sleep(0.2)
    assert not session.released and not FakeInput.instances[0].cancelled
    await session.stop()
    await task


async def _set_ready(emulator):
    emulator.started, emulator.advertised_name = True, emulator.device_name
    emulator.state = EmulatorState.READY


async def test_zwift_connecting_right_after_a_release_starts_the_input(tmp_path):
    """Review Focus: Zwift pairs while the release waits for the input to stop."""
    class ConnectsOnCancel(FakeInput):
        async def run(self):
            try:
                await super().run()
            finally:
                if len(FakeInput.instances) == 1:
                    FakeEmulator.instances[0].state = EmulatorState.READY

    session, _ = _session(tmp_path)
    session._input_factory = ConnectsOnCancel
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: len(FakeInput.instances) == 2)
    await asyncio.sleep(0.1)
    assert not session.released and not FakeInput.instances[1].cancelled
    await session.stop()
    await task


async def test_pick_another_while_released_searches_the_new_remote(tmp_path):
    session, _ = _session(tmp_path, pick=_picks("B2:B2:B2:B2:B2:B2"))
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: session.released)
    await session.pick_another()
    assert not session.released
    assert FakeInput.instances[-1].address == "B2:B2:B2:B2:B2:B2" and not FakeInput.instances[-1].cancelled
    await session.stop()
    await task


async def test_stop_while_released_returns(tmp_path):
    session, _ = _session(tmp_path)
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: session.released)
    await asyncio.wait_for(session.stop(), 1)
    assert await asyncio.wait_for(task, 1) == 0


async def test_a_pick_during_the_release_keeps_one_running_input(tmp_path):
    """Review of #35: a pick that starts while the release waits for the input to stop wins."""
    gate = asyncio.Event()

    class SlowToStop(FakeInput):
        async def run(self):
            try:
                await super().run()
            finally:
                if len(FakeInput.instances) == 1:
                    await gate.wait()

    session, _ = _session(tmp_path, pick=_picks("B2:B2:B2:B2:B2:B2"))
    session._input_factory = SlowToStop
    task = asyncio.create_task(_quick_release(session).run())
    await until(lambda: FakeInput.instances and FakeInput.instances[0].cancelled)
    pick = asyncio.create_task(session.pick_another())
    await asyncio.sleep(0.02)
    gate.set()
    await pick
    await asyncio.sleep(0.03)
    assert not session.released
    FakeEmulator.instances[0].state = EmulatorState.READY
    await asyncio.sleep(0.05)
    running = [i for i in FakeInput.instances if not i.cancelled]
    assert [i.address for i in running] == ["B2:B2:B2:B2:B2:B2"]
    await session.stop()
    await task
