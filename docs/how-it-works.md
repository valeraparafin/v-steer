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
| `src/vsteer/net.py` | picks the LAN address to advertise |
| `src/vsteer/config.py` | `%APPDATA%\V-Steer\config.toml` |
| `src/vsteer/app.py` | command line, logging, single instance |

## Run from source

Needs Python 3.11+.

```bat
git clone https://github.com/valeraparafin/v-steer.git
cd v-steer
.\setup.cmd
.\run.cmd
```

`.\run.cmd --debug` logs the full DirCon traffic to `%APPDATA%\V-Steer\v-steer.log`.

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

The result is `dist\V-Steer.exe`. `build.cmd` runs `packaging\build.py`, which bundles the
packages listed in `LAZY_PACKAGES` (`src/vsteer/app.py`) and finishes with `V-Steer.exe --check`:
it loads those packages and builds a Bluetooth scanner, client and mDNS stack to prove the build
is complete.

GitHub Actions in `.github/workflows` are pinned to commit SHAs; Dependabot proposes the bumps.

## Release

A release is made by a `v*` tag; CI does the rest: tests, builds `V-Steer.exe`, checks the tag
matches `__version__` and attaches the exe to the GitHub Release. Running copies of V-Steer
announce the new version on their next start.

**1. Bump the version** (website is enough):

1. Open `src/vsteer/__init__.py` on GitHub, click the pencil, change `__version__ = "0.1.1"` to
   the new number, e.g. `"0.1.2"`.
2. **Commit changes… → Create a new branch → Propose changes → Create pull request.**
3. Wait for the `test` and `build` checks, then **Merge**.

**2a. Release from the website:**

1. **Releases → Draft a new release.**
2. **Tag:** type `v0.1.2` (the same number as `__version__`, with the `v`) → *Create new tag*.
   **Target:** `main`.
3. **Title:** `V-Steer v0.1.2`. **Generate release notes**, edit the text if you like.
4. **Publish release.** CI attaches `V-Steer.exe` in about 5 minutes (progress under **Actions**).

**2b. Or from a terminal:** `git tag -a v0.1.2 -m "V-Steer v0.1.2"` then `git push origin v0.1.2`.
CI creates the release with notes from `packaging/release-notes.md` plus the merged PRs.

**If the exe does not appear:** open **Actions**, find the red step. Most often the tag and
`__version__` differ: delete the release and the tag, fix the version, release again. Re-running a
failed run is safe; it re-uploads the exe to the existing release.

## Icon

`packaging/make_icon.py` draws the icon (`packaging/v-steer.ico` for the exe, `docs/icon.png`
for the README). Edit it and run `.venv\Scripts\python packaging\make_icon.py` (needs `pip install
pillow`); commit both outputs.
