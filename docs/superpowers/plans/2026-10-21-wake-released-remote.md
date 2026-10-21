# Wake a Released Remote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A remote released for sleep (#2) reconnects when the user presses a button on it, not only when Zwift connects.

**Architecture:** On release, the Session starts a wake watch: it scans for the remote's address in bursts. A `WakeWatch` (plain logic, like `ReleaseTimer`) turns scan results into "asleep" (not seen for 30 s) and then "woken" (seen again after being asleep). On "woken" the Session clears the release and starts the input, as Zwift connecting does today. The watch never fires while the remote is still advertising right after the release, so it can still fall asleep.

**Tech Stack:** Python 3.12, asyncio, bleak, pytest + pytest-asyncio (auto mode), ruff.

**Spec:** issue #39 (design section), building on #2 (`docs/superpowers/plans/2026-10-20-release-idle-remote.md`).

## Global Constraints

- `ASLEEP_AFTER_S = 30`: the remote counts as asleep after no scan has seen it for 30 s.
- One watch scan = `vs200.SCAN_S` (5 s) via the same `find_device(address, timeout)` the input uses; pause `WAKE_PAUSE_S = 1` between scans.
- A scan error (Bluetooth off) counts as "not seen" and is logged at debug, never fatal.
- Status line while released: `Remote: asleep, press a button to wake · Zwift: waiting`.
- Release log line: `VS200 released: Zwift not connected for 10 min, so the remote can sleep. Press a button on it, or connect Zwift, to use it again.`
- Wake log line: `VS200 woken by a button press: connecting`.
- Branch `feat/wake-released-remote`, one PR, closes #39, milestone v0.2.2. `ruff check .` before each commit.

## Review Focus

- Remote keeps advertising after the release and never sleeps: never reconnected by the watch (only by Zwift). Test: `test_wake_watch_waits_for_sleep_first`.
- One missed scan while the remote is still awake (radio noise): not "asleep" before 30 s. Test: `test_wake_watch_ignores_a_short_gap`.
- Zwift connects while the watch is running: the watch stops, exactly one input runs. Test: `test_zwift_connecting_stops_the_wake_watch`.
- Pick another remote while released: the watch stops before the pick scans (one scanner at a time). Test: `test_pick_another_stops_the_wake_watch`.
- stop() during a watch scan: run returns 0. Test: `test_stop_during_the_wake_watch_returns`.

---

### Task 1: WakeWatch logic

**Files:** Modify `src/vsteer/session.py` (next to `ReleaseTimer`); Test `tests/test_session.py`

**Interfaces:**
- Produces: `ASLEEP_AFTER_S = 30`; `class WakeWatch(asleep_after_s: float = ASLEEP_AFTER_S)` with `update(seen: bool, now: float) -> bool` — True once, on the first `seen` after the remote has been unseen for ≥ `asleep_after_s`; `asleep: bool` property. The first `update` call starts the clock (the remote was just connected, so it counts as seen at that moment).

- [ ] **Step 1: Tests**
  - `test_wake_watch_waits_for_sleep_first`: updates `(True, 0)`, `(True, 100)`, `(True, 1000)` → all False, `asleep` False.
  - `test_wake_watch_ignores_a_short_gap`: `(True, 0)`, `(False, 10)`, `(False, 29)` → `asleep` False; `(True, 35)` → False.
  - `test_wake_watch_fires_once_after_sleep`: `(True, 0)`, `(False, 10)`, `(False, 41)` → `asleep` True; `(True, 50)` → True; `(True, 55)` → False.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_session.py -k wake_watch -q` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `WakeWatch`: track `last_seen`; asleep when `now - last_seen >= asleep_after_s` on an unseen update; fire on a seen update while asleep, then reset.
- [ ] **Step 4: Run** same — Expected: 3 passed.
- [ ] **Step 5: Commit** `feat: add WakeWatch to tell a woken remote from an awake one (#39)`

### Task 2: Session runs the watch while released

**Files:** Modify `src/vsteer/session.py` (`Session.__init__` gains `find_device=None`, `_release`, `_release_loop`, `_repick`, new `_wake_watch`); Test `tests/test_session.py`

**Interfaces:**
- Consumes: `WakeWatch` (Task 1); `vs200.SCAN_S`; `vs200._bleak_find` as the default `find_device`.
- Produces: `Session(..., find_device=None)` (tests inject a fake); instance attributes `asleep_after_s = ASLEEP_AFTER_S`, `wake_pause_s = WAKE_PAUSE_S`, `wake_scan_s = SCAN_S` (tests shrink them); `self._wake_task: asyncio.Task | None`, spawned by `_release` with `self._spawn`, cancelled and awaited by a `_stop_wake_watch()` helper that `_release_loop`'s Zwift path and `_repick` call before starting the input or the pick.

`_wake_watch` loop: `seen = await find_device(address, wake_scan_s) is not None` (exceptions → False, debug log); if `watch.update(seen, loop.time())` → log the wake line, clear `_released`, `_start_input()`, return; else sleep `wake_pause_s`.

- [ ] **Step 1: Tests** (fake `find_device` driven by a list or flag; `_quick_release` also shrinks the watch times: `asleep_after_s=0.05`, `wake_pause_s=0.005`, `wake_scan_s=0.005`)
  - `test_a_woken_remote_reconnects_without_zwift`: fake sees the remote, then not, then sees it → `not session.released`, a second FakeInput running, `"woken by a button press"` in the log.
  - `test_a_remote_that_never_sleeps_is_not_reconnected`: fake always sees it → after 0.3 s still released, one FakeInput.
  - `test_zwift_connecting_stops_the_wake_watch`: while the watch runs, emulator READY → watch task done, exactly one running FakeInput.
  - `test_pick_another_stops_the_wake_watch`: fake records calls; after `pick_another` starts, no new find calls.
  - `test_stop_during_the_wake_watch_returns`: fake `find_device` blocks forever; `stop()` → run returns 0 within 1 s.
  - Existing #2 tests keep passing (they inject a `find_device` that never sees the remote).
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_session.py -q` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** as in Interfaces; release log line per Global Constraints.
- [ ] **Step 4: Run** full suite — Expected: all pass.
- [ ] **Step 5: Commit** `feat: reconnect a released remote when a button wakes it (#39)`

### Task 3: Wording and docs

**Files:** Modify `src/vsteer/ui/tray_model.py`, `src/vsteer/vs200.py` (ASLEEP comment), `README.md` (the sleep paragraph), `docs/how-it-works.md` (Letting the remote sleep); Test `tests/test_tray_model.py` (`test_asleep_status_line`, `test_asleep_tooltip_fits` updated to the new wording)

- [ ] **Step 1:** Update the two tests to `Remote: asleep, press a button to wake · Zwift: waiting`.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_tray_model.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; README: "press any button on the remote to wake it; it reconnects by itself"; how-it-works: the wake watch in two sentences.
- [ ] **Step 4: Run** full suite + `ruff check .` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: tell the user a button wakes the remote (#39)`
