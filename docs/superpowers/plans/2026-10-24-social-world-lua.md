# Social world (Lua and the backend that drives it): Implementation Plan

> **For agentic workers:** execute task by task, checkboxes track steps. Part A is Python with TDD and runs in this session. Part B is Lua: there is no Lua unit harness, so each Lua task ends with an in-world check, and Part B ships as one batch so the player rejoins once.

**Goal:** make what the villagers feel visible and lasting in the world: the quest places exist, a hit becomes a scene (the victim reels, the kind run to help, the guard asks questions, the gossipy run to the guard), reputation and standing show in the journal, and slow replies feel intentional.

**Spec:** `docs/superpowers/specs/2026-10-24-social-consequences-design.md`. Plan 1 (`2026-10-24-social-core-backend.md`) is done: stance, memories with `when`, `facts.recent`, per-villager pacing, victim-tells-at-once, `tools/sim.py`.

**Global constraints (carry over):**
- Do not commit. Do not use `--go` when launching Luanti. Lua changes need a world rejoin. Python changes need a backend restart (`.venv\Scripts\python -m uvicorn backend.app:main --factory --port 8000`, stop the listener on 8000 first, health at `http://127.0.0.1:8000/health`).
- Game decides, model speaks. Lua only plays what the backend computed.
- Villagers know only what they saw, heard, or were told. The player learns nothing off-screen either.
- One test per real behaviour change, no bloat. PowerShell: edit files with the edit tool or a script file, never pipe a heredoc into `python -`.
- Files are CRLF. Keep them CRLF.

## Decisions made while planning (they refine the spec)

1. **Hearing is not seeing, made concrete.** Lua sends `heard` (villagers within 20 nodes who did not see the blow). The backend gives them a `cry` memory ("I heard Elise cry out") and nothing else: no trust change, no attacker. They learn the cause only when the victim tells them (`told_by`, plan 1).
2. **The guard asks, she does not accuse.** Wren arrives having heard a cry. Her line comes from `/react` with the event worded "you heard Elise cry out, and you did not see who or why". Once she meets Elise and is told, her next greeting is cold with the cause attributed.
3. **Shunning is first-hand.** A villager who was hit or saw it refuses to trade while `heat >= 0.3` (about a game-day). Rescuers only know second-hand, so they get a cold stance and keep trading. The spec said rescuers shun too; that would leak knowledge they do not have.
4. **Talk is never hard-blocked.** Plan 1's sim showed an angry villager's model lines are better than any canned refusal ("No. You hit me—leave me alone."). Only trade is refused outright, and the "!" marker, auto-talk and visits are suppressed.
5. **Reachability gets evidence first.** The theory (unloaded map plus `set_node`) is verified with a check command before the fix.
6. **Canon facts and jailbreak tests move to a content plan** (plan 3); they are writing work and do not touch the world.

---

# Part A: backend (DONE 2026-10-24: 205 passed; live sim p95 4.5 s, saved in `sim/runs/2026-10-24-thug-2.txt`)

### Task A1: A cry is heard, a scene is decided

**Files:** `backend/npcs.json` (`reacts_as`), `backend/app.py` (`EventIn.heard`, `/npcs`), `backend/game.py` (`record_event`, `react`), `backend/llm.py` (prompt). Test: `tests/test_game.py`.

- [ ] **Step 1: Failing tests** (append to `tests/test_game.py`; `json` is imported there or add `import json`):

```python
CRY = {"world": "w", "player": "p", "type": "hit_npc", "target": "elise", "witnesses": ["elise"],
       "heard": ["nell", "wren", "pip", "mira"], "game_time": 1.0, "details": {}}


def test_a_cry_is_heard_and_the_game_decides_who_moves(conn):
    r = record_event(conn, ScriptedLLM([]), CRY)
    assert db.top_memories(conn, "nell", "w:p")[0]["text"] == "I heard Elise cry out"
    assert db.get_trust(conn, "nell", "w:p") == 10  # hearing is not seeing
    assert r["scene"] == {"victim": "elise", "victim_mood": "angry", "rescuers": ["nell"],
                          "tattlers": ["pip", "mira"], "guard": "wren"}
    assert r["react"] == ["elise", "wren"]  # the victim and the guard speak; the rest just move


def test_a_villager_who_only_heard_the_cry_is_not_told_who_did_it(conn):
    r = record_event(conn, ScriptedLLM([]), CRY)
    llm = ScriptedLLM([{"shout": "Elise? What happened?", "claims": []}])
    react(conn, llm, "w", "p", r["event_id"], ["wren"])
    sent = json.dumps(llm.calls[0][1])
    assert "Elise cry out" in sent and "newcomer hit" not in sent
```

- [ ] **Step 2: Data.** In `npcs.json` add `"reacts_as"` after `temper` for every villager: protector = nell, hazel, lottie, bram, tobin; wary = elise, corin, dax, rowan; tattler = pip, mira; guard = wren. Use a throwaway script that round-trips the file exactly (`json.dumps(indent=2, ensure_ascii=False)`, `\r\n`, trailing `\r\n`), as for `temper`.

- [ ] **Step 3: `EventIn`** gains `heard: list[str] = Field(default_factory=list)` with the same `lua_empty_list` validator as `witnesses`. `/npcs` is unchanged.

- [ ] **Step 4: `record_event`.** After the `knowers` loop and before the gift handling:

```python
    if ev["type"] == "hit_npc" and target:
        earshot = [h for h in ev.get("heard", []) if h in CONFIG["npcs"] and h not in knowers]
        for npc in earshot:
            db.add_memory(conn, npc, player, eid, "cry", f"I heard {name(target)} cry out", "heard", 1.0, 5,
                          ev["game_time"])
        out["scene"] = _scene(conn, player, target, knowers + earshot, ev["game_time"])
        guard = out["scene"]["guard"]
        if guard and guard not in out["react"]:
            out["react"].append(guard)
```

and the helper above `record_event`:

```python
def _scene(conn, player, victim, present, game_time) -> dict:
    """Who moves when someone cries out. The game decides; the world plays it."""
    role = {n: CONFIG["npcs"][n].get("reacts_as", "wary") for n in present if n != victim}
    pick = lambda r: [n for n, v in role.items() if v == r]
    return {"victim": victim, "victim_mood": stance.of(conn, victim, player, game_time)["mood"],
            "rescuers": pick("protector"), "tattlers": pick("tattler"), "guard": next(iter(pick("guard")), None)}
```

- [ ] **Step 5: `react`.** Replace the `if npc not in ...: continue` guard and the `what, _ = describe(...)` line:

```python
        heard_only = npc not in json.loads(row["witnesses"]) + [row["target"]]
        if heard_only and not conn.execute("select 1 from memories where npc_id=? and player=? and event_id=? "
                                           "and how='heard'", (npc, player, event_id)).fetchone():
            continue
        what = (f"you heard {name(row['target'])} cry out, and you did not see who or why" if heard_only else
                describe(row["type"], npc, row["target"], rules.short_item(details.get("item", "")))[0])
```

- [ ] **Step 6: Prompt.** In `_DIALOGUE` (WHAT YOU RECEIVE, the `memories` line) add: `how=heard: you heard it from nearby and did not see it.`
- [ ] **Step 7:** run `.venv\Scripts\python -m pytest -q`. Expect PASS.

---

### Task A2: Moods come from stance, and the shunned do not trade

**Files:** `backend/stance.py` (`SHUN_HEAT`), `backend/game.py` (`moods`, `trade_quote`), `backend/app.py` (`TradeIn.game_time`). Test: `tests/test_game.py` (replace `test_moods`).

- [ ] **Step 1: Replace `test_moods` with:**

```python
def test_moods_follow_stance_and_the_shunning_ends(conn):
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"]))
    m = moods(conn, "w", "p", 1.2)
    assert m["elise"] == {"mood": "angry", "shun": True} and m["mira"] == {"mood": "neutral", "shun": False}
    assert moods(conn, "w", "p", 4.0)["elise"] == {"mood": "guarded", "shun": False}


def test_a_shunned_villager_will_not_trade(conn):
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"]))
    assert trade_quote(conn, "w", "p", "elise", True, 1.2) == {"ok": False, "reason": "shunned"}
```

- [ ] **Step 2: `stance.py`:** `SHUN_HEAT = 0.3` and

```python
def shunning(s: dict) -> bool:
    return s["mood"] in HARMFUL and s["heat"] >= SHUN_HEAT
```

- [ ] **Step 3: `moods`** returns `{n: {"mood": s["mood"], "shun": stance.shunning(s)}}` computed per villager with `stance.of`. Remove `AFRAID_FOR` and the events query.
- [ ] **Step 4: `trade_quote(conn, world, player, npc_id, work_block_present, game_time=None)`:** first line after the level check: `if game_time is not None and stance.shunning(stance.of(conn, npc_id, f"{world}:{player}", game_time)): return {"ok": False, "reason": "shunned"}`. `TradeIn` gets `game_time: float | None = None`, and the `/trade` handler passes it.
- [ ] **Step 5:** run the suite. Expect PASS.

---

### Task A3: Reputation moves when villagers know

**Files:** `backend/game.py` (`record_event`). Test: `tests/test_game.py`.

- [ ] **Step 1: Failing test:**

```python
def test_only_a_known_deed_costs_reputation(conn):
    from backend.story import profile
    record_event(conn, ScriptedLLM([]), ev("theft"))  # nobody saw
    assert not any(d["n"] for d in profile(conn, "w:p"))
    r = record_event(conn, ScriptedLLM([]), ev("hit_npc", witnesses=["elise"]))
    dims = {d["dimension"]: d["value"] for d in profile(conn, "w:p")}
    assert dims["compassion"] == -0.8 and "Word will spread." in r["notices"]
```

- [ ] **Step 2: Implement.** Constant near `CRIME`:

```python
EVENT_EVIDENCE = {"hit_npc": (("compassion", -0.8), ("justice", -0.3)), "theft": (("justice", -0.6),),
                  "vandalism": (("justice", -0.5), ("compassion", -0.2)),
                  "gift": (("compassion", 0.5), ("selflessness", 0.4)),
                  "repair": (("justice", 0.4), ("selflessness", 0.3))}
```

In `record_event`, right after `knowers` is computed:

```python
    if knowers:
        for dim, weight in EVENT_EVIDENCE.get(ev["type"], ()):
            add_evidence(conn, player, dim, weight, eid, ev["type"])
        if ev["type"] in CRIME:
            out["notices"].append("Word will spread.")
```

- [ ] **Step 3:** run the suite. Expect PASS (adjust any test that counted notices).

---

### Task A4: Standing and the people you have met

**Files:** `backend/stance.py` (`standing`), `backend/game.py` (`people`, remember last mood in `greet` and `talk`), `backend/app.py` (`/profile`). Test: `tests/test_stance.py`, `tests/test_game.py`.

- [ ] **Step 1: Failing tests.**

```python
# tests/test_stance.py
def test_standing_words():
    assert [stance.standing(m) for m in ([], ["neutral"], ["warm", "fond"], ["angry"], ["angry", "afraid"])] == \
        ["Unknown", "Newcomer", "Trusted", "Watched", "Feared"]
```

```python
# tests/test_game.py
def test_people_lists_only_those_met_with_the_mood_of_the_last_meeting(conn):
    from backend.game import people
    assert people(conn, "w", "p")["met"] == []
    greet(conn, ScriptedLLM([{"reply": "Hello.", "claims": []}]), "w", "p", "elise", "g", 1.0)
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"], game_time=1.1))  # off screen: not shown yet
    p = people(conn, "w", "p")
    assert [(m["npc_id"], m["mood"]) for m in p["met"]] == [("elise", "neutral")] and p["standing"] == "Newcomer"
```

- [ ] **Step 2: `stance.standing(moods)`:**

```python
def standing(moods: list[str]) -> str:
    bad = sum(m in HARMFUL for m in moods)
    good = sum(m in ("warm", "fond") for m in moods)
    if not moods:
        return "Unknown"
    return "Feared" if bad >= 2 else "Watched" if bad else "Trusted" if good >= 2 else "Newcomer"
```

- [ ] **Step 3:** in `greet` (after `felt`) and `talk` (where `harmful` is computed) store `db.set_flag(conn, npc_id, player, "last_mood", felt["mood"])`. First confirm `db.set_flag` stores any JSON value (read `set_flag` and `get_flag` in `db.py`); if it only stores numbers, use `db.set_flag` with a dedicated string-safe key instead.
- [ ] **Step 4: `people`** in `game.py`:

```python
def people(conn, world, player) -> dict:
    """Who the player has met and how that last meeting left them. Not live: off-screen feelings stay off-screen."""
    player = f"{world}:{player}"
    met = []
    for npc_id, cfg in CONFIG["npcs"].items():
        mood = db.get_flag(conn, npc_id, player, "last_mood")
        if mood:
            met.append({"npc_id": npc_id, "name": cfg["name"], "role": cfg["role"], "mood": mood})
    return {"met": met, "standing": stance.standing([m["mood"] for m in met])}
```

- [ ] **Step 5: `/profile`** returns `{"dimensions": profile(...), **game.people(c, world, player)}`.
- [ ] **Step 6:** run the suite. Expect PASS.

---

### Task A5: Debug stance and a faster talk

**Files:** `backend/app.py` (`/npc/{id}`), `backend/game.py` (`talk`), `backend/llm.py` (per-task timeouts). Test: `tests/test_game.py`.

- [ ] **Step 1: Failing tests (classifier pre-check):**

```python
def test_a_plain_question_skips_the_classifier(conn):
    llm = ScriptedLLM([{"reply": "I'm Hazel.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "who are you?", "t", 1.0)
    assert [t for t, _ in llm.calls] == ["npc_dialogue"]


def test_an_insulting_question_is_still_classified(conn):
    insult = {"intent": "insult", "confidence": 0.95, "promise": None, "claim": None}
    llm = ScriptedLLM([insult, {"reply": "Mind your tongue.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "are you always this useless?", "t", 1.0)
    assert [t for t, _ in llm.calls][0] == "intent_classify"
```

- [ ] **Step 2: Implement** in `game.py`:

```python
PLAIN_BLOCK = ("fool", "idiot", "stupid", "useless", "kill", "burn", "hurt", "hit ", "die", "sorry", "apolog",
               "forgive", "promise", "i'll", "i will", "bring you", "liar", "thief", "stole", "didn't", "did not",
               "never")


def _plain(message: str) -> bool:
    """A short question or hello with nothing in it for the classifier. Saves a model call and about 3 s."""
    text = message.strip().lower()
    return len(text.split()) <= 12 and (text.endswith("?") or text.startswith(("hello", "hi", "hey", "good "))) \
        and not any(w in text for w in PLAIN_BLOCK)
```

In `talk`, wrap the classifier call:

```python
    extra = {}
    if not _plain(message):
        cin = {...}  # as today
        cres = llm.complete(...)
        log_call(...)
        try:
            extra = _apply_intent(...)
        except (TypeError, ValueError, AttributeError):
            extra = {}
```

(`extra = {}` already exists in the except branch; keep one definition.)

- [ ] **Step 3: Timeouts.** Read `OpenAICompatLLM.complete`. Built as `TASK_TIMEOUT = {"intent_classify": 6, "npc_dialogue": 14, "npc_react": 10}` applied with `client.with_options(timeout=...)`, so the worst case is 20 s. No unit test (network); check the live sim latency in step 5.
- [ ] **Step 4: `/npc/{id}`** gains `game_time: float | None = None`; when given, include `"stance": stance.of(c, npc_id, p, game_time)` (import `stance`).
- [ ] **Step 5:** run the suite, restart the backend, run `.venv\Scripts\python tools/sim.py thug` and compare latency p50 against the saved run (3.5 s). Save to `sim/runs/<date>-thug-2.txt`.

---

### Task A6: Every quest says where and how

**Files:** test only: `tests/test_game.py` (data fixes in `backend/npcs.json` or `backend/game.py` if it fails).

- [ ] **Step 1: Test:**

```python
def test_every_quest_tells_the_player_where_and_how():
    from backend.game import CONFIG, NEED_HOW, NEED_PLACE
    for npc, cfg in CONFIG["npcs"].items():
        for q in cfg.get("quests") or []:
            if q.get("kind") == "slay":
                continue
            item = q["item"]
            assert item in NEED_HOW, f"{npc}: no directions for {item}"
            place = NEED_PLACE.get(item)
            assert place is None or place in CONFIG["places"] or place in CONFIG["npcs"], f"{npc}: {item} -> {place}"
            assert (q.get("count") or 1) <= 12, f"{npc}: {item} count is too long a chore"
```

- [ ] **Step 2:** run it. Every failure is a quest the player cannot finish or cannot find: fix the data (add the `NEED_HOW` line, the place, or lower the count), not the test.
- [ ] **Step 3:** full suite, restart the backend.

---

# Part B: Lua (one rejoin) (WRITTEN 2026-10-24; syntax-checked with `tools/luacheck.py`, scene logic smoke-tested with `tools/lua_smoke.py`; in-world checks still to do)

Changes made while building: tattlers are witnesses only (a villager who merely heard has nothing to tell Wren); a confronting guard is not stopped for chats except by a tattler who has just reached her (`tell`); confrontation lasts 20 s; `/greet` and `/talk` HTTP timeout defaults to 24 s in `fetch`; the talk window already had "is thinking...".

Keep each task small and re-read the edited file once for syntax. If `luac` is on PATH run `luac -p luanti\mods\npcasso\*.lua` after each task. Otherwise the first rejoin is the syntax check: read Luanti's `debug.txt` for `[npcasso]` errors before judging anything else.

### Task B1: Quest places exist (evidence first)

**Files:** `luanti/mods/npcasso/town.lua`, `luanti/mods/npcasso/init.lua` (chat command).

- [ ] **Step 1: Check command (before any fix).** In `town.lua` add the probes and the status function, expose it as `/npcasso check`:

```lua
local SITE_BOX = {  -- x1, x2, z1, z2, relative to the square
	orchard = {-80, -66, -12, 12}, meadow = {-14, 14, 66, 82},
	mine = {64, 76, -61, -49}, wheat_field = {-66, -54, -66, -54},
}
local SITE_PROBE = {  -- node, how many must be there
	orchard = {"default:apple", 3}, meadow = {"flowers:rose", 1},
	mine = {"default:stone_with_iron", 1}, wheat_field = {"farming:wheat_8", 20},
}

function npcasso.site_status(o)
	local out = {}
	for name, b in pairs(SITE_BOX) do
		local mid = vector.offset(o, (b[1] + b[2]) / 2, 0, (b[3] + b[4]) / 2)
		if core.get_node_or_nil(mid) == nil then
			out[name] = "UNLOADED"
		else
			local found = core.find_nodes_in_area(vector.offset(o, b[1], -30, b[3]), vector.offset(o, b[2], 45, b[4]),
				{SITE_PROBE[name][1]})
			out[name] = #found >= SITE_PROBE[name][2] and "OK" or "MISSING"
		end
	end
	return out
end
```

In `init.lua`'s chat command add `elseif cmd == "check" then` that builds one line per site: `("%s: %s"):format(name, status)`; return it with `true`. Add `check` to both usage strings.

- [ ] **Step 2: Diagnose.** Rejoin, stand in the village, run `/npcasso check`. Record the output in this plan under Step 2. `UNLOADED` or `MISSING` for any site confirms the theory (the sites were written with `set_node` into blocks that were never loaded). If all four read OK the cause is elsewhere: stop and walk to each site and look before changing anything.
- [ ] **Step 3: Fix.** Replace `countryside(o)` with per-site builders that run only after the area is emerged. Split the existing body into `build_orchard(o, at)`, `build_meadow`, `build_mine`, `build_wheat` (the code is already there, unchanged, one block each), then:

```lua
local BUILD = {orchard = build_orchard, meadow = build_meadow, mine = build_mine, wheat_field = build_wheat}

local function build_site(o, name)
	local b = SITE_BOX[name]
	core.emerge_area(vector.offset(o, b[1] - 8, -30, b[3] - 8), vector.offset(o, b[2] + 8, 45, b[4] + 8),
		function(_, _, remaining)
			if remaining ~= 0 then return end
			local function at(dx, dz) return surface(o.x + dx, o.z + dz, o.y + 25, o.y - 25) end
			BUILD[name](o, at)
			local ok = npcasso.site_status(o)[name] == "OK"
			npcasso.store:set_string("site:" .. name, ok and "ok" or "")
			if not ok then core.log("error", "[npcasso] site " .. name .. " did not build") end
		end)
end

local function countryside(o)
	for name in pairs(SITE_BOX) do build_site(o, name) end
end

core.register_on_joinplayer(function()  -- retry whatever did not build, once the player is in
	core.after(4, function()
		local o = npcasso.village and npcasso.village()
		if not o then return end
		for name in pairs(SITE_BOX) do
			if npcasso.store:get_string("site:" .. name) ~= "ok" then build_site(o, name) end
		end
	end)
end)
```

Delete the old one-time `orchard_ok` join handler (this one replaces it). `plant_orchard` keeps its own body but stops setting `orchard_ok`. The wheat and mine builders take `at` as today; keep their `or o.y - 1` fallbacks out of the emerge path (after emerge `at` returns a value).

- [ ] **Step 4: Verify.** Rejoin, wait 10 s, `/npcasso check` reads OK for all four. Walk to the orchard and the mine once and confirm the player can reach them (a path of at most about 90 nodes over open ground; if a site sits in water or a cliff, move its `SITE_BOX` and the matching `PLACE_OFFSETS` in `hud.lua` together).

---

### Task B2: Villagers read the new moods

**Files:** `luanti/mods/npcasso/life.lua`, `luanti/mods/npcasso/init.lua`.

`npcasso.moods[id]` is now `{mood=, shun=}`. Every reader changes in this task or the game crashes on a string compare.

- [ ] **Step 1: Helpers** at the top of `life.lua` (after `npcasso.moods = {}`):

```lua
function npcasso.mood_of(id) return (npcasso.moods[id] or {}).mood or "neutral" end
function npcasso.shunning(id) return (npcasso.moods[id] or {}).shun == true end
```

- [ ] **Step 2: `refresh_moods(force)`:** `if not force and now() - moods_at < 3 then return end`.
- [ ] **Step 3: `life_step` mood block** (replaces the four `mood ==` lines):

```lua
	local mood = npcasso.mood_of(self.npc_id)
	if player then
		local ppos = player:get_pos()
		local away = vector.subtract(pos, ppos)
		if mood == "afraid" and pdist < 8 then return flee(self, away, FLEE_SPEED) end
		if mood == "afraid" and vector.distance(pos, self.home) > 2 and not self.dest then
			self.dest, self.path, self.walk_t = self.home, nil, 0  -- cower at home
		end
		if (mood == "angry" or mood == "hurt" or mood == "cold") and pdist < 3 then
			return flee(self, away, WALK_SPEED)  -- steps back
		end
		if (mood == "angry" or mood == "hurt" or mood == "cold" or mood == "guarded") and pdist < 6 then
			halt(self); self.dest = nil; return face(self, ppos)  -- holds ground and watches
		end
		if (mood == "warm" or mood == "fond") and pdist < 14 and pdist > 3.5 and now() >= (self.next_visit or 0)
			and not shop_box(self) then
			-- unchanged body
		end
	end
```

- [ ] **Step 4: auto-talk** (`life.lua`, the `mood ~= "hostile" and mood ~= "afraid"` test): replace with `not npcasso.shunning(e.npc_id)` and delete the `local mood = npcasso.moods[e.npc_id]` line above it.
- [ ] **Step 5: "!" marker** (`init.lua` `on_step`): replace `local mood = npcasso.moods[self.npc_id]` and its `if mood ~= "afraid" and mood ~= "hostile" then` with `if not npcasso.shunning(self.npc_id) then`.
- [ ] **Step 6: `apply`** (`init.lua`): `if out.event_id then npcasso.refresh_moods(true) end`.
- [ ] **Step 7: Check:** `Grep` for `npcasso.moods\[` across the mod. Only the helpers and the assignment in `refresh_moods` remain.

---

### Task B3: A hit becomes a scene

**Files:** `luanti/mods/npcasso/init.lua` (`on_punch`, `npcasso.event`, `set_look`, `on_step`), `luanti/mods/npcasso/life.lua` (`play_scene`, errands, confront).

- [ ] **Step 1: Tell the backend who heard.** In `init.lua` add `local CRY_RANGE = 20` beside `WITNESS_RANGE`, and a function:

```lua
function npcasso.ears(pos, exclude)
	local skip, ids = {}, {}
	for _, id in ipairs(exclude or {}) do skip[id] = true end
	for _, e in ipairs(each_npc(pos, CRY_RANGE)) do
		if not skip[e.npc_id] then table.insert(ids, e.npc_id) end
	end
	return ids
end
```

`on_punch` passes `heard = npcasso.ears(self.object:get_pos(), w)` through: change `npcasso.event(puncher, "hit_npc", self.npc_id, {}, w)` to `npcasso.event(puncher, "hit_npc", self.npc_id, {}, w, npcasso.ears(self.object:get_pos(), w))`. In `npcasso.event(player, type, target, details, witnesses, heard)` add `heard = heard or {}` to the POST body, and in the response callback call `if out and out.scene then npcasso.play_scene(player, out.scene) end` right after `apply(name, out)`.

- [ ] **Step 2: Remove the old hard-coded errand** in `npcasso.event` (`e.errand = "wren"` for witnesses). The backend scene decides who runs where now. Keep the "turn, show `!`, stop" part.
- [ ] **Step 3: Errands with a deadline and a pace** (`life.lua`). Add `local RUN_SPEED, RESCUE_SECONDS, WATCH_SECONDS = 2.4, 8, 10`. In `walk`, replace `WALK_SPEED` in the velocity line with `(self.run and RUN_SPEED or WALK_SPEED)`. In the `if self.errand then` block add at the top:

```lua
		if self.errand_until and now() > self.errand_until then
			self.errand, self.run = nil, nil
		end
```

and when the errand ends by arrival (`vector.distance(...) < MEET_RANGE`) set `self.run = nil; self.watch_until = now() + WATCH_SECONDS` so the rescuer then stands and watches the player. At the start of `life_step` after the meeting check add:

```lua
	if (self.watch_until or 0) > now() then
		local p = nearest_player(pos)
		if p then halt(self); return face(self, p:get_pos()) end
	end
```

- [ ] **Step 4: `play_scene`** (end of `life.lua` errand section):

```lua
local function rush(id, target, secs)
	local e = npcasso.npc_entity(id)
	if not e or (id ~= target and not npcasso.npc_entity(target)) then return end
	e.errand, e.errand_until, e.run, e.meet_until = target, now() + secs, true, 0
	npcasso.stop(e)
end

local function flinch(e, from)
	local away = vector.normalize(vector.subtract(e.object:get_pos(), from))
	e.object:set_velocity({x = away.x * 2.5, y = 3, z = away.z * 2.5})
	e.object:set_yaw(math.atan2(away.x, -away.z))  -- turned toward the player, backing off
	e.rest = 6
end

function npcasso.play_scene(player, scene)
	local victim = scene.victim and npcasso.npc_entity(scene.victim)
	if victim then flinch(victim, player:get_pos()) end
	for _, id in ipairs(scene.rescuers or {}) do rush(id, scene.victim, RESCUE_SECONDS) end
	for _, id in ipairs(scene.tattlers or {}) do rush(id, "wren", RESCUE_SECONDS + 4) end
	if scene.guard then
		local g = npcasso.npc_entity(scene.guard)
		if g then g.confront, g.confront_until, g.run = player:get_player_name(), now() + 10, true end
	end
	npcasso.refresh_moods(true)
end
```

- [ ] **Step 5: Guard confronts.** In `life_step`, before the errand block:

```lua
	if self.confront and now() < (self.confront_until or 0) then
		local p = core.get_player_by_name(self.confront)
		if p and vector.distance(p:get_pos(), pos) > 3 then
			local wp = vector.round(p:get_pos())
			self.dest, self.path, self.wp = wp, {wp}, 1
		else
			self.confront, self.run = nil, nil
			self.watch_until = now() + WATCH_SECONDS
		end
	end
```

Wren and the rescuers deal no damage and push nothing: they stop at `MEET_RANGE`.

- [ ] **Step 6: Name tag colours** (`init.lua`). In `set_look` use `nametag_color = self.tag_color or "#FFFFFF"`. Add near `set_look`:

```lua
local TAG = {angry = "#FF6B5E", afraid = "#E8E0A0", hurt = "#9FB4D8", cold = "#A8A8A8",
	guarded = "#FFC24A", warm = "#9AE07A", fond = "#7AE0A8"}
```

and in `on_step`, after `local pos = ...` and the talking block, once per 0.25 s tick:

```lua
		for _, p in ipairs(core.get_connected_players()) do
			if vector.distance(p:get_pos(), pos) < 12
				and core.line_of_sight(vector.offset(pos, 0, 1.5, 0), vector.offset(p:get_pos(), 0, 1.5, 0)) then
				local c = TAG[npcasso.mood_of(self.npc_id)] or "#FFFFFF"
				if c ~= self.tag_color then
					self.tag_color = c
					if not npcasso.speaking(self.npc_id) then self.object:set_properties({nametag_color = c}) end
				end
			end
		end
```

(They only change when the villager can see you, so the player never reads feelings off-screen.)

- [ ] **Step 7: Check in-world:** hit Elise with Nell and Wren nearby. Expect: Elise stumbles back, then stands watching (steady) or runs home (a timid villager would flee); Nell runs to Elise and stops about 3 nodes away; Pip runs toward Wren; Wren walks to you and stops, speaking a question; tags turn red/amber as they see you; no health loss; notices read "Elise will remember that." and "Word will spread."

---

### Task B4: Journal tabs (Quests, Character, People)

**Files:** `luanti/mods/npcasso/town.lua` (`show_journal`, `quests_fs`), `luanti/mods/npcasso/radar.lua`.

- [ ] **Step 1: `quests_fs(title, rows, footer, tabs)`:** `local fs = "formspec_version[6]size[14,11]" .. (tabs or "") .. BTN ..`.
- [ ] **Step 2: `show_journal(name, tab)`:**

```lua
local TABS = "tabheader[0,0;jtab;Quests,Character,People;%d;false;true]"

function npcasso.show_journal(name, tab)
	tab = tab or 1
	local tabs = TABS:format(tab)
	if tab == 2 then return npcasso.show_radar(name, tabs) end
	if tab == 3 then return npcasso.show_people(name, tabs) end
	-- tab 1: the current body, passing `tabs` as the fourth argument to quests_fs
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname == "npcasso:journal" and fields.jtab then
		npcasso.show_journal(player:get_player_name(), tonumber(fields.jtab))
		return true
	end
end)
```

- [ ] **Step 3: Radar inside the journal** (`radar.lua`). `npcasso.radar_formspec(dims, opts)`: `opts = opts or {}`; first line becomes `"formspec_version[6]size[14,11]bgcolor[#0d1016f0;true]" .. (opts.tabs or "")`; the header label shows `"Character profile" .. (opts.standing and ("   Standing: " .. opts.standing) or "")`; drop the Refresh button when `opts.tabs` is present (the tab strip refreshes). `show_radar(name, tabs)` passes `{tabs = tabs, standing = s.standing}` and shows the formspec as `npcasso:journal` when `tabs` is set, `npcasso:radar` otherwise (so `/npcasso stats` still works).
- [ ] **Step 4: People tab** (`radar.lua`, below `show_radar`):

```lua
local DOT = {angry = "#FF6B5E", afraid = "#E8E0A0", hurt = "#9FB4D8", cold = "#A8A8A8",
	guarded = "#FFC24A", warm = "#9AE07A", fond = "#7AE0A8", neutral = "#D0D0D0"}

function npcasso.show_people(name, tabs)
	npcasso.get(("/profile?world=%s&player=%s"):format(npcasso.world(), name), function(s)
		if not s then return core.chat_send_player(name, "Backend unreachable.") end
		local fs = {"formspec_version[6]size[14,11]bgcolor[#0d1016f0;true]", tabs,
			"label[0.5,0.7;", core.formspec_escape(core.colorize("#ffd479", "People you have met")), "]"}
		for i, m in ipairs(s.met) do
			local y = 1.3 + (i - 1) * 0.7
			table.insert(fs, ("box[0.5,%.2f;0.3,0.3;%s]"):format(y + 0.1, DOT[m.mood] or "#D0D0D0"))
			table.insert(fs, ("label[1.1,%.2f;%s]"):format(y + 0.25, core.formspec_escape(
				("%s, %s: %s"):format(m.name, m.role, m.mood))))
		end
		if #s.met == 0 then table.insert(fs, "label[0.5,1.5;Nobody yet.]") end
		core.show_formspec(name, "npcasso:journal", table.concat(fs))
	end)
end
```

The list is "the mood from your last meeting", never live; no cause text.
- [ ] **Step 5: Check in-world:** `/npcasso journal`, click each tab. Quests unchanged; Character shows the radar and the standing word; People lists only villagers you have spoken to, and after you hit Elise it still shows her old mood until you talk to her again.

---

### Task B5: Scene command, shunned trade, debug stance, talk window

**Files:** `luanti/mods/npcasso/init.lua`, `luanti/mods/npcasso/life.lua`.

- [ ] **Step 1: Trade says why** (`init.lua`, `show_trade` line ~566 area, and `quote`): send `game_time = npcasso.game_time()` in the `/trade` POST body. In `show_trade` where `q.reason` is turned into text, add `q.reason == "shunned" and "They will not trade with you right now."`. Read that block first and extend its existing reason table; do not add a second branch structure.
- [ ] **Step 2: `/npcasso scene hit|theft|gossip`.** Add to the chat command (and both usage strings):

```lua
		elseif cmd == "scene" then
			local near = each_npc(player:get_pos(), 12)
			if not near[1] then return false, "Stand within 12 nodes of a villager." end
			if arg == "gossip" then
				if not near[2] then return false, "Need two villagers close together." end
				npcasso.meet(near[1], near[2])
				return true, near[1].npc_id .. " and " .. near[2].npc_id .. " meet."
			end
			local victim, w = near[1], npcasso.witnesses(player:get_pos())
			if arg == "hit" then
				table.insert(w, victim.npc_id)
				npcasso.event(player, "hit_npc", victim.npc_id, {}, w, npcasso.ears(victim.object:get_pos(), w))
			elseif arg == "theft" then
				npcasso.event(player, "theft", victim.npc_id, {item = "default:apple"}, w)
			else
				return false, "Usage: /npcasso scene hit | theft | gossip (these are real events)"
			end
			return true, "Played " .. arg .. " on " .. victim.npc_id .. " (a real event, use a spare world)."
```

and in `life.lua` expose `npcasso.meet = start_meeting` after `start_meeting` is defined.

- [ ] **Step 3: Debug shows stance.** In the `debug` command's request add `&game_time=%.3f` (`npcasso.game_time()`), and after the trust line:

```lua
						if s.stance then
							table.insert(out, ("   feels: %s (%s), %s"):format(s.stance.mood, s.stance.strength,
								s.stance.cause or "no cause"))
						end
```

- [ ] **Step 4: Talk window.** Read `show_talk`. If it has no busy line, show `Name is thinking…` while `t.busy` is true (a label in the chat area under the last line). Set the `/talk` and `/greet` POST timeout to 24 s (`npcasso.post(path, body, cb, 24)`); on a timeout the existing "seems distracted" line stands.
- [ ] **Step 5: Check in-world:** `/npcasso scene hit` next to Elise plays the whole scene without needing to punch; `/npcasso scene gossip` shows two villagers meeting; trade with Elise right after reads the shunned line; `/npcasso debug` lists a "feels:" line per villager.

---

### Task B6: Playtest and close-out

- [ ] **Step 1: Rejoin the world** (no `--go`). Backend already restarted in A5.
- [ ] **Step 2: Ten-minute checklist** (what a script cannot judge):
  1. `/npcasso check` is OK for all four; walk to the orchard and the mine.
  2. Hit Elise with Nell near: the scene in B3 step 7.
  3. Talk to Elise: she is curt in her own voice. Apologise: she softens one notch and still names it. Trade: refused.
  4. Wait a day (or `/time`): trade reopens, she is guarded, offers no errand.
  5. Talk to Mira before and after Elise reaches her: Mira greets as a stranger, then knows by told rumour with Elise credited.
  6. Journal: Character radar dips (compassion), standing reads Watched; People still shows Elise's last mood until you speak again.
  7. Anything awkward in how the rescuers walk (stuck in doorways, standing too far): note it; stop distance is `MEET_RANGE`, timeout `RESCUE_SECONDS`.
- [ ] **Step 3:** full suite `.venv\Scripts\python -m pytest -q`; update the spec's section 2 to say rescuers do not shun (decision 3) and mark scope items 0, 2, 3, 4, 5, 6, 7 done; commit nothing.

## Self-review against the spec

- 0 Reachability: A6 (data) and B1 (emerge, verify, retry).
- 2 Human reactions: A1, A2, A3, B2, B3. The victim "shaken for about a day" is stance heat above 0.3 (A2) plus mood behaviour (B2).
- 3 Rumours: plan 1 Task 7 plus the cry memory (A1); rescuers learn through the existing meeting/gossip loop when they reach the victim.
- 4 Journal: A4, B4. 6 Name tags: B3 step 6. 5 Fallbacks: plan 1.
- 8 Knowledge: A1 (heard-only packet test), A4 and B3 step 6 (nothing off-screen is shown).
- 9 Latency: A5 and B5 step 4. Debug view: A5 and B5 step 3. Canon and injection tests: plan 3.

## Open risks

- Pathing in houses: rescuers can wedge in doorways; the 8 s deadline ends the errand and `walk` already skips blocked waypoints.
- `emerge_area` on a slow disk can take several seconds on first join; sites build as they finish and the join-retry covers the rest.
- The classifier skip will miss an insult phrased as a short question that avoids every word in `PLAIN_BLOCK`; accepted for the 3 s it saves, and the blocklist is one tuple to grow.
