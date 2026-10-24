# Winter bound and ending score

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run stays open while the player lives in Bellwether, and once winter has closed in the player is forced toward the one fixed ending their dimension score points to.

**Architecture:** New `backend/story.py` owns the twelve dimensions, the five ending signatures, and the internal winter bound. `game.tick` reports the phase. The client is never given a day count, a meter, or an ending while the phase is still open. This plan does not generate conflicts and does not build the Palimpsest.

**Tech Stack:** Python, SQLite via `backend/db.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-npcasso-core-vision-design.md`

## Global Constraints

- Do not change the engine.
- No countdown, doom meter, or announced day is sent to the player.
- The score is never shown.
- Winter is counted in clock days from the player's arrival, not from the age of the world. Day 1 is `open`. Days 2–5 are `pressure`. Days 6–9 are `closing`. Day 10 is `frozen`: `sustain` is false.
- During days 6–9, `cold` is hit points lost per second. It is 0 before day 6 and steeper as day 10 gets closer. Refusing the steered ending stays on this path. Accepting an ending is not built in this plan.
- The on-screen clock shows that day and the time of day. `game.tick` returns the same `day` and `time`. Neither names the stage.
- The Palimpsest is not part of this game.
- The model writing conflicts and consequences is out of this plan. This plan only stores evidence and reads it.
- Ending ids, in tie-break order: `names_we_buried`, `last_place_at_the_table`, `the_peace_you_made`, `the_last_departure`, `the_end_of_all_things`.
- A tie on the mean score uses that order.
- Epilogue text is out of this plan.

## Review Focus

- A tick during the open stretch must not include an ending, even if the score already leans one way.
- A tick during `pressure` must not include an ending.
- A tick exactly at `game_time == 6` is `closing` and names an ending when any evidence exists.
- Evidence on a dimension that is not one of the twelve is rejected.
- With no evidence, `closing` still returns no ending id.
- A negative weight must be able to lead `the_end_of_all_things` over a small positive on another ending.

---

### Task 1: Dimension evidence and the leading ending

**Files:**
- Create: `backend/story.py`
- Test: `tests/test_story.py`

**Interfaces:**
- Consumes: `backend.db.connect`
- Produces:
  - `DIMENSIONS: tuple[str, ...]` the twelve ids: `candor`, `bravery`, `compassion`, `selflessness`, `ambition`, `ingenuity`, `loyalty`, `pragmatism`, `curiosity`, `justice`, `forgiveness`, `independence`
  - `add_evidence(conn, player: str, dimension: str, weight: float, event_id: int | None, note: str | None) -> None`
  - `leading_ending(conn, player: str) -> str | None` — mean of evidence weights on each ending's signature dimensions. Signatures: `names_we_buried` candor+ bravery+ loyalty+; `last_place_at_the_table` compassion+ selflessness+ loyalty+; `the_peace_you_made` ambition+ pragmatism+ ingenuity+; `the_last_departure` independence+ ambition− loyalty−; `the_end_of_all_things` forgiveness− compassion− independence+. A dimension's signed contribution is `mean(weight) * sign`. Ending score is the mean of its three contributions. Highest score wins. Tie uses the order in Global Constraints. No evidence, or a non-positive best score, returns `None`. `add_evidence` raises `ValueError` on an unknown dimension or a weight outside `-1..1`.

- [ ] **Step 1: Write the failing test**

```python
def test_score_names_the_buried_truth():
    add_evidence(conn, "p", "candor", 1, 1, None)
    add_evidence(conn, "p", "bravery", 1, 1, None)
    add_evidence(conn, "p", "loyalty", 1, 1, None)
    assert leading_ending(conn, "p") == "names_we_buried"

def test_negative_weights_name_the_end_of_all_things():
    add_evidence(conn, "p", "forgiveness", -1, 1, None)
    add_evidence(conn, "p", "compassion", -1, 1, None)
    add_evidence(conn, "p", "independence", 1, 1, None)
    assert leading_ending(conn, "p") == "the_end_of_all_things"

def test_no_evidence_has_no_ending():
    assert leading_ending(conn, "p") is None

def test_unknown_dimension_is_rejected():
    with pytest.raises(ValueError):
        add_evidence(conn, "p", "evil", 1, None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_story.py -q`
Expected: FAIL with import or name error

- [ ] **Step 3: Implement `add_evidence` and `leading_ending` in `backend/story.py`**

Store rows in a new `evidence` table (`player`, `dimension`, `weight`, `event_id`, `note`), created on first use. Follow the signatures in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_story.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/story.py tests/test_story.py
git commit -m "feat: score a run toward one of the five endings"
```

### Task 2: Winter phase

**Files:**
- Modify: `backend/story.py`
- Test: `tests/test_story.py`

**Interfaces:**
- Consumes: `PRESSURE_AT = 2` and `CLOSING_AT = 6` defined in `story.py`
- Produces: `phase(game_time: float) -> str` returning `"open"` below 2, `"pressure"` from 2 until 6, and `"closing"` at 6 and after

- [ ] **Step 1: Write the failing test**

```python
def test_phase_is_open_then_pressure_then_closing():
    assert phase(1.9) == "open"
    assert phase(2) == "pressure"
    assert phase(5.9) == "pressure"
    assert phase(6) == "closing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_story.py::test_phase_is_open_then_pressure_then_closing -q`
Expected: FAIL

- [ ] **Step 3: Implement `phase` in `backend/story.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_story.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/story.py tests/test_story.py
git commit -m "feat: mark when winter has closed in"
```

### Task 3: Tick forces the ending only after winter closes

**Files:**
- Modify: `backend/game.py` (`tick`)
- Test: `tests/test_story.py`

**Interfaces:**
- Consumes: `story.phase`, `story.leading_ending`, `story.add_evidence`
- Produces: `game.tick` adds `phase`, `day` (int), and `time` (`"HH:MM"`). `day` is `floor(game_time) + 1`. `time` is the fractional day as hours and minutes. It adds `ending` only when `phase == "closing"` and `leading_ending` is not `None`. The ending id is never present during `open` or `pressure`.

- [ ] **Step 1: Write the failing test**

```python
def test_open_tick_hides_a_leaning_score(conn):
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 1.0)
    assert out["phase"] == "open" and "ending" not in out

def test_pressure_hides_a_leaning_score(conn):
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 3.0)
    assert out["phase"] == "pressure" and "ending" not in out

def test_closing_tick_names_the_ending(conn):
    add_evidence(conn, "w:p", "candor", 1, 1, None)
    add_evidence(conn, "w:p", "bravery", 1, 1, None)
    add_evidence(conn, "w:p", "loyalty", 1, 1, None)
    out = tick(conn, None, "w", "p", 6.5)
    assert out["phase"] == "closing" and out["ending"] == "names_we_buried"
    assert out["day"] == 7 and out["time"] == "12:00"

def test_closing_without_evidence_names_nothing(conn):
    out = tick(conn, None, "w", "p", 6)
    assert out["phase"] == "closing" and "ending" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_story.py::test_closing_tick_names_the_ending -q`
Expected: FAIL

- [ ] **Step 3: Implement the phase and ending fields in `game.tick`**

Keep the existing promise-deadline behaviour. Do not add the day number to the response.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_story.py tests/test_game.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/game.py backend/story.py tests/test_story.py
git commit -m "feat: force an ending once winter has closed in"
```
