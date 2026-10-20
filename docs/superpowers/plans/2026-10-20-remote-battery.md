# Remote Battery Level Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the VS200's battery level and pass it to Zwift and the tray; warn once when it is low.

**Architecture:** `Vs200Input` reads and subscribes to the standard Battery Level (`0x2A19`) after connecting and reports it through a new `on_battery` callback. `Core` keeps it in `Status.battery` and hands it to the emulator, which answers Zwift's `BATTERY_STATE` GET with the real level and sends a `BATTERY_NOTIF` frame when the level changes or Zwift becomes ready. The tray shows the level in its status line and notifies once per run at 15 % or less.

**Tech Stack:** Python 3.12, asyncio, bleak, pytest + pytest-asyncio (auto mode), ruff.

**Spec:** in-chat design approved 2026-10-20, spike result in issue #36 (comment 6297945932): VS200 has `0x180F`/`0x2A19` (read, notify), read 25 %.

## Global Constraints

- `BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"` (in `vs200.py`).
- Zwift frame: `BATTERY_NOTIF` opcode `0x19` + protobuf field 1 (`newPercLevel`) on `ASYNC_CHAR_UUID`.
- `BATTERY_STATE` (object 771) reply: field 2 `percLevel` = real level; 100 while unknown (today's value).
- Status line: `Remote: connected 25% · Zwift: ready` (level only when connected and known).
- Low threshold `LOW_BATTERY = 15` (≤ 15 %); notification `"battery"`: `The steering remote's battery is at {level}%. Replace it soon.`
- Battery read/subscribe failures never break steering: log at debug, keep the connection.
- Branch `feat/remote-battery`, one PR, closes #36. `ruff check .` before every commit.

## Review Focus

- A remote without a Battery Service (another model): connects and steers as before, battery stays unknown. Test: `test_a_remote_without_battery_still_steers`.
- Level out of range (e.g. 255 from a broken read): ignored, not sent to Zwift. Test: `test_battery_out_of_range_is_ignored`.
- Zwift connects after the level was read: it gets the level at once. Test: `test_battery_is_sent_when_zwift_becomes_ready`.
- Remote reconnects or is released (#2): the shown level is dropped (`battery=None`) while not connected. Test: `test_battery_is_cleared_when_the_remote_is_not_connected`.
- Low warning repeats every status update: shown once per run. Test: `test_low_battery_notifies_once`.

---

### Task 1: Zwift protocol and emulator carry the level

**Files:** Modify `src/vsteer/zwift/protocol.py`, `src/vsteer/zwift/ride.py`; Test `tests/test_protocol.py`, `tests/test_ride.py`

**Interfaces:**
- Produces: `P.OP_BATTERY_NOTIF = 0x19`; `P.battery_notification(level: int) -> bytes`; `P.battery_state_reply(level: int) -> bytes`; `GET_REPLIES[771]` removed (served from the emulator's level); `RideEmulator.set_battery(level: int) -> None`, `RideEmulator.battery: int | None`.

- [ ] **Step 1: Tests**
  - `test_battery_notification_frame`: `P.battery_notification(25) == bytes([0x19, 0x08, 25])`.
  - `test_battery_state_reply_carries_the_level`: `P.battery_state_reply(25)` equals today's 771 reply with 100 replaced by 25.
  - `test_get_requests_are_answered` keeps passing for 771 with level unknown (expects `battery_state_reply(100)`).
  - `test_battery_is_sent_when_zwift_becomes_ready`: `emu.set_battery(25)` before a client subscribes; after the session, frames on ASYNC include `battery_notification(25)`.
  - `test_battery_change_is_sent_to_a_ready_zwift`: ready client; `set_battery(24)` → one `battery_notification(24)` frame; `set_battery(24)` again → no new frame.
  - `test_battery_out_of_range_is_ignored`: `set_battery(255)` → `emu.battery is None`, no frame.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_protocol.py tests/test_ride.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** `_on_sync_write` answers 771 with `battery_state_reply(self.battery or 100)`; `_refresh_state` spawns a notification send when the new state is READY and a level is known.
- [ ] **Step 4: Run** same — Expected: all pass.
- [ ] **Step 5: Commit** `feat: pass the remote's battery level to Zwift (#36)`

### Task 2: VS200 reads the level; Core keeps it

**Files:** Modify `src/vsteer/vs200.py`, `src/vsteer/core.py`, `src/vsteer/session.py` (`_start_input` passes `on_battery=core.on_battery`); Test `tests/test_vs200.py`, `tests/test_core.py`, `tests/test_session.py` (FakeInput accepts `on_battery=None`)

**Interfaces:**
- Consumes: `RideEmulator.set_battery` (Task 1).
- Produces: `Vs200Input(..., on_battery: Callable[[int], None] | None = None)`; `Status.battery: int | None = None`; `Core.on_battery(level: int) -> None`; `Core.on_input_state` sets `battery=None` for any state but CONNECTED.

- [ ] **Step 1: Tests**
  - `test_battery_is_read_and_followed_after_connect` (test_vs200): FakeClient returns `bytearray([25])` from `read_gatt_char(BATTERY_LEVEL_UUID)` and records `start_notify` for it; `on_battery` gets 25, then 24 when the fake fires the battery handler with `bytearray([24])`.
  - `test_a_remote_without_battery_still_steers`: `read_gatt_char` and battery `start_notify` raise; state reaches CONNECTED, taps still arrive, `on_battery` never called.
  - `test_core_passes_the_battery_on` (test_core): `core.on_battery(25)` → `status.battery == 25`, emulator fake got `set_battery(25)`.
  - `test_battery_is_cleared_when_the_remote_is_not_connected`: after `on_battery(25)`, `on_input_state(SEARCHING)` → `status.battery is None`.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_vs200.py tests/test_core.py tests/test_session.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** After `start_notify(FEA1_UUID, ...)` and CONNECTED: best-effort read + `start_notify(BATTERY_LEVEL_UUID, ...)`, each in its own try/except logging at debug.
- [ ] **Step 4: Run** same + full suite — Expected: all pass.
- [ ] **Step 5: Commit** `feat: read the VS200 battery level (#36)`

### Task 3: Tray shows the level and warns once

**Files:** Modify `src/vsteer/ui/tray_model.py`, `src/vsteer/ui/tray.py` (`TrayEvents.status`), `README.md` (tray section), `docs/how-it-works.md`; Test `tests/test_tray_model.py`, `tests/test_tray.py`

**Interfaces:**
- Consumes: `Status.battery` (Task 2).
- Produces: `LOW_BATTERY = 15`; `battery_low(status: Status) -> bool`; `MESSAGES["battery"]`.

- [ ] **Step 1: Tests**
  - `test_status_line_shows_the_battery`: CONNECTED, battery 25, READY → `"Remote: connected 25% · Zwift: ready"`; battery None → `"Remote: connected · Zwift: ready"`.
  - `test_battery_low_threshold`: 15 → True, 16 → False, None → False.
  - `test_low_battery_notifies_once` (test_tray): two `TrayEvents.status` calls with battery 10 → one notification with `MESSAGES["battery"].format(level=10)`.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_tray_model.py tests/test_tray.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement**; README: one line that the tooltip shows the remote's battery and a notification warns at 15 %; how-it-works: one line on the battery path.
- [ ] **Step 4: Run** full suite + `ruff check .` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: show the remote's battery in the tray (#36)`
