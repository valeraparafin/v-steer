# How vs200-steer works

```
VS200 --BLE notify--> vs200-steer --DirCon over TCP + mDNS--> Zwift
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
| `src/vs200steer/vs200.py` | find, pick and reconnect the VS200; turn packets into taps |
| `src/vs200steer/zwift/ride.py` | Zwift Ride emulation: DirCon server, mDNS, D-pad pulses, keepalive |
| `src/vs200steer/zwift/dircon.py` | DirCon server, vendored from ZwiftBridge (MIT) |
| `src/vs200steer/zwift/protocol.py` | UUIDs, frames, GET replies |
| `src/vs200steer/core.py` | wires taps to pulses, publishes status |
| `src/vs200steer/net.py` | picks the LAN address to advertise |
| `src/vs200steer/config.py` | `%APPDATA%\vs200-steer\config.toml` |
| `src/vs200steer/app.py` | command line, logging, single instance |

## Run from source

Needs Python 3.11+.

```bat
git clone https://github.com/valeraparafin/vs200-steer.git
cd vs200-steer
.\setup.cmd
.\run.cmd
```

`.\run.cmd --debug` logs the full DirCon traffic to `%APPDATA%\vs200-steer\vs200-steer.log`.

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

The result is `dist\vs200-steer.exe`. `build.cmd` finishes with `vs200-steer.exe --check`, which
loads the Bluetooth and mDNS modules to prove the build is complete.

## Release

1. Bump `__version__` in `src/vs200steer/__init__.py` and merge to `main`.
2. Tag and push: `git tag v0.1.1` then `git push origin v0.1.1`.
3. CI tests, builds the exe, checks the tag matches the version and publishes the GitHub Release.
