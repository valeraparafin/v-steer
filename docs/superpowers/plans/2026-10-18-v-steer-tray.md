# V-Steer v0.2 Tray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** V-Steer runs as a tray icon (no console window): the icon shows the connection state, the menu holds every action, and three kinds of notifications cover first run, updates and errors.

**Architecture:** The tray (pystray) owns the main thread. Today's asyncio app moves into a `Session` object that runs on a background thread and reports through an `Events` interface; the console mode (`--console`) and the tray are two `Events` implementations over the same `Session`. Pure logic (icon state, tooltip, once-per-run notifier) lives apart from the pystray wrapper so it is tested without Windows UI.

**Tech Stack:** Python 3.11, asyncio, bleak, zeroconf, pystray, Pillow, winreg, PyInstaller, pytest + pytest-asyncio (auto mode).

**Spec:** `docs/superpowers/specs/2026-10-18-v-steer-tray-design.md`

## Global Constraints

- Windows 10/11 only; Python 3.11; run from source (`run.cmd`) and as `V-Steer.exe` must both work.
- All user-facing strings are English and exactly as in the spec (menu, tooltip, notifications).
- The tray runs on the main thread; the asyncio app runs on one background thread.
- Each notification kind shows at most once per run; `Pick another remote…` re-arms pick/picked.
- Icon scheme D′ is the default; schemes A, B, C, D stay selectable by one constant.
- New dependencies `pystray` and `Pillow` are pinned in `packaging/constraints.txt` (exact versions installed in `.venv`).
- One source for lazily loaded code: `LAZY_PACKAGES` (and the new `LAZY_MODULES`) in `src/vsteer/app.py`, read by `packaging/build.py` and `--check`.
- The exe is windowed; `--check` and `--version` still print and return their exit code in CI.
- Work on branch `feat/tray` (from `docs/tray-spec`); one PR at the end; `/code-review` before the user merges.

## Task 0 (first): remove the rename leftovers

**Files:** Modify `src/vsteer/app.py` (drop `LEGACY_MUTEX`, `legacy_instance_running`, the legacy check and the settings move in `main()`), `src/vsteer/config.py` (drop `LEGACY_DIR_NAME`, `migrate_legacy_config`); Test: `tests/test_app.py`, `tests/test_config.py` (drop the tests for both).

- [ ] **Step 1:** Delete the code and its tests; `git grep -n "legacy\|vs200-steer" src tests` finds nothing but comments about history.
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest -q` and `.venv\Scriptsuff check .` — all pass.
- [ ] **Step 3:** Commit: `git commit -am "refactor: drop the vs200-steer rename leftovers"`

## Review Focus

1. Quit while a remote pick or a BLE connect is in progress: the app must still exit within a few seconds and unregister mDNS (Task 4).
2. A menu click after the background session died (fatal error): no crash, no exception dialog; the click is ignored and logged (Task 5).
3. Saving the config fails (read-only file, antivirus lock) when toggling Swap: the app keeps running, the setting still applies for this run, the failure is logged (Task 4).
4. Clicking `Pick another remote…` again while a pick runs: the second click is ignored, not a second scan (Task 4).
5. A long error reason: the Windows tooltip limit is 127 characters, so the tooltip is cut, never rejected (Task 2).

---

### Task 1: Icon renderer with state schemes

**Files:**
- Create: `src/vsteer/ui/icon.py`
- Modify: `packaging/make_icon.py` (draw through `ui.icon`), `pyproject.toml` (`dependencies` += `"pystray>=0.19"`, `"Pillow>=10"`), `packaging/constraints.txt` (add the installed `pystray`, `Pillow`, `six` versions)
- Test: `tests/test_icon.py`

**Interfaces:**
- Produces: `class IconState(Enum)` with members `READY`, `PARTIAL`, `IDLE`, `ERROR`; `SCHEMES: dict[str, dict[IconState, Look]]` with keys `"A"`, `"B"`, `"C"`, `"D"`, `"D'"`; `ACTIVE_SCHEME = "D'"`; `render(state: IconState, size: int, scheme: str = ACTIVE_SCHEME) -> PIL.Image.Image` (RGBA, `size`×`size`).
- `Look` is a frozen dataclass: `v: str`, `arrows: str`, `outline: str | None`, `dot: str | None` (hex colours).

Colours (spec): background `#16181D`; V `#FFFFFF`, grey V `#8B8F98`; arrows `#FF7A1A`, grey `#6B6F78`, red `#E5484D`; yellow `#F2C230`; green `#3FB950`.
D′: READY = white V, orange arrows, no outline; PARTIAL = grey V, grey arrows, yellow outline; IDLE = grey V, grey arrows, no outline; ERROR = white V, red arrows, red outline. D = D′ plus a green outline on READY. A: white V, arrows orange/yellow/grey/red, no outline. B: white V, orange arrows, dot green/yellow/grey/red bottom-right. C: READY normal, PARTIAL and IDLE all grey, ERROR red arrows.

- [ ] **Step 1: Install and pin the dependencies**

Run: `.venv\Scripts\python -m pip install pystray Pillow` then add the installed versions (`pip freeze | findstr /i "pystray pillow six"`) to `packaging/constraints.txt` and the two entries to `pyproject.toml`.
Expected: `python -c "import pystray, PIL"` exits 0.

- [ ] **Step 2: Write the failing tests** in `tests/test_icon.py`

```python
@pytest.mark.parametrize("size", [16, 32, 256])
@pytest.mark.parametrize("state", list(IconState))
def test_every_state_renders_at_tray_and_file_sizes(state, size):
    img = render(state, size)
    assert img.size == (size, size) and img.mode == "RGBA"

def test_ready_is_the_normal_icon():  # sample the right arrow's tip and the V at 256 px
    img = render(IconState.READY, 256)
    assert _near(img.getpixel(ARROW_TIP), "#FF7A1A") and _near(img.getpixel(V_ARM), "#FFFFFF")

def test_partial_is_grey_with_a_yellow_outline():
    img = render(IconState.PARTIAL, 256)
    assert _near(img.getpixel(V_ARM), "#8B8F98") and _near(img.getpixel(OUTLINE), "#F2C230")

def test_idle_has_no_outline():
    assert _near(render(IconState.IDLE, 256).getpixel(OUTLINE), "#16181D")

def test_error_has_red_arrows_and_outline():
    img = render(IconState.ERROR, 256)
    assert _near(img.getpixel(ARROW_TIP), "#E5484D") and _near(img.getpixel(OUTLINE), "#E5484D")

@pytest.mark.parametrize("scheme", ["A", "B", "C", "D", "D'"])
def test_every_kept_scheme_renders_every_state(scheme):
    for state in IconState:
        render(state, 32, scheme)
```

`_near(rgba, hex)` compares RGB within ±40 per channel; pick `ARROW_TIP`, `V_ARM`, `OUTLINE` coordinates from the geometry (512-unit canvas scaled to 256: right arrow tip ≈ (224, 135), V arm ≈ (100, 90), outline ≈ (128, 6)).

- [ ] **Step 3: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_icon.py -q`
Expected: FAIL (`ModuleNotFoundError: vsteer.ui.icon`).

- [ ] **Step 4: Implement `ui/icon.py`**

Move the drawing from `packaging/make_icon.py` (supersampled Pillow strokes with round caps, thicker strokes at ≤24 and ≤48 px). Outline: a rounded-rect stroke inset from the tile edge (≈44 of 512 units). Dot: a circle at (420, 420) r≈72 with a background-coloured ring. `make_icon.py` keeps its outputs (`packaging/v-steer.ico`, `docs/icon.png`) and calls `render(IconState.READY, size)`.

- [ ] **Step 5: Run tests, regenerate the icon, commit**

Run: `.venv\Scripts\python -m pytest -q` (all pass), `.venv\Scripts\python packaging\make_icon.py`, open `docs/icon.png` and compare with the current icon (same look).

```bash
git add src/vsteer/ui/icon.py packaging/make_icon.py packaging/v-steer.ico docs/icon.png pyproject.toml packaging/constraints.txt tests/test_icon.py
git commit -m "feat: icon renderer with tray state schemes (D' default)"
```

---

### Task 2: Tray model (pure logic)

**Files:**
- Create: `src/vsteer/ui/tray_model.py`
- Test: `tests/test_tray_model.py`

**Interfaces:**
- Consumes: `Status`, `InputState`, `EmulatorState` (existing), `IconState` (Task 1).
- Produces:
  - `icon_state(status: Status, error: str | None) -> IconState`
  - `status_line(status: Status) -> str` → `"Remote: connected · Zwift: ready"`
  - `tooltip(version: str, status: Status, error: str | None) -> str`, ≤127 chars
  - `MESSAGES: dict[str, str]` with keys `pick`, `picked`, `update`, `error`
  - `class Notifier(send: Callable[[str], None])` with `once(kind: str, **fmt) -> bool` and `rearm(*kinds: str) -> None`

Exact strings (spec):
- remote word: `connected` for `InputState.CONNECTED`, else `searching`; Zwift word: `ready` for `EmulatorState.READY`, else `waiting`.
- tooltip: `f"V-Steer {version} · Remote: {r} · Zwift: {z}"`, or `f"V-Steer {version} · Error: {error}"`.
- `pick`: `Press a button on the VS200 you want to steer with.`
- `picked`: `Remote saved. In Zwift: Paired Devices → Controls → KICKR BIKE PRO 1337.`
- `update`: `V-Steer {tag} is out. Download it from the V-Steer menu.`
- `error`: `V-Steer can't steer: {reason}. Open the log from the V-Steer menu.`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("vs200,zwift,expected", [
    (InputState.CONNECTED, EmulatorState.READY, IconState.READY),
    (InputState.CONNECTED, EmulatorState.ADVERTISING, IconState.PARTIAL),
    (InputState.SEARCHING, EmulatorState.READY, IconState.PARTIAL),
    (InputState.CONNECTED, EmulatorState.CONNECTED, IconState.PARTIAL),  # TCP open, not subscribed
    (InputState.SEARCHING, EmulatorState.ADVERTISING, IconState.IDLE),
    (InputState.SEARCHING, EmulatorState.STOPPED, IconState.IDLE),
])
def test_icon_state(vs200, zwift, expected): ...

def test_an_error_overrides_everything():
    assert icon_state(Status(InputState.CONNECTED, EmulatorState.READY), "no LAN") is IconState.ERROR

def test_tooltip_and_status_line():
    s = Status(InputState.CONNECTED, EmulatorState.ADVERTISING)
    assert status_line(s) == "Remote: connected · Zwift: waiting"
    assert tooltip("0.2.0", s, None) == "V-Steer 0.2.0 · Remote: connected · Zwift: waiting"
    assert tooltip("0.2.0", s, "Config error") == "V-Steer 0.2.0 · Error: Config error"

def test_a_long_error_fits_the_windows_tooltip():
    assert len(tooltip("0.2.0", Status(), "x" * 500)) <= 127

def test_each_notification_shows_once_per_run():
    sent = []
    n = Notifier(sent.append)
    assert n.once("update", tag="v0.2.1") and not n.once("update", tag="v0.2.1")
    assert sent == ["V-Steer v0.2.1 is out. Download it from the V-Steer menu."]

def test_pick_another_remote_rearms_pick_and_picked():
    sent = []
    n = Notifier(sent.append)
    n.once("pick"); n.once("picked"); n.rearm("pick", "picked")
    assert n.once("pick") and len(sent) == 3
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_tray_model.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `ui/tray_model.py`** with the signatures above; the tooltip cuts to 127 characters with a trailing `…`.

- [ ] **Step 4: Run tests and commit**

Run: `.venv\Scripts\python -m pytest -q` — all pass.

```bash
git add src/vsteer/ui/tray_model.py tests/test_tray_model.py
git commit -m "feat: tray model: icon state, tooltip, once-per-run notifier"
```

---

### Task 3: Start with Windows

**Files:**
- Create: `src/vsteer/autostart.py`
- Test: `tests/test_autostart.py`

**Interfaces:**
- Produces: `RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"`, `VALUE_NAME = "V-Steer"`;
  `is_enabled(reg=winreg) -> bool`, `enable(exe_path: str, reg=winreg) -> None` (writes `f'"{exe_path}"'`), `disable(reg=winreg) -> None` (no error when absent), `available() -> bool` (True only when `sys.frozen`).

- [ ] **Step 1: Write the failing tests** with a `FakeReg` exposing the `winreg` calls used (`OpenKey`/`CreateKey`, `SetValueEx`, `QueryValueEx`, `DeleteValue`, `HKEY_CURRENT_USER`, `REG_SZ`, `KEY_*`), storing values in a dict and raising `FileNotFoundError` like `winreg` does:

```python
def test_enable_quotes_a_path_with_spaces():
    reg = FakeReg()
    enable(r"C:\Users\Valera Bike\Downloads\V-Steer.exe", reg)
    assert reg.values["V-Steer"] == r'"C:\Users\Valera Bike\Downloads\V-Steer.exe"' and is_enabled(reg)

def test_disable_twice_is_fine():
    reg = FakeReg(); disable(reg); disable(reg)
    assert not is_enabled(reg)

def test_only_offered_in_the_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert available() is False
```

- [ ] **Step 2: Run to verify they fail** — Run: `.venv\Scripts\python -m pytest tests/test_autostart.py -q` — Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `autostart.py`** (HKCU only, no admin rights).

- [ ] **Step 4: Run tests and commit**

Run: `.venv\Scripts\python -m pytest -q` — all pass.

```bash
git add src/vsteer/autostart.py tests/test_autostart.py
git commit -m "feat: Start with Windows via the HKCU Run key"
```

---

### Task 4: Session and Events (the asyncio app as an object)

**Files:**
- Create: `src/vsteer/session.py`
- Modify: `src/vsteer/app.py` (`run()` and `_ride()` become `Session`; hint loop, update announcement move into `session.py`), `src/vsteer/ui/console.py` (add `ConsoleEvents`)
- Test: `tests/test_session.py`; keep `tests/test_app.py` green (`app.run` stays as a thin wrapper)

**Interfaces:**
- Consumes: `pick_remote`, `Vs200Input`, `RideEmulator`, `Core`, `config.save`, `update.check_for_update`, `net.pick_address` (existing).
- Produces:
  - `class Events` (no-op base): `status(s: Status)`, `pick_started()`, `picked(address: str)`, `update_available(tag: str)`, `fatal(reason: str)`.
  - `class ConsoleEvents(Events)` in `ui/console.py`: logs exactly what the console shows today (`== ...` status lines, `New version ... is available: ...`, the first-run lines).
  - `class Session(cfg, cfg_path, events, *, pick=pick_remote, input_factory=Vs200Input, emulator_factory=RideEmulator, lan: str | None = None, check_update=update.check_for_update)` with
    - `async run() -> int`: 0 after `stop()`; 2 after a fatal error (and `events.fatal(reason)` called once).
    - `async pick_another() -> None`: ignored while a pick runs; cancels the running input, emits `pick_started`, runs `pick`, saves the address, emits `picked`, starts a new input.
    - `set_swap(on: bool) -> None`: sets `cfg.swap`, saves; a failed save is logged and the new value still applies.
    - `async stop() -> None`: makes `run()` return; safe during a pick or a connect.
  - `app.run(cfg, cfg_path) -> int` = `await Session(cfg, cfg_path, ConsoleEvents()).run()`.

Fatal reasons (spec): `"No VS200 was pressed within 2 minutes"`, `"No LAN address found"`, `"Zwift link could not start: {exc}"` (port/mDNS), passed to `events.fatal`.

- [ ] **Step 1: Write the failing tests** (fakes from `test_vs200.py` / a fake emulator with `start/stop/state/on_state_change/advertised_name/bound_port`)

```python
async def test_first_run_reports_pick_and_saves_the_remote(tmp_path): ...
    # events.calls == ["pick_started", ("picked", "A1"), ...]; config.toml has address A1
async def test_no_lan_address_is_fatal_once(tmp_path): ...
    # Session(..., lan="") -> run() == 2; events.fatal called once with "No LAN address found"
async def test_stop_ends_run_and_stops_the_emulator(tmp_path): ...
async def test_stop_during_a_pick_returns_quickly(tmp_path): ...       # Review Focus 1
    # pick waits forever; stop() -> run() returns within 1 s; emulator.stop not required (not started)
async def test_pick_another_restarts_the_input_with_the_new_remote(tmp_path): ...
async def test_a_second_pick_another_while_picking_is_ignored(tmp_path): ...  # Review Focus 4
def test_set_swap_saves_and_applies(tmp_path): ...
def test_set_swap_survives_a_read_only_config(tmp_path, monkeypatch): ...      # Review Focus 3
    # config.save raises PermissionError -> no exception, cfg.swap is True, warning logged
async def test_a_newer_release_reaches_events(tmp_path): ...
    # check_update returns "v0.2.1" -> events.update_available("v0.2.1")
```

- [ ] **Step 2: Run to verify they fail** — Run: `.venv\Scripts\python -m pytest tests/test_session.py -q` — Expected: FAIL (`ModuleNotFoundError: vsteer.session`).

- [ ] **Step 3: Implement `session.py`; slim `app.py`**

`run()` keeps its tasks (input, hint loop, update check) in a set and cancels them on `stop()`; the emulator is stopped in `finally` as today. `Core.subscribe(events.status)`. Keep the log lines `app.py` writes today (hint loop text unchanged).

- [ ] **Step 4: Run the whole suite and commit**

Run: `.venv\Scripts\python -m pytest -q` and `.venv\Scripts\ruff check .` — all pass, `tests/test_app.py` unchanged.

```bash
git add src/vsteer/session.py src/vsteer/app.py src/vsteer/ui/console.py tests/test_session.py
git commit -m "refactor: the asyncio app becomes a Session reporting through Events"
```

---

### Task 5: Tray app and threads

**Files:**
- Create: `src/vsteer/ui/tray.py`
- Test: `tests/test_tray.py`

**Interfaces:**
- Consumes: `Session`, `Events` (Task 4); `icon_state`, `tooltip`, `status_line`, `Notifier`, `MESSAGES` (Task 2); `render`, `IconState` (Task 1); `autostart` (Task 3); `update.RELEASES_PAGE`.
- Produces:
  - `class BackgroundLoop`: `start() -> None` (thread `"v-steer-session"` with its own loop), `submit(coro) -> concurrent.futures.Future`, `stop(timeout: float = 10) -> None`, `alive: bool`.
  - `class TrayApp(session_factory: Callable[[Events], Session], *, backend=pystray, version=__version__, autostart_mod=autostart, open_path=os.startfile, open_url=webbrowser.open, log_path: Path, settings_dir: Path)` with `run() -> int` (blocks on the main thread until Quit; returns the session's exit code, 0 on Quit).
  - `notify_and_exit(message: str, *, backend=pystray) -> None` for "already running" (shows a temporary icon, notifies, waits ~5 s, stops).
  - `TrayApp.run_error(reason: str) -> int`: the tray in `ERROR` with the error notification, no session (config error); only Open log / Open settings folder / Help / Quit work.
  - `HELP_URL = "https://github.com/valeraparafin/v-steer#troubleshooting"`.

Menu (spec, in order): status line (disabled) · `Swap + and −` (checked = `cfg.swap`) · `Pick another remote…` · `Start with Windows` (checked = `autostart.is_enabled()`, visible = `autostart.available()`) · separator · `Open log` · `Open settings folder` · `Help` · `Download {tag}` (visible only after `update_available`) · separator · `Quit`.

- [ ] **Step 1: Write the failing tests** with a `FakeBackend` mimicking `pystray.Icon` (`icon`, `title`, `menu`, `notify(msg, title)`, `run(setup)`, `stop()`, `update_menu()`) and `Menu`/`MenuItem` that record items; drive the menu by calling item actions.

```python
def test_status_changes_reach_the_icon_and_tooltip(): ...
    # TrayEvents.status(Status(CONNECTED, READY)) -> backend.icon == render(READY,...) bytes, title "V-Steer 0.2.0 · Remote: connected · Zwift: ready"
def test_menu_matches_the_spec(): ...           # labels in order, Download hidden until update
def test_update_shows_download_and_notifies_once(): ...
def test_fatal_turns_the_icon_red_and_notifies_once(): ...
def test_swap_click_reaches_the_session_on_its_loop(): ...   # real BackgroundLoop + fake session; set_swap called on the session thread
def test_quit_stops_the_session_then_the_tray(): ...         # session.stop awaited, backend.stop called, run() returns 0
def test_a_click_after_the_session_died_is_ignored(): ...    # Review Focus 2: loop stopped -> click logs, no exception
def test_a_crash_in_the_session_turns_the_icon_red(): ...    # session.run raises -> ERROR icon, error notification, traceback logged
def test_help_and_download_open_the_right_urls(): ...
```

- [ ] **Step 2: Run to verify they fail** — Run: `.venv\Scripts\python -m pytest tests/test_tray.py -q` — Expected: FAIL (`ModuleNotFoundError: vsteer.ui.tray`).

- [ ] **Step 3: Implement `ui/tray.py`**

`TrayEvents` (an `Events`) records the latest status/error/update tag under a lock and calls `TrayApp.refresh()` (sets `backend.icon`, `backend.title`, `update_menu()`); notifications go through `Notifier` with `backend.notify(message, "V-Steer")`. Menu callbacks submit coroutines to `BackgroundLoop`; when `alive` is false they log and return. The pick/picked notifications are re-armed when `Pick another remote…` is clicked.

- [ ] **Step 4: Run tests and commit**

Run: `.venv\Scripts\python -m pytest -q` — all pass.

```bash
git add src/vsteer/ui/tray.py tests/test_tray.py
git commit -m "feat: tray app: icon, menu, notifications over a background session"
```

---

### Task 6: Tray as the default mode; windowed exe

**Files:**
- Modify: `src/vsteer/app.py` (mode choice, `--console`, console attach, logging, `LAZY_MODULES`, `_smoke_runtime`), `packaging/build.py` (`--noconsole`, `--hidden-import` for `LAZY_MODULES`), `packaging/entry.py` (unchanged entry, check), `run.cmd` (no change needed; verify)
- Test: `tests/test_app.py`, `tests/test_build.py`

**Interfaces:**
- Consumes: `TrayApp`, `notify_and_exit` (Task 5), `Session`, `ConsoleEvents` (Task 4).
- Produces: `--console` flag; `LAZY_MODULES = ("pystray._win32",)`; `attach_console(new: bool) -> None` (`AllocConsole` when `new`, else `AttachConsole(ATTACH_PARENT_PROCESS)`; then rebinds `sys.stdout`/`sys.stderr` to `CONOUT$`; when no console can be had, to `os.devnull`); `setup_logging(debug, log_path, console: bool)`.

Flow in `main()`: `--check`/`--version` → `attach_console(new=False)` first. `--console` → `attach_console(new=True)`, today's path with `ConsoleEvents`. Default → tray: second instance → `notify_and_exit("V-Steer is already running — look for its icon next to the clock.")`; config error → `run_error(<the ConfigError text>)`; otherwise `TrayApp(...).run()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_check_prints_even_without_a_console(monkeypatch, capsys): ...
    # sys.stdout None before main(["--check"]) -> no exception, exit code 0
def test_console_flag_uses_the_console_events(monkeypatch): ...   # Session built with ConsoleEvents
def test_default_mode_starts_the_tray(monkeypatch): ...            # TrayApp.run called
def test_second_instance_in_tray_mode_notifies_and_exits(monkeypatch): ...
def test_a_config_error_starts_the_tray_in_error(monkeypatch, tmp_path): ...   # run_error called with the ConfigError text
def test_no_console_log_handler_without_stderr(monkeypatch, tmp_path): ...   # sys.stderr None -> only the file handler
def test_the_exe_bundles_pystrays_windows_backend():               # in tests/test_build.py
    assert ["--hidden-import", "pystray._win32"] in pairs(_build_module().pyinstaller_args())
def test_the_exe_is_windowed():
    assert "--noconsole" in _build_module().pyinstaller_args() and "--console" not in ...
```

- [ ] **Step 2: Run to verify they fail** — Run: `.venv\Scripts\python -m pytest tests/test_app.py tests/test_build.py -q` — Expected: FAIL on the new tests.

- [ ] **Step 3: Implement** the flow above; `--check` also imports `LAZY_MODULES` and builds (not runs) `pystray.Icon("v-steer-check", render(IconState.IDLE, 32))`.

- [ ] **Step 4: Verify the exe**

Run: `.\build.cmd`
Expected: ends with `V-Steer 0.1.1 check OK`; `dist\V-Steer.exe` ~15–16 MB; double-click shows the tray icon and no console; `dist\V-Steer.exe --console` opens the log window.

- [ ] **Step 5: Run the suite and commit**

Run: `.venv\Scripts\python -m pytest -q` and `.venv\Scripts\ruff check .` — all pass.

```bash
git add src/vsteer/app.py packaging/build.py tests/test_app.py tests/test_build.py
git commit -m "feat: tray is the default; windowed exe; --console for the log window"
```

---

### Task 7: Docs and the manual check

**Files:**
- Modify: `README.md` (First run and Every next ride describe the tray; a short "The tray icon" table with the four states and the menu; `--console` under Troubleshooting), `docs/how-it-works.md` (code map rows for `session.py`, `ui/icon.py`, `ui/tray_model.py`, `ui/tray.py`, `autostart.py`; threads in one paragraph)

- [ ] **Step 1: Update the docs** (user steps only in README, technical notes in how-it-works).

- [ ] **Step 2: Manual check on the author's PC** — record the result in the PR description:
  - the icon is grey, turns yellow-outlined when one side connects, normal when both connect;
  - first run: pick/picked notifications; restart: none of them again;
  - Zwift restart: icon back to yellow-outlined, then normal after re-pairing;
  - Swap and Start with Windows survive a restart; autostart works after a reboot;
  - Quit: the device disappears from Zwift's list; `--console` still works.

- [ ] **Step 3: Commit, push, open the PR, run `/code-review`**

```bash
git add README.md docs/how-it-works.md
git commit -m "docs: the tray in README and how-it-works"
git push -u origin feat/tray
```
