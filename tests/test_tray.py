import asyncio
import logging
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import ClassVar

import pytest

from vsteer.config import Config
from vsteer.core import Status
from vsteer.ui.icon import IconState, render
from vsteer.ui.tray import HELP_URL, BackgroundLoop, TrayApp, notify_and_exit
from vsteer.update import RELEASES_PAGE
from vsteer.vs200 import InputState
from vsteer.zwift.ride import EmulatorState


class FakeMenuItem:
    def __init__(self, text, action=None, checked=None, radio=False, default=False, visible=True, enabled=True):
        self._text, self.action, self._checked, self._visible, self._enabled = text, action, checked, visible, enabled

    def _value(self, v):
        return v(self) if callable(v) else v

    @property
    def text(self):
        return self._value(self._text)

    @property
    def checked(self):
        return self._value(self._checked)

    @property
    def visible(self):
        return self._value(self._visible)

    @property
    def enabled(self):
        return self._value(self._enabled)


SEPARATOR = FakeMenuItem("- - - -")


class FakeMenu:
    SEPARATOR = SEPARATOR

    def __init__(self, *items):
        self.items = items


class FakeIcon:
    instances: ClassVar[list] = []

    def __init__(self, name, icon=None, title=None, menu=None):
        self.icon_sets = -1  # the constructor's own set does not count
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.visible = False
        self.notes = []
        self.menu_updates = 0
        self.stopped = threading.Event()
        FakeIcon.instances.append(self)

    def run(self, setup=None):
        threading.Thread(target=setup, args=(self,)).start()
        self.stopped.wait(10)

    def stop(self):
        self.stopped.set()

    def notify(self, message, title=None):
        assert self.visible, "Windows drops notifications of a hidden icon"
        self.notes.append((message, title))

    def update_menu(self):
        """Like pystray on Windows: rebuilding the menu evaluates every item's callables."""
        self.menu_updates += 1
        for item in self.menu.items:
            item.text, item.checked, item.enabled, item.visible  # noqa: B018

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, image):  # pystray re-uploads the image on every set, same image or not
        self._icon = image
        self.icon_sets += 1


backend = SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)


class FakeSession:
    def __init__(self, events, *, run_result=None, crash=None):
        self.events = events
        self.cfg = Config(vs200_address="AA:AA:AA:AA:AA:AA")
        self.calls = []
        self._stop = asyncio.Event()
        self._run_result, self._crash = run_result, crash

    async def run(self):
        self.calls.append(("run", threading.current_thread().name))
        if self._crash:
            raise self._crash
        if self._run_result is not None:
            return self._run_result
        await self._stop.wait()
        return 0

    async def stop(self):
        self.calls.append("stop")
        self._stop.set()

    async def pick_another(self):
        self.calls.append("pick_another")

    def set_swap(self, on):
        self.calls.append(("set_swap", on, threading.current_thread().name))
        self.cfg.swap = on


class FakeAutostart:
    def __init__(self, available=True):
        self.enabled, self._available, self.paths = False, available, []

    def available(self):
        return self._available

    reads = 0

    def is_enabled(self):
        self.reads += 1
        return self.enabled

    def enable(self, path):
        self.enabled = True
        self.paths.append(path)

    def disable(self):
        self.enabled = False


def wait_for(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("condition not met")
        time.sleep(0.005)


class Harness:
    """Runs TrayApp.run() on a thread the way main() runs it on the main thread."""

    def __init__(self, tmp_path, *, autostart_available=True, **session_kwargs):
        FakeIcon.instances = []
        self.sessions, self.opened, self.urls = [], [], []
        self.autostart = FakeAutostart(autostart_available)

        def factory(events):
            session = FakeSession(events, **session_kwargs)
            self.sessions.append(session)
            return session

        self.app = TrayApp(factory, backend=backend, version="0.2.0", autostart_mod=self.autostart,
                           open_path=self.opened.append, open_url=self.urls.append,
                           log_path=tmp_path / "v-steer.log", settings_dir=tmp_path, exe_path=r"C:\V-Steer.exe")
        self.rc = None

    def start(self, run=None):
        def body():
            self.rc = (run or self.app.run)()
        self.thread = threading.Thread(target=body)
        self.thread.start()
        wait_for(lambda: FakeIcon.instances and FakeIcon.instances[0].visible)
        return self

    @property
    def icon(self):
        return FakeIcon.instances[0]

    @property
    def session(self):
        wait_for(lambda: self.sessions)
        return self.sessions[0]

    def items(self):
        return [i for i in self.icon.menu.items if i is not SEPARATOR and i.visible]

    def labels(self):
        return [i.text for i in self.items()]

    def click(self, label):
        item = next(i for i in self.items() if i.text.startswith(label))
        assert item.enabled, f"{label} is disabled"
        item.action()

    def quit(self):
        self.click("Quit")
        self.thread.join(5)
        assert not self.thread.is_alive()
        return self.rc


def test_the_tray_starts_idle_and_runs_the_session_on_its_own_thread(tmp_path):
    h = Harness(tmp_path).start()
    wait_for(lambda: h.session.calls)
    assert h.session.calls[0] == ("run", "v-steer-session")
    assert h.icon.icon.tobytes() == render(IconState.IDLE, 32).tobytes()
    assert h.icon.title == "V-Steer 0.2.0 · Remote: searching · Zwift: waiting"
    assert h.quit() == 0


def test_status_changes_reach_the_icon_and_tooltip(tmp_path):
    h = Harness(tmp_path).start()
    h.session.events.status(Status(InputState.CONNECTED, EmulatorState.READY))
    assert h.icon.icon.tobytes() == render(IconState.READY, 32).tobytes()
    assert h.icon.title == "V-Steer 0.2.0 · Remote: connected · Zwift: ready"
    assert h.labels()[0] == "Remote: connected · Zwift: ready"
    h.quit()


def test_menu_matches_the_spec(tmp_path):
    h = Harness(tmp_path).start()
    assert h.labels() == ["Remote: searching · Zwift: waiting", "Swap + and −", "Pick another remote…",
                          "Start with Windows", "Open log", "Open settings folder", "Help", "Quit"]
    assert not h.items()[0].enabled  # the status line is not a button
    h.quit()


def test_start_with_windows_only_in_the_exe(tmp_path):
    h = Harness(tmp_path, autostart_available=False).start()
    assert "Start with Windows" not in h.labels()
    h.quit()


def test_start_with_windows_toggles_the_registry(tmp_path):
    h = Harness(tmp_path).start()
    h.click("Start with Windows")
    assert h.autostart.enabled and h.autostart.paths == [r"C:\V-Steer.exe"]
    assert next(i for i in h.items() if i.text == "Start with Windows").checked
    h.click("Start with Windows")
    assert not h.autostart.enabled
    h.quit()


def test_update_shows_download_and_notifies_once(tmp_path):
    h = Harness(tmp_path).start()
    h.session.events.update_available("v0.2.1")
    h.session.events.update_available("v0.2.1")
    assert "Download v0.2.1" in h.labels()
    assert h.labels().index("Download v0.2.1") == h.labels().index("Help") + 1
    assert h.icon.notes == [("V-Steer v0.2.1 is out. Download it from the V-Steer menu.", "V-Steer")]
    h.quit()


def test_pick_and_picked_notify_once_until_pick_another(tmp_path):
    h = Harness(tmp_path).start()
    events = h.session.events
    events.pick_started()
    events.picked("A1", "KICKR BIKE PRO 1337")
    events.pick_started()
    assert [n for n, _ in h.icon.notes] == [
        "Press a button on the VS200 you want to steer with.",
        "Remote saved. In Zwift: Paired Devices → Controls → KICKR BIKE PRO 1337.",
    ]
    h.click("Pick another remote…")
    wait_for(lambda: "pick_another" in h.session.calls)
    events.pick_started()
    assert len(h.icon.notes) == 3
    h.quit()


def test_fatal_turns_the_icon_red_and_notifies_once(tmp_path):
    h = Harness(tmp_path).start()
    h.session.events.fatal("No LAN address found")
    h.session.events.fatal("No LAN address found")
    assert h.icon.icon.tobytes() == render(IconState.ERROR, 32).tobytes()
    assert h.icon.title == "V-Steer 0.2.0 · Error: No LAN address found"
    assert h.icon.notes == [("V-Steer can't steer: No LAN address found. Open the log from the V-Steer menu.",
                             "V-Steer")]
    h.session.events.status(Status(InputState.CONNECTED, EmulatorState.READY))  # an error stays an error
    assert h.icon.icon.tobytes() == render(IconState.ERROR, 32).tobytes()
    assert h.quit() == 0


def test_a_long_notification_fits_windows(tmp_path):
    h = Harness(tmp_path).start()
    h.session.events.fatal("x" * 400)
    assert len(h.icon.notes[0][0]) <= 255
    h.quit()


def test_swap_click_reaches_the_session_on_its_loop(tmp_path):
    h = Harness(tmp_path).start()
    h.click("Swap + and −")
    wait_for(lambda: any(c[0] == "set_swap" for c in h.session.calls if isinstance(c, tuple)))
    assert ("set_swap", True, "v-steer-session") in h.session.calls
    wait_for(lambda: next(i for i in h.items() if i.text == "Swap + and −").checked)
    h.quit()


def test_quit_stops_the_session_then_the_tray(tmp_path):
    h = Harness(tmp_path).start()
    assert h.quit() == 0
    assert "stop" in h.session.calls
    assert not h.app.loop.alive


def test_a_click_after_the_session_died_is_ignored(tmp_path, caplog):
    h = Harness(tmp_path).start()
    h.app.loop.stop()
    with caplog.at_level(logging.INFO, logger="vsteer"):
        h.click("Swap + and −")
        h.click("Pick another remote…")
    assert "ignored" in caplog.text
    assert h.quit() == 0


def test_a_crash_in_the_session_turns_the_icon_red(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="vsteer"):
        h = Harness(tmp_path, crash=RuntimeError("bluetooth stack exploded")).start()
        wait_for(lambda: h.icon.notes)
    assert h.icon.icon.tobytes() == render(IconState.ERROR, 32).tobytes()
    assert "bluetooth stack exploded" in h.icon.notes[0][0]
    assert "Traceback" in caplog.text
    assert h.quit() == 0


def test_help_and_download_open_the_right_urls(tmp_path):
    h = Harness(tmp_path).start()
    h.click("Help")
    h.session.events.update_available("v0.2.1")
    h.click("Download v0.2.1")
    assert h.urls == [HELP_URL, RELEASES_PAGE]
    assert HELP_URL == "https://github.com/valeraparafin/v-steer#troubleshooting"
    h.quit()


def test_open_log_and_settings_folder(tmp_path):
    h = Harness(tmp_path).start()
    h.click("Open log")
    h.click("Open settings folder")
    assert h.opened == [str(tmp_path / "v-steer.log"), str(tmp_path)]
    h.quit()


def test_open_log_failure_is_logged_not_raised(tmp_path, caplog):
    h = Harness(tmp_path).start()

    def broken(path):
        raise OSError("no app for .log")

    h.app._open_path = broken
    with caplog.at_level(logging.WARNING, logger="vsteer"):
        h.click("Open log")
    assert "no app for .log" in caplog.text
    h.quit()


def test_run_error_shows_the_error_without_a_session(tmp_path):
    h = Harness(tmp_path)
    h.start(lambda: h.app.run_error("Config error in config.toml"))
    wait_for(lambda: h.icon.notes)
    assert h.sessions == []
    assert h.icon.icon.tobytes() == render(IconState.ERROR, 32).tobytes()
    assert h.icon.notes[0][0].startswith("V-Steer can't steer: Config error in config.toml.")
    disabled = [i.text for i in h.items() if not i.enabled]
    assert "Swap + and −" in disabled and "Pick another remote…" in disabled
    h.click("Open log")
    assert h.quit() == 0


def test_notify_and_exit_shows_a_message_then_leaves(tmp_path):
    FakeIcon.instances = []
    notify_and_exit("V-Steer is already running — look for its icon next to the clock.", backend=backend, wait_s=0)
    icon = FakeIcon.instances[0]
    assert icon.notes == [("V-Steer is already running — look for its icon next to the clock.", "V-Steer")]
    assert icon.stopped.is_set()


def test_background_loop_runs_coroutines_and_stops():
    loop = BackgroundLoop()
    loop.start()

    async def where():
        return threading.current_thread().name

    assert loop.submit(where()).result(1) == "v-steer-session"
    loop.stop()
    assert not loop.alive
    with pytest.raises(RuntimeError):
        loop.submit(where())


def test_two_quick_swap_clicks_cancel_out(tmp_path):
    """Review: the new value was read on the tray thread, so a second click before the first
    reached the session set the same value again."""
    h = Harness(tmp_path).start()
    wait_for(lambda: h.session.calls)

    async def busy():
        time.sleep(0.2)  # noqa: ASYNC251 - block the session loop on purpose: both clicks queue up

    h.app.loop.submit(busy())
    h.click("Swap + and −")
    h.click("Swap + and −")
    wait_for(lambda: len([c for c in h.session.calls if isinstance(c, tuple) and c[0] == "set_swap"]) == 2)
    assert h.session.cfg.swap is False
    h.quit()


def test_a_session_that_cannot_start_turns_the_icon_red(tmp_path, caplog):
    """Review: an error while starting the session was lost in pystray's setup thread."""
    h = Harness(tmp_path)

    def broken(events):
        raise OSError("no event loop for you")

    h.app._session_factory = broken
    with caplog.at_level(logging.ERROR, logger="vsteer"):
        h.start()
        wait_for(lambda: h.icon.notes)
    assert h.icon.icon.tobytes() == render(IconState.ERROR, 32).tobytes()
    assert "no event loop for you" in h.icon.notes[0][0] and "Traceback" in caplog.text
    assert h.quit() == 0


def test_low_battery_notifies_once(tmp_path):
    """#36: one warning per run, not one per status update."""
    h = Harness(tmp_path).start()
    low = Status(vs200=InputState.CONNECTED, battery=10)
    h.session.events.status(low)
    h.session.events.status(replace(low, battery=9))
    assert h.icon.notes == [("The steering remote's battery is at 10%. Charge it soon.", "V-Steer")]
    h.quit()


def test_menu_is_rebuilt_only_when_its_content_changes(tmp_path):
    """#31: a status that changes nothing in the menu does not rebuild it or read the registry."""
    h = Harness(tmp_path).start()
    events = h.session.events
    events.status(Status(vs200=InputState.CONNECTED, battery=50))
    before = h.icon.menu_updates
    events.status(Status(vs200=InputState.CONNECTED, battery=50))
    assert h.icon.menu_updates == before
    events.status(Status(vs200=InputState.CONNECTED, zwift=EmulatorState.READY, battery=50))
    assert h.icon.menu_updates == before + 1
    h.quit()


def test_ctrl_c_in_the_tray_stops_the_session(tmp_path):
    """#28: Ctrl+C from run.cmd goes through Quit's shutdown, not straight out of main()."""
    class InterruptedIcon(FakeIcon):
        def run(self, setup=None):
            threading.Thread(target=setup, args=(self,)).start()
            wait_for(lambda: h.sessions and h.sessions[0].calls)
            raise KeyboardInterrupt

    h = Harness(tmp_path)
    h.app._backend = SimpleNamespace(Icon=InterruptedIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    assert h.app.run() == 0
    assert "stop" in h.sessions[0].calls


def test_status_changes_do_not_read_the_registry(tmp_path):
    """/simplify: the Start with Windows checkmark is cached, not read on every menu rebuild."""
    h = Harness(tmp_path).start()
    events = h.session.events
    events.status(Status(vs200=InputState.CONNECTED, battery=50))
    reads = h.autostart.reads
    for level in (49, 48, 47):
        events.status(Status(vs200=InputState.CONNECTED, battery=level))
    assert h.autostart.reads == reads
    h.quit()


def test_icon_image_is_kept_while_its_state_is_the_same(tmp_path):
    h = Harness(tmp_path).start()
    events = h.session.events
    events.status(Status(vs200=InputState.CONNECTED, battery=50))
    sets = h.icon.icon_sets
    events.status(Status(vs200=InputState.CONNECTED, battery=49))
    assert h.icon.icon_sets == sets
    h.quit()


def test_ctrl_c_during_quit_stops_the_session_once(tmp_path):
    class QuitThenInterrupt(FakeIcon):
        def run(self, setup=None):
            threading.Thread(target=setup, args=(self,)).start()
            wait_for(lambda: h.sessions and h.sessions[0].calls)
            h.app._quit()
            raise KeyboardInterrupt

    h = Harness(tmp_path)
    h.app._backend = SimpleNamespace(Icon=QuitThenInterrupt, Menu=FakeMenu, MenuItem=FakeMenuItem)
    assert h.app.run() == 0
    assert h.sessions[0].calls.count("stop") == 1
