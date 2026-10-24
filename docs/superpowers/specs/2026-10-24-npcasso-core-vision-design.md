# NPCasso — Core game vision

Date: 2026-10-24

The goal is not a traditional RPG with predefined quests, dialogue trees, and a story the player follows. NPCasso is a dynamically generated, single-player narrative in which the player lives through human conflicts, difficult choices, unsettling discoveries, and lasting consequences.

The game must feel like a world the player has discovered, not a story that is being explained to them.

## 1. Intent

The player arrives outside Bellwether knowing almost nothing. A controls-only tutorial book is the only text waiting for them. From then on, a model generates a unique run from the people, the circumstances, and what the player has already done. The start is the same every time. Five world endings, plus one optional Palimpsest ending, are the only ways out. The path between those boundaries is different every run, and it stays coherent because the prompts carry the world and the game remembers what happened.

Two players can start in the same place, meet different conflicts, and leave different histories. Both runs should feel authored.

## 2. Goals

1. **Fixed start.** The player begins just outside Bellwether. The book there explains controls and how to interact. It contains no lore, no quest, and no mystery.
2. **Discovery by interaction.** The player learns by walking, looking, and talking. No opening narration, no plot-revealing markers, no villager who explains the significance of everything.
3. **Early unease.** Fairly soon after they enter the village, something ordinary is slightly wrong. The model invents that detail. It is not the same opening mystery every run. The player should feel curious and uneasy before they understand why.
4. **Dynamic journey.** The model invents the conflicts, the revelations, and the outcomes of each run. It does not pick from a list of canned events. A situation has to follow from what people want, what they know, what is left to go around, and what the player has done.
5. **Human conflicts.** Most trouble is personal: secrets, debts, broken promises, scarce food or firewood, a kindness that harms someone else. Winter and the forgotten past do not explain every harm.
6. **Winter as pressure, and as the end of the run.** An approaching winter changes the village gradually. No countdown, no doom meter, and no one announces the day it breaks. Winter is what keeps the game from continuing without end. As it closes in, the player is forced toward one of the endings. Which one follows from the dimension score of that run.
7. **A world that remembers.** Deaths, promises, exposed secrets, lost supplies, and shifts in trust persist. Later events are built from that history. The story never invents a past action that did not happen.
8. **Twelve hidden tendencies.** What happens in the run builds a score across twelve dimensions. The score is never shown. Through the journey it colours how people read the player and what the next dilemma can press on. When the game is ending, that score is the structure the model uses to steer toward one of the five fixed endings.
9. **Five fixed world endings, one optional special ending.** The route to any of them is not a quest chain. Finishing the Palimpsest ends the game through that special ending and does not continue into the five.
10. **An epilogue of this run.** It may mention only the people, relationships, sacrifices, winter, and consequences that actually occurred.

## 3. Non-goals

- Predefined main quests, dialogue trees, and a plot the player is walked through.
- Quest markers that reveal the story.
- A visible morality meter or a personality quiz.
- A countdown or a fixed date for the winter.
- Making the Palimpsest the cause of every mystery, or a path every player must take.
- Extra principal endings invented during a run.
- Combat, a bestiary, or treasure as the point of a place.

## 4. Anti-goals

These are failures even if the game runs.

- The world is explained to the player instead of found.
- An encounter resets when the conversation ends.
- Kindness always earns gratitude, and selfishness always earns punishment.
- Every problem has a perfect answer.
- Every villager talks about the weather.
- A player who never visits a place still hears its secrets from someone else, unprompted.
- The epilogue mentions a deed, a death, a bond, or a sacrifice that never happened.
- The ending steer starts before the player has had time to understand the village.
- One early act locks an ending.
- The same predetermined opening mystery plays every run.
- A run can continue forever. Winter is what brings it to an ending.

## 5. Constraints

- **Boundaries.** The beginning is fixed. The five world endings and the two Palimpsest outcomes are fixed. Everything between them is generated.
- **The model decides the middle.** It invents the conflict and what follows: trust, food, firewood, promises, injury, death, and what happens if the player walks away. Those outcomes have to make sense given the run so far. They may be painful or ambiguous. They may surprise the player.
- **The prompts are the authorship.** Well-written system prompts carry Bellwether, the winter, the people, the twelve dimensions, the rule that explanations are withheld, and the fixed endings. That is what keeps a generated run inside a controlled shape.
- **Memory is mandatory.** The game stores the history of the run and gives that history back to the model. New events must be compatible with it.
- **Ignorance is real.** A fact the player has not encountered is not delivered as exposition.
- **Engine.** Do not change the engine for now. Build this in the game that already runs.
- **Time before the ending.** Winter arrives in stages, never in one step, counted from the day the player arrives. Day 1 is only the village. Days 2 to 5 are pressure, and no ending is forced. Days 6 to 9 steer the player toward the ending their score points to, and the cold starts to cost life, faster as day 10 nears. On day 10, if they have not taken an ending, they cannot sustain the cold and the run ends. Refusing the steered ending is this path. There is still no countdown. *(The clock shows the day. It does not announce these thresholds.)*
- **Day and time.** The game keeps the day and the time of day for the run. The player can see them on a clock. The clock does not name the winter stage. No text element covers another: each HUD line and each formspec line has its own box.

## 6. The start

The player is standing just outside Bellwether. The tutorial book teaches how to play and nothing else. They are there to go into the village and interact with it.

The first unsettling detail is the model's to invent, and it should be available fairly soon after they enter. The prompts ask for something small and unexplained: a place, an object, or a person who does not finish a thought. The tutorial never points at the winter, the priest, or the book in the town hall.

## 7. How a run proceeds

The player creates the journey by choosing what to engage with. Investigating, taking a side, making a promise, exploiting a shortage, or walking away are all decisions. Ignoring a conflict is a decision. The player is not required to follow a main quest.

What they meet might be a family hiding a secret, two neighbours fighting over a debt, someone stealing firewood, a request for help they cannot afford, or a person whose manner says something is wrong. These are events. A decision can cost trust, take a family's food, expose a secret, save a life, cause a death, create an obligation, or set two people against each other.

If the player refuses a family, that refusal remains. The family may stop trusting them, go to someone else, fall into a debt, or do something desperate. Which of those happens is up to the model and the circumstances. If the player helps, the person may become an ally, feel ashamed, grow dependent, or come back with a harder request.

Conflicts may continue when the player does nothing. The next situation should be personal to this run: the person they helped now asks for something costly, a secret they kept is found by someone else, an earlier choice has left a shortage that hits a family they have not met.

An hour with no priest and no Palimpsest is a valid game. So is an hour spent on the priest, the records, and a forgotten tragedy. Neither hour is a prescribed sequence.

## 8. Winter

Winter is one continuing pressure, not the whole story. It is felt before it is understood.

It shows up as frost, thin snow in the shade, freezing puddles, quieter paths, more smoke, a short woodpile, a farmer worried about the harvest, a shopkeeper rationing fuel, an inn closing earlier, a child pleased by the first snow while adults worry, a family arguing about whether to stay. Some people prepare, some deny it, some see a chance to profit. These signs accumulate. Do not have every character discuss them.

The model draws conflicts out of that pressure. A firewood shortage can force a choice between two families. A promise made earlier can become impossible when food runs short. Someone who seemed selfish before can become desperate. The player can help, hoard, exploit, protect one household, ignore the signs, or leave. Those acts change relationships, what is left, and the state of the village.

Passing time is shown by small changes to places the player already knows. A warm house later has boarded windows. A table has one fewer chair. A building goes neglected after its owner is gone.

Winter's severity comes from the circumstances and the choices people make. It is not automatically a supernatural apocalypse.

Winter is also why a run cannot go on forever. It does not arrive in one step. First the village is simply there. Then the cold is a pressure the player can feel and answer. Only after that pressure has already been part of ordinary life does the winter close in, and only then is the player forced toward an ending. Nobody states the day. Which ending they are forced toward follows from the dimension score of the run.

Refusing that ending does not start another life in the village. The player stays, and the cold takes life faster as day 10 approaches. On day 10 they cannot sustain it. The run ends in the freeze. Days are counted from the player's arrival, so an old world does not begin already frozen. The clock shows that day and the time of day. It does not name the stage.

## 9. People and what they know

Bellwether is a community. Each person has concerns, relationships, work, beliefs, fears, and ambitions. They can lie, misremember, repeat a rumour, or believe something false. Their accounts can contradict. Nobody is there to deliver the whole truth.

Ordinary conflicts include concealing a truth that would wreck a family, two legitimate claims on the same scarce thing, a broken promise with an understandable reason, a theft from someone even worse off, a friend who asks the player to lie, help that means abandoning another commitment, a wrongdoer who has also done good, forgiveness asked for before the harmed person can give it, and help that unintentionally hurts someone else.

There is often no perfect answer. The player is deciding how to live among these people.

Stories are also told by places: a locked room, an abandoned cart, a grave whose name disagrees with a record, a map that does not match the streets, a ruin that still holds the traces of an ordinary life, a person who changes the subject when a name is spoken. Some of this can stay unexplained.

## 10. The priest and the Palimpsest

The priest warns that terrible things happened here and that almost no one remembers them. Some villagers think he is losing his mind. Some pity him, avoid him, or suspect he is hiding a crime of his own. His claims can be partly true and partly wrong. He does not explain the mystery in one conversation. Clues can be found in different orders: records that disagree, ruins, objects, and people who remember different versions.

The Palimpsest is an ancient book, kept in the town hall and treated as sacred. It was made to soften unbearable memories. It was also used to erase inconvenient truths. It raises questions of consent, identity, forgiveness, and who may decide what a village forgets. It does not explain every tragedy. Many conflicts have ordinary human causes.

This is not a quest and it has no ending. The game ends in one of the five world endings, or in the freeze, which is an ordinary death.

## 11. The twelve dimensions

These are inferred from what the player does. They are never shown.

| Dimension | One pole | The other |
|---|---|---|
| Candor | Hide the truth | Say it |
| Bravery | Avoid the risk | Take it yourself |
| Compassion | Indifferent to suffering | Moved by it |
| Selflessness | Keep the gain | Give it up |
| Ambition | Accept a small role | Seek power or a mark |
| Ingenuity | Use the usual path | Find another way |
| Loyalty | Drop a commitment | Stand by a person or a principle |
| Pragmatism | Hold the ideal | Take the workable outcome |
| Curiosity | Accept the surface | Look for what is hidden |
| Justice | Let a wrong stand | Demand an account |
| Forgiveness | Keep the grievance | Offer another chance |
| Independence | Stay with the group or the authority | Choose your own path |

One act can move several. The reading depends on what the player knew, what else they could have done, what it cost, and whether they followed through. Do not infer the motive from the outcome alone. Helping can be compassion, loyalty, guilt, strategy, or a wish for influence. Refusing can be cruelty, fear, another obligation, or a practical limit.

People can change their minds. A compassionate player can grow pragmatic after losses. Someone can value truth until it threatens a person they love. Contradictions stay in the record. Through the open stretch, the record informs how villagers treat the player and how later dilemmas can challenge them.

The same record is a score. It is set by what actually happened in the run. When the game is ending, the model reads that score and steers toward the fixed ending that fits it. Finishing the Palimpsest still ends the game through that special ending instead.

## 12. The five world endings

These are destinations the broader story can arrive at. They are not five quests. One superficial act cannot determine one, and the player is not forced toward an ending until they have had time to understand the village, and the force is the winter closing in. The model generates the journey that gives an ending its meaning. It must not invent a sixth principal ending. When the ending comes, the model steers toward the fixed ending the dimension score points to, and the stored history is what the epilogue may use.

The tendencies below are that structure. Each ending is the destination for a score that leans that way.

1. **The Names We Buried.** Associated with candor, bravery, and loyalty. The player reveals a consequential truth, and the cost to someone they love or trust may be irreversible. Truth is gained and something irreplaceable is lost.
2. **The Last Place at the Table.** Associated with compassion, selflessness, and loyalty. There is a real shortage and no hidden way to save everyone. The player decides who is helped, which promises to keep, and what to give up. Kindness does not guarantee a happy ending. The village may recover, stagnate, or collapse.
3. **The Peace You Made.** Associated with ambition, pragmatism, and ingenuity. The player makes a settlement that genuinely improves ordinary life. That peace can rest on compromises, unequal power, or a buried truth people have learned to live with. It can help real people and still carry a moral cost.
4. **The Last Departure — Self-Exile.** The player leaves a world they helped shape. The world may still have a future. Someone who loves them asks them to stay, not because they are needed, but because they want them there. The player leaves anyway. They give up the right to decide what the future means. The emotional core is: this world deserves a future, but I can no longer be part of it.
5. **The End of All Things — Chaos.** A rare ending. Through a sustained pattern of choices, the player rejects the idea that the world should continue through suffering, obligations, and broken promises. An ancient mechanism, separate from the Palimpsest, can dissolve the world. Reaching it takes a chain of decisions and discoveries, not violence alone and not a hidden evil score. Someone the player once trusted, who remembers a real promise, can be part of the last confrontation. The world disappears and nobody remains to remember it. The statement is: this world does not deserve to exist. The game does not declare that right or wrong.

Winter, who survived, and the player's relationships shape the epilogue of whichever ending occurs. They do not multiply the endings into a catalogue of thin variants.

## 13. What success feels like

The player remembers a particular person and a particular choice: someone they failed, a promise they broke, a family they protected, a secret they found, or the moment a small decision changed a life. They felt the winter without a countdown. They found the lore instead of receiving it. The story feels like the life they lived in Bellwether.

## 14. Left to the builder

- The wording of the system prompts, as long as they carry the constraints in this document.
- How the run's history is stored and handed back to the model.
- How an ending, once the history supports it, is presented. The destinations themselves are fixed here. As built: from day 7 the village gathers and the player stands with them or walks away. Standing plays a short scene with fixed narration for that ending and one line each from the three villagers who remember the run most. Walking away leaves the cold to take the run.
- The exact early moment the first uneasy detail becomes available, as long as it is soon after entering the village and is generated, not canned.
