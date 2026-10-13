import uuid

from vs200steer.app import acquire_single_instance, release_single_instance, should_hint
from vs200steer.core import Status
from vs200steer.ui.console import format_status
from vs200steer.vs200 import InputState
from vs200steer.zwift.ride import EmulatorState


def test_second_instance_is_refused():
    name = f"Local\\vs200-steer-test-{uuid.uuid4()}"
    first = acquire_single_instance(name)
    assert first is not None
    assert acquire_single_instance(name) is None
    release_single_instance(first)
    again = acquire_single_instance(name)
    assert again is not None
    release_single_instance(again)


def test_hint_only_once_after_60s_while_unpaired():
    assert should_hint(EmulatorState.ADVERTISING, 61, hinted=False) is True
    assert should_hint(EmulatorState.ADVERTISING, 59, hinted=False) is False
    assert should_hint(EmulatorState.ADVERTISING, 61, hinted=True) is False
    assert should_hint(EmulatorState.READY, 61, hinted=False) is False


def test_format_status():
    s = Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY, vs200_address="D3:F7")
    assert format_status(s) == "VS200 D3:F7: connected | Zwift: ready"


def test_unexpected_error_is_reported_not_raised(tmp_path, monkeypatch):
    from vs200steer import app

    async def boom(cfg, cfg_path):
        raise RuntimeError("bluetooth stack exploded")

    monkeypatch.setattr(app, "run", boom)
    monkeypatch.setattr(app, "acquire_single_instance", lambda name="x": 1)
    monkeypatch.setattr(app, "release_single_instance", lambda handle: None)
    assert app.main(["--config", str(tmp_path / "config.toml")]) == 1
