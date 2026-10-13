import logging

from vs200steer.config import Config
from vs200steer.core import Core, Status
from vs200steer.events import Tap
from vs200steer.vs200 import InputState
from vs200steer.zwift.ride import EmulatorState


class FakeEmulator:
    def __init__(self, delivered=True):
        self.pulses, self.delivered = [], delivered

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
    with caplog.at_level(logging.INFO, logger="vs200steer"):
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
