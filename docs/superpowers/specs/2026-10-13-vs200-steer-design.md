# vs200-steer — design

Date: 2026-10-13 · Status: draft for review

## Goal

Steer in Zwift with a ThinkRider VS200 thumb remote: tap `+` → rider moves one step right,
tap `−` → one step left. A second VS200 does the steering; the first one keeps shifting
through the trainer and is not touched by this tool.

Users: the author plus a few friends, each on their own Windows PC. Public GitHub repo, MIT.

**Success:** start the tool, start Zwift, and steering works for the whole ride without
touching the PC — including after the VS200 falls asleep and wakes up again.

## Non-goals

- Analog/proportional steering. Zwift steering is lane-based; the VS200 only reports taps.
- Shifting, double-tap or hold actions (double-tap detection would delay every steer tap).
- MyWhoosh in v0.1 (the same emulation likely works there, unverified).
- macOS/Linux.

## Milestones

1. **v0.1 console** — runs from source (`run.cmd`) on the author's PC; debugged on real rides.
2. **v0.1 release** — public GitHub repo, CI (lint + tests), tag `v*` → PyInstaller
   `vs200-steer.exe` attached to a GitHub Release. Done only after milestone 1 is stable.
3. **v0.2 tray** — tray icon (`pystray`) over the same core: status colour, pulse length, quit.

## Architecture

Python 3.11, `asyncio`. Dependencies: `bleak` (BLE), `zeroconf` (mDNS, brings `ifaddr`).
v0.2 adds `pystray` + `Pillow`. Dev: `pytest`, `ruff`, `pyinstaller`.

```
src/vs200steer/
  __main__.py      entry point: load config, start core, start UI
  config.py        %APPDATA%\vs200-steer\config.toml (read: tomllib, write: small own writer)
  vs200.py         VS200 BLE input: discover, first-run pick, connect, reconnect → Tap events
  net.py           pick the LAN IPv4 address to advertise
  zwift/dircon.py  DirCon TCP server (vendored from ZwiftBridge, MIT, with attribution)
  zwift/ride.py    Zwift Ride controller emulation on top of dircon.py
  core.py          wires Tap → Ride.pulse; holds observable status for the UI
  ui/console.py    status lines + log for v0.1 (v0.2 adds ui/tray.py)
tests/             pytest, no hardware
NOTICE             ZwiftBridge MIT notice; protocol facts credited to BikeControl / ZwiftBridge
```

Each unit has one job and a small interface:

- `Vs200Input(address|None)` → async iterator of `Tap.LEFT | Tap.RIGHT`; exposes `state`
  (`searching | connected | asleep`).
- `RideEmulator(address, port)` → `start()`, `stop()`, `async pulse(direction, ms)`; exposes
  `state` (`advertising | connected | ready`).
- `Core` owns both, maps taps through config, publishes a `Status` snapshot to the UI.
- UI only reads `Status` and the log; it never talks to BLE or the network directly.

## Data flow

VS200 notification on `FEA1` → `Tap` → `Core` (apply `swap` mapping) →
`RideEmulator.pulse(dir, pulse_ms)` → DirCon notification on ASYNC → Zwift moves the rider.

## Protocol facts (verified live on 2026-10-13, Zwift on the same Windows PC)

**VS200 (input).** Name starts with `THINK VS`. Service `0xFEA0`, notify characteristic
`0xFEA1`. One packet per press, at press time; no repeat while held, no release event.
`f3050301fc` = `+`, `f3050300fb` = `−`. Sleeps after ~30 min idle; while asleep it is
not discoverable (bleak raises `BleakDeviceNotFoundError`).

**Discovery (output).** mDNS `_wahoo-fitness-tnp._tcp`, TXT exactly:
`ble-service-uuids=FC82`, `mac-address=50-50-25-6C-66-9C`, `serial-number=244700181`,
`manufacturer-data=094A0BAAAA`; instance name `KICKR BIKE PRO 1337` (configurable).
Without `manufacturer-data` (ZwiftBridge's TXT) Zwift does not list the device.
Zwift also browses `_zwift-protocol._tcp`; not needed.

**DirCon characteristic properties use DirCon bits, not GATT bits:**
SYNC_RX `00000003-19ca-…` = `0x02` (write), ASYNC `00000002-…` = `0x04` (notify),
SYNC_TX `00000004-…` = `0x04` (notify). With GATT bits Zwift subscribes to SYNC_RX only
and nothing works. Expected DISCOVER_CHARACTERISTICS reply (golden):
`0102010000430000fc8200001000800000805f9b34fb0000000319ca465186e5fa29dcdd09d1020000000219ca465186e5fa29dcdd09d1040000000419ca465186e5fa29dcdd09d104`.

**Zwift's session sequence:** DISCOVER_SERVICES, DISCOVER_CHARACTERISTICS, ENABLE 02,
ENABLE 04, WRITE SYNC_RX `RideOn` (reply on SYNC_TX: `RideOn` + `01 03`), then GETs
(opcode `0x00`, protobuf `{1: dataObjectId}`) for 0, 16, 1024, 771. Replies are
`0x3C` GET_RESPONSE `{1: id, 2: data}` on SYNC_TX:

| id | page | reply |
|----|------|-------|
| 0 | DEV_INFO | BikeControl's captured "Zwift Click2" page (golden hex in tests) |
| 16 | CLIENT_SERVER_CONFIGURATION | `3c081012020800` |
| 1024 | CONTROLLER_INPUT_CONFIG | `{1: 4607, 2: 0}` (digital only) |
| 771 | BATTERY_STATE | `{1: 0, 2: 100, 3: 0, 4: 0}` |

Replies to 0 and 16 were verified. Unanswered 1024/771 coincided with Zwift reconnecting
every ~20–80 s; replying to them is expected to stop that — **verify in milestone 1**.

**Steering = D-pad** (verified: rider moves sideways). Frame on ASYNC:
`23 08 <varint buttonMap>`, active-low. Left `2308feffffff0f`, right `2308fbffffff0f`,
released `2308ffffffff0f`. A pulse re-sends the pressed frame every 50 ms for `pulse_ms`
(default 200), then sends released. Keepalive: released frame every 20 s while idle.
Analog paddle frames were accepted on the wire but did not steer; not used.

## Behaviour and error handling

- **First run / no address in config:** scan for `THINK VS*`, print "press a button on the
  remote you want to steer with", take the first one that sends `FEA1` data, save its address.
  The VS200 paired to the trainer is connected there and does not advertise, so it is not picked.
- **VS200 asleep or lost:** retry discovery every few seconds (capped backoff), log once per
  state change; the first press after wake reconnects it (that press may be lost — acceptable).
- **Zwift disconnects / reconnects:** keep advertising and the server running; a new client
  replays the full session sequence. Taps while no client is ready are dropped and logged.
- **Network:** advertise one IPv4: skip loopback, `169.254.*`, and adapters whose name looks
  like VPN/TAP/Hyper-V/vEthernet/Bluetooth; prefer the adapter carrying the default route.
  `network.address` in config overrides. If none is found, exit with a clear message.
- **Port busy:** try 36866…36875. **mDNS name taken:** append a suffix.
- **Second instance:** refuse to start (Windows named mutex).
- **Hint:** if no Zwift client connects within 60 s, log a hint (pair "KICKR BIKE PRO 1337"
  under Controls; allow Python/the exe through the firewall; Public network profile).
- **Log:** console + rotating file `%APPDATA%\vs200-steer\vs200-steer.log`; `--debug` adds
  the full DirCon trace.

## Config (`config.toml`)

```toml
[vs200]
address = ""          # filled on first run
swap = false          # false: + = right, - = left

[steer]
pulse_ms = 200

[zwift]
device_name = "KICKR BIKE PRO 1337"

[network]
address = ""          # empty = auto
```

## Testing

- Unit: VS200 packet parsing; D-pad frames; GET replies and DISCOVER_CHARACTERISTICS reply
  against golden bytes from the spike; config read/write; interface selection with fake
  adapter lists.
- Integration: a fake Zwift TCP client replays the verified session sequence against
  `RideEmulator` and asserts every reply, then triggers a pulse and asserts the ASYNC frames
  and timing.
- Manual (milestone 1): real rides on the author's PC — steering both ways, VS200 sleep/wake,
  Zwift restart, no periodic reconnects.

## Release (milestone 2)

GitHub Actions on `windows-latest`: `ruff` + `pytest` on every push; on tag `v*`, PyInstaller
one-file build and a GitHub Release with the exe and notes. The exe is unsigned: README explains
the SmartScreen prompt and the firewall prompt. README also covers setup, pairing in Zwift,
and troubleshooting.
