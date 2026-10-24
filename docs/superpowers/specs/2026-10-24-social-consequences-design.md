# NPCasso: social behaviour and visible consequences

Status: draft for review. Date: 2026-10-24.

## Why

NPCasso lives or dies on how villagers behave. Play testing shows the surface is polished and the people are not:

- A villager who was just hit carries on as before. A villager who was insulted answers with a cheery errand pitch.
- The model is told only a trust *band* ("wary") plus memory text, so it has nothing to be angry or frightened *with*.
- Quest places are placed with `set_node` in map areas that may not be loaded, 70 to 100 nodes out. Some goals may simply not exist.
- Actions have no visible, audible, or lasting consequence. Rumours trail by a fixed delay. Reputation is invisible.

## Principles

1. **The game decides, the model speaks.** Mood, who helps, who shuns, what spreads: all computed. The model puts it into words.
2. **Every act answers within seconds** (something you can see), **and again within days** (something people remember).
3. **People have reasons.** Every quarrel comes from a need, a debt, a tie, or a slight. Never invented for its own sake.
4. **Villagers know only what they were there for or were told.** No pack, no quest board, no secrets kept from them.
5. **Nothing is forgotten, and everything can thaw.** Memories stay. Heat cools.

## Scope of this slice (A)

0. Reachability fix (prerequisite)
1. Stance: a computed emotional state per villager toward the player
2. Human reactions to harm: victim, bystanders, guard, shunning
3. Rumours that move the moment the affected person talks to someone
4. Journal "Character" tab with the radar and standing
5. Fallback lines so a failed model call never leaves a villager silent
6. Conversation context (the last turns of each chat reach the model)
7. Knowledge boundaries, with a leak canary test
8. The smaller gaps in section 9

Later slices (design hooks are in place, see the end): B conflicts with motive, routines, ties. C audio. D winter store and rationing.

## 0. Reachability

- Build the countryside (orchard, meadow, mine, wheat field) only after the area is loaded, using `core.emerge_area` with a callback. Never call `set_node` into an unloaded block.
- After placing, read each landmark back (`core.get_node`). On failure, log an error and retry on the next join. `/npcasso village` rebuilds.
- Move resources inside about 40 nodes of the square. Waypoints stay as they are, with the new distances.
- Audit every starter quest for a path of at most 3 steps and about 10 real minutes, tools included. Adjust counts or places where it is longer (for example Rowan's iron chain: mine, smelt, return).
- Check: after a fresh village build, each of the four sites contains its nodes, verified by a debug command that prints OK or MISSING per site.

## 1. Stance

A pure function `stance(conn, npc_id, player, game_time)` returns:

```
{mood, heat, cause}
```

- `mood`: angry, afraid, hurt, cold, guarded, neutral, warm, fond.
- Pacing is per villager: each one is met for the first time once (introduce), then a hint, then open. Their stance outranks pacing: a villager who is hurt, angry, afraid, cold or guarded gets no pacing text, no sign, and no errand.
- `heat`: 0 to 1, how strongly it is felt now.
- `cause`: a plain-words reason from this villager's own top memory ("you hit me").

Inputs are this villager's memories of the player (type, severity, time, `how`) plus trust. Nothing else.

- Heat per memory = severity weight x `0.5 ^ (age_days / 1.5)`. Told-by memories count half. Gifts, repairs, apologies and returns subtract.
- Scar floor: while a grave memory (hit, theft, vandalism) exists the villager never drops below guarded, and keeps the cause.
- Mood from the dominant memory and the villager's `temper`: a hit makes a hot villager angry and a timid one afraid. Theft and vandalism make anger or coldness. An insult makes hurt or cold.
- Warm and fond come from trust and kept promises.

How it reaches the model: `facts.stance` joins the packet, with `cause`. The prompt adds a short block: stay in this mood, let the cause come out in your own words when it fits, never quote the numbers. The `heard_as` and `need` gating from the last change stays.

Validator: a reply from an angry, afraid, hurt or cold villager that reads warm becomes an error (today it is only a flag), and the retry is told why.

## 2. Human reactions to harm

All of this is computed by the backend in the response to `/event`, and Lua only plays it.

**Victim ladder (hit or threat):**
- Flinch and stumble back, then a short spoken line (model, from stance).
- Then cower or flee to their home or a safe place, and stay shaken: no wandering, no auto-talk, for about one game-day.
- Afterwards they speak the way hurt people speak: short, wary, unwilling to turn their back.
- While shaken, chat and trade open with a curt refusal line. An apology or a gift opens a window to talk again.

**Bystanders** react by an authored `reacts_as` field per villager in `npcs.json` (protector, wary, tattler, guard). Each villager also gets a `temper` (hot, steady, timid), which decides angry versus afraid in section 1:
- Protectors (Nell, Hazel, Lottie, Bram) run to the victim and stand between you and them.
- The wary (Elise, Corin, Dax, Rowan) back off and watch. They remember it.
- The tattler (Pip, Mira) runs to the guard, and only if they saw it: someone who merely heard a cry has nothing to tell her.
- The guard (Wren) closes in and asks what happened. She heard a cry and does not know who or why, so she asks; she turns cold once she has been told.

**Reputation:** the act scores the relevant dimensions (compassion, justice, selflessness) through the existing evidence path. A notice says "Word will spread." The victim and anyone who saw it refuse to trade for about a game-day (stance heat at or above 0.3). Rescuers only know it second-hand, so they greet you coldly and keep trading. Talk is never blocked: an angry villager answers in their own voice, which reads better than any canned refusal.

**Not in scope:** hurting the player's health.

## 3. Rumours

- The first time a victim (or anyone who saw a public deed) meets another villager, they tell it at once. Today there is a fixed delay.
- The listener is chosen by closeness. Friends and kin come first (see ties, slice B; until then, the nearest).
- The listener stores it as `told_by:NAME`, reliability lower than a witness. Their next meeting with you is already coloured.
- Only public deeds travel (`PUBLIC_RUMOUR`, unchanged). Secrets and quests never do.
- If you are within earshot you see and hear it; otherwise it happens out of sight.

## 4. Journal "Character" tab

- The journal gets two tabs, Quests and Character.
- Character shows the radar (reusing `npcasso.radar_formspec`) and a standing line from the profile, for example "Feared" or "Trusted".
- Below it, a row for each villager you have met, with a mood word and colour dot from your last meeting (no cause text, see section 8).
- `/npcasso stats` remains as the demo shortcut.

## 5. Fallback lines

When the model fails twice, each stance has a short deterministic line in that villager's voice: angry gives a curt dismissal, afraid gives a stammer, warm gives a greeting. A greeting never returns an empty string.

## 6. Seen in the world

A villager's name tag colour follows their stance toward the player once they notice you: red angry, grey cold, amber guarded, green warm.

## 7. Conversation context

Today each reply is generated without the last few lines of the same conversation. That is why a villager greets twice, re-introduces themselves, or answers "One what?" to a follow-up.

- `facts.recent`: the last 6 turns between this player and this villager only, read from `interactions` (accepted, non-retried replies). Each entry is `{who: "you" | "them", text}`.
- The prompt adds one line: continue what the two of you just said; do not greet again or repeat yourself.
- A greeting after a gap is a "back again" greeting when `recent` is non-empty.

## 8. Knowledge boundaries

A villager's packet holds only: their own memories, public rules, their own stock, the map, their own stance (derived from those memories), and the current exchange. Rules for the new mechanics:

- **Hearing is not seeing.** A cry for help reaches villagers within earshot (about 20 nodes). Those who did not see it record only "Elise cried out". They learn the cause when the victim tells them, stored as `told_by:Elise`.
- **Told memories carry their source and no more than the teller knew.** Reliability stays below a witness.
- **Stance cause is attributed.** "I saw you hit her" for a witness, "Pip told me you hit her" for a hearer. Wren's warning cites what she was told and by whom.
- **Secrets (`hidden_from`) and quests never enter a rumour.** `PUBLIC_RUMOUR` stays the only list that travels.
- **No hidden state leaks to the player either.** The Character tab lists only villagers you have met, with the mood from your last meeting, not live. Name tag colour updates only when a villager notices you (about 12 nodes, in view). The player does not learn who has heard what off screen.
- **The provider holds no memory.** Verified: every call is stateless and no thread id is sent to Mubit.
- **Canary test.** Seed villager A with a unique secret, a quest and a pack item, then assert none of it appears in any other villager's packet, for every pair, using the real `_heard` output. A second test asserts that a villager who only heard the cry has no attacker identity in their packet.

## 9. Also missing, folded in

- **Latency.** Replies take seconds. Show a typing indicator, cut the timeout from 30 s to about 12 s with a stance fallback line, and skip the intent classifier call for clear-cut messages with a keyword pre-check.
- **Out-of-character input.** A player message is only speech. Rules and facts cannot be changed by it. Tests with five jailbreak lines per run.
- **Canon sheet.** A short `canon` list per villager in `npcs.json` (age, family, a shared history fact) so two lines never contradict.
- **Edge cases, decided.** Villagers cannot die: they go down, flee, or go home. A gift to an angry villager is accepted coldly and cools them a little. Hitting the guard escalates her confrontation but never hurts you. Missing villagers are skipped in rescues and rumours.
- **Debug view.** `/npcasso debug` also prints each villager's stance and cause, so tuning is done against numbers.

## Simulation (the user test)

A single script, `tools/sim.py`, plays the game for you against the real model on a throwaway database. The backend already takes `game_time` per call, so ten game-days run in minutes with no Luanti.

**Personas (scripted, repeatable):** Thug (hits, insults, threatens), Saint (gifts, helps, apologises), Thief, Lost newcomer (asks what to do), Troll (jailbreak lines, nonsense), Drifter (leaves for days and returns).

**Scenarios:** each persona runs a day-by-day script across a few villagers, for example hit Elise with Nell watching, then talk to Elise, Nell, and Mira (who saw nothing) at set times over three days.

**Output:** a readable transcript per run, plus these automatic measures:
- **Leak canary:** secrets, quests, pack items, and unseen deeds never appear in a packet or reply where they should not.
- **Mood fit:** does the line match the villager's stance and the cause (judge call at temperature 0, with a keyword check as a cheap second opinion)?
- **Repetition:** how alike openers and replies are across villagers and turns.
- **Silent replies, validator failure rate, latency p50 and p95.**
- **Asks per ten turns,** and whether the ease-in stayed in order.

**Judge rubric (1 to 5, with the single worst line quoted):** in character; mood fits what the player did; knows only what they could know; human; not repetitive.

**Baseline recorded on the current build (before any of this work):**
- Elise, just hit: "hello?" gets a cheerful "Hello. Just weighing these apples…".
- An apology is accepted at once.
- Nell, who saw it, greets with "Have you eaten?".
- The next day Elise offers her errand and pay as if nothing happened.
- Mira, who has met no one and heard nothing, greets as if she knows you.

The target after the build: each of those five is measured and fixed, and results are compared run to run in `sim/runs/`. An optional LLM-driven player agent can play open-ended chats for exploration. It varies run to run, so it is for discovery, not for pass/fail.

**In the engine:** `/npcasso scene hit|theft|gossip` replays a scene in the world so a human can watch it in seconds, and a ten-minute playtest checklist covers what a script cannot judge: how rescues look and path, audio, and feel.

## Testing

- Unit: stance math (a hit makes anger or fear, heat halves in 1.5 days, an apology cools faster, the scar floor stays); rumour immediacy for the victim; fallback never empty; validator rejects a warm reply from an angry villager.
- Play script (manual, in Luanti): hit Elise. She stumbles, cries out, Nell runs to her, Wren confronts you, Elise refuses to talk for a day, Mira knows by evening, an apology and a gift reopen the conversation, and the radar shows the dip.
- Reachability: the debug command shows OK for all four sites after a fresh build.

## Risks

- Lua pathing for rescuers can glitch in cramped houses. Mitigation: stop at 2 nodes from the victim, time out after 8 seconds.
- Over-reaction: a tuned half-life of 1.5 days is a starting value for play testing.

## Later slices (hooks only)

- **B. Conflicts with real motive.** A `ties` map in `npcs.json` (friend, kin, supplier, debtor, rival). The game raises a quarrel from a seed (two needs for one scarce thing, a debt, a slight), the model voices it, and it escalates or resolves over days with or without you. Daily routines (forge at dawn, inn at dusk). Villagers learn your name only when you give it.
- **C. Audio.** Cues: a blow, a cry, a gasp, a crowd murmur, UI clicks, ambience, a winter wind that rises with the day clock. Needs a sound source plan and licensing.
- **D. Winter store and rationing.** A shared town-hall store, a daily draw, and the ration call. Scarcity is the main source of B's seeds.
