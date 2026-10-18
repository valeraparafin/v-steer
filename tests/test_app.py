import uuid
from typing import ClassVar

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
    assert app.main(["--console", "--config", str(tmp_path / "config.toml")]) == 1


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


# --- v0.2: the tray is the default, --console keeps the log window -------------------------


def _single(monkeypatch, app, handle=1):
    monkeypatch.setattr(app, "acquire_single_instance", lambda name="x": handle)
    monkeypatch.setattr(app, "release_single_instance", lambda handle: None)
    monkeypatch.setattr(app, "attach_console", lambda new: None)


class FakeTray:
    instances: ClassVar[list] = []

    def __init__(self, session_factory, **kwargs):
        self.session_factory, self.kwargs, self.calls = session_factory, kwargs, []
        FakeTray.instances.append(self)

    def run(self):
        self.calls.append("run")
        return 0

    def run_error(self, reason):
        self.calls.append(("run_error", reason))
        return 0


def test_default_mode_starts_the_tray(monkeypatch, tmp_path):
    from vsteer import app
    from vsteer.session import Events, Session

    _single(monkeypatch, app)
    FakeTray.instances = []
    monkeypatch.setattr(app, "TrayApp", FakeTray)
    assert app.main(["--config", str(tmp_path / "config.toml")]) == 0
    tray = FakeTray.instances[0]
    assert tray.calls == ["run"]
    assert tray.kwargs["settings_dir"] == tmp_path and tray.kwargs["log_path"] == tmp_path / "v-steer.log"
    events = Events()
    session = tray.session_factory(events)
    assert isinstance(session, Session) and session.events is events


def test_console_flag_uses_the_console_events(monkeypatch, tmp_path):
    from vsteer import app
    from vsteer.ui.console import ConsoleEvents

    _single(monkeypatch, app)
    made, consoles = [], []

    class FakeSession:
        def __init__(self, cfg, cfg_path, events):
            made.append(events)

        async def run(self):
            return 0

    monkeypatch.setattr(app, "Session", FakeSession)
    monkeypatch.setattr(app, "attach_console", lambda new: consoles.append(new))
    monkeypatch.setattr(app, "TrayApp", FakeTray)
    FakeTray.instances = []
    assert app.main(["--console", "--config", str(tmp_path / "config.toml")]) == 0
    assert isinstance(made[0], ConsoleEvents) and consoles == [True] and not FakeTray.instances


def test_second_instance_in_tray_mode_notifies_and_exits(monkeypatch, tmp_path):
    from vsteer import app

    _single(monkeypatch, app, handle=None)
    shown = []
    monkeypatch.setattr(app, "notify_and_exit", shown.append)
    assert app.main(["--config", str(tmp_path / "config.toml")]) == 1
    assert shown == ["V-Steer is already running — look for its icon next to the clock."]


def test_second_instance_in_console_mode_only_logs(monkeypatch, tmp_path):
    from vsteer import app

    _single(monkeypatch, app, handle=None)
    shown = []
    monkeypatch.setattr(app, "notify_and_exit", shown.append)
    assert app.main(["--console", "--config", str(tmp_path / "config.toml")]) == 1
    assert shown == []


def test_a_config_error_starts_the_tray_in_error(monkeypatch, tmp_path):
    from vsteer import app

    _single(monkeypatch, app)
    FakeTray.instances = []
    monkeypatch.setattr(app, "TrayApp", FakeTray)
    p = tmp_path / "config.toml"
    p.write_text("[steer]\npulse_ms = 5\n", encoding="utf-8")
    assert app.main(["--config", str(p)]) == 2
    (call,) = FakeTray.instances[0].calls
    assert call[0] == "run_error" and call[1].startswith("Config error: ") and "steer.pulse_ms" in call[1]


def test_check_prints_even_without_a_console(monkeypatch):
    """The windowed exe starts with no stdout; --check must still print and return its code."""
    import io

    from vsteer import app

    out = io.StringIO()
    attached = []

    def attach(new):
        attached.append(new)
        app.sys.stdout = out

    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app, "attach_console", attach)
    assert app.main(["--check"]) == 0
    assert attached == [False] and "check OK" in out.getvalue()


class FakeKernel32:
    def __init__(self, attach=1, alloc=1):
        self._attach, self._alloc, self.calls = attach, alloc, []

    def AttachConsole(self, pid):
        self.calls.append(("attach", pid))
        return self._attach

    def AllocConsole(self):
        self.calls.append("alloc")
        return self._alloc

    def SetConsoleOutputCP(self, cp):
        self.calls.append(("cp", cp))
        return 1


def _attach(monkeypatch, new, kernel32):
    import io

    from vsteer import app

    opened = []

    def opener(path, mode, **kw):
        opened.append(path)
        return io.StringIO()

    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    monkeypatch.setattr(app.sys, "stdin", None)
    app.attach_console(new, kernel32=kernel32, opener=opener)
    return app.sys, opened


def test_check_attaches_to_the_parent_console(monkeypatch):
    k = FakeKernel32()
    s, opened = _attach(monkeypatch, False, k)
    assert k.calls == [("attach", 0xFFFFFFFF)] and opened == ["CONOUT$"]
    assert s.stdout is not None and s.stderr is not None


def test_console_flag_opens_its_own_window_with_input(monkeypatch):
    k = FakeKernel32()
    s, opened = _attach(monkeypatch, True, k)
    assert "alloc" in k.calls and ("attach", 0xFFFFFFFF) not in k.calls
    assert opened == ["CONOUT$", "CONIN$"] and s.stdin is not None  # "Press Enter" works after an error


def test_no_console_to_attach_still_gives_somewhere_to_print(monkeypatch):
    import os

    s, opened = _attach(monkeypatch, False, FakeKernel32(attach=0))
    assert opened == [os.devnull] and s.stdout is not None


def test_attach_console_leaves_working_streams_alone():
    from vsteer import app

    k = FakeKernel32()
    app.attach_console(True, kernel32=k, opener=lambda *a, **kw: None)
    assert k.calls == []


def test_no_console_log_handler_without_stderr(monkeypatch, tmp_path):
    import logging.handlers

    from vsteer import app

    monkeypatch.setattr(app.sys, "stderr", None)
    before = list(app.log.handlers)
    try:
        app.setup_logging(False, tmp_path / "v-steer.log")
        added = [h for h in app.log.handlers if h not in before]
        assert [type(h) for h in added] == [logging.handlers.RotatingFileHandler]
    finally:
        for h in [h for h in app.log.handlers if h not in before]:
            app.log.removeHandler(h)
            h.close()


def test_check_builds_a_tray_icon(monkeypatch, capsys):
    from vsteer import app

    monkeypatch.setattr(app, "LAZY_MODULES", ("vsteer_no_such_tray_backend",))
    assert app.main(["--check"]) == 1
    assert "vsteer_no_such_tray_backend" in capsys.readouterr().out
