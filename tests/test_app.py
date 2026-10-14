import uuid

from vsteer.app import acquire_single_instance, release_single_instance
from vsteer.core import Status
from vsteer.ui.console import format_status
from vsteer.vs200 import InputState
from vsteer.zwift.ride import EmulatorState


def test_second_instance_is_refused():
    name = f"Local\\V-Steer-test-{uuid.uuid4()}"
    first = acquire_single_instance(name)
    assert first is not None
    assert acquire_single_instance(name) is None
    release_single_instance(first)
    again = acquire_single_instance(name)
    assert again is not None
    release_single_instance(again)


def test_hint_counts_from_when_zwift_went_away():
    """#9: the firewall hint waits 60 s of no Zwift, measured from the disconnect, not from app start."""
    from vsteer.app import HintTimer

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
    from vsteer.app import HintTimer

    t = HintTimer(after_s=60)
    t.update(EmulatorState.ADVERTISING, 0)
    assert t.was_connected is False
    t.update(EmulatorState.READY, 10)
    t.update(EmulatorState.ADVERTISING, 20)
    assert t.was_connected is True


def test_format_status():
    s = Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY, vs200_address="D3:F7")
    assert format_status(s) == "VS200 D3:F7: connected | Zwift: ready"


def test_unexpected_error_is_reported_not_raised(tmp_path, monkeypatch):
    from vsteer import app

    async def boom(cfg, cfg_path):
        raise RuntimeError("bluetooth stack exploded")

    monkeypatch.setattr(app, "run", boom)
    monkeypatch.setattr(app, "acquire_single_instance", lambda name="x": 1)
    monkeypatch.setattr(app, "release_single_instance", lambda handle: None)
    assert app.main(["--config", str(tmp_path / "config.toml")]) == 1


def test_version_flag_prints_version(capsys):
    import pytest

    from vsteer import __version__, app

    with pytest.raises(SystemExit) as exc:
        app.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_check_loads_bluetooth_and_mdns(capsys):
    from vsteer import app

    assert app.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_fails_when_a_module_is_missing(monkeypatch, capsys):
    from vsteer import app

    monkeypatch.setattr(app, "LAZY_PACKAGES", ("vsteer_no_such_module",))
    assert app.main(["--check"]) == 1
    assert "vsteer_no_such_module" in capsys.readouterr().out


def _exe_main(monkeypatch, rc, *, frozen, interactive):
    from vsteer import app

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


def _exe_main_raising(monkeypatch, exc):
    from vsteer import app

    paused = []

    def boom(argv=None):
        raise exc

    monkeypatch.setattr(app, "main", boom)
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app, "_interactive", lambda: True)
    return app.exe_main([], pause=paused.append), paused


def test_exe_keeps_the_window_open_when_startup_crashes(monkeypatch, capsys):
    rc, paused = _exe_main_raising(monkeypatch, PermissionError("APPDATA is read-only"))
    assert rc == 1 and paused
    assert "APPDATA is read-only" in capsys.readouterr().err


def test_exe_keeps_the_window_open_after_a_bad_argument(monkeypatch):
    rc, paused = _exe_main_raising(monkeypatch, SystemExit(2))
    assert rc == 2 and paused


def test_exe_closes_after_version(monkeypatch):
    rc, paused = _exe_main_raising(monkeypatch, SystemExit(0))
    assert rc == 0 and not paused


def test_check_fails_when_bluetooth_or_mdns_cannot_start(monkeypatch, capsys):
    from vsteer import app

    async def broken():
        raise OSError("winrt projection missing")

    monkeypatch.setattr(app, "_smoke_runtime", broken)
    assert app.main(["--check"]) == 1
    assert "winrt projection missing" in capsys.readouterr().out


async def test_a_new_release_is_announced_in_the_console(caplog):
    import logging

    from vsteer import app
    from vsteer.update import RELEASES_PAGE

    async def newer():
        return "v0.2.0"

    with caplog.at_level(logging.INFO, logger="vsteer"):
        await app._announce_update(check=newer)
    assert "v0.2.0" in caplog.text and RELEASES_PAGE in caplog.text


async def test_nothing_is_announced_when_up_to_date(caplog):
    import logging

    from vsteer import app

    async def none():
        return None

    with caplog.at_level(logging.INFO, logger="vsteer"):
        await app._announce_update(check=none)
    assert "New version" not in caplog.text


def test_an_old_vs200_steer_still_running_is_detected():
    from vsteer.app import legacy_instance_running

    name = f"Local\vs200-steer-test-{uuid.uuid4()}"
    assert legacy_instance_running(name) is False
    held = acquire_single_instance(name)
    assert legacy_instance_running(name) is True
    release_single_instance(held)


def test_v_steer_refuses_to_start_next_to_an_old_copy(monkeypatch, capsys):
    from vsteer import app

    monkeypatch.setattr(app, "legacy_instance_running", lambda name=None: True)
    assert app.main([]) == 1
    assert "vs200-steer" in capsys.readouterr().out
