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

The result is `dist\V-Steer.exe`. `build.cmd` finishes with `V-Steer.exe --check`, which
loads the Bluetooth and mDNS modules to prove the build is complete.

## Release

1. Bump `__version__` in `src/vsteer/__init__.py` and merge to `main`.
2. Tag and push: `git tag v0.1.1` then `git push origin v0.1.1`.
3. CI tests, builds the exe, checks the tag matches the version and publishes the GitHub Release.
