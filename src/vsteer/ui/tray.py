"""The tray icon: pystray on the main thread, the Session on a background asyncio thread.

Background -> tray: TrayEvents stores the news and refreshes the icon, tooltip and menu (pystray's
setters may be called from any thread on Windows). Tray -> background: menu clicks submit
coroutines to the session's loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pystray

from .. import __version__, autostart, update
from ..core import Status
from ..session import Events, Session
from .icon import IconState, render
from .tray_model import Notifier, icon_state, status_line, tooltip

log = logging.getLogger("vsteer")

HELP_URL = "https://github.com/valeraparafin/v-steer#troubleshooting"
TITLE = "V-Steer"
TRAY_SIZE = 32  # Windows scales it to the tray (16-32 px by DPI); the small-size strokes stay thick
NOTIFY_MAX = 255  # szInfo holds 256 characters with the terminator
QUIT_TIMEOUT_S = 10


@cache
def _image(state: IconState):
    return render(state, TRAY_SIZE)


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


class BackgroundLoop:
    """An asyncio loop on its own thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        ready = threading.Event()

        def main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            try:
                loop.run_forever()
            finally:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
                loop.close()

        self._thread = threading.Thread(target=main, name="v-steer-session", daemon=True)
        self._thread.start()
        ready.wait()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._loop and self._loop.is_running())

    def submit(self, coro) -> concurrent.futures.Future:
        if not self.alive:
            coro.close()
            raise RuntimeError("the background loop has stopped")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self, timeout: float = 10) -> None:
        if self._loop and self._thread and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout)


class TrayEvents(Events):
    def __init__(self, app: TrayApp) -> None:
        self._app = app

    def status(self, s: Status) -> None:
        self._app._set(status=s)

    def pick_started(self) -> None:
        self._app.notifier.once("pick")

    def picked(self, address: str, device: str) -> None:
        self._app.notifier.once("picked", device=device)

    def update_available(self, tag: str) -> None:
        self._app._set(update_tag=tag)
        self._app.notifier.once("update", tag=tag)

    def fatal(self, reason: str) -> None:
        self._app._set(error=reason)
        self._app.notifier.once("error", reason=reason)


class TrayApp:
    def __init__(self, session_factory: Callable[[Events], Session], *, backend=pystray, version: str = __version__,
                 autostart_mod=autostart, open_path=None, open_url=webbrowser.open, log_path: Path,
                 settings_dir: Path, exe_path: str | None = None) -> None:
        self._session_factory = session_factory
        self._backend = backend
        self._version = version
        self._autostart = autostart_mod
        self._open_path = open_path or os.startfile
        self._open_url = open_url
        self._log_path = log_path
        self._settings_dir = settings_dir
        self._exe_path = exe_path or sys.executable
        self._lock = threading.Lock()
        self._status = Status()
        self._error: str | None = None
        self._update_tag: str | None = None
        self.session: Session | None = None
        self.loop = BackgroundLoop()
        self.notifier = Notifier(self._notify)
        self._icon = None
        self._quitting = False

    # --- running -----------------------------------------------------------------

    def run(self) -> int:
        """Show the tray and ride until Quit. Blocks; call it on the main thread."""
        self._show(self._start_session)
        return 0

    def run_error(self, reason: str) -> int:
        """The tray in ERROR without a session (e.g. a broken config): log, settings, help and quit work."""
        self._error = reason

        def setup() -> None:
            self.notifier.once("error", reason=reason)

        self._show(setup)
        return 0

    def _show(self, then: Callable[[], None]) -> None:
        state, title = self._looks()
        self._icon = self._backend.Icon(TITLE, _image(state), title, menu=self._menu())

        def setup(icon) -> None:
            icon.visible = True  # first: Windows drops notifications of a hidden icon
            then()

        self._icon.run(setup)

    def _start_session(self) -> None:
        self.loop.start()
        self.session = self._session_factory(TrayEvents(self))
        self.loop.submit(self._run_session(self.session))

    async def _run_session(self, session: Session) -> None:
        try:
            await session.run()
        except Exception as exc:  # keep the tray up so the log can be opened
            log.exception("V-Steer stopped on an unexpected error")
            self._set(error=f"unexpected error: {exc}")
            self.notifier.once("error", reason=f"unexpected error: {exc}")

    # --- what the tray shows --------------------------------------------------------

    def _set(self, **changes) -> None:
        with self._lock:
            if "status" in changes:
                self._status = changes["status"]
            if "error" in changes:
                self._error = changes["error"]
            if "update_tag" in changes:
                self._update_tag = changes["update_tag"]
        self.refresh()

    def _looks(self) -> tuple[IconState, str]:
        with self._lock:
            return icon_state(self._status, self._error), tooltip(self._version, self._status, self._error)

    def refresh(self) -> None:
        icon = self._icon
        if icon is None:
            return
        state, title = self._looks()
        icon.icon = _image(state)
        icon.title = title
        icon.update_menu()

    def _notify(self, message: str) -> None:
        if self._icon is not None:
            try:
                self._icon.notify(_fit(message, NOTIFY_MAX), TITLE)
            except Exception as exc:  # noqa: BLE001 - a lost notification must not stop the ride
                log.warning("Could not show a notification: %s", exc)

    def _status_text(self, _item=None) -> str:
        with self._lock:
            return _fit(f"Error: {self._error}", 60) if self._error else status_line(self._status)

    def _menu(self):
        item, separator = self._backend.MenuItem, self._backend.Menu.SEPARATOR
        has_session = lambda _item: self.session is not None
        return self._backend.Menu(
            item(self._status_text, None, enabled=False),
            item("Swap + and −", self._toggle_swap, checked=lambda _item: self._swap_on(), enabled=has_session),
            item("Pick another remote…", self._pick_another,
                 enabled=lambda _item: self.session is not None and self._error is None),
            item("Start with Windows", self._toggle_autostart, checked=lambda _item: self._autostart_on(),
                 visible=self._autostart.available()),
            separator,
            item("Open log", self._open_log),
            item("Open settings folder", self._open_settings),
            item("Help", self._help),
            item(lambda _item: f"Download {self._update_tag}", self._download,
                 visible=lambda _item: self._update_tag is not None),
            separator,
            item("Quit", self._quit),
        )

    # --- menu actions (on the tray's thread) -----------------------------------------------

    def _submit(self, what: str, make_coro: Callable[[], object]) -> bool:
        if self.session is None or not self.loop.alive:
            log.info("%s ignored: the background session has stopped", what)
            return False
        try:
            self.loop.submit(make_coro())
        except RuntimeError:
            log.info("%s ignored: the background session has stopped", what)
            return False
        return True

    def _swap_on(self) -> bool:
        return bool(self.session and self.session.cfg.swap)

    def _toggle_swap(self) -> None:
        session = self.session
        if session is None:
            return
        on = not session.cfg.swap

        async def apply() -> None:
            session.set_swap(on)
            self.refresh()

        self._submit("Swap", apply)

    def _pick_another(self) -> None:
        session = self.session
        if session is None:
            return
        self.notifier.rearm("pick", "picked")  # a new pick is a new action, not a repeat
        self._submit("Pick another remote", session.pick_another)

    def _autostart_on(self) -> bool:
        try:
            return self._autostart.is_enabled()
        except OSError:
            return False

    def _toggle_autostart(self) -> None:
        try:
            if self._autostart.is_enabled():
                self._autostart.disable()
            else:
                self._autostart.enable(self._exe_path)
        except OSError as exc:
            log.warning("Could not change Start with Windows: %s", exc)
        self.refresh()

    def _open(self, path: Path) -> None:
        try:
            self._open_path(str(path))
        except OSError as exc:
            log.warning("Could not open %s: %s", path, exc)

    def _open_log(self) -> None:
        self._open(self._log_path)

    def _open_settings(self) -> None:
        self._open(self._settings_dir)

    def _help(self) -> None:
        self._open_url(HELP_URL)

    def _download(self) -> None:
        self._open_url(update.RELEASES_PAGE)

    def _quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        # Off the tray's thread: the icon must keep pumping messages while the session shuts down.
        threading.Thread(target=self._shutdown, name="v-steer-quit").start()

    def _shutdown(self) -> None:
        session = self.session
        if session is not None and self.loop.alive:
            try:
                self.loop.submit(session.stop()).result(QUIT_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - quit anyway
                log.warning("The session did not stop cleanly: %r", exc)
        self.loop.stop()
        log.info("Stopped.")
        if self._icon is not None:
            self._icon.stop()


def notify_and_exit(message: str, *, backend=pystray, wait_s: float = 5) -> None:
    """Show one notification from a temporary icon (Windows ties notifications to an icon), then leave."""

    def setup(icon) -> None:
        icon.visible = True
        icon.notify(message, TITLE)
        time.sleep(wait_s)
        icon.stop()

    backend.Icon(TITLE, _image(IconState.IDLE), TITLE).run(setup)
