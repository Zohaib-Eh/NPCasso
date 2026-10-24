# Social core (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Villagers feel what you did to them, show it in what they say and whether they ask you for anything, remember the conversation they are in, and pass news on at once.

**Architecture:** A pure function `stance()` turns a villager's own memories of the player into `{mood, strength, cause, heat}`. The game gates asks and pacing on it and hands the model only the words. Insults, threats and apologies now leave memories so they count. Pacing is per villager. The recent conversation reaches the model.

**Tech Stack:** Python 3.13, FastAPI, SQLite, pytest (`.venv\Scripts\python -m pytest`).

**Spec:** `docs/superpowers/specs/2026-10-24-social-consequences-design.md` (sections 1, 3, 5, 7, 8).

**This plan does not commit.** The user asked that nothing be committed unless they say so.

## Global Constraints

- The game decides, the model speaks. No numbers in anything the model sees (heat stays in code).
- A villager's packet holds only their own memories, public rules, their stock, the map, their own stance, and the current exchange.
- Memories are never deleted.
- Do not start Luanti with `--go`. Restart the backend with `.venv\Scripts\python -m uvicorn backend.app:main --factory --port 8000`.
- No bloated tests: one test per behaviour that changed.

## Root causes this plan fixes (from captured packets)

1. A hit costs 25 trust, `band` still says "wary", and one apology returns it to "neutral".
2. `_ease` counts all the player's talks, so a villager met for the first time gets "you know them a little by now".
3. Nothing in the packet says how the villager feels, why, or when it happened. No `recent` conversation either.
4. Generic pacing text outweighs a one-line memory.
5. The ask gate only checks `hostile`, so a villager at trust -5 pitches an errand the next day.
6. Insults and threats change trust but leave no memory, so they are forgotten at once.

## File Structure

- Create `backend/stance.py`: `of(conn, npc_id, player, game_time)`, `when(age)`, `fallback(mood)`.
- Modify `backend/game.py`: `_apply_intent`, `build_context`, `_heard`, `_ease`, `player_ask`, `greet`, `talk`, `gossip`.
- Modify `backend/db.py`: `top_memories` returns `learned_at`; new `recent_turns`.
- Modify `backend/llm.py`: stance block, recent, pacing.
- Modify `backend/validator.py`: `tone_mismatch` becomes an error for harmful stances.
- Modify `backend/npcs.json`: `temper` per villager.
- Create `tools/sim.py`: simulation harness (Task 9).
- Tests: `tests/test_stance.py` (new), edits to `tests/test_game.py`.

---

### Task 1: Insults, threats and apologies leave memories

**Files:** Modify `backend/game.py` (`_apply_intent`). Test: `tests/test_game.py`.

**Interfaces:** Produces memory rows of type `insult`, `threat`, `apology` for the addressed villager. These are not in `PUBLIC_RUMOUR`, so they never travel.

- [ ] **Step 1: Write the failing test** (append to `tests/test_game.py`)

```python
def test_an_insult_leaves_a_memory_that_does_not_travel(conn):
    insult = {"intent": "insult", "confidence": 0.95, "promise": None, "claim": None}
    talk(conn, ScriptedLLM([insult, {"reply": "Mind your tongue.", "claims": []}]), "w", "p", "corin", "you fool", "t", 1.0)
    assert db.top_memories(conn, "corin", "w:p")[0]["text"] == "the newcomer insulted me"
    assert not gossip(conn, "w", "p", "corin", "elise", 2.0, roll=0.0)["shared"]
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv\Scripts\python -m pytest tests/test_game.py::test_an_insult_leaves_a_memory_that_does_not_travel -q`
Expected: FAIL (`IndexError`, no memory).

- [ ] **Step 3: Implement.** In `_apply_intent`, capture the event id and write the memory:

```python
    eid = db.add_event(conn, {"player": player, "actor": player, "target": npc_id, "type": kind, "details": intent,
                              "witnesses": [npc_id], "game_time": game_time, "source": "llm_classified",
                              "verified": False, "confidence": conf})
    if kind in ("threat", "insult"):
        delta = rules.trust_delta(kind)
        db.add_trust(conn, npc_id, player, delta)
        db.add_memory(conn, npc_id, player, eid, kind,
                      "the newcomer insulted me" if kind == "insult" else "the newcomer threatened me",
                      "witnessed", 1.0, abs(delta), game_time)
        return {"heard_as": kind}
    elif kind == "apology":
        if rules.apology_allowed(db.get_flag(conn, npc_id, player, "last_apology"), game_time):
            delta = rules.trust_delta("apology")
            db.add_trust(conn, npc_id, player, delta)
            db.add_memory(conn, npc_id, player, eid, "apology", "the newcomer apologised to me",
                          "witnessed", 1.0, delta, game_time)
            db.set_flag(conn, npc_id, player, "last_apology", game_time)
            notices.append(f"{name(npc_id)} noticed your apology.")
        return {"heard_as": "apology"}
```

(Replace the existing `db.add_event(...)` call and the `threat/insult` and `apology` branches; leave `promise` and `correction` as they are.)

- [ ] **Step 4: Run, expect PASS**, then `.venv\Scripts\python -m pytest -q` for regressions.

---

### Task 2: When it happened

**Files:** Modify `backend/db.py` (`top_memories`), `backend/stance.py` (new, `when`), `backend/game.py` (`build_context`). Test: `tests/test_stance.py`.

**Interfaces:** `stance.when(age_days: float) -> str` returns `"moments ago" | "earlier" | "yesterday" | "days ago"`. `build_context(..., game_time=None)` adds `"when"` to each memory when `game_time` is given.

- [ ] **Step 1: Failing test** (`tests/test_stance.py`, new file)

```python
from backend import db, stance


def test_when_words():
    assert [stance.when(a) for a in (0.01, 0.3, 1.0, 3.0)] == ["moments ago", "earlier", "yesterday", "days ago"]
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError`).

- [ ] **Step 3: Create `backend/stance.py`** with the header and `when` only for now:

```python
"""How a villager feels about the player right now. Computed from their own memories; the model only voices it."""


def when(age: float) -> str:
    if age < 0.05:
        return "moments ago"
    if age < 0.5:
        return "earlier"
    if age < 1.5:
        return "yesterday"
    return "days ago"
```

- [ ] **Step 4: `db.top_memories`:** select `learned_at` too:

```python
    rows = conn.execute("select event_id, type, text, how, reliability, learned_at from memories "
                        "where npc_id=? and player=? and type != 'walk_away' "
                        "order by severity desc, ts desc, id desc limit ?", (npc_id, player, limit))
```

- [ ] **Step 5: `build_context`:** add the `game_time=None` parameter and, after `memories` is built:

```python
def _dated(memories, game_time):
    out = []
    for m in memories:
        m = dict(m)
        learned = m.pop("learned_at", None)
        if game_time is not None:
            m["when"] = stance.when(game_time - learned if learned is not None else 3.0)
        out.append(m)
    return out
```

and use `"memories": _dated(db.top_memories(conn, npc_id, player), game_time)`. Add `from . import stance` to the imports of `game.py`.

- [ ] **Step 6: Pass `game_time` at the callers** that have it: `greet` (`build_context(..., game_time=game_time)`), `talk`, `react` (`row["game_time"]`), `_voice` (its `game_time` argument).

- [ ] **Step 7: Run** `tests/test_stance.py` and the full suite. Expect PASS.

---

### Task 3: The stance function

**Files:** Modify `backend/stance.py`, `backend/npcs.json`. Test: `tests/test_stance.py`.

**Interfaces:**
`stance.of(conn, npc_id, player, game_time) -> {"mood": str, "strength": "faint"|"clear"|"strong", "cause": str|None, "heat": float}`.
Moods: `angry, afraid, hurt, cold, guarded, warm, fond, neutral`. `stance.HARMFUL = {"angry","afraid","hurt","cold"}`.

- [ ] **Step 1: Add `temper`** to every villager in `backend/npcs.json` (next to `persona`): elise steady, rowan hot, mira steady, tobin steady, wren hot, pip timid, bram steady, nell steady, corin timid, hazel timid, dax hot, lottie timid. Default in code is `steady`.

- [ ] **Step 2: Failing tests** (append to `tests/test_stance.py`)

```python
def _hit(conn, victim, witnesses, t):
    from backend.game import record_event
    from tests.conftest import ScriptedLLM
    record_event(conn, ScriptedLLM([]), {"world": "w", "player": "p", "type": "hit_npc", "target": victim,
                                         "witnesses": witnesses, "game_time": t, "details": {}})


def test_a_hit_is_felt_then_cools_into_a_scar(conn):
    _hit(conn, "elise", ["elise", "nell"], 1.0)
    first = stance.of(conn, "elise", "w:p", 1.01)
    assert first["mood"] == "angry" and first["strength"] != "faint" and first["cause"] == "you hit me"
    later = stance.of(conn, "elise", "w:p", 4.0)
    assert later["mood"] == "guarded" and later["cause"] == "you hit me"  # never fully gone


def test_a_timid_villager_is_afraid_and_a_witness_disapproves(conn):
    _hit(conn, "pip", ["pip", "nell"], 1.0)
    assert stance.of(conn, "pip", "w:p", 1.01)["mood"] == "afraid"
    seen = stance.of(conn, "nell", "w:p", 1.01)
    assert seen["mood"] == "cold" and seen["cause"] == "I saw you hit Pip"


def test_amends_cool_it_faster(conn):
    _hit(conn, "elise", ["elise"], 1.0)
    before = stance.of(conn, "elise", "w:p", 1.1)["heat"]
    db.add_memory(conn, "elise", "w:p", None, "apology", "the newcomer apologised to me", "witnessed", 1.0, 10, 1.1)
    assert stance.of(conn, "elise", "w:p", 1.1)["heat"] < before


def test_nothing_to_feel_is_neutral(conn):
    assert stance.of(conn, "mira", "w:p", 1.0)["mood"] == "neutral"
```

Run: expect FAIL (`of` missing).

- [ ] **Step 3: Implement** (append to `backend/stance.py`)

```python
from .db import load_config

CONFIG = load_config()
HALF_LIFE = 1.5  # game-days for a grievance to halve
HARM = {"hit_npc": 25, "theft": 30, "vandalism": 40, "threat": 15, "insult": 10}
AMENDS = {"apology", "gift", "repair", "return", "quest_done"}
GRAVE = {"hit_npc", "theft", "vandalism"}
HARMFUL = {"angry", "afraid", "hurt", "cold"}
MOOD = {  # what each kind of harm does to each temper, when it was done to them
    "hit_npc": {"hot": "angry", "steady": "angry", "timid": "afraid"},
    "threat": {"hot": "angry", "steady": "guarded", "timid": "afraid"},
    "theft": {"hot": "angry", "steady": "cold", "timid": "cold"},
    "vandalism": {"hot": "angry", "steady": "angry", "timid": "cold"},
    "insult": {"hot": "angry", "steady": "hurt", "timid": "hurt"},
}
SCALE = 40.0  # harm points that make a villager fully worked up


def _cause(row, me: str) -> str:
    text = row["text"].replace("the newcomer", "you")
    if row["how"].startswith("told") or row["target"] in (me, None):
        return text
    return f"I saw {text}"


def of(conn, npc_id: str, player: str, game_time: float) -> dict:
    temper = CONFIG["npcs"][npc_id].get("temper", "steady")
    rows = conn.execute(
        "select m.type, m.text, m.how, m.severity, m.learned_at, e.target from memories m "
        "left join events e on e.id = m.event_id where m.npc_id=? and m.player=? and m.type != 'walk_away'",
        (npc_id, player)).fetchall()
    harm, amends, top, scar = 0.0, 0.0, None, False
    for r in rows:
        age = game_time - r["learned_at"] if r["learned_at"] is not None else 3.0
        fade = 0.5 ** (max(age, 0.0) / HALF_LIFE)
        if r["type"] in AMENDS:
            amends += (r["severity"] or 0) * fade
        elif r["type"] in HARM:
            mine = r["target"] in (npc_id, None)
            weight = HARM[r["type"]] * fade * (1.0 if mine else 0.6) * (0.5 if r["how"].startswith("told") else 1.0)
            harm += weight
            scar = scar or r["type"] in GRAVE
            if top is None or weight > top[0]:
                top = (weight, r, mine)
    heat = min(1.0, max(0.0, harm - amends) / SCALE)
    if top is None or (heat < 0.1 and not scar):
        trust = conn.execute("select trust from relationships where npc_id=? and player=?",
                             (npc_id, player)).fetchone()
        t = trust["trust"] if trust else CONFIG["start_trust"]
        mood = "fond" if t >= 30 else "warm" if t >= 15 else "neutral"
        return {"mood": mood, "strength": "faint", "cause": None, "heat": 0.0}
    _, row, mine = top
    if heat < 0.25:
        mood = "guarded"
    elif not mine:
        mood = "cold"
    else:
        mood = MOOD[row["type"]][temper]
    strength = "faint" if heat < 0.25 else "clear" if heat < 0.6 else "strong"
    return {"mood": mood, "strength": strength, "cause": _cause(row, npc_id), "heat": round(heat, 3)}
```

- [ ] **Step 4: Run** `tests/test_stance.py`. Expect PASS. If `a_hit` first-mood is not "angry" because Elise's `temper` is `steady` and `hit_npc` maps steady to angry, the table above already yields angry. If a witness test fails on `learned_at`, check `record_event` passes `ev["game_time"]` (it does).

---

### Task 4: Wire stance into asks, pacing and fallbacks

**Files:** Modify `backend/game.py`. Test: `tests/test_game.py`.

**Interfaces:**
- `_ease(conn, player, npc_id) -> "introduce"|"hint"|"open"` is per villager.
- `build_context` adds `facts.stance` (full dict, including `heat`, for game code). `_heard` forwards only `mood`, `strength`, `cause`.
- `fallback_line(stance) -> str` and `stance.FALLBACK`.

- [ ] **Step 1: Failing tests** (replace the two tests that encode global pacing)

```python
def test_each_villager_is_met_for_the_first_time_once(conn):
    hello = {"reply": "Hello.", "claims": []}
    for i in range(5):
        greet(conn, ScriptedLLM([hello]), "w", "p", "elise", f"g{i}", 1.0)
    fresh = ScriptedLLM([hello])
    greet(conn, fresh, "w", "p", "mira", "m", 1.0)
    assert fresh.calls[0][1]["facts"]["ease"] == "introduce"  # she has never met the player


def test_a_hit_villager_does_not_pitch_an_errand_or_start_over(conn):
    from backend.game import record_event
    hello = {"reply": "Hello.", "claims": []}
    for i in range(3):
        greet(conn, ScriptedLLM([hello]), "w", "p", "elise", f"g{i}", 1.0)
    record_event(conn, ScriptedLLM([]), {"world": "w", "player": "p", "type": "hit_npc", "target": "elise",
                                         "witnesses": ["elise"], "game_time": 2.0, "details": {}})
    llm = ScriptedLLM([hello])
    greet(conn, llm, "w", "p", "elise", "after", 3.0)
    facts = llm.calls[0][1]["facts"]
    assert facts["stance"]["mood"] in ("angry", "guarded") and facts["stance"]["cause"] == "you hit me"
    assert not facts.get("need") and "ease" not in facts and "heat" not in facts["stance"]
```

Also change `test_greet_invalid_returns_empty` to expect a non-empty line:

```python
def test_a_failed_greeting_is_never_silent(conn):
    bad = {"reply": "x", "claims": [{"event_id": 5, "type": "gift", "how": "witnessed"}]}
    assert greet(conn, ScriptedLLM([bad, bad]), "w", "p", "elise", "g", 1.0)["reply"]
```

and update `test_the_shortage_comes_after_the_introductions` to the per-villager shape: Nell's first greeting is `introduce`, the second `hint`, the third carries `need` (item flour), the fourth within half a day does not.

Run: expect FAIL.

- [ ] **Step 2: `_ease` per villager** (replace the old function; drop the `ease_from` flag logic):

```python
def _ease(conn, player, npc_id) -> str:
    """Each villager is met once. Introduction, then a hint, then they know you."""
    met = conn.execute("select count(*) from interactions where player=? and npc_id=? and task='npc_dialogue' "
                       "and ifnull(retried,0)=0", (player, npc_id)).fetchone()[0]
    return "introduce" if met < 1 else "hint" if met < 2 else "open"
```

Update the two call sites (`greet`: `_ease(conn, player, npc_id)`; `talk`: same).

- [ ] **Step 3: stance in `build_context`.** Add to `facts`: `"stance": stance.of(conn, npc_id, player, game_time) if game_time is not None else None`. Add `"stance"` to `_FACT_KEYS`. In `_heard`, after building `kept`:

```python
    if kept.get("stance"):
        s = kept["stance"]
        kept["stance"] = {k: s[k] for k in ("mood", "strength", "cause")}
        if s["mood"] in stance.HARMFUL or s["mood"] == "guarded":
            kept.pop("ease", None)  # a villager who feels something is not meeting a stranger
    else:
        kept.pop("stance", None)
```

(Run this before the `ease`-based pops and give the `ease` branch `kept.get("ease")` reads after it.)

- [ ] **Step 4: gate asks.** Replace `player_ask`:

```python
def player_ask(conn, player, npc_id, game_time) -> dict | None:
    """A villager does not carry the quest list. Someone who is angry or afraid tells you to keep away."""
    s = stance.of(conn, npc_id, player, game_time)
    if rules.band(db.get_trust(conn, npc_id, player)) == "hostile" or (
            s["mood"] in ("angry", "afraid") and s["heat"] >= 0.5):
        text = "Tell them to keep their distance." if s["mood"] == "afraid" else "Tell them to leave you alone."
        return {"kind": "refuse", "text": text}
    return None
```

In `greet`: `harmful = stance.of(...)["mood"] in stance.HARMFUL`; `need = None if ask or harmful or not _may_ask(...) else own_need(...)`; and when the stance is not neutral/warm/fond use `STANCE_GREET` as the situation:

```python
STANCE_GREET = ("the newcomer comes up to you and you speak first. You feel what facts.stance says, "
                "and you let it show before anything else")
```

In `talk`: `need = mine if mine and not abused and not harmful and (lost or _wants_help(message)) else None` with `harmful` computed from the same stance.

- [ ] **Step 5: fallbacks.** Add to `stance.py`:

```python
FALLBACK = {"neutral": "Hm. Morning.", "warm": "Good to see you.", "fond": "There you are. Good to see you.",
            "guarded": "Hm. You again.", "cold": "I've nothing to say to you.", "hurt": "...Not now.",
            "angry": "Leave me be.", "afraid": "Please... keep back."}
```

`greet` failure returns `{"reply": stance.FALLBACK[st["mood"]], "notices": [], "point_to": None, "give": []}`. In `talk`, `guidance_line` keeps "Sorry, say that once more." for neutral, warm and fond, and returns `stance.FALLBACK[mood]` for the others.

- [ ] **Step 6: Run** the full suite. Fix anything red that still assumes global pacing.

---

### Task 5: Conversation context

**Files:** Modify `backend/db.py` (new `recent_turns`), `backend/game.py` (`build_context`, `_FACT_KEYS`). Test: `tests/test_game.py`.

**Interfaces:** `db.recent_turns(conn, npc_id, player, limit=6) -> [{"who": "you"|"them", "text": str}]`. Excludes scene and event threads.

- [ ] **Step 1: Failing test**

```python
def test_the_model_is_given_the_conversation_so_far(conn):
    llm = ScriptedLLM([Q, {"reply": "I'm Hazel.", "claims": []}, Q, {"reply": "Pleased.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "who are you?", "t", 1.0)
    talk(conn, llm, "w", "p", "hazel", "nice to meet you", "t", 1.1)
    recent = [u for t, u in llm.calls if t == "npc_dialogue"][1]["facts"]["recent"]
    assert recent == [{"who": "you", "text": "who are you?"}, {"who": "them", "text": "I'm Hazel."}]
```

- [ ] **Step 2: Implement `db.recent_turns`:**

```python
def recent_turns(conn, npc_id, player, limit=6) -> list[dict]:
    """The last lines of this one conversation, oldest first. Scenes and event shouts are not conversation."""
    rows = conn.execute(
        "select request, reply from interactions where npc_id=? and player=? and task='npc_dialogue' "
        "and ifnull(retried,0)=0 and thread_id not like '%:scene:%' and validator_result like '%\"ok\": true%' "
        "order by id desc limit ?", (npc_id, player, limit)).fetchall()
    turns = []
    for r in reversed(rows):
        try:
            said = json.loads(r["request"]).get("player_message")
            reply = json.loads(r["reply"]).get("reply")
        except (TypeError, ValueError, AttributeError):
            continue
        if said:
            turns.append({"who": "you", "text": said})
        if reply:
            turns.append({"who": "them", "text": reply})
    return turns[-limit:]
```

- [ ] **Step 3:** `build_context` facts gain `"recent": db.recent_turns(conn, npc_id, player)`; add `"recent"` to `_FACT_KEYS`; in `_heard` drop it when empty (`if not kept.get("recent"): kept.pop("recent", None)`).

- [ ] **Step 4: Run.** Expect PASS. Check `db.py` already imports `json`.

---

### Task 6: Prompt and validator

**Files:** Modify `backend/llm.py`, `backend/validator.py`. Test: `tests/test_validator.py`.

- [ ] **Step 1: Failing test**

```python
def test_a_cheerful_reply_from_an_angry_villager_is_rejected():
    ctx = {"memories": [], "facts": {"stance": {"mood": "angry", "strength": "strong", "cause": "you hit me"}}}
    warm = {"reply": "Welcome, friend! Lovely to see you.", "claims": []}
    assert "tone_mismatch" in validate("npc_dialogue", warm, ctx)["errors"]
    cold = {"reply": "Get away from my stall.", "claims": []}
    assert validate("npc_dialogue", cold, ctx)["errors"] == []
```

- [ ] **Step 2: Implement** in `validator.validate` (npc_dialogue branch):

```python
        s = facts.get("stance") or {}
        if s.get("mood") in ("angry", "afraid", "hurt", "cold") and words & {"welcome", "friend", "lovely", "glad",
                                                                             "delighted", "pleasure", "wonderful"}:
            res["errors"].append("tone_mismatch")
```

- [ ] **Step 3: Prompt** (`backend/llm.py`, inside `_DIALOGUE`): add this section after "HOW YOU TALK":

```python
    "HOW YOU FEEL\n"
    "facts.stance is how you feel about this person right now, and it outranks relationship.band. mood is the "
    "feeling, strength is how strongly, and cause is why, in plain words. Stay in that mood for the whole "
    "exchange. angry: short, sharp, you want them gone. afraid: you keep your distance and your voice shakes. "
    "hurt: quiet and withdrawn. cold: civil and closed. guarded: you remember and you do not relax. warm and "
    "fond: open. When the cause fits, say it in your own words; if the player did the harm, you may name it. "
    "An apology softens you one notch and does not wipe the memory. When someone has just hurt you, you do not "
    "greet them cheerfully, offer errands, or introduce yourself again.\n"
    "facts.recent is what the two of you just said, oldest first. Continue it. Do not greet again, introduce "
    "yourself again, or repeat a point you have made. memories carry when: moments ago, earlier, yesterday, "
    "days ago.",
```

and change the pacing line `introduce: a first meeting.` to `introduce: you have never met this person.`

- [ ] **Step 4: Run** the suite. Expect PASS.

---

### Task 7: The victim tells it at once

**Files:** Modify `backend/game.py` (`gossip`). Test: `tests/test_game.py`.

- [ ] **Step 1: Failing test**

```python
def test_a_victim_passes_it_on_the_first_time_they_meet_someone(conn):
    from backend.game import record_event
    record_event(conn, ScriptedLLM([]), {"world": "w", "player": "p", "type": "hit_npc", "target": "elise",
                                         "witnesses": ["elise"], "game_time": 1.0, "details": {}})
    # a bystander would wait out the delay; the victim does not, and is not shy
    assert gossip(conn, "w", "p", "elise", "mira", 1.0, roll=0.99)["shared"]
    assert db.top_memories(conn, "mira", "w:p")[0]["how"] == "told_by:elise"
```

- [ ] **Step 2: Implement.** In `gossip`, change the delay clause and the roll gate:

```python
        "and (m.learned_at is null or ? - m.learned_at >= ? or e.target = m.npc_id) "
```

```python
    victim = m["target"] == teller
    if roll >= npc_cfg(teller).get("chattiness", 0.5) and not victim and not (m["type"] in CRIME and listener == "wren"):
        return none
```

- [ ] **Step 3: Run.** Expect PASS.

---

### Task 8: Knowledge canary

**Files:** Test only: `tests/test_situations.py` (append).

- [ ] **Step 1: Write the test**

```python
def test_one_villagers_private_memory_never_reaches_another(conn):
    from backend.game import _heard, build_context
    from backend.db import load_config
    db.add_memory(conn, "elise", "w:p", None, "gift", "CANARY the newcomer gave me a ruby", "witnessed", 1.0, 5, 1.0)
    others = [n for n in load_config()["npcs"] if n != "elise"]
    assert "CANARY" in json.dumps(_heard(build_context(conn, "elise", "w:p", game_time=1.0)))
    for n in others:
        assert "CANARY" not in json.dumps(_heard(build_context(conn, n, "w:p", game_time=1.0)))
```

(Add `import json` and `from backend import db` at the top of the test file if missing.)

- [ ] **Step 2: Run.** Expect PASS immediately (this guards against regressions).

---

### Task 9: Simulation harness

**Files:** Create `tools/sim.py`.

**Interfaces:** `python tools/sim.py <scenario> [--mock]` plays a persona against the real model on a temp database and prints a transcript plus measures. Scenarios: `thug`, `saint`, `lost`, `troll`.

- [ ] **Step 1: Write the harness** with these pieces:
  - The temp database and simulated clock from the baseline script, using `game.greet`, `game.talk`, `game.record_event`, `game.react`, `game.gossip`.
  - A `Step` list per scenario: `("greet", npc)`, `("say", npc, text)`, `("hit", victim, witnesses)`, `("gossip", teller, listener)`, `("wait", days)`.
  - `thug`: intros for elise and nell, hit elise with nell watching, `say elise "hello?"`, `say elise "sorry about that"`, greet nell, `say nell "what happened to Elise?"`, wait 1 day, greet elise, greet mira (never met), then `gossip elise mira` and greet mira again.
  - Measures printed after the transcript: silent replies, validator failures (from `interactions`), latency p50 and p95, mean pairwise word-overlap between replies (repetition), and the number of lines containing a request ("bring me", "could you bring", "would you bring").
  - `--mock` uses the offline `MockLLM` so the harness itself can be checked with no network.

- [ ] **Step 2: Smoke test** with `--mock`: `.venv\Scripts\python tools/sim.py thug --mock` prints a transcript and the measures with no exception.

- [ ] **Step 3: Run it live** (real model) and save the output to `sim/runs/<date>-thug.txt`. Compare against the baseline recorded in the spec: after the build, Elise must not greet cheerfully right after the hit, must not pitch an errand the next day, Nell must raise what she saw, and Mira must not greet as if she knows the player until she has been told.

---

### Task 10: Close out

- [ ] Run the full suite: `.venv\Scripts\python -m pytest -q`. Expect all green.
- [ ] Restart the backend (stop the listener on port 8000, then the uvicorn command from the Global Constraints) and check `/health`.
- [ ] Update the spec: add `neutral` to the mood list in section 1, and note the per-villager pacing.

## Self-review against the spec

- Section 1 (stance): Tasks 2, 3, 4, 6.
- Section 3 (rumours, victim at once): Task 7. Hearing-versus-seeing and `told_by` attribution are in Task 3 (`_cause`) and are exercised again in plan 2 when the cry for help exists.
- Section 5 (fallback lines): Task 4.
- Section 7 (conversation context): Task 5.
- Section 8 (knowledge): Task 8, plus the attributed cause in Task 3.
- Simulation: Task 9.
- Out of this plan and covered by plan 2: sections 0 (reachability), 2 (victim and bystander behaviour in the world), 4 (journal tab), 6 (name tags), and the latency, canon, debug and `scene` items.
