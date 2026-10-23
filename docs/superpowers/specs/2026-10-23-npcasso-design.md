# NPCasso — Design

*An open world. No background characters.*

Date: 2026-10-23 · Event: Mubit "Night Shift" hackathon, London · Track: **Fast refresh** · Code freeze: Sun 25 Oct 10:00

## 1. Intent

NPCasso is a small, Minecraft-like, single-player village where NPCs remember what the player does, hold relationships, do real jobs whose terms change with trust, and talk about the player behind their back.

It exists to demonstrate Mubit's loop on a workload that keeps changing: the world keeps producing new events, new NPCs and spreading reputation, every NPC reaction and conversation flows through Mubit as recurring tasks, and Mubit's task adapters keep pace with that changing data.

The judging criteria (equally weighted): **use of Mubit** (show a correction turning into a model update live), usefulness, technical execution, live demo within the time limit.

### Core principle

**The LLM proposes and voices; the game verifies and decides.** Authoritative facts (what was stolen, who witnessed it, whether a promise was kept, trust values, prices) are set by deterministic game logic. The LLM interprets free text into structured intents, writes NPC speech and first-person memories, and proposes quests, but every proposal is validated by game logic before it has any effect.

### Look and feel

**Stardew Valley vibe, Minecraft-like blocks.** A cosy, warm little village where relationships are the point.

- **Engine/game:** Luanti running **[Asuna](https://content.luanti.org/packages/EmptyStar/asuna/)**, a Minetest Game fork that provides `default` and keeps Minetest Game mod compatibility, with 60+ biomes and Animalia animals. Fallback if Asuna fails on current Luanti within a 30-minute timebox: Minetest Game plus a texture pack. Mineclonia was rejected because of its larger, less documented API.
- **Village:** built by hand once, saved as a schematic, and placed at a fixed spot in every new world, so all worlds (including both demo worlds) are identical. It sits in a meadow with flowers, a small farm plot and warm lighting.
- **Landmarks** (also gameplay hooks):
  - Elise's fruit stall: apple crate/chest, fences, awning, sign. Taking from the crate = theft.
  - Rowan's forge: anvil, furnace, stone walls, fire. Digging the anvil = vandalism; placing it back = repair.
  - Mira's inn: beds, tables, benches, barrels, sign. Renting a bed; the rumour corner.
- **Anvil, barrels, benches** come from the [cottages](https://content.luanti.org/packages/Sokomine/cottages/) mod; if it gives trouble, `npcasso` defines its own `npcasso:anvil`.
- **Hidden relationships:** nametags show only name and role (`Elise · Merchant`). Trust, suspicion and mood are never shown as numbers, hearts or labels. The player reads them from behaviour: tone, prices, refusals, gossip. The only explicit cue is the "Elise will remember that." notice, which says something stuck but not how much (Hollow Knight-style ambiguity).
- **Debug view for the demo:** a chat command (e.g. `/npcasso debug`) toggles an overlay with trust values and recent memories, for judges and testing only. *(Builder's call.)*
- **Gift preferences** per NPC in config (loved / liked / disliked). The game sets the trust change; the LLM voices the reaction.

## 2. Goals

1. Playable Luanti village with three NPCs, each with a role, personality and motivation:
   - **Elise — Merchant.** Friendly but cautious, values honesty. Trades apples for items.
   - **Rowan — Blacksmith.** Blunt, proud of his craft, respects reliability. Crafts/repairs tools, gives small quests.
   - **Mira — Innkeeper.** Sociable, observant. Rents a bed, spreads and shares rumours.
   NPC definitions live in a config file; adding an NPC requires no code change.
2. Gameplay actions recorded as structured events whether or not an LLM is called.
3. Witness logic: NPCs only know what they saw or were told.
4. Persistent memories, trust/suspicion, promises and quests, surviving restart.
5. Free-text dialogue with intent classification (threat, apology, insult, promise, question, trade, correction, other).
6. Role behaviour that adapts deterministically to trust (prices, refusal of service).
7. Gossip: witnessed events propagate to other NPCs as second-hand, lower-reliability memories.
8. Validator that checks NPC replies against the event log, retries on failure, and logs every catch.
9. All LLM calls routed through Mubit, organised into three stable recurring tasks.
10. Offline mock mode: game and tests run without network.
11. Evaluation harness with held-out scenarios, scored by the validator.
12. Demo:
    - **Two worlds side by side**, same NPCs, different player histories (A: honest and helpful; B: thief and vandal). The same question to Elise gets visibly different answers, prices and treatment. This shows memory and adaptation.
    - **Mubit console**: tasks filling, a caught lie rated Bad, adapter versions v1 and v2 with test results, and a Try-models comparison. This shows the model-update loop (the game itself can't call an adapter).
    - Add a new NPC live and show its calls landing in the same tasks.

## 3. Non-goals

- Multiplayer, procedural world, combat AI, large quest trees.
- Visual polish beyond readable nametags, HUD notices and a dialogue window.
- Using a Mubit adapter inside the game loop (no documented route; see §8).
- NPC pathfinding/routines/schedules and seasons. NPCs stand at their posts and turn to face the player.

## 4. Anti-goals (failure even if it "works")

- An NPC accuses the player of something it did not witness or hear about.
- The LLM changes authoritative state (trust, inventory, event facts) directly.
- Claiming an adapter improved behaviour without Mubit's test result or our eval evidence.
- Fabricated Mubit API calls or capabilities.
- Per-call varying text in system prompts, which splits Mubit tasks.
- A demo that only works online with no fallback.

## 5. Constraints

- Hackathon rule: all project code written during the event; every LLM call goes through Mubit.
- Windows 11 dev machine, Python 3.13.5 installed, Luanti **not yet installed**, repo empty apart from README.
- Mubit daily limits: daily training limit (resets 00:00 UTC), pause between trainings, 3 adapter starts per org per UTC day, daily Try-models call cap. London is UTC+1 until Sun 02:00, so the reset is 01:00 local Saturday and Sunday.
- First adapter training happens at 25 kept examples per task.
- No credentials in Lua or git. `.env` holds `MUBIT_API_KEY` (starts `mbt_`), `MUBIT_BASE_URL`, `LLM_MODEL`, `LLM_PROVIDER=mock|local|mubit`. `local` is any OpenAI-compatible local server (e.g. Ollama) via the same `openai` client with a different `base_url`; it is for development only, since the hackathon requires project LLM calls to go through Mubit.
- The game is built against mock/local. In parallel, once the Mubit key arrives, one final model is chosen and the backend scenario runner feeds Mubit in the background so training isn't left until the end. The final model never changes after that, because Mubit groups tasks by model.

## 6. Architecture

```
Luanti (Lua mod "npcasso")  --HTTP JSON-->  FastAPI backend  --OpenAI SDK, base_url=Mubit-->  Mubit --> provider model
   world, NPC entities,                       rules engine, SQLite,
   witness checks, HUD,                       memory retrieval, validator,
   dialogue formspec                          LLM client (mock | mubit)
```

- **Luanti mod** uses `core.request_http_api()` (requires `secure.http_mods = npcasso` in `minetest.conf`). It detects actions, computes witnesses (distance + `core.line_of_sight` + facing angle), posts events, shows the dialogue formspec, nametags and HUD notices. No secrets, no LLM logic.
- **Backend** (FastAPI + SQLite, stdlib `sqlite3`) owns all state and rules.
- **LLM client**: the official `openai` Python SDK with `base_url` pointed at Mubit (`https://api.mubit.ai/openai/v1`, `Authorization: Bearer mbt_...`). A mock client returns deterministic replies.

### Data (SQLite)

- `npcs`: id, name, role, persona, background, config JSON.
- `relationships`: npc_id, player_id, trust (−100..100), flags (e.g. `refuses_service`).
- `events`: id, game_time, ts, actor, target, type, details JSON, witnesses JSON, verified (bool), source (`game` | `llm_classified`), confidence.
- `memories`: id, npc_id, event_id, text, how (`witnessed` | `told_by:<npc>`), reliability, ts.
- `promises` / `quests`: id, npc_id, player_id, item, count, deadline_game_time, status (`open` | `kept` | `broken` | `done` | `failed`).
- `interactions`: id, task, npc_id, thread_id, request JSON, reply, mubit_request_id, latency_ms, tokens, validator_result JSON, retried (bool), outcome.

### Event types

Game-detected (verified): `theft`, `gift`, `trade`, `vandalism` (digging an NPC's work block), `repair` (placing it back), `hit_npc`, `promise_kept`, `promise_broken`, `quest_done`, `quest_failed`, `told` (gossip transfer).
LLM-classified (unverified, with confidence): `threat`, `apology`, `insult`, `promise`, `correction`.

### Trust rules (deterministic, tunable in config)

Each event type maps to a trust delta per NPC, scaled by how the NPC knows: witnessed = full, told = half. Apology and kept promises recover trust gradually, capped per game day. Role terms derive from trust bands, e.g. Elise's apple price 1/2/3 iron or refusal; Rowan refuses service while his anvil is missing.

### Memory retrieval

For each request: the NPC's memories scored by (involves this player) + recency + event severity, top 5. No embeddings.

### Gossip

When an NPC with a witnessed memory and another NPC are both within range (or on a timer), the second NPC gains a `told_by` memory with lower reliability. NPCs speak of told memories as rumours.

## 7. Recurring LLM tasks (Mubit)

Each task has one **fixed system prompt** (never contains NPC names or per-call data). Everything variable goes in the user message as a structured block: NPC persona, role, trust band, top memories with `how`/reliability, relevant facts, the player's message. Every call sets `metadata.thread_id` to the conversation id and stores the returned `x-middleware-request-id`.

| Task | Trigger | Output |
|---|---|---|
| `npc_react` | A significant witnessed event | JSON: `{"shout": str, "memory": str, "claims": [...]}`, shown as a speech line plus HUD notice "Elise will remember that." |
| `intent_classify` | Every player chat message, **before** dialogue | JSON: `{"intent": ..., "confidence": 0-1, "promise": {...}?, "claim": str?}` |
| `npc_dialogue` | Every player chat message, after classify (so the reply can react to an apology/promise/correction in the same turn) | JSON: `{"reply": str, "claims": [...], "quest_offer": {...}?}` |

Output formats are frozen before the first real Mubit call, because output format is part of Mubit's task fingerprint and changing it splits tasks. *(Builder's call.)*

### Validator (on `npc_dialogue` and `npc_react`)

The model must list every past event it refers to in `claims`: `[{"event_id": str|null, "type": str, "how": "witnessed"|"told"}]`. Each event in the context block carries its id. The validator checks deterministically against the event log:
- A claim with no matching event id, or a type that doesn't match → fail (invented event).
- `how: witnessed` when the NPC's memory is `told_by` or absent → fail (stating rumour as fact / unknown knowledge).
- A light keyword check on `reply` for item/event words with no supporting claim → flag.
- Tone clearly contradicting the trust band (warm when hostile) → flag.
- Quest offer referencing an unknown item → reject the offer.

On fail: retry once with the failure appended to the user message; log both attempts with their `mreq_` ids. If the retry also fails, return a safe neutral line. Failed drafts are **stored** in Mubit (not suppressed), so they can be rated Bad in the console during the demo; revisit once Mubit answers open question 1. *(Builder's call.)*

### Player corrections

A confirmed correction (the classifier's `claim` contradicts the event log in the player's favour) marks the NPC's offending memory `retracted`, recovers a small amount of trust, logs a strong signal against the `mreq_` id, and on the next turn the NPC acknowledges the mistake. Retracted memories are not gossiped further; NPCs already told keep theirs (rumours don't un-spread). *(Builder's call.)*

## 8. Mubit: verified facts and open questions

Verified from docs.mubit.ai (2026-10-23):
- Proxy: change base URL, keep provider SDK and model ids. Keys start `mbt_`.
- Tasks group automatically by instructions + tools + output format + model. Numbers, dates and ids don't split a task; other varying words do.
- Sessions come from `metadata.thread_id` (then `session_id`, `conversation_id`); used to hold out test cases.
- Training is automatic at 25 kept examples. Adapters are scored against the provider model's answers: Passed / Below target (match %) / Malformed tool calls / Prompt only / Not tested.
- `x-middleware-record: full|metadata|off` and `x-middleware-store: false` reduce what is kept.
- Feedback: only the console's "Rate this reply" Good/Bad. No API.
- Using an adapter: only via console **Try models**. No adapter model id for app calls.

Open questions for Mubit office hours:
1. Do Bad-rated calls get excluded from training, or weighted?
2. Is there any feedback API or a route to call a passing adapter from code?
3. How is match % computed for free text vs JSON?
4. Which models on the starter credit are adapter-eligible?

Implication: Mubit makes an adapter a cheaper copy of the frontier model on a task; it does not judge truth. NPCasso supplies the truth check (validator + eval harness) and keeps the kept examples as clean as possible.

## 9. Feedback signals

- **Strong:** validator catch (claim contradicts event log); player correction confirmed by event log; malformed JSON; failed deterministic requirement.
- **Weak (logged only, never auto-labelled):** player walks away mid-dialogue, conversation ends early, player doesn't return to the NPC.

Pipeline: events → state updates → dialogue + validation → correction log keyed by `mreq_` id → (manual) console ratings → Mubit training/testing → our eval comparison.

## 10. Evaluation

`eval/scenarios.json` with ordinary and edge cases, split into train (run freely, also feeds Mubit's 25 examples) and held-out:
witnessed theft recalled; unwitnessed theft unknown; gift remembered; apology acknowledged; no invented events; persona maintained; tone matches trust; rumour treated as rumour, not fact; promise tracked; correction verified.

`eval/run.py` seeds a fresh DB per scenario, runs through the configured provider, scores with the validator plus per-scenario expectations, and reports pass rate, latency and tokens per task. Baseline = frontier via Mubit. Adapter comparison = held-out user messages pasted into Try models, results recorded manually in `docs/eval-report.md`. Report actual numbers, including no improvement.

## 11. Build order

Mubit training is the critical path: the daily training limit and the pause between trainings mean an adapter can't be trained inside a demo slot, so tasks must reach 25 kept examples early. The backend and Mubit wiring therefore come before most of the game. *(Builder's call.)*

1. **Backend first, on mock:** prompts and output formats frozen, three tasks, validator with `claims`, scenario runner driving the backend directly (no game needed). As soon as the Mubit key arrives, switch the runner to Mubit with the final model and leave it feeding examples in the background, aiming for 25 per task before the Saturday 01:00 local reset. `mreq_` ids are stored.
2. **Vertical slice:** Luanti + mod, Elise, dialogue formspec → backend → reply → interaction persisted.
3. **Events and memory:** theft with witness check, trust, HUD notice, survives restart.
4. **Classify effects:** promises, corrections, retry, correction log.
5. **Roles + quests + gossip:** Rowan, Mira, trust-driven trade terms. Their traffic and a Sunday-reset training give adapter v2 (the Fast Refresh story).
6. **Eval + demo:** harness results, console screenshots, live add-an-NPC moment. Adding an NPC is a config edit plus mod reload (restart acceptable). If the network fails on stage, run in mock mode and show pre-captured console screenshots.

## 12. Left to the builder

- Exact trust deltas, bands, gossip range and timing.
- Formspec layout, nametag format, HUD styling.
- Village layout (hand-built map or a small schematic).
- Prompt wording within the fixed-system-prompt rule.
- Mock reply content.
