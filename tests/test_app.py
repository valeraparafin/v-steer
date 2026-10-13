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


def test_version_flag_prints_version(capsys):
    import pytest

    from vs200steer import __version__, app

    with pytest.raises(SystemExit) as exc:
        app.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_check_loads_bluetooth_and_mdns(capsys):
    from vs200steer import app

    assert app.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_fails_when_a_module_is_missing(monkeypatch, capsys):
    from vs200steer import app

    monkeypatch.setattr(app, "RUNTIME_MODULES", ("vs200steer_no_such_module",))
    assert app.main(["--check"]) == 1
    assert "vs200steer_no_such_module" in capsys.readouterr().out


def _exe_main(monkeypatch, rc, *, frozen, interactive):
    from vs200steer import app

    paused = []
    monkeypatch.setattr(app, "main", lambda argv=None: rc)
    monkeypatch.setattr(app.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(app, "_interactive", lambda: interactive)
    assert app.exe_main([], pause=paused.append) == rc
    return paused


def test_exe_keeps_the_window_open_after_an_error(monkeypatch):
    assert _exe_main(monkeypatch, 1, frozen=True, interactive=True)


def test_exe_closes_normally_after_a_clean_stop(monkeypatch):
    assert not _exe_main(monkeypatch, 0, frozen=True, interactive=True)


def test_exe_does_not_wait_for_enter_without_a_console(monkeypatch):
    assert not _exe_main(monkeypatch, 1, frozen=True, interactive=False)
    assert not _exe_main(monkeypatch, 1, frozen=False, interactive=True)
