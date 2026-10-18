# V-Steer v0.2 tray — design

Date: 2026-10-18 · Status: approved in chat, written for review · Milestone: v0.2.0 (issue #11)

## Goal

A friend downloads `V-Steer.exe`, double-clicks it and rides: no console window ever appears. A tray
icon next to the clock shows at a glance whether steering works, and its menu covers everything that
used to need the console or Notepad.

**Success:** first run, pairing in Zwift, a ride, a Zwift restart and quitting all work without the
console; the icon state matches what is connected; no notification shows more than once per run.

## Non-goals

- Auto-reconnect after a Zwift restart (#10): a separate experiment.
- A settings window: the menu is enough.
- Languages other than English (all strings are a handful of short English phrases).
- Changing the pulse length from the menu: it stays in `config.toml` (`steer.pulse_ms`).
- macOS (#24), but the design keeps the tray on the main thread, which macOS requires.

## Behaviour

### Start

- `V-Steer.exe` starts without a window; the tray icon appears.
- `V-Steer.exe --console` keeps today's behaviour: a console window with the log, no tray.
- Running from source (`run.cmd`) starts the tray too; `run.cmd --console` for the log window.

### Icon: scheme D′

| state | when | icon |
|-------|------|------|
| `READY` | VS200 `connected` **and** Zwift `ready` | the normal icon: white V, orange arrows |
| `PARTIAL` | exactly one of the two | grey V and arrows, yellow outline |
| `IDLE` | neither | grey V and arrows, no outline |
| `ERROR` | steering is impossible (fatal error, see below) | white V, red arrows, red outline |

Zwift `connected` (TCP open, not yet subscribed) and `advertising` count as "Zwift not connected".

Colours: background `#16181D`, V `#FFFFFF` (grey `#8B8F98`), arrows `#FF7A1A` (grey `#6B6F78`,
red `#E5484D`), outline yellow `#F2C230` / red `#E5484D` / green `#3FB950`.

Kept for experiments after testing on a real taskbar (selected by one constant in `ui/icon.py`):

- **A** arrows change colour: orange / yellow / grey / red.
- **B** fixed icon plus a traffic-light dot bottom-right: green / yellow / grey / red.
- **C** colour or all-grey, red arrows for errors.
- **D** like D′ with a green outline when `READY`.

Small sizes (16–48 px) use thicker strokes, as `packaging/make_icon.py` does today.

### Tooltip

`V-Steer 0.2.0 · Remote: connected · Zwift: waiting` (`waiting` for anything but `ready`). In
`ERROR`: `V-Steer 0.2.0 · Error: <short reason>`.

### Menu

1. Status line, disabled: `Remote: connected · Zwift: ready`
2. `Swap + and −` (checkmark)
3. `Pick another remote…`
4. `Start with Windows` (checkmark; only when running as the exe)
5. separator · `Open log` · `Open settings folder` · `Help`
6. `Download v0.2.1` (only when the update check found a newer release)
7. separator · `Quit`

Menu changes apply at once and are saved to `config.toml`. `Help` opens
`https://github.com/valeraparafin/v-steer#troubleshooting`; `Download` opens the releases page.

### Notifications

Each kind shows at most once per run:

| kind | text |
|------|------|
| pick | `Press a button on the VS200 you want to steer with.` |
| picked | `Remote saved. In Zwift: Paired Devices → Controls → KICKR BIKE PRO 1337.` |
| update | `V-Steer v0.2.1 is out. Download it from the V-Steer menu.` |
| error | `V-Steer can't steer: <reason>. Open the log from the V-Steer menu.` |

`Pick another remote…` shows pick/picked again (a new pick is a new action, not a repeat).

The "Zwift has not connected" hint stays in the log only; the tooltip and `Help` cover it.

### Errors

Fatal (icon `ERROR`, error notification, the app stays in the tray so the log and settings can be
opened; the user quits and starts again):

- config error; no LAN address; the DirCon port or mDNS name cannot be taken;
- an older vs200-steer is running;
- an unexpected exception in the background thread (logged with traceback).

Not fatal (icon only): VS200 asleep or out of range, Zwift not connected, a failed update check.

Second V-Steer: shows `V-Steer is already running — look for its icon next to the clock.` and exits
(Windows ties notifications to a tray icon, so it shows its own icon for that moment).

## Architecture

```
main thread                         background thread (asyncio, today's code)
-----------                         -----------------------------------------
TrayApp (pystray Icon, menu)  <---  Core status / update / errors  (via callbacks)
        |  menu actions                                ^
        +---------------------------------------------+  loop.call_soon_threadsafe
```

- The tray runs on the main thread; the existing asyncio app (`run()`: VS200 input, Zwift emulator,
  update check) runs unchanged in a background thread with its own loop.
- Background → tray: status, update and error callbacks hand plain data to the tray, which updates
  the icon image, tooltip and menu (pystray's setters are safe to call from another thread on
  Windows).
- Tray → background: menu actions are scheduled with `loop.call_soon_threadsafe` / coroutines with
  `asyncio.run_coroutine_threadsafe`.

### Units

| file | job | depends on |
|------|-----|------------|
| `ui/icon.py` | draw the icon for a state and size (Pillow); holds schemes A–D′ as data | Pillow |
| `ui/tray_model.py` | pure logic: `Status` → icon state, tooltip, menu items/checks; once-per-run notifier | core types |
| `ui/tray.py` | thin pystray wrapper: shows the model, forwards clicks | pystray, tray_model, icon |
| `autostart.py` | read/write `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\V-Steer` | winreg |
| `app.py` | mode choice (tray / `--console`), threads, start/stop, fatal errors | all above |

`packaging/make_icon.py` keeps writing `v-steer.ico` and `docs/icon.png`, now through `ui/icon.py`.

### Actions

- **Swap**: toggle `cfg.swap`, save; `Core.map_tap` already reads it live.
- **Pick another remote**: cancel the running `Vs200Input`, run `pick_remote` (with the pick/picked
  notifications), save the address, start a new `Vs200Input`.
- **Start with Windows**: registry value = the exe path in quotes; the checkmark reflects the
  registry, so a value removed elsewhere shows unchecked.
- **Open log / settings folder**: `os.startfile`.
- **Quit**: stop the background loop gracefully (as Ctrl+C does today: VS200 disconnect, mDNS
  unregister, port closed), then stop the tray. The second-instance mutex is released last.

### Build

- The exe is built windowed (no console). With `--console`, the app opens a console
  (`AllocConsole`); with `--check`/`--version` it attaches to the parent console
  (`AttachConsole(ATTACH_PARENT_PROCESS)`) so CI still sees the output and the exit code.
- Logging: no console handler in tray mode (`sys.stderr` is `None` in a windowed exe); the file log
  is unchanged.
- `pystray` and Pillow join the dependencies and `packaging/constraints.txt`; pystray's Windows
  backend joins the lazily loaded packages; `--check` also creates (not shows) a tray icon.
- Expected exe growth: ~3–4 MB.

## Testing

- `tray_model`: every `Status` combination → icon state and tooltip; menu items, checks and the
  `Download` item; once-per-run notifier, including pick/picked repeating after `Pick another
  remote`.
- `icon`: each state renders at 16/32/256 px with the expected colours at sample pixels; every
  kept scheme renders.
- `autostart`: enable/disable/is-enabled against a fake registry.
- Actions: swap persists to `config.toml`; pick-another restarts the input (fakes, as in
  `test_vs200.py`).
- Threads: a menu action reaches the background loop and a status change reaches the tray
  (real loop in a thread, fake tray backend).
- Build: `--check` in the windowed exe prints and returns its code in CI.
- Manual on the author's PC: icon states during a ride, Zwift restart, notifications, autostart
  after a reboot, Quit leaves no device in Zwift, `--console` still works.
