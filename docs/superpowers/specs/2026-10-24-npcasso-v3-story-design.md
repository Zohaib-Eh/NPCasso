# NPCasso v3 — Bellwether: dilemmas, dimensions, endings (Godot)

Date: 2026-10-24 · Builds on v1 and v2 specs. Code freeze: Sun 2026-10-25 10:00.
The v1 core principle still binds: **the LLM proposes and voices; the game verifies and decides.**

## 1. Intent

NPCasso becomes a short, intense, story-driven RPG set in the village of **Bellwether**. The start is fixed, the five endings are fixed, and everything between them is generated. The LLM invents **philosophically hard dilemmas** out of the player's real relationships. The game records each choice as evidence on twelve personality dimensions. Near the end, the story naturally converges on the ending that the player's dimensions describe, and it finishes with a cutscene and an epilogue built from what really happened.

The player's words, in short:

- Choices must be hard. No right answer, no hidden perfect solution.
- The middle must not nudge toward anything predetermined. It should move smoothly and unpredictably, like life.
- Example of the feel: a farmer hoards grain because last winter nearly killed his family. He tells you because he trusts you. Then you learn someone else is starving and grain is short. Do you break his trust or keep it?
- Get into the heat fast. Little build-up.
- Toward the end, steer naturally toward an ending based on the player's dimensions. It ends in a cutscene.

The frontend moves to **Godot 4** (player's decision: Minecraft-style visuals don't suit these endings). The Python backend, SQLite, the LLM layer and Mubit stay.

## 2. Goals

1. **Fixed start (≈2 min).** A short opening cutscene. The player arrives in Bellwether at dusk on Tobin's grain cart. They helped Tobin on the road, so he already trusts them (start trust: friendly). The village is in a grain shortage from the first frame: half-empty market, a notice at the town hall about rationing. The first dilemma (Tobin's hidden grain) is authored and starts in the first conversation with Tobin.
2. **Generated middle (long: about 8–12 dilemmas, 45–90 min).** *(Player's decision: keep it long. The video is a trailer cut from footage, and the debug panel can trigger anything.)* Dilemmas overlap: the next can start before the last one's consequences settle. After the first, each dilemma is proposed by the LLM from the current world state and validated by the game (section 4).
3. **Twelve dimensions as evidence** (section 5). Never shown as a stat screen.
4. **Natural convergence** (section 6). After at least 6 resolved dilemmas, if one ending's signature clearly leads, the director starts building that ending's climax.
5. **Fixed endings with cutscenes** (section 7). Five authored endings. Each ends in a cutscene and an epilogue built from verified events.
6. **The world moves without the player.** An ignored dilemma resolves itself after a time limit (e.g. the starving man's condition worsens, then he dies). Gossip spreads. Moods shift. The player can walk away from a dilemma; walking away is also a choice and is recorded as one.
7. **Playable in Godot** (section 8). One compact village, a third-person player, 6–7 villagers, dialogue, cutscenes.
8. **Every demo LLM call goes through Mubit.**
9. **Filmable.** The deliverable is an edited video of clips, not a live run (player's decision). Every ending and its cutscene must be reachable on demand for recording: a debug panel (F1) can seed evidence for a chosen ending profile, skip to the climax, replay any cutscene, and take a free camera for b-roll. The generated middle still runs for real on camera, with real LLM calls via Mubit.

## 3. Non-goals

- The Palimpsest questline and its two outcomes. Deferred; the priest may appear as atmosphere only.
- Combat, monsters, XP, levels, crafting, trading, the quest board. The Luanti v2 features stay in the Luanti build, frozen.
- Porting the Luanti village or skins to Godot.
- Save slots. One save per world name, as today.
- Free roaming with pathfinding for every villager.

## 4. Anti-goals (a failure even if it works)

- A dilemma with an obviously right answer, or one where a clever option saves everyone at no cost.
- The director steering toward an ending before convergence (section 6). In the open middle, dilemma choice must not look at ending scores.
- The LLM deciding consequences, evidence, or the ending.
- An ending triggered just because a score crossed a line. The climax always requires a final choice by the player.
- A long slow intro. The first dilemma must be live within 3 minutes of starting.
- A cutscene or epilogue mentioning something that never happened.

## 5. Dilemmas

### Shape

A dilemma is a collision between what one villager **trusts you with** and what another villager **needs**. Every dilemma has:

- `holder`: the villager who confides (must have trust ≥ friendly).
- `secret` or `commitment`: what you are trusted with (grain hoard, a past crime, an affair, a debt).
- `affected`: one or more villagers whose need collides with it.
- `stakes`: what happens if nobody acts (the deadline outcome).
- `options`: 2–4 choices. Each maps to one **action kind** from a fixed list. The game owns the consequences of each action kind.
- `deadline`: game time after which the `stakes` outcome happens on its own.

### Action kinds (fixed, game-owned)

`keep_secret`, `reveal_to(npc)`, `reveal_publicly`, `give_own(item, to)`, `take(item, from, to)`, `persuade(holder)` (risky: success decided by the game from trust and dimensions, not the LLM), `confront(npc)`, `forgive(npc)`, `walk_away`.

**Reconciliation** *(builder's call)*: a dilemma whose options include `forgive(npc)` is a reconciliation offer. This covers a villager who wronged the player or a villager apologising. Choosing `confront` or `walk_away` on it adds 1 to `chaos_marks`. The game marks a dilemma as a reconciliation by checking for a `forgive` option, so `dilemma_propose` needs no extra field. Once the player has wronged at least one villager, the prompt asks for a reconciliation offer at least every other dilemma.

### Resources and life *(builder's call)*

The backend owns a small resource model. Godot only displays it.

- **Village grain stock:** an integer in `story.flags`.
- **The player's satchel:** a `satchel` table with grain, bread, coin and a few named items. Godot shows it as a strip in the dialogue window.
- **NPC state:** `npcs` gains `alive` and `condition` (`well|hungry|starving|sick`). Conditions worsen as a dilemma's stakes play out. A starving villager whose deadline passes dies.
- **"Something the player needs":** the satchel's grain plus bread is ≤ 1 day's ration (2 units) before giving. Giving it counts as a full cost.
- **Dead villagers:** they leave the scene, and a grave marker with their name appears in the graveyard. They can never appear in later dilemmas. They are listed in the ending facts.

Each action kind has a deterministic effect in `rules`: trust deltas for everyone who learns of it, resource moves, memories created, follow-up flags (e.g. `tobin_betrayed`, `corin_fed`), and evidence (section 6). Witnesses and gossip work as today, so a betrayal can be found out later.

### Who proposes them

- **Dilemma 1 is authored:** Tobin's grain versus Corin starving.
- **Later dilemmas** come from a new LLM task, `dilemma_propose`. Input: villagers with trust bands, open grievances, recent consequences, resources, and the flags from earlier dilemmas. Output: a dilemma in the shape above.
- **Validation:** all NPCs exist and are alive. The holder has trust ≥ friendly. Items exist. Every option uses a valid action kind. There are 2–4 options. If validation fails, the game retries once, then uses an authored fallback from a pool of 4 (`backend/dilemmas.json`).
- The prompt asks for dilemmas that **grow out of the consequences of the previous ones** (Tobin found out you told; now his family is the one going hungry). That is what makes the story feel like life rather than a quest chain.
- **Hardness rule, checked by the game:** every option must cost something. At least one villager loses trust or a resource with each option, `walk_away` included. A proposal where some option has no losers is rejected.

### How the player meets them

- The holder starts the conversation: the confession is voiced by the existing `npc_dialogue` task, with the secret given as facts.
- The affected villager's need is made visible in the world: a scene, a line, an object. For example, Corin collapsing by the well.
- Choices appear as **explicit options in the dialogue window**. Free-text talk still works for everything else.
- Only one dilemma is active at a time. The next is proposed when the current one resolves (by a choice or its deadline), after a short breather of about 30 s.

## 6. Dimensions, evidence and convergence

### Evidence

The twelve dimensions are: Candor, Bravery, Compassion, Selflessness, Ambition, Ingenuity, Loyalty, Pragmatism, Curiosity, Justice, Forgiveness, Independence.

Each resolved choice writes evidence rows: `(player, dimension, weight -1..+1, confidence 0..1, event_id, note)`. Weights come from a deterministic table per action kind, adjusted by context:

- **Cost to the player:** `give_own` of something the player needs counts more than giving a surplus.
- **Voluntary or not:** a `walk_away` caused by the deadline passing counts less than choosing it.
- **What the player knew:** the evidence notes which facts the player had been told.

Example: revealing Tobin's hoard so Corin can eat gives Candor +, Compassion +, Justice +, Loyalty − (toward Tobin).

There is no LLM in this step.

### Ending signatures (agreed with the player)

| Ending | Signature |
|---|---|
| 1. The Names We Buried | Candor +, Bravery +, Loyalty + |
| 2. The Last Place at the Table | Compassion +, Selflessness +, Loyalty + |
| 3. The Peace You Made | Ambition +, Pragmatism +, Ingenuity + |
| 4. The Road That Goes On (self-exile; the opposite of Chaos) | Independence +, Forgiveness +, Compassion +, Ambition − |
| 5. The End of All Things (chaos) | Forgiveness −, Compassion −, Independence +, plus ≥ 2 rejected reconciliations (`chaos_marks`) |

### Convergence (the steer)

- The match score for each ending is the mean of the confidence-weighted evidence on its signature dimensions, with signs applied.
- **Open phase:** until at least 6 dilemmas are resolved, `dilemma_propose` gets no ending information at all. It also stays blind in the converging phase until a destination is set *(builder's call; the player wants no nudging, only a late steer)*.
- **Converging phase:** from then on, if the top ending leads the next by a clear margin (builder tunes it; start at 0.15) and its score is > 0, that ending becomes the **destination**. Chaos additionally requires `chaos_marks` ≥ 2.
- If no ending leads clearly, another open dilemma follows. After 12 resolved dilemmas, the top score wins.
- Once a destination is set, the next dilemma is the **climax**: an authored template for that ending, filled with the player's real villagers and history. The destination never changes after it is set.
- **Tie-breaking:** if scores are exactly equal, use the order 1, 2, 3, 4, 5.

## 7. Climaxes, endings and cutscenes

The core idea and emotional impact of each ending, in the player's own words:

| Ending | Core idea | Emotional impact |
|---|---|---|
| 1. The Names We Buried | Reveal the truth, even when justice comes at the cost of someone you love. | Truth can set the world free and still leave you alone. |
| 2. The Last Place at the Table | Try to save everyone you love when there isn't enough to go around. | The people you save, and the person you couldn't, stay with you. |
| 3. The Peace You Made | Build a lasting peace through compromises that may become injustices of their own. | You create a better world, but question what you sacrificed to get it. |
| 4. The Road That Goes On | Help people build a future that no longer depends on you. | You discover that being needed isn't the same as being loved. |
| 5. The End of All Things | Reject the world's endless cycle of suffering and destroy its possibility of a future. | You end suffering by ending everything that could give life meaning. |

Every cutscene and epilogue must deliver its row's emotional impact.

Each climax is a final, irreversible choice. The ending is committed only when the player makes it.

1. **The Names We Buried:** reveal the consequential truth the player knows (from the flags) to the village, at the cost of the villager they're closest to. Choosing to stay silent instead commits the same ending in its darker variant: the truth stays buried.
2. **The Last Place at the Table:** the final shared meal. There are fewer portions than chairs. The player chooses who goes without, possibly themselves. There is no option that feeds everyone.
3. **The Peace You Made:** the player proposes the rationing order that ends the feud. It works, but it requires suppressing a truth or granting power to one person. The player chooses which.
4. **The Road That Goes On:** the village can now run itself without the player. The game sets this from flags: villagers the player taught, mediated for or handed authority to. The opposite of Chaos: hope in a future, just without you. A loved villager (highest trust) asks the player to stay, not because they need them but because they want them there. The player learns that being needed isn't the same as being loved. They choose to leave or to stay.
5. **The End of All Things:** the old mechanism beneath the bell tower (builder names it; distinct from the Palimpsest). The villager with the oldest real promise to the player asks if nothing was worth saving. The player activates it, or doesn't. The player activates it, or doesn't.

**Refusing a climax** *(player's decision: give them the choice, then trigger the ending)*: every climax offers the destination's act and the option to refuse it. That final choice is what the player thinks, and it is final. The game records it as evidence and commits the ending at once, with no second climax:
- Taking the act commits the destination ending.
- Refusing re-scores the endings without the destination and commits the top remaining one. Its full cutscene and epilogue play, and the facts include the refusal, so the epilogue can mention it. For example, the player stays instead of leaving, and gets Ending 2 with the empty chair at the table.
- Ending 1 is the exception: staying silent is its darker variant, not a refusal.

**Committing:** the ending, its variant, and the supporting facts (event ids) are written to an `endings` row. From then on it never changes.

**Cutscene:** a Godot scene per ending: camera path, letterbox, music, 3–5 shots. Each shot is staged with the real villagers involved: the empty chair is Corin's, the grave bears Tobin's name.

**Epilogue:** a new LLM task, `epilogue_narrate`, writes 4–6 short lines from the committed facts only. It is validated like other replies: any claimed event must exist. If validation fails, an authored template epilogue filled from the facts is used instead.

## 7a. Emotional payoff (the reason for the references)

The player picked Elden Ring, Silksong, Expedition 33 and Hollow Knight because their **endings are emotionally strong**. The rules NPCasso takes from them:

- **The ending is about people you know, not the world.** Every climax and epilogue centres on the 2–3 villagers with the strongest relationship to the player: highest trust, deepest grievance, or most shared history.
- **The final choice hurts someone you love.** Each climax puts the two villagers closest to the player on opposite sides wherever the template allows, as in Expedition 33's ending.
- **Callbacks to small moments.** The game marks small verified moments as **keepsakes**: the first bread Tobin shared, a promise kept, a gift loved. These are `keepsake` flags on events, set by rules, not the LLM. Climaxes, cutscenes and epilogues call them back: the same bread on the final table, the promise quoted word for word.
- **Lives that ended off-screen.** As in Elden Ring, a villager's fate can play out while the player is elsewhere, and the epilogue names it plainly.
- **Quiet after the storm.** Every ending cutscene ends with a long, quiet, ordinary shot: a table, a grave, a road. No victory screen.
- **Music motif:** one recurring theme from the opening, returning in a changed form in each ending.

## 8. Godot frontend

- **Godot 4** (latest stable 4.x), GDScript, in `godot/` alongside `luanti/`. The Luanti build is kept as-is.
- **One compact village scene:** square with a well, town hall with a notice board, Tobin's farm and granary, an inn, a few houses, a bell tower, a graveyard. Use free assets with verified CC0 or CC-BY licences (Kenney, Quaternius, Poly Pizza, or similar), listed in `godot/CREDITS.md`.
- **Mood:** a world full of people, not a wordless one (player's decision). Villagers talk, call out, argue and gossip within earshot. Lighting runs dusk to night, with fog, warm window light, ambient sound and a music bed.
- **Player:** third-person controller and camera. Interact prompt when facing a villager within about 2.5 m.
- **Villagers:** 6–7 from the existing cast: Tobin (farmer), Corin (fisher), Bram (elder), Wren (guard), Nell (baker), Hazel (herbalist), Mira (innkeeper). They stand at their posts with idle animations, turn to face the player, and walk only in scripted moments. Gossip is simulated in the backend tick rather than by physical meetings.
- **Dialogue UI:** speaker name, line, choice buttons when a dilemma is active, free-text input otherwise.
- **Notices:** a bottom-left feed ("Tobin will remember that.").
- **Cutscenes:** opening, the stakes moments (e.g. Corin collapses), climax, ending.
- **Backend link:** an `Api` autoload using `HTTPRequest` with JSON and a timeout. If the backend is down, show a clear on-screen message.

## 9. Backend changes

Reused unchanged: db and migrations, events, memories, witnesses, gossip, trust and moods, `npc_dialogue`, `intent_classify`, `npc_react`, the validator and the Mubit client.

New:

- **Tables:**
  - `dilemmas` (id, player, status, holder, payload json, deadline, chosen_option, resolved_at)
  - `evidence` (described in section 6)
  - `story` (player, phase `open|converging|climax|ended`, destination, resolved_count, chaos_marks, flags json)
  - `endings` (player, ending, variant, facts json, epilogue)
- **Modules:**
  - `backend/story.py`: director, convergence and endings.
  - `backend/evidence.py`: weights.
  - `backend/dilemmas.json`: the authored first dilemma, fallbacks and climax templates.
- **LLM tasks:** `dilemma_propose` and `epilogue_narrate`. These are new Mubit task groups. The model must stay the same as for the existing tasks.
- **Endpoints:**
  - `GET /story?world&player`: phase, the active dilemma for the UI, destination if any (debug only), ending if committed.
  - `POST /dilemma/choose {world, player, dilemma_id, option_id}`: returns consequences, notices and the next state.
  - `POST /tick` (extended): handles dilemma deadlines and proposes the next dilemma.
  - `GET /ending?world&player`: ending, variant, facts and epilogue lines for the cutscene.
- **Tests (mock LLM):** evidence weights, convergence (including no destination before 6 dilemmas and destination stability), hardness validation, deadline resolution, ending commitment, and the epilogue fallback.

## 10. Constraints

- Code freeze Sun 10:00, and the video must be cut before then. Order of work:
  1. The backend story loop, with tests.
  2. The Godot scene with dialogue.
  3. The debug panel.
  4. Cutscenes.
  5. Look and sound polish.
  6. Filming.
- **Robust as well as filmable.** The repo goes on GitHub, and others may clone and play it. A full playthrough must work start to finish with no debug panel. LLM failures fall back cleanly, and the backend being down shows a clear message. The README must give accurate setup steps for both the backend and the Godot project. Debug tools are for filming only.
- **Cut order** if time runs short:
  1. Free-text talk in Godot.
  2. Endings 4 and 5 get one shared cutscene, with per-ending text.
  3. Generated dilemmas after the first two: play authored ones instead, but film at least one generated dilemma for the Mubit story.
- **Fallback:** if the Godot build isn't filmable by Sat 23:00, film the story loop in the existing Luanti build instead. This is a contingency only. Nothing is built for it in advance. The story endpoints are client-neutral JSON, so a Luanti talk-window hookup could be added in about an hour if needed *(builder's call)*.
- No API keys in Godot. Godot talks only to the local backend.
- No new Python dependencies.

## 11. Decisions

The player decided:

- Godot frontend; backend kept.
- Fixed start, fixed endings, a generated middle.
- Hard dilemmas that come from trust, with no nudging in the middle.
- A fast start.
- A late steer by dimensions.
- Cutscene endings.
- The ending signature table in section 6, including the two the builder proposed.

Builder's calls:

- Dilemma count: 8–12, with convergence from 6 and a cap of 12.
- Arrival on Tobin's cart.
- The Palimpsest deferred.
- A cast of 7 villagers.
- Explicit choice buttons for dilemmas.
- Convergence margin 0.15.
- Climax designs and fallback variants.
- Gossip simulated in the tick.
- The fallback-demo cutoff time.

## 12. Left to the builder

- Exact evidence weights.
- Deadline lengths.
- Asset choice.
- The village layout.
- Cutscene shot lists.
- Names for the chaos mechanism.
- Prompt wording.
- The 4 fallback dilemmas.
- Whether the priest appears as atmosphere.
