# NPCasso

*An open world. No background characters.*

A cosy Luanti village whose NPCs remember what you do, judge you for it, and gossip behind your back. Every NPC reaction, intent read and conversation goes through Mubit as three recurring tasks (`npc_react`, `intent_classify`, `npc_dialogue`), so Mubit can train task adapters on them.

Design: `docs/superpowers/specs/2026-10-23-npcasso-design.md` · Mubit notes: `docs/mubit-notes.md`

## How it works

```
Luanti mod (luanti/mods/npcasso)  --HTTP JSON-->  FastAPI backend (backend/)  --openai client-->  mock | Ollama | Mubit
  witnesses, dialogue UI, notices                  SQLite state, rules, memory, validator
```

- **Game logic decides, the LLM only speaks.** Theft, witnesses, trust, prices, promises and quests are deterministic (`backend/rules.py`, `backend/game.py`).
- NPCs only know what they saw or were told. Gossip spreads witnessed events as rumours.
- Every NPC reply lists the events it refers to (`claims`). `backend/validator.py` checks them against the event log, and the backend retries once with the mistake as feedback.
- Relationships are hidden from the player. Use `/npcasso debug` to see them.

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env      # then set LLM_PROVIDER: mock | local | mubit
```

- `mock`: offline, deterministic. Used by the tests.
- `local`: any OpenAI-compatible local server, e.g. Ollama with `LLM_MODEL=qwen2.5:7b`. For development only.
- `mubit`: `MUBIT_API_KEY=mbt_...`. Choose `LLM_MODEL` once and never change it, because Mubit groups tasks by model. The hackathon requires demo traffic to go through Mubit.

## Run

```powershell
.venv\Scripts\python -m uvicorn backend.app:main --factory --port 8000
```

Luanti (already installed at `C:\Users\zohai\Luanti`, with Asuna in `games\`, cottages in `mods\`, and `mods\npcasso` linked to this repo):

1. `minetest.conf` must contain `secure.http_mods = npcasso` (and optionally `npcasso.backend_url = http://127.0.0.1:8000`).
2. Start `C:\Users\zohai\Luanti\bin\luanti.exe`, create a world with the **Asuna** game, and enable the mods **cottages** and **npcasso**.
3. In game, as the world owner, stand where an NPC should stand, look the way it should face, and run `/npcasso spawn elise` (or `rowan`, `mira`). Use `/npcasso remove` to delete the nearest NPC.

### Playing

| Action | How | What happens |
|---|---|---|
| Talk | Right-click an NPC | Free-text dialogue. Apologies, threats, promises and corrections are detected and applied by game rules |
| Gift | Hold an item, click **Give held item** | Trust changes by that NPC's taste; a gift can settle promises and quests |
| Trade | **Trade** | Price depends on hidden trust; hostile NPCs refuse; Rowan refuses without his anvil |
| Steal | Right-click an `npcasso:apple_crate` (Elise's) | Elise only knows if she saw you (range, line of sight, facing) |
| Vandalise / repair | Dig / place the `cottages:anvil` near Rowan | |
| Hit | Punch an NPC | |
| Debug | `/npcasso debug` | Trust, memories and promises (hidden from players) |

Get a crate with `/giveme npcasso:apple_crate`.

**Demo worlds:** build the village once in a template world, then copy the world folder (`worlds\npcasso_template` to `worlds\npcasso_thief`, `worlds\npcasso_honest`). The folder name is the backend's world id, so states never mix.

**Adding an NPC:** add an entry to `backend/npcs.json`, restart the backend, run `/npcasso reload`, then `/npcasso spawn <id>`.

## Test and evaluate

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m eval.run --provider local --split heldout      # score replies against game state
.venv\Scripts\python -m eval.run --provider mubit --split train --repeat 5   # feed Mubit training examples
```

Results go to `eval/results/`. Train messages feed Mubit; held-out messages are only used for scoring.

Debug API: `GET /health`, `GET /npcs`, `GET /npc/{id}?world=&player=`, `GET /interactions?npc_id=`.
