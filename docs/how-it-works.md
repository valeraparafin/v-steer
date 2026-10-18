# How V-Steer works

```
VS200 --BLE notify--> V-Steer --DirCon over TCP + mDNS--> Zwift
```

- **Input.** The VS200 sends one BLE notification per press on characteristic `0xFEA1`
  (service `0xFEA0`): `f3050301fc` for `+`, `f3050300fb` for `−`. No repeat, no release.
- **Output.** The app pretends to be a Zwift Ride controller on the local network, the way
  Wi-Fi trainers do: Wahoo DirCon over TCP (port 36866+), announced over mDNS
  (`_wahoo-fitness-tnp._tcp`). Zwift pairs it under Controls.
- **Steering.** Each tap becomes a short D-pad press (left/right) on the controller: one lane
  step. A "released" frame every 5 s keeps Zwift from dropping the idle controller.

The full protocol notes and design decisions are in
[the design spec](superpowers/specs/2026-10-13-vs200-steer-design.md).

## Code map

| file | job |
|------|-----|
| `src/vsteer/vs200.py` | find, pick and reconnect the VS200; turn packets into taps |
| `src/vsteer/zwift/ride.py` | Zwift Ride emulation: DirCon server, mDNS, D-pad pulses, keepalive |
| `src/vsteer/zwift/dircon.py` | DirCon server, vendored from ZwiftBridge (MIT) |
| `src/vsteer/zwift/protocol.py` | UUIDs, frames, GET replies |
| `src/vsteer/core.py` | wires taps to pulses, publishes status |
| `src/vsteer/session.py` | one ride: pick, advertise, steer; reports through `Events` |
| `src/vsteer/ui/tray.py` | the tray icon and menu over a background session |
| `src/vsteer/ui/tray_model.py` | what the tray shows: icon state, tooltip, notification texts |
| `src/vsteer/ui/icon.py` | draws the icon for each state (schemes A–D′, `ACTIVE_SCHEME`) |
| `src/vsteer/ui/console.py` | `--console`: the status line in the log |
| `src/vsteer/autostart.py` | Start with Windows (`HKCU\...\Run`, value `V-Steer`) |
| `src/vsteer/net.py` | picks the LAN address to advertise |
| `src/vsteer/config.py` | `%APPDATA%\V-Steer\config.toml` |
| `src/vsteer/app.py` | command line, logging, single instance, tray or console |

**Threads.** The tray (pystray) owns the main thread, as Windows and macOS want. The ride runs as
a `Session` on one background thread with its own asyncio loop. The session reports through
`Events` (status, pick, update, fatal error); the tray stores the news and redraws the icon,
tooltip and menu. Menu clicks go the other way as coroutines submitted to the session's loop.
`--console` runs the same `Session` with `ConsoleEvents` on the main thread instead.

## Run from source

Needs Python 3.11+.

```bat
git clone https://github.com/valeraparafin/v-steer.git
cd v-steer
.\setup.cmd
.\run.cmd
```

`.\run.cmd` starts the tray; `.\run.cmd --console` shows the log in the terminal instead.
`--debug` logs the full DirCon traffic to `%APPDATA%\V-Steer\v-steer.log`.

## Tests

```bat
.venv\Scripts\ruff check .
.venv\Scripts\python -m pytest
```

No hardware needed: Bluetooth and Zwift are faked.

## Build the exe

```bat
.venv\Scripts\python -m pip install -e .[build]
.\build.cmd
```

The result is `dist\V-Steer.exe`, a windowed exe (no console). `build.cmd` runs
`packaging\build.py`, which bundles what `LAZY_PACKAGES` and `LAZY_MODULES` (`src/vsteer/app.py`)
list, leaves out the Pillow codecs the icon never uses, and finishes with `V-Steer.exe --check`: it
loads those modules and builds a Bluetooth scanner, client, mDNS stack and tray icon to prove the
build is complete. `--check` and `--version` print to the console they are started from.

GitHub Actions in `.github/workflows` are pinned to commit SHAs; Dependabot proposes the bumps.

## Release

A release is made by a `v*` tag; CI does the rest: tests, builds `V-Steer.exe`, checks the tag
matches `__version__` and attaches the exe to the GitHub Release. Running copies of V-Steer
announce the new version on their next start.

**1. Bump the version** (website is enough):

1. Open `src/vsteer/__init__.py` on GitHub, click the pencil, change the `__version__` number to
   the new one, higher than the last release, e.g. `"0.2.1"`. Optional: add the release notes as
   `docs/release-notes/v0.2.1.md` in the same branch.
2. **Commit changes… → Create a new branch → Propose changes → Create pull request.**
3. Wait for the `test` and `build` checks, then **Merge**.

**2a. Release from the website:**

1. **Releases → Draft a new release.**
2. **Tag:** type `v0.2.1` (the same number as `__version__`, with the `v`) → *Create new tag*.
   **Target:** `main`.
3. **Title:** `V-Steer v0.2.1`. Paste `docs/release-notes/v0.2.1.md` if you wrote it (CI does not
   replace text on a release made here), or **Generate release notes**.
4. Choose **Pre-release**, then **Publish release**. (A pre-release is not announced to running
   copies yet: the exe is not attached for the first few minutes.)
5. Under **Actions** a run for `v0.2.1` starts; after about 5 minutes `V-Steer.exe` is attached to
   the release.
6. Edit the release, choose **Latest**, **Update release**. Now running copies announce it.

This website path has not been used for a V-Steer release yet: if no run starts under **Actions**
in step 5, delete the release and its tag (see below) and use 2b.

**2b. Or from a terminal:**

```bat
git checkout main
git pull
git tag -a v0.2.1 -m "V-Steer v0.2.1"
git push origin v0.2.1
```

CI creates the release itself, with the exe and the notes from `docs/release-notes/v0.2.1.md` if
that file exists (write it in the version PR), otherwise from `packaging/release-notes.md` plus the
merged PRs. Edit the text afterwards if you like.

**If the exe does not appear:** open **Actions** and find the red step. Most often the tag and
`__version__` differ. Delete the release (**Releases → … → Delete**), then its tag (**Tags** → the
tag → **Delete**, or `git push origin --delete v0.2.1`): deleting a release keeps its tag. Fix the
version and release again. Re-running a failed run is safe; it re-uploads the exe to the existing
release.

## Icon

`src/vsteer/ui/icon.py` draws the icon for every tray state; `packaging/make_icon.py` writes the
ready look to `packaging/v-steer.ico` (the exe) and `docs/icon.png`, and every state to
`docs/tray/` (the README table). After a design change run
`.venv\Scripts\python packaging\make_icon.py` and commit the outputs.
