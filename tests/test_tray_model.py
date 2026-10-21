import pytest

from vsteer.core import Status
from vsteer.ui.icon import IconState
from vsteer.ui.tray_model import (
    MESSAGES,
    TOOLTIP_MAX,
    Notifier,
    battery_low,
    icon_state,
    status_line,
    tooltip,
)
from vsteer.vs200 import InputState
from vsteer.zwift.ride import EmulatorState


@pytest.mark.parametrize("vs200,zwift,expected", [
    (InputState.CONNECTED, EmulatorState.READY, IconState.READY),
    (InputState.CONNECTED, EmulatorState.ADVERTISING, IconState.PARTIAL),
    (InputState.SEARCHING, EmulatorState.READY, IconState.PARTIAL),
    (InputState.CONNECTED, EmulatorState.CONNECTED, IconState.PARTIAL),  # TCP open, not subscribed
    (InputState.SEARCHING, EmulatorState.ADVERTISING, IconState.IDLE),
    (InputState.SEARCHING, EmulatorState.STOPPED, IconState.IDLE),
])
def test_icon_state(vs200, zwift, expected):
    assert icon_state(Status(vs200, zwift), None) is expected


def test_an_error_overrides_everything():
    assert icon_state(Status(InputState.CONNECTED, EmulatorState.READY), "no LAN") is IconState.ERROR


def test_tooltip_and_status_line():
    s = Status(InputState.CONNECTED, EmulatorState.ADVERTISING)
    assert status_line(s) == "Remote: connected · Zwift: waiting"
    assert status_line(Status(InputState.SEARCHING, EmulatorState.READY)) == "Remote: searching · Zwift: ready"
    assert tooltip("0.2.0", s, None) == "V-Steer 0.2.0 · Remote: connected · Zwift: waiting"
    assert tooltip("0.2.0", s, "Config error") == "V-Steer 0.2.0 · Error: Config error"


def test_a_long_error_fits_the_windows_tooltip():
    text = tooltip("0.2.0", Status(), "x" * 500)
    assert len(text) <= 127 and text.endswith("…")


def test_the_messages_are_the_spec_wording():
    assert MESSAGES["pick"] == "Press a button on the VS200 you want to steer with."
    assert MESSAGES["picked"].format(device="KICKR BIKE PRO 1337") == (
        "Remote saved. In Zwift: Paired Devices → Controls → KICKR BIKE PRO 1337.")
    assert MESSAGES["error"].format(reason="No LAN address found") == (
        "V-Steer can't steer: No LAN address found. Open the log from the V-Steer menu.")


def test_each_notification_shows_once_per_run():
    sent = []
    n = Notifier(sent.append)
    assert n.once("update", tag="v0.2.1") and not n.once("update", tag="v0.2.1")
    assert sent == ["V-Steer v0.2.1 is out. Download it from the V-Steer menu."]


def test_pick_another_remote_rearms_pick_and_picked():
    sent = []
    n = Notifier(sent.append)
    n.once("pick")
    n.once("picked", device="KICKR BIKE PRO 1337")
    n.rearm("pick", "picked")
    assert n.once("pick") and len(sent) == 3
    assert not n.once("pick")


def test_asleep_status_line():
    """#2: a released remote is shown as sleeping, not as lost."""
    s = Status(vs200=InputState.ASLEEP, zwift=EmulatorState.ADVERTISING)
    assert status_line(s) == "Remote: asleep, press a button to wake · Zwift: waiting"
    assert icon_state(s, None) is IconState.IDLE


def test_asleep_tooltip_fits():
    s = Status(vs200=InputState.ASLEEP, zwift=EmulatorState.ADVERTISING)
    assert len(tooltip("0.2.1", s, None)) <= TOOLTIP_MAX


def test_status_line_shows_the_battery():
    s = Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY, battery=25)
    assert status_line(s) == "Remote: connected 25% · Zwift: ready"
    assert status_line(Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY)) == (
        "Remote: connected · Zwift: ready")


def test_battery_low_threshold():
    assert battery_low(Status(vs200=InputState.CONNECTED, battery=15))
    assert not battery_low(Status(vs200=InputState.CONNECTED, battery=16))
    assert not battery_low(Status(vs200=InputState.CONNECTED))
