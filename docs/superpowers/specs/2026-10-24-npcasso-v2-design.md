# NPCasso v2 — Town, quests, XP, monsters, livelier NPCs

Date: 2026-10-24 · Builds on `2026-10-23-npcasso-design.md` (all its principles still bind: **the LLM proposes and voices; the game verifies and decides**; relationships hidden; memories per save).

## Intent

Make the village feel like a Minecraft-style game world with something to do: more people, a town hall, quests with rewards, progression (XP/levels), and danger outside the walls at night. Interactions should feel fluid: villagers start conversations when you come close, and game messages appear in a Minecraft-like feed at the bottom-left, not raw chat.

For Mubit: new NPCs reuse the same three tasks (`npc_react`, `intent_classify`, `npc_dialogue`) — the Fast Refresh story of a world that keeps growing without new tasks. Output schemas stay frozen (quest offers already exist in `npc_dialogue`).

## Goals

1. **Town hall** on the square (built by the village builder): a stone/wood hall with a **quest board** node inside. Right-click the board → a window listing every villager's open quests (who, what, reward, progress), Minecraft-UI style.
2. **A real village: 12 villagers**, each with a small house built by the village builder around the square. New NPCs in `npcs.json`, each with role, persona, likes, trade (or none), expertise, `home` post, `chattiness` (0..1):
   - **Tobin — Farmer** (near the farm): wheat/bread/animal quests; trades bread for wheat.
   - **Wren — Guard** (town hall): monster quests; learns about every crime (any witnessed crime is told to Wren on the next tick, before other gossip).
   - **Pip — Kid**: errands; the village's fastest gossip (chattiness 1.0).
   - **Bram — Elder** (town hall): hosts the Harvest Festival; values tradition and fairness.
   - **Nell — Baker**: trades bread; warm, nosy (chattiness 0.8).
   - **Corin — Fisher** (pond): quiet, superstitious (0.3).
   - **Hazel — Herbalist**: gentle, knows plants and healing (0.5).
   - **Dax — Miner**: rough, distrusts newcomers; trades coal (0.4).
   - **Lottie — Shepherd**: cheerful, loves animals; wool quests (0.7).
   Existing: Elise (0.5), Rowan (0.3), Mira (0.9), Tobin (0.5), Wren (0.6, hears crimes first).
9. **Villagers roam and gossip face to face**
   - **Roaming**: during the day each villager walks between village places (square, inn, farm, town hall, market, pond, other villagers' houses) using `core.find_path`, rests a few seconds at each, returns home at dusk and stays near home at night. Talking to the player, reacting to an event, or gossiping pauses roaming. If a path fails or takes too long they walk back home.
   - **Gossip only on meetings**: when two roaming villagers come within 3 nodes (pair cooldown 60 s) they stop and face each other; the game asks the backend whether the first has news for the second (per online player). If so the teller's bubble shows the rumour ("Psst... the newcomer took apples from Elise's stall."), the listener's shows a reaction ("Really?!"), and the listener gains a `told_by:<teller>` memory. The teller shares with probability = their chattiness.
   - Rules (backend): teller must have known the memory >= 0.1 game-day; reliability halves per retelling; trust effect scales with reliability; crimes are always shared with Wren.
3. **Quests**
   - **Starter quests** per NPC defined in `npcs.json` (`quests`: id, title, kind `bring`|`slay`, item or mob, count, reward items, xp, trust). Each player can take each starter quest once. Examples: Tobin "Bring 10 wheat", Wren "Slay 3 monsters", Rowan "Bring 5 iron ingots", Elise "Find 3 apples", Mira "Bring 3 flowers", Pip "Bring 1 bread".
   - **LLM quests** offered in dialogue (existing `quest_offer`) become journal entries too (kind `bring`, xp default 20).
   - Taking a quest: from the quest board (Accept button) or by asking the NPC (talk window "Quests" button lists that NPC's offers).
   - Progress: `bring` completes by handing the items to the quest giver (existing gift flow, or a "Hand in" button that takes the needed count from inventory). `slay` counts monster kills reported by the game.
   - Completion: reward items, XP, trust delta (`quest_done`), notice "Quest complete: <title>".
   - **Journal**: book item `npcasso:journal` in the starter kit + `/npcasso journal`: active quests with progress, completed quests.
4. **XP and levels** (deterministic, backend-owned, per player per save):
   - XP sources: quest reward xp, monster kill 5, trade 2, harvest wheat 1 (per harvest event, capped 20/game-day), promise kept 10.
   - Level thresholds: level n needs `50 * n * (n+1) / 2` total XP (50, 150, 300, …).
   - HUD: top-left "Lv 2 · 40/100 XP" bar; on level up a centered "Level up! Lv 3" notice + sound.
   - Levels gate trades: each trade offer may have `min_level`; below it the trade window shows "Come back when you're more experienced (Lv 2)". Rowan's steel pickaxe needs Lv 2.
   - Titles: villagers are told the player's title in context (`newcomer` Lv1, `villager` Lv2–3, `friend of the village` Lv4+). The LLM uses it to address the player; trust stays hidden.
5. **Monsters**: install `mobs` (Mobs Redo API) and `mobs_monster` from ContentDB into the Luanti mods folder and enable them. Monsters spawn per those mods (night/dark). **Safe zone**: any monster within 32 nodes of the village square is removed (globalstep check every 2 s). Killing a monster (any `mobs_monster:*` entity dying from player damage) posts a `slay` event (no LLM call) → XP + slay quest progress. Animals stay from Asuna.
6. **Interactivity**
   - **Auto-talk**: when the player stands within 2.5 nodes of a villager, roughly facing them, for 1 s, the talk window opens. 60 s cooldown per NPC after closing; never while another formspec is open. Can be turned off with setting `npcasso.auto_talk = false`.
   - **Feed**: a HUD message log at the bottom-left (last 6 lines, each fades after 8 s): NPC lines (`Elise: …`), notices, quest updates, XP gains, level ups. Replaces raw chat for game messages (chat still gets NPC lines for history).

7. **Crafting table**: node `npcasso:crafting_table` (Minecraft-style). Right-click opens a 3x3 crafting window bound to the player's own `craft` list and `craftpreview`, plus their inventory. Placed by the village builder in the town hall and at Rowan's forge; also craftable (4 wood planks in a square, no recipe conflict check needed beyond the engine's).
8. **End goal: the Harvest Festival vote**
   - Each villager has one **main quest** (`main: true` in their starter quests). The festival unlocks when the player has completed every villager's main quest **and** reached **Lv 4**. A notice and feed message announce it; the quest board shows "The Harvest Festival" with an "Begin the festival" button (town hall).
   - **The vote is decided by the game**: each villager votes *for* if their trust in the player is ≥ 30 (friendly), *abstains* if -10..29, *against* if < -10. Votes use the same hidden trust everything else uses, so every remembered theft, gift, promise and apology counts.
   - **Endings** (deterministic): **Hero of the village** (≥ 2/3 for and none against), **Accepted** (more for than against), **Turned away** (otherwise).
   - **Presentation**: a festival window shows each villager in turn with their vote and a one-line speech. Speeches use the existing `npc_dialogue` task (facts.situation = "the village festival vote; you vote <for/against/abstain>; explain why in one or two sentences, citing what you remember"), validated like any reply; on failure a template line is used. Then the ending screen. The result is recorded as an event and remembered (villagers refer to it afterwards).
   - The festival can be held once per save. (`/npcasso debug` can show vote predictions for testing.)

10. **LLM only for the villager who speaks** *(user request)*. State (memories, trust, moods) updates for every
    villager deterministically, so every later dialogue and reaction reflects everything; only spoken lines cost LLM calls.
    - Event with several witnesses: one `npc_react` call, for the primary witness (the target if they witnessed it, else
      the nearest witness). Other witnesses get a free reaction: turn, a "!" bubble, or a template line.
    - Gossip lines are templates (no LLM). Greetings and talk are already one NPC.
    - Festival: LLM speeches only for Bram (opening and closing lines) and the strongest opinions (up to 2 highest-trust
      "for" and 2 lowest-trust "against"); every other villager shows their vote with a template line.
11. **Motives drive movement** *(user request)*. `GET /moods?world&player` returns `{npc_id: mood}`, for behaviour only
    (never shown to the player):
    - `afraid`: hit or threatened by the player within the last 0.5 game-day
    - `hostile`: band hostile
    - `wary`: band wary
    - `friendly`: band friendly
    - `neutral`: otherwise

    Lua behaviour:
    - afraid: back away to keep about 8 nodes from the player, occasional "Stay away!" bubble
    - hostile: turn away and avoid coming within 4 nodes; no auto-talk
    - wary: stop and watch the player when within 6
    - friendly: occasionally (5 min cooldown) walk to the player and greet
    - neutral: roam

    After witnessing a crime, a villager walks to Wren (if Wren exists and is loaded) before resuming. The meeting
    triggers normal gossip, so news reaches the guard by an actual visit. Moods refresh on every tick and after each
    event response.

## Non-goals

- Combat AI changes, custom monster models, boss fights, branching quest trees beyond the main-quests-to-festival line, a quest editor, multiplayer balancing, monster drops economy, NPC routines/schedules.

## Anti-goals

- XP, levels, quest completion or rewards decided by the LLM.
- Monsters inside the village.
- Auto-talk that traps the player (reopens immediately, opens while running past).
- Quests that can't be completed with what the world provides.

## Constraints

- Keep three LLM tasks and their output schemas unchanged.
- No new Python dependencies. New Luanti content only from ContentDB (`mobs`, `mobs_monster`).
- Starter quest items must exist in Asuna: `farming:wheat`, `default:steel_ingot`, `default:apple`, `flowers:*`, `farming:bread`.
- Village builder must still fit: town hall goes south-east of the square (x 6..14, z -14..-6); Tobin at the farm, Wren in the hall, Pip on the square.

## Data (additions)

- `players` table: player, xp, harvest_day, harvest_count.
- `promises` gains `title`, `xp`, `trust`, `quest_id`, `kind` (`bring`|`slay` for quests; `promise` unchanged), `target` (mob prefix for slay).
- New event types (game, verified): `slay` (details.mob), `harvest` (details.item), `quest_done` already exists.

## API (additions)

- `GET /player?world&player` → `{xp, level, title, next_level_xp, quests: {active, done}}`.
- `GET /quests?world&player` → all NPCs' available starter quests + active quests with progress.
- `POST /quest/accept {world, player, quest_id}` → journal entry.
- `POST /quest/handin {world, player, npc_id, items: {itemstring: count}}` → completes bring quests the inventory can cover; returns items consumed, rewards, notices.
- Event responses gain `xp_gained`, `level_up` (new level or null).

## Decisions (builder's calls, from the review)

- **LLM quest offers** go straight into the journal when offered (as today); talking to the NPC *is* accepting. The talk window's "Quests" button and the board list the NPC's starter quests, which need Accept.
- **No deadlines on quests.** Starter, slay and LLM quests never expire or fail (no trust penalty for a forgotten quest). Only spoken *promises* keep deadlines and can be broken.
- **Gossip spreads only when villagers meet** (goal 9); the periodic tick no longer spreads anything. *(User request: rumours spread like real life.)* The paragraph below is superseded.
- ~~Realistic gossip (replaces v1's "one memory to everyone per tick")~~: rumours spread **one person at a time**. Each gossip step moves one memory from one NPC who knows it to one NPC who doesn't. A memory can only be retold once the teller has known it for ≥ 0.1 game-day (~2 real minutes at default day length). Reliability halves per retelling (witness 1.0 → told 0.5 → told-of-told 0.25 …) and the trust effect scales with reliability. Spreading the whole village takes many minutes, not one tick. *(User request: gossip was too fast.)*
- **Wren** is the preferred listener for crimes (theft, vandalism, hit): when a crime memory is retold, Wren hears it before anyone else, but still through gossip timing, not instantly. **Pip** adds one extra gossip step per tick.
- **Levels**: start at Lv 1 with 0 XP; reaching Lv n+1 needs `50 * n * (n+1) / 2` total XP → Lv 2 at 50, Lv 3 at 150, Lv 4 at 300. HUD shows progress within the current level (e.g. "Lv 2 · 40/100").
- **Monsters**: Asuna ships no `mobs` mod (only Animalia/Creatura), so `mobs` + `mobs_monster` don't clash by name. Kills are detected by wrapping `on_death` of every registered `mobs_monster:*` entity after mods load, when the killer is a player. If the mods fail to load on Luanti 5.17 within a 30-minute timebox, fall back to counting kills of hostile Animalia mobs (wolf, grizzly bear) and drop night monsters.

## Left to the builder

Exact XP numbers beyond those listed, HUD styling, town hall look, quest rewards per quest, monster removal radius tuning, auto-talk facing angle.
