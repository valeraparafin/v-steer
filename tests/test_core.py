import logging

from vsteer.config import Config
from vsteer.core import Core, Status
from vsteer.events import Tap
from vsteer.vs200 import InputState
from vsteer.zwift.ride import EmulatorState


class FakeEmulator:
    def __init__(self, delivered=True):
        self.pulses, self.delivered = [], delivered
        self.battery = None

    def set_battery(self, level):
        self.battery = level

    async def pulse(self, direction, ms):
        self.pulses.append((direction, ms))
        return self.delivered


async def test_taps_become_pulses_with_configured_length():
    emu = FakeEmulator()
    core = Core(Config(pulse_ms=250), emu)
    core.on_tap(Tap.RIGHT)
    core.on_tap(Tap.LEFT)
    await core.wait_idle()
    assert emu.pulses == [(Tap.RIGHT, 250), (Tap.LEFT, 250)]


async def test_swap_inverts_direction():
    emu = FakeEmulator()
    core = Core(Config(swap=True), emu)
    core.on_tap(Tap.RIGHT)
    await core.wait_idle()
    assert emu.pulses == [(Tap.LEFT, 200)]


async def test_dropped_pulse_is_logged(caplog):
    core = Core(Config(), FakeEmulator(delivered=False))
    with caplog.at_level(logging.INFO, logger="vsteer"):
        core.on_tap(Tap.LEFT)
        await core.wait_idle()
    assert "dropped" in caplog.text


def test_status_listeners_get_current_then_changes_only():
    core = Core(Config(vs200_address="AA"), FakeEmulator())
    seen = []
    core.subscribe(seen.append)
    core.on_input_state(InputState.CONNECTED)
    core.on_input_state(InputState.CONNECTED)
    core.on_emulator_state(EmulatorState.READY)
    assert seen == [
        Status(vs200_address="AA"),
        Status(vs200=InputState.CONNECTED, vs200_address="AA"),
        Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY, vs200_address="AA"),
    ]


def test_core_passes_the_battery_on():
    emu = FakeEmulator()
    core = Core(Config(), emu)
    core.on_input_state(InputState.CONNECTED)
    core.on_battery(25)
    assert core.status.battery == 25 and emu.battery == 25


def test_battery_is_cleared_when_the_remote_is_not_connected():
    core = Core(Config(), FakeEmulator())
    core.on_input_state(InputState.CONNECTED)
    core.on_battery(25)
    core.on_input_state(InputState.SEARCHING)
    assert core.status.battery is None


def test_core_ignores_a_nonsense_battery_level():
    core = Core(Config(), FakeEmulator())
    core.on_input_state(InputState.CONNECTED)
    core.on_battery(255)
    assert core.status.battery is None


def test_a_late_battery_level_after_a_drop_is_ignored():
    """Review of #37: a notification queued before the drop must not refill the cleared level."""
    core = Core(Config(), FakeEmulator())
    core.on_input_state(InputState.SEARCHING)
    core.on_battery(14)
    assert core.status.battery is None
