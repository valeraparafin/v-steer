# Release the Idle Remote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the VS200 sleep when Zwift is not connected: release it after 10 min without Zwift, search for it again when Zwift connects.

**Architecture:** A `ReleaseTimer` (same shape as `HintTimer`) decides when Zwift has been away 10 min. A Session job polls the emulator state every 5 s: when the timer fires, it cancels the input task and reports `InputState.ASLEEP`; when Zwift connects while released, it starts the input again. The tray shows the new state in its status line.

**Tech Stack:** Python 3.12, asyncio, pytest + pytest-asyncio (auto mode), ruff.

**Spec:** in-chat design approved 2026-10-20, recorded in issue #2 (comment 6294167101):
release after 10 min with Zwift not connected; search again when Zwift connects; never release during a ride; at start search as today; tray tooltip "VS200: asleep until Zwift connects"-style wording; README line.

## Global Constraints

- Release delay: `RELEASE_AFTER_S = 600` (10 min); poll interval `RELEASE_CHECK_S = 5`.
- "Zwift connected" means `EmulatorState.CONNECTED` or `EmulatorState.READY`; ADVERTISING and STOPPED count as away.
- Status line wording: `Remote: asleep until Zwift connects`.
- Log line on release: `VS200 released: Zwift not connected for 10 min, so the remote can sleep. It is searched again when Zwift connects.`
- Repo text in English. Branch `feat/release-idle-remote`, one PR, closes #2.
- Run `ruff check .` before every commit; full suite `.venv\Scripts\python -m pytest -q`.

## Review Focus

- Zwift connects while the release is in progress (input task being cancelled): the input must end up running, not released. Test: `test_zwift_connecting_right_after_a_release_starts_the_input`.
- Pick another remote while released: the new remote is searched at once and the release state is cleared. Test: `test_pick_another_while_released_searches_the_new_remote`.
- Zwift flaps (READY → ADVERTISING → READY within 10 min): never released. Covered by `test_release_timer_restarts_when_zwift_comes_back`.
- stop() while released: run returns 0, no task left running. Test: `test_stop_while_released_returns`.
- Tooltip with the longer wording still fits 127 chars. Test: `test_asleep_tooltip_fits`.

---

### Task 1: ASLEEP state and ReleaseTimer

**Files:**
- Modify: `src/vsteer/vs200.py` (`InputState`)
- Modify: `src/vsteer/session.py` (next to `HintTimer`)
- Test: `tests/test_session.py`

**Interfaces:**
- Produces: `InputState.ASLEEP = "asleep"`; `RELEASE_AFTER_S = 600`; `class ReleaseTimer(after_s: float = RELEASE_AFTER_S)` with `update(state: EmulatorState, now: float) -> bool` (True once per away period, when away ≥ after_s) and `zwift_connected(state) -> bool` module function.

- [ ] **Step 1: Write the failing tests**

```python
def test_release_timer_fires_once_after_ten_minutes_away():
    t = ReleaseTimer(after_s=600)
    assert not t.update(EmulatorState.ADVERTISING, 0)
    assert not t.update(EmulatorState.ADVERTISING, 599)
    assert t.update(EmulatorState.ADVERTISING, 600)
    assert not t.update(EmulatorState.ADVERTISING, 700)

def test_release_timer_restarts_when_zwift_comes_back():
    t = ReleaseTimer(after_s=600)
    t.update(EmulatorState.ADVERTISING, 0)
    assert not t.update(EmulatorState.READY, 500)
    assert not t.update(EmulatorState.ADVERTISING, 550)
    assert not t.update(EmulatorState.ADVERTISING, 1100)
    assert t.update(EmulatorState.STOPPED, 1150)  # STOPPED counts as away
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_session.py -k release_timer -q` — Expected: FAIL (ImportError ReleaseTimer).
- [ ] **Step 3: Implement** `InputState.ASLEEP`, `zwift_connected`, `ReleaseTimer` in `session.py`.
- [ ] **Step 4: Run** the same command — Expected: 2 passed.
- [ ] **Step 5: Commit** `feat: add ReleaseTimer and the ASLEEP remote state (#2)`

### Task 2: Session releases and re-searches the remote

**Files:**
- Modify: `src/vsteer/session.py` (`Session.__init__`, `_ride`, `_repick`, new `_release_loop`)
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: Task 1's `ReleaseTimer`, `zwift_connected`, `InputState.ASLEEP`.
- Produces: `Session.release_after_s: float = RELEASE_AFTER_S`, `Session.release_check_s: float = RELEASE_CHECK_S` (instance attributes tests shrink); `Session.released: bool` (read-only property); `async def _release_loop(self) -> None` spawned with `self._spawn` next to the hint loop.

Loop body each tick: `timer.update(emulator.state, loop.time())`; if it fires and not released → cancel and await `_input_task`, set released, `core.on_input_state(InputState.ASLEEP)`, log the release line. If released and `zwift_connected(emulator.state)` → clear released, `_start_input()`. `_repick` clears released before `_start_input()`.

- [ ] **Step 1: Write the failing tests** (FakeEmulator state is set directly; shrink `release_after_s=0.05`, `release_check_s=0.01`)

```python
async def test_the_remote_is_released_when_zwift_stays_away(tmp_path):
    # run; until FakeInput.instances; then until session.released
    assert FakeInput.instances[0].cancelled
    assert events.named("status")[-1][1].vs200 is InputState.ASLEEP

async def test_the_remote_is_searched_again_when_zwift_connects(tmp_path):
    # after released: FakeEmulator.instances[0].state = EmulatorState.READY
    # until len(FakeInput.instances) == 2 and not session.released

async def test_the_remote_is_kept_while_zwift_is_connected(tmp_path):
    # emulator state READY from the start; sleep 0.2; not released, input not cancelled

async def test_zwift_connecting_right_after_a_release_starts_the_input(tmp_path):
    # set READY in the same tick released becomes True; input ends up running (2 instances)

async def test_pick_another_while_released_searches_the_new_remote(tmp_path):
    # released; pick_another with _picks("BB:..."); new FakeInput for BB, session.released is False

async def test_stop_while_released_returns(tmp_path):
    # released; await session.stop(); run() result == 0
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_session.py -q` — Expected: the 6 new tests FAIL, the rest pass.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** the same command — Expected: all pass.
- [ ] **Step 5: Commit** `feat: release the VS200 after 10 min without Zwift (#2)`

### Task 3: Tray wording and docs

**Files:**
- Modify: `src/vsteer/ui/tray_model.py` (`status_line`)
- Modify: `README.md` ("Every next ride", Troubleshooting "remote isn't found"), `docs/how-it-works.md` (session jobs)
- Test: `tests/test_tray_model.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_asleep_status_line():
    s = Status(vs200=InputState.ASLEEP, zwift=EmulatorState.ADVERTISING)
    assert status_line(s) == "Remote: asleep until Zwift connects · Zwift: waiting"
    assert icon_state(s, None) is IconState.IDLE

def test_asleep_tooltip_fits():
    s = Status(vs200=InputState.ASLEEP, zwift=EmulatorState.ADVERTISING)
    assert len(tooltip("0.2.1", s, None)) <= TOOLTIP_MAX
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_tray_model.py -q` — Expected: first FAILs.
- [ ] **Step 3: Implement** the ASLEEP branch in `status_line`; README: "With no Zwift for 10 min, V-Steer lets the remote sleep; after pairing in Zwift, press any button on it once." how-it-works: one line on the release job.
- [ ] **Step 4: Run** full suite + `ruff check .` — Expected: all pass, no lint.
- [ ] **Step 5: Commit** `feat: show the sleeping remote in the tray; document it (#2)`
