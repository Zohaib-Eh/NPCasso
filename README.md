# NPCasso

*An open world. No background characters.*

NPCasso is a single-player village game for Luanti (the Asuna game plus the `npcasso` mod). You arrive at Bellwether, a village that is short of food, fuel and patience, with winter closing in. Twelve villagers live there. They remember what you do, judge you for it, talk about you when you are not in the room, and answer with moods, prices, refusals, screams and rumours. Ten days after you arrive the cold cannot be survived, and what you did until then decides how it ends.

Mubit sits in front of the model and learns the three speaking jobs. The village itself stays in the game.

## Contents

**[Part 1: Technical](#part-1-technical)**: how to set it up and run it

1. [Setup](#setup-windows-powershell): requirements, dependencies, model provider, backend, Luanti, mods, schematics, world, troubleshooting
2. [Playing](#playing) and [commands](#commands-npcasso-command-server-privilege)
3. [Mubit](#mubit): what it does, what we send, what the game keeps, the validator, feeding it
4. [Tools, tests and evaluation](#tools-tests-and-evaluation)
5. [Project layout](#project-layout)

**[Part 2: The game](#part-2-the-game)**: the idea, the lore, the people and the endings

1. [The idea](#the-idea)
2. [The lore](#the-lore)
3. [How a run goes](#how-a-run-goes)
4. [The five endings](#the-five-endings)
5. [The twelve hidden traits](#the-twelve-hidden-traits)
6. [The villagers](#the-villagers)
7. [How the village thinks](#how-the-village-thinks): memory, witnesses, rumours, moods, trust, troubles
8. [Quests, XP, trade and the Harvest Festival](#quests-xp-trade-and-the-harvest-festival)
9. [The world, the winter and the sound](#the-world-the-winter-and-the-sound)
10. [Designed but not built yet](#designed-but-not-built-yet)

---

# Part 1: Technical

## Setup (Windows, PowerShell)

NPCasso has two programs that talk over HTTP on your machine: a **Python backend** (all the rules, memory and model calls) and **Luanti** with the `npcasso` mod (what you see and hear). Set up both, then start the backend before the game.

### What you need

| Need | Version used | Why | Where from |
|---|---|---|---|
| Windows with PowerShell | Windows 10/11 | The commands below are PowerShell. | |
| Python | 3.13 (the project's `.venv` runs 3.13.5) | The backend, tests and tools. | https://www.python.org/downloads/ |
| Git | any | To clone the repo. | https://git-scm.com/ |
| Luanti | 5.17.0 (Windows, LuaJIT 2.1) | The game engine. | https://www.luanti.org/downloads/ |
| Asuna (game) | latest | The game NPCasso runs on (Minetest Game based, with biomes, Animalia animals, farming, skinsdb and more). | In Luanti: **Content** tab, search `Asuna` (EmptyStar) |
| `cottages` (mod) | latest | Anvil and furniture. Rowan's anvil and the cottage blocks come from it. | **Content** tab, `cottages` (Sokomine) |
| `mobs` and `mobs_monster` (mods) | latest (Mobs Redo and Mobs Monster by TenPlus1) | Night monsters outside the village. Wren's slay quest needs them. | **Content** tab |
| `mg_villages` schematics | any | The hand-built houses. See step 4. | https://github.com/Sokomine/mg_villages (`schems` folder) |
| A model provider | | The villagers' voices. `mock` needs nothing. | See step 2 |
| ffmpeg with libvorbis | optional | Only to regenerate the sounds. The `.ogg` files are already in the repo. | https://ffmpeg.org/ |
| An internet connection | | Only for the `mubit`, `claude` or ContentDB downloads. | |

`mobs`, `mobs_monster` and the schematics are optional in the sense that the game starts without them (the mod lists `mobs`, `mobs_monster`, `cottages` and others as `optional_depends`). Without the schematics the village falls back to a plainer hand-laid layout, and without the mobs there are no monsters, so Wren's quest cannot finish.

### 1. Get the code and the Python environment

```powershell
git clone <repo-url> C:\Users\zohai\Projects\NPCasso
cd C:\Users\zohai\Projects\NPCasso
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

`requirements.txt` holds these packages (all unpinned):

| Package | Used for |
|---|---|
| `fastapi` | The backend's HTTP routes (`backend/app.py`). Brings in `pydantic` and `starlette`. |
| `uvicorn` | Runs the FastAPI app. |
| `openai` | The one client every provider uses (OpenAI-compatible endpoints for `local`, `mubit` and `claude`). |
| `python-dotenv` | Loads `.env` when the backend starts. |
| `httpx` | The test client for FastAPI. |
| `pytest` | The test suite. |

The standard library covers everything else (`sqlite3` for state, `threading`, `json`, `re`, `wave`, and so on).

The helper tools need one extra package that is not in `requirements.txt`:

```powershell
.venv\Scripts\pip install lupa      # tools\luacheck.py and tools\lua_smoke.py (a LuaJIT runtime inside Python)
```

Check the install:

```powershell
.venv\Scripts\python -m pytest -q    # expect: 214 passed, 23 skipped
```

### 2. Choose a model provider

```powershell
Copy-Item .env.example .env
```

Edit `.env` (it is git-ignored, so your keys stay local). The backend reads it on start.

```
LLM_PROVIDER=mock          # mock | local | mubit | claude
LLM_MODEL=qwen2.5:7b       # used by local, and by claude if you want a model other than the default
LOCAL_BASE_URL=http://localhost:11434/v1
MUBIT_BASE_URL=https://api.mubit.ai/openai/v1
MUBIT_API_KEY=mbt_your_key_here
MUBIT_MODEL=gpt-6-luna
ANTHROPIC_BASE_URL=https://api.anthropic.com/v1/
ANTHROPIC_API_KEY=sk-ant-your_key_here
NPCASSO_DB=npcasso.db
```

| Provider | Use | Settings |
|---|---|---|
| `mock` | Offline and deterministic. Used by the tests. Villagers answer with simple scripted lines, so use it to check that the game runs. | none |
| `local` | Any OpenAI-compatible local server, e.g. Ollama (`ollama pull qwen2.5:7b`, then keep it running). For development. | `LLM_MODEL=qwen2.5:7b`, `LOCAL_BASE_URL=http://localhost:11434/v1` |
| `mubit` | The proxy that records and trains. Demo traffic goes here. | `MUBIT_API_KEY=mbt_...` from the Mubit console, `MUBIT_MODEL=gpt-6-luna` (keep it fixed, because Mubit groups tasks by model) |
| `claude` | Anthropic directly. | `ANTHROPIC_API_KEY=sk-ant-...` from https://console.anthropic.com/ (a Claude Code login is not this key). Default model `claude-haiku-4-5`. |

State (memories, trust, promises, quests, the story clock, every logged model call) lives in one SQLite file, `NPCASSO_DB=npcasso.db`, in the repo folder. Delete the file to reset every world.

### 3. Start the backend

```powershell
.venv\Scripts\python -m uvicorn backend.app:main --factory --port 8000
```

Open `http://127.0.0.1:8000/health`. You should see `{"ok":true,"provider":"..."}` with the provider you chose. Keep this window open while you play. Python changes need a backend restart (stop the listener on port 8000 first).

### 4. Install Luanti, the game and the mods

1. Install Luanti and start it once so it creates its folder (`C:\Users\zohai\Luanti` in this setup, holding `bin`, `games`, `mods`, `worlds`, `minetest.conf`).
2. In the **Content** tab, install **Asuna** (it is a game, so it lands in `games\asuna`), then the mods **cottages**, **mobs** and **mobs_monster** (they land in `mods\`). Asuna already includes Animalia, farming, flowers, skinsdb and sfinv_buttons.
3. Link the mod folder so Luanti loads NPCasso straight from the repo (a junction, so edits take effect on the next rejoin):

   ```powershell
   New-Item -ItemType Junction -Path C:\Users\zohai\Luanti\mods\npcasso -Target C:\Users\zohai\Projects\NPCasso\luanti\mods\npcasso
   ```

   Copying the folder works too, but you would then re-copy after every change.

### 5. Add the building schematics

The village houses are the hand-built schematics from Sokomine's `mg_villages` (GPL-3.0). They are not stored in git. Copy them in once:

```powershell
git clone https://github.com/Sokomine/mg_villages C:\Temp\mg_villages
New-Item -ItemType Directory -Force luanti\mods\npcasso\schems_mgv | Out-Null
Copy-Item C:\Temp\mg_villages\schems\* luanti\mods\npcasso\schems_mgv\
```

The folder is `luanti\mods\npcasso\schems_mgv\` (git-ignored; about 200 `.mts` files, including `well_1.mts`, which the mod checks for). The `mg_villages` mod itself is **not** enabled and its world generation is not used. The mod aliases the few door and marker blocks the old schematics expect.

### 6. Configure Luanti

Close Luanti first (it rewrites `minetest.conf` when it exits and would wipe your edits), then add to `C:\Users\zohai\Luanti\minetest.conf`:

```
secure.http_mods = npcasso
npcasso.backend_url = http://127.0.0.1:8000
```

`secure.http_mods` is required. Without it Luanti blocks the mod from calling the backend and every villager stays silent. `npcasso.backend_url` is optional and defaults to the address above.

Optional settings:

| Setting | Effect |
|---|---|
| `npcasso.auto_talk = true` | Looking at a nearby villager for a moment opens the talk window by itself. Default false. |
| `music_global_gain`, `music_time_interval`, `music_maximum_random_delay` | Asuna's ambient music: loudness, gap between tracks, extra random gap. This setup uses 0.8, 20 and 10. |
| `sound_volume` | Master volume. This setup uses 1.0. |
| `enable_damage = true`, `creative_mode = false` | Needed for the winter to cost health and for monsters to hurt. Set them when you create the world, since they are stored in its `world.mt`. |

### 7. Create the world

1. Start `C:\Users\zohai\Luanti\bin\luanti.exe`.
2. **New world:** name it (this setup calls it `NPCasso`; any name works), pick the game **Asuna**, and keep the default mapgen (Asuna rules out `v6`).
3. **Configure** the world and enable **npcasso**, **cottages**, **mobs** and **mobs_monster**. (Or write `load_mod_<name> = mods/<name>` lines into the world's `world.mt` by hand.) Turn on **Enable damage** and leave **Creative mode** off.
4. Select the world and press **Play**.

### 8. First join

- The mod builds Bellwether where you stand: the houses, the square, the farm, the pond, the sheep pen and four countryside sites (orchard, meadow, mine, wheat field), then spawns the twelve villagers. It seals the ground under the village. This can take a moment.
- You get the Village Guide book. Right-click a villager and type something.
- Run `/npcasso check` to see OK or MISSING for each of the four countryside sites, and `/npcasso village` to rebuild if one is missing. (Commands need the `server` privilege, which the world owner has.)
- The world's id for the backend is the save folder name plus a random id kept in that save's mod storage, so deleting a save clears the villagers' memory, and a copied world (different folder name) keeps its own.

### If something is wrong

| Symptom | Fix |
|---|---|
| Villagers have no names or skins, and talk does nothing | The backend is not running, or `secure.http_mods = npcasso` is missing. The mod keeps retrying `/npcs` every 10 s, so starting the backend late is fine. Check `http://127.0.0.1:8000/health`. |
| The village is a plain layout with no houses | The schematics are missing. Redo step 5 (`schems_mgv\well_1.mts` must exist), then `/npcasso village`. |
| No monsters, and Wren's quest cannot finish | `mobs` and `mobs_monster` are not enabled in the world, or `spawn_mobs` is off. |
| Villagers answer with the same short canned lines | `LLM_PROVIDER=mock`, or a provider call failed and the fixed fallback line played. Check the backend window. |
| `KeyError: MUBIT_API_KEY` on start | `LLM_PROVIDER=mubit` with no key in `.env`. |
| No sound | Restart Luanti after changing audio devices (it keeps the old one), and check `mute_sound = false`. |
| `minetest.conf` edits vanish | Luanti rewrote the file on exit. Edit it while Luanti is closed. |
| Port 8000 is busy | Stop the old listener, or start uvicorn with another `--port` and set `npcasso.backend_url` to match. |

### Day-to-day

Start the backend, then start Luanti and press Play. Lua changes need a world rejoin. Changes to `minetest.conf`, the menu banner or the icon need a full Luanti restart.

## Playing

| Action | How | What happens |
|---|---|---|
| Talk | Right-click a villager | Free-text dialogue. Apologies, threats, promises and corrections are detected and applied by game rules. |
| Gift | Hold an item, click **Give held item** | Trust changes by that villager's taste. A gift can settle promises and quests. |
| Trade | **Trade** | Price depends on hidden trust. Hostile or shunning villagers refuse. Rowan refuses without his anvil. |
| Quests | **Quests**, the quest board, the journal | Accept, hand in items, earn XP and rewards. |
| Steal | Right-click an `npcasso:apple_crate` (Elise's) | Elise knows only if she saw you. |
| Vandalise / repair | Dig / place the `cottages:anvil` near Rowan | |
| Hit | Punch a villager | They scream, others react. |
| Festival | Quest board, once eligible | The village votes. |
| Ending | Stand with the village when it gathers (from day 7) | Your ending plays and the run is over. |

Get a crate with `/giveme npcasso:apple_crate`.

### Commands (`/npcasso <command>`, server privilege)

| Command | Does |
|---|---|
| `guide` | Show the in-game guide. |
| `journal`, `board`, `stats`, `hand` | Open the journal, the quest board, the radar, or empty your hand. |
| `check` | Print OK or MISSING for each of the four village sites. |
| `home`, `unstuck` | Return to the square, or move to open ground. |
| `village`, `fillcaves` | Rebuild the village in place, or seal the ground under it. |
| `winter 0..1` | Preview the winter look. The next tick returns it to the story's own value. |
| `scene hit\|theft\|gossip` | Play a real event on the nearest villager (use a spare world). |
| `spawn <npc_id>`, `remove`, `reload` | Place a villager, delete the nearest, or reload the villager list. |
| `debug` | Trust, mood, memories and promises, hidden from players. |

**Adding a villager:** add an entry to `backend/npcs.json`, restart the backend, run `/npcasso reload`, then `/npcasso spawn <id>`. A new villager needs a persona, voice, background, temper, `reacts_as`, tastes and a quest, and a lean entry in `BENT` (`backend/game.py`) if you want one other than "both ways".

**Demo worlds:** build the village once in a template world, then copy the world folder (`worlds\npcasso_template` to `worlds\npcasso_thief`, `worlds\npcasso_honest`). The folder name is the backend's world id, so states never mix.

## Mubit

### What Mubit does

With `LLM_PROVIDER=mubit`, every model call goes through Mubit's proxy on the way to the model (`https://api.mubit.ai/openai/v1`, model `gpt-6-luna`). Mubit records the call and files it under the fixed system prompt. After enough kept examples of one prompt (25 per task), it trains a small adapter to answer that same job the way the big model does. You compare the adapter in Mubit's **Try models** screen.

The game receives the big model's reply. There is no adapter id the game can call yet. A reply that invents a past event is rejected by the game's validator, and that failure is stored (`interactions.validator_result`, with the Mubit request id in `interactions.mubit_request_id`) so it can be marked Bad in the Mubit console.

### What we send

Three tasks, each with a fixed system prompt (`SYSTEM_PROMPTS` in `backend/llm.py`).

| Task | When it runs | What it produces |
|---|---|---|
| `intent_classify` | Once when the player talks | Labels the sentence as a threat, apology, insult, promise, question, trade, correction, or something else. A confident threat, insult, apology, promise or correction (confidence 0.6 or more) changes trust or records the promise before anyone replies. |
| `npc_dialogue` | The voice of the village | The reply in a conversation, the greeting when you walk up, the two lines when you are close enough to hear a rumour, a villager explaining a festival vote, and the lines of an ending scene. It can offer a small quest and point you somewhere. Talk and greet try once more if the first line fails the check. |
| `npc_react` | A witness is asked to react to something you just did | The shout: up to two villagers voice a reaction to a theft, a vandalised anvil or a hit. Everyone else turns and looks, with no model call. |

Each call is a fresh snapshot. It carries who the villager is, their trust band, their current mood toward you and its cause, the strongest memories they have of you, open promises, the recent turns of the conversation, and what you just said. It continues no stored chat.

### What the game keeps

A gift, theft, hit, trade or spoken promise is written down immediately, along with who saw it. Trust moves by a fixed table, and that band sets prices and whether someone will trade. Each villager's mood is computed from their own memories. A rumour reaches the listener when you are too far away to hear it: they gain the memory and the trust change, and no model call is made. The festival tally is counted from the trust numbers. The winter clock and the five endings are read from the game's own hidden score. The next time a villager speaks, the snapshot already includes whatever changed.

Per call, timeouts are 6 s for `intent_classify`, 14 s for `npc_dialogue` and 10 s for `npc_react`. A slow or failed call gives way to a fixed line, so a villager is never silent.

### The validator

`backend/validator.py` checks every reply against the event log and the villager's state:

- Every past event named must be listed in `claims` and must exist in that villager's memories. Words that assert a past event ("stole", "gave", "broke", "smashed", "promised") without a claim are errors.
- A reply from an angry, afraid, hurt or cold villager that reads warm is an error.
- A chore request outside the villager's own need is sent back (`wrong_task`), as is a request before the villager is ready (`too_soon`), directions that miss the answer (`no_directions`), and a payment that differs from the quest's real reward.
- A trouble must be allowed, well-formed, have a real motive, not be about the player and not duplicate an open one. A consequence needs an open trouble and may only name people who know it.

The backend retries once with the mistake as feedback. Every catch is logged.

### How this helps

The instructions never change. Only the villager, the memories and the player's sentence change, so the same three jobs repeat all game. Mubit learns those jobs while the game keeps memory, trust, prices and endings consistent. You pay the big model for the lines someone hears, and the silent life of the village stays in the database.

### Feeding Mubit

Mubit trains per task, so each task needs its own volume of kept examples. `tools/feed_mubit.py` plays scripted afternoons (greetings, questions, promises, apologies, insults, threats, and hit, theft, gift and vandalism events with witnesses) against the real villagers on a throwaway database, all through the Mubit proxy.

```powershell
.venv\Scripts\python tools\feed_mubit.py --mock --scenarios 3        # offline check of the script
.venv\Scripts\python tools\feed_mubit.py --scenarios 2 --workers 2   # live smoke test
.venv\Scripts\python tools\feed_mubit.py --scenarios 40 --workers 4  # live volume run
```

One scenario produces about 22 calls (roughly 14 `npc_dialogue`, 4 `npc_react`, 5 `intent_classify`). The script stops on a 429, quota or credit refusal and prints per-task calls, validator results and Mubit request ids. On 2026-10-24, 947 calls went through, which put all three tasks above 25 (`npc_dialogue` 584, `npc_react` 140, `intent_classify` 223).

In the Mubit console each task moves through Collecting, Reviewing, Training and Testing. Mubit allows 3 adapter starts per organisation per UTC day plus a daily training limit, so a task may wait for the next day. Mubit's console has no API for rating replies, so a Bad rating happens there by hand.

**Keep the system prompts fixed once feeding starts.** Mubit groups a task by its instructions, format and model. A changed prompt starts a new group at zero. The starter credit serves `gpt-6-luna` and refuses the `store` option and `metadata`, so calls carry neither.

## Tools, tests and evaluation

```powershell
.venv\Scripts\python -m pytest -q                                              # 214 pass, 23 skipped
.venv\Scripts\python tools\sim.py thug|saint|lost|troll [--mock]               # scripted players on a throwaway database
.venv\Scripts\python tools\luacheck.py                                         # syntax-check the Lua mod
.venv\Scripts\python tools\lua_smoke.py                                        # run the village-life Lua against stubs
.venv\Scripts\python tools\make_sounds.py                                      # regenerate the .ogg sounds (needs ffmpeg with libvorbis)
.venv\Scripts\python tools\feed_mubit.py --scenarios 40 --workers 4            # volume traffic through Mubit
.venv\Scripts\python -m eval.run --provider local --split heldout              # score replies against game state
.venv\Scripts\python -m eval.run --provider mubit --split train --repeat 5     # feed Mubit training examples
```

Simulation transcripts are saved in `sim/runs/`. Evaluation results go to `eval/results/`. Train messages feed Mubit, and held-out messages are used only for scoring.

Debug API: `GET /health`, `GET /npcs`, `GET /npc/{id}?world=&player=`, `GET /player`, `GET /profile`, `GET /quests`, `GET /moods`, `GET /festival`, `GET /interactions?npc_id=`.

## Project layout

| Path | Holds |
|---|---|
| `backend/app.py` | FastAPI routes (`/event`, `/talk`, `/greet`, `/react`, `/gossip`, `/trade`, `/tick`, `/festival`, `/ending/*`, `/quest/*`, `/die`). |
| `backend/game.py` | Events, memory, witnesses, gossip, quests, talk, greet, festival, ending hand-off. |
| `backend/stance.py` | Each villager's mood toward the player. |
| `backend/situations.py` | Troubles between villagers and their consequences. |
| `backend/story.py`, `backend/finale.py` | The winter clock, the twelve traits, the five ending scenes. |
| `backend/llm.py` | The three fixed system prompts and the mock, local, Mubit and Claude clients. |
| `backend/validator.py` | Checks every reply against the event log and the villager's state. |
| `backend/rules.py`, `backend/progress.py`, `backend/db.py`, `backend/npcs.json` | Trust tables, XP, storage, the villagers and the world's facts. |
| `luanti/mods/npcasso/` | `init.lua` (villagers, events, village, guide, commands), `town.lua` (buildings, quests, journal, festival), `life.lua` (roaming, moods, gossip, monsters), `finale.lua` (the gathering and ending scenes), `hud.lua`, `radar.lua`, `atmosphere.lua` (winter look), `sfx.lua` (voice and sound), `sounds/`, `textures/`. |
| `tools/`, `sim/`, `eval/`, `tests/` | Helpers, simulation transcripts, the evaluation harness, the tests. |
| `docs/` | Design specs (`2026-10-23-npcasso-design.md`, `2026-10-24-npcasso-core-vision-design.md`, `2026-10-24-social-consequences-design.md`, `2026-10-24-npcasso-v2-design.md`), plans, and `mubit-notes.md`. |

Credits: villager skins come from SkinsDB (licences in `luanti/mods/npcasso/SKINS_CREDITS.md`). Building schematics come from Sokomine's mg_villages (GPL-3.0). The game is Asuna, with the cottages mod.

---

# Part 2: The game

## The idea

Most games with talking characters read lines from a tree. NPCasso takes a different route: **the game decides, the model speaks.**

- Everything that matters is plain code: what happened, who saw it, who was told, how much each person trusts you, what things cost, who will trade, how each person feels about you right now, which ending you lean toward, how cold it is.
- A language model puts those facts into words, in the voice of one villager at a time. It cannot change a fact. A reply that invents a past event is rejected and sent back.
- Nothing is shown as a number. There are no hearts, no trust bars, no morality meter. You read the village from behaviour: tone, prices, who turns away, who walks up to you, what a villager lets slip about their own shelf.
- Two players in the same village meet different people on different days and leave different histories.

The founding rule: **villagers know only what they saw or were told.** They do not know your pack, your level, the quest board, what another villager asked of you, or a secret kept from them.

## The lore

The player arrives outside **Bellwether**, a small village that has not got enough to get through the winter: thin stores, short firewood, a worried farmer, a shopkeeper rationing. Nobody explains it. The village shows it through small sights at each person's own place: crates spread out to hide how few apples are left, forge coals fed one lump at a time, a tavern with one table laid, a ledger left open to the same page, an oven cold at midday.

Each villager has a work, a history, a temper and a lean:

- Some look out for their own work (Elise, Rowan, Dax, Corin).
- Some are pulled both ways (Tobin, Mira, Wren, Pip).
- Some try to keep other people fed and warm (Nell, Hazel, Bram, Lottie).

That lean shifts with how you treat them. Over the days the model also opens **troubles between villagers**, each with a reason of its own: a debt, a secret kept from someone, a shortage that sets two people against each other. The game stores the trouble, so the village remembers it and the model cannot rewrite it. You can help, hide, exploit or walk past. Each of those is remembered.

The vision documents describe a larger story (a priest who warns that terrible things happened here and are forgotten, and an ancient book, the Palimpsest, made to soften memories and used to erase inconvenient truths). That layer is [designed but not built yet](#designed-but-not-built-yet). What is built is the village, the people, the winter and the five endings.

## How a run goes

Days count from the moment you arrive, so an old world never starts frozen. The clock shows the day and the time of day. It never names a stage and never announces a threshold.

| Days | Phase | What changes |
|---|---|---|
| 1 | Open | Ordinary days. Nobody asks for anything on a first meeting, and one trouble at a time may open between villagers. |
| 2 to 5 | Pressure | The cold gets into food, firewood and who is provided for. Up to three troubles may be open at once. Thin snow settles on the village. |
| 6 to 9 | Closing | Winter closes in. The cold starts to cost health, slowly at first and faster as day 10 nears. The village leans toward the ending your hidden score points to. From day 7 the village may gather. |
| 10 | Frozen | The cold cannot be survived. If you have not taken an ending, the run ends in the freeze. |

The sky, fog, snow, wind and voices follow the winter a little at a time, as one value from 0 on arrival to 1 on day 10, so the change happens in front of you.

You can **stand with the village** when it gathers, which plays your ending as a short scene and ends the run. You can also **walk away**: the cold keeps coming, and the village does not offer again for half a game day. Dying ends a run too (to the cold, a fall, water, fire, a blow or a beast) and is not one of the five endings.

## The five endings

The ending comes from your hidden score over twelve traits. Each ending leans on a few traits, and the strongest positive match wins (ties go in the table's order). No single act locks an ending, and the village steers only after you have had days to understand it.

| Ending | Leans on | The scene |
|---|---|---|
| **The Names We Buried** | candor, bravery, loyalty | The village is carrying a truth through the cold and waits to see whether you will say it. Truth is gained and something irreplaceable is lost. |
| **The Last Place at the Table** | compassion, selflessness, loyalty | The little that is left is laid on one table, with less bread than people. You give something up so the table can stay a table, and in spring the village is thinner and closer. |
| **The Peace You Made** | ambition, pragmatism, ingenuity | A settlement is on the table that could hold. The winter is survivable and the days are better, and a few people are paying for them. |
| **The Last Departure** | independence, with low ambition and loyalty | The road out is open. Someone who would like you to stay asks you to, for no reason that would help. You go anyway. |
| **The End of All Things** | low forgiveness and compassion, high independence | Something under the square has begun to turn, and every promise ever broken is suddenly loud. The lights go out house by house. |

When you stand with the village, each ending plays as fixed narration around one or two lines from each of the three villagers who remember you most. Those lines come from the model, and they use only what that villager really remembers of the run. The narration and the title cards are fixed text. A fixed fallback line stands in if the model cannot speak. The ending never names a deed that did not happen.

## The twelve hidden traits

What you do builds evidence on twelve traits, each from -1 to +1. You never see these in play. (`/npcasso stats` shows a radar of them for demos, and the journal's **Character** tab shows it too.)

| Trait | Low pole | High pole |
|---|---|---|
| Candor | hides what happened | says the hard thing |
| Bravery | steps back from the risk | takes the risk |
| Compassion | walks past suffering | is moved by suffering |
| Selflessness | keeps the gain | gives the gain up |
| Ambition | accepts a small place | reaches for a mark |
| Ingenuity | uses the usual way | finds another way |
| Loyalty | drops a commitment | stands by someone |
| Pragmatism | holds out for the ideal | takes the workable outcome |
| Curiosity | leaves the surface as it is | looks underneath |
| Justice | lets a wrong stand | asks for an account |
| Forgiveness | keeps the grievance | lets the grievance go |
| Independence | stays with the village | goes their own way |

Evidence comes from two places: the game's own table for deeds villagers know about (hitting costs compassion and justice, theft costs justice, vandalism costs justice and compassion, a gift adds compassion and selflessness, a repair adds justice and selflessness), and the model's reading of a moment in a conversation, which the game validates before storing. An unseen deed scores nothing. Each trait is the mean of its evidence, and the run keeps contradictions.

The villagers see your conduct only in words ("the player says the hard thing and takes the risk"). It colours their manner and never reaches them as a number.

## The villagers

Twelve people live in Bellwether. Each has a persona, a voice, a background, a temper, things they love, like and dislike, one main quest, a small piece of expertise, a chattiness, and two small signs of the winter at their place.

| Villager | Role | Temper | Lean | Place | Main quest | Loves |
|---|---|---|---|---|---|---|
| **Elise** | Merchant | steady | own work | fruit shop, west of the square | Find 3 apples | gold ingots |
| **Rowan** | Blacksmith | hot | own work | forge, east | Bring 3 iron ingots (reward: steel pickaxe) | iron |
| **Mira** | Innkeeper | steady | both ways | tavern, north-west | Bring 3 roses | roses |
| **Tobin** | Farmer | steady | both ways | farmhouse, south-west | Harvest 5 wheat | wheat |
| **Wren** | Guard | hot | both ways | watchtower by the town hall | Slay 2 monsters (reward: steel sword) | iron |
| **Pip** | Kid | timid | both ways | runs around the square | Bring a loaf of bread | apples, bread |
| **Bram** | Elder | steady | others | library, north end | Bring a loaf for the elders' table | bread |
| **Nell** | Baker | steady | others | bakery, north-east | Bring 3 flour | flour |
| **Corin** | Fisher | timid | own work | cabin by the pond, far west | Bring 3 wheat seeds for bait | wheat seeds |
| **Hazel** | Herbalist | timid | others | garden house, west | Bring 3 roses | roses |
| **Dax** | Miner | hot | own work | ore shop, south-east | Bring 4 coal | coal |
| **Lottie** | Shepherd | timid | others | cottage by the sheep pen, north-east | Bring 3 wheat for the sheep | wool |

How each sounds:

- **Elise:** warm on the surface and careful underneath; counts and weighs things as she talks. She came to the village after a partner cheated her.
- **Rowan:** blunt and clipped, talks in metal, weight and heat. Third-generation smith; the anvil was his grandmother's.
- **Mira:** chatty, leans in close, always says who she heard it from. She hears everything.
- **Tobin:** slow, dry, plain farmer's talk about weather and soil.
- **Wren:** speaks like a sentry giving a report, eyes elsewhere. She lost a brother to monsters.
- **Pip:** quick, breathless, interrupts himself, cheeky, cannot keep a secret.
- **Bram:** measured and formal; sets today against what the village has weathered. He moved the winter stores into the hall and keeps the key on his belt.
- **Nell:** warm and fussy, calls people dear, asks whether you have eaten.
- **Corin:** few words and long pauses; speaks of water, birds and omens; wary of anyone loud.
- **Hazel:** soft and unhurried; speaks to people as if they were already a little hurt.
- **Dax:** gruff, nearly grunting, answers a question with a question.
- **Lottie:** bright and chatty; wanders off mid-sentence to talk to an animal.

Their temper decides how harm lands: a hit makes a hot villager angry and a timid one afraid. Their `reacts_as` role decides what they do in a scene: **protectors** (Tobin, Bram, Nell, Hazel, Lottie) come to help, **tattlers** (Mira, Pip) run to tell, the **guard** (Wren) steps in, and the **wary** (Elise, Rowan, Corin, Dax) keep their distance.

## How the village thinks

### Events and memory

Every act is written down at once as an event: a gift, theft, hit, trade, vandalised or repaired anvil, a kept or broken promise, a monster slain, wheat harvested, putting stolen goods back, walking away from a chat. The event stores who was there. Each villager who knew gets a first-person memory with how they know it (witnessed, heard, told by someone, or their own business), a reliability and a severity.

The game builds each villager's snapshot from their own memories only. The strongest memories reach the model with a rough "when" (moments ago, earlier, yesterday, days ago).

### Witnesses

A villager witnesses an act if they are close, have line of sight and face roughly toward it. Villagers within earshot who did not see it hear it, so they know a cry went out and nothing more. The victim of a hit always knows. The nearest witnesses, up to two, speak a reaction through the model. The others turn and look.

### Trust and bands

Trust starts at 10 for everyone and moves by a fixed table, and bands come from it.

| Event | Trust |
|---|---|
| Theft / vandalism / hit | -30 / -40 / -25 |
| Threat / insult | -15 / -10 |
| Gift (loved / liked / neutral / disliked) | +20 / +10 / +5 / -5 |
| Apology | +10 (once per game day) |
| Promise kept / broken | +15 / -20 |
| Repair / return what you took | +15 / +10 |
| Quest done / failed | the quest's own value (+15 for starters) / -10 |
| Trade | +2 |
| A correction that proves true | +5 (once per game day) |

Something you only hear about second-hand counts half. Bands: **hostile** (-50 or less), **wary** (below -10), **neutral** (below 30), **friendly** (30 or more). The band sets what you pay (friendly 1x, neutral 2x, wary 3x the base price) and whether anyone will trade (hostile villagers refuse).

### Moods

Each villager has a mood toward you, computed from their own memories: angry, afraid, hurt, cold, guarded, neutral, warm or fond.

- Harm heats a villager (hit 25, theft 30, vandalism 40, threat 15, insult 10) and the heat halves every game day and a half. Gifts, repairs, apologies, returns and finished quests cool it.
- What you did to someone else counts at 60% of what you did to them, and rumours count at half.
- A grave memory (hit, theft, vandalism) leaves a scar: the villager never drops below guarded.
- A villager who is hot enough will **shun** you and refuse to trade.
- Without harm, trust sets the mood: warm from 15, fond from 30.
- Mood outranks everything. A hurt or guarded villager makes no request, and a reply that reads warm from an angry, afraid, hurt or cold villager is rejected.

The mood also drives the body. Name tags tint with how they feel when they can see you. An afraid villager backs away or flees. A villager who is sore (angry, hurt, cold) or guarded stops and faces you if you come near. A warm or fond villager walks up to you. Your standing (Unknown, Newcomer, Trusted, Watched, Feared) is one word summed from the villagers you have met.

### Hits become scenes

The backend decides who moves when someone cries out and the world plays it. The victim screams (at their own pitch) and the street hears it. Bystanders gasp. Protectors come to help, tattlers run to tell, the guard steps in. Witnesses of crimes are told "Word will spread."

### Rumours

When two villagers meet, the teller may pass on one thing about you that the listener does not know yet. Only public deeds travel (theft, gift, vandalism, repair, hit, trade, returning something), after a short delay. A quest, a promise or a secret never travels this way. The teller's chattiness sets the odds, a victim always tells, and Wren always hears about crimes. The listener gets a memory credited to the teller ("Mira told me...") at half reliability and half severity, plus half the trust change.

If you are close enough to hear, the two lines are spoken through the model. If you are far away, the rumour still arrives with its memory and trust change, and no model call is made.

### A conversation builds

A first meeting is a conversation. The pacing then advances by how many exchanges you have had with that villager:

1. **Introduce** (never met): name, work showing through what they are doing, no hardship, no request.
2. **Hint** (met once): a small sight of their own place may surface. No request.
3. **Open** (met twice or more): their worry colours their talk. From the third exchange they let slip what their place is short of. From the sixth, if they have a real need, it comes up once (with a cooldown of half a game day) and becomes a quest. Their need is also the only chore they may ask. Asking for anything else is sent back.

If you say you are lost, they give you directions in their own words.

### What you say is classified

`intent_classify` reads each sentence. With confidence 0.6 or more:

- **Threat / insult:** trust drops and they remember it.
- **Apology:** trust rises (once per game day).
- **Promise:** a promise is recorded with an item, a count and a deadline. Miss it and it breaks.
- **Correction:** if you deny something that did happen, it earns nothing. If you deny something that did not happen, you earn trust (once per game day).

Short questions and hellos skip the classifier to save a call.

### Troubles between villagers

When a villager is free (none open, a cooldown since their last, a gap since anyone's last), the model may open a trouble: who is involved, who it is hidden from, and a reason it picked from who those people are. The game keeps it. Only the opener and the people they let in know it. A villager it is hidden from knows nothing until someone tells them. A trouble can end with a consequence that moves someone's trust by a small, medium or large step (3, 6 or 10). Troubles are never about you.

## Quests, XP, trade and the Harvest Festival

**Quests.** Each villager has a main quest (marked with a star on the board). Kinds are `bring` (hand in items) and `slay` (kill monsters). Accept from the quest board in the town hall or in conversation. Hand in items from the talk window. A matching gift can also settle a quest. Quests never expire. Promises do.

**Rewards.** Items, XP and trust on finishing (+15 for each starter quest).

**XP and levels.** Level thresholds are 0, 50, 150, 300 and so on (50 x level x (level - 1) / 2). Levels map to titles: newcomer (Lv 1), villager (Lv 2 and 3), friend of the village (Lv 4 and up). XP comes from quests, trades (2), slain monsters (5), kept promises (10) and harvests (1 each, up to 20 a day).

**Trade.** One offer per trader, in the Minecraft villager style. Elise sells apples for iron ingots. Rowan sells steel pickaxes for iron ingots (Lv 2 and up, and only when his anvil is in place). Mira sells bread for apples. Tobin sells bread for wheat. Wren sells torches for coal. Nell sells bread for wheat. Dax sells iron ore for coal. Prices follow your band, and a shunning villager will not trade.

**The Harvest Festival.** Finish every villager's main quest and reach Lv 3, then begin it at the quest board. Each villager votes from their trust: **for** at 30 or more, **against** below -10, **abstain** between. The village answers with **Hero** (two-thirds for and nobody against), **Accepted** (more for than against) or **Turned away**. Votes and the result are set at once. Each speech is written on demand as you read the last. You get one festival per run, and every villager remembers it.

## The world, the winter and the sound

**The village.** The first time you join a world, the mod builds Bellwether where you stand: hand-built schematics for every house (from Sokomine's mg_villages, loaded from an installed copy that this repo does not ship), a square with lamps and gravel paths, Elise's stall, Rowan's forge, Mira's inn, the town hall (quest board and a crafting table), a farm with water, a pond, a sheep pen, and four countryside sites for quests: an orchard to the west, a rose meadow to the north, a mine to the south-east and a wheat field to the south-west. Each site is built only once its area is loaded and read back afterwards, with a retry on the next join. The ground under the village is sealed so no cave leaves a black hole at the edge of the square. A soft border at about 110 nodes turns you back, since the game is short.

**Landmarks that count.** Elise's apple crate is her stock chest: taking from it is theft if she sees you, and putting things back is a return. Digging Rowan's anvil is vandalism and placing it back is a repair.

**Village life.** Villagers wander between their places, stay in their shop footprints (traders), stop to face you, meet each other and gossip, and flee or approach by mood. Monsters are kept out of the village and come out at night outside it. A guide book tells you the controls and how things work, and an in-game guide has tabs for Start, Farming, Trading, Villagers, Quests and Festival.

**HUD.** A message feed bottom-left, an XP bar top-left, the day and the time of day top-right, waypoint markers when a villager points you somewhere, and a journal with **Quests**, **Character** and **People** tabs. The People tab lists only villagers you have spoken to and how the last meeting left them, never live.

**The winter, seen and felt.** The backend reports a `winter` value from 0 to 1 on every tick. `atmosphere.lua` eases the sky colour, the fog (190 nodes down to 70), the clouds, the saturation (down to half), the snow around you (from 0.2, none indoors), a wind bed that rises with the cold, and the voice pitch and speed (slower and lower as it worsens). It never jumps. Separately, thin snow settles on the village at day 2, and the farm pool freezes once the cold closes in.

**Sound.**

- **Voices:** wordless babble in the style of Animal Crossing, one syllable per few letters, with a longer pause at a comma or full stop. Each villager has a pitch and speed (low and slow for the old, high and quick for the young), shaped by mood (angry, hurt, cold, afraid). The sentence ending rises on a question and falls on a full stop.
- **Cues:** a chime when someone has something for you, a rising chime on accepting a quest, a bell when you finish one.
- **Scream and gasp:** the victim of a hit screams at their own pitch and others gasp.
- **Wind:** a seamless loop that fades in as the winter grows.
- **Music:** Asuna's own ambient tracks.
- **Source:** all sounds are synthesised by `tools/make_sounds.py` into mono Ogg Vorbis (Luanti plays only that).

## Designed but not built yet

The core vision (`docs/superpowers/specs/2026-10-24-npcasso-core-vision-design.md`) describes more than the game does today:

- **The priest and the Palimpsest.** A priest who warns that terrible things happened here and are forgotten, and an ancient book in the town hall that was made to soften unbearable memories and used to erase inconvenient truths. It would end the game through a special sixth ending. Neither is in the code.
- **A generated first unease.** A small unexplained detail the model invents soon after you enter, different every run. Today the early signs are the fixed per-villager winter signs, and the troubles the model opens from day 2.
- **Winter stores and rationing**, and a **routines and ties** layer for villagers (later slices of the social design).
- **Calling a trained adapter from the game.** Mubit has no route for that yet, so adapters are compared in the console only.
