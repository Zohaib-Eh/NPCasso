"""Sends Mubit a lot of varied traffic through the game's own code, so each task collects the kept
examples its adapter trains on (first training starts at 25 kept examples per task).

    python tools/feed_mubit.py [--scenarios 40] [--workers 4] [--seed 1] [--mock]

Every scenario is one made-up player on a throwaway database, talking to villagers, hitting, stealing,
gifting, promising and apologising. The prompts and context are exactly what the game sends, so the calls
land in the same three tasks. Do not edit the system prompts between runs: Mubit groups a task by its
prompt, and a changed prompt starts a new group.
"""
import argparse
import json
import os
import random
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from backend import db  # noqa: E402
from backend.game import CONFIG, greet, react, record_event, talk  # noqa: E402
from backend.llm import MockLLM, make_llm  # noqa: E402

NPCS = list(CONFIG["npcs"])
PLAIN = ["How is business today?", "Do you sell anything this week?", "How long have you lived here?",
         "Is the road to the pond safe?", "Who looks after the inn?", "What is the weather doing?",
         "Where can I find the orchard?", "Is it always this quiet here?", "What is that smell?",
         "Is there anything I can help you with?", "Do you need a hand with anything?", "What do you do all day?",
         "Which way is the mine from here?", "Hello, who are you?", "Any news from the other end of the village?"]
STATEMENTS = ["I came past the orchard on my way here and half the trees were bare.",
              "Winter feels close already, the mornings have an edge to them now.",
              "I passed the forge earlier and nobody looked up from their work.",
              "Nobody seems to have much to spare at the stalls this week, I noticed that.",
              "I have been walking the village all morning and it is stranger than I expected.",
              "The pond looked very still when I went by, almost like glass already."]
PROMISES = ["I'll bring you {n} {item} tomorrow, I promise.", "I will bring {n} {item} before the end of the day.",
            "Give me a day and I'll bring you {n} {item}."]
APOLOGIES = ["I'm sorry about before, I let my temper get the better of me.",
             "Sorry for what I did, it was wrong of me and I mean it.", "I apologise, truly, it won't happen again."]
INSULTS = ["You're useless and your work is a joke.", "Everyone says you're a fool, and they are right.",
           "What a stupid thing to say, you idiot."]
THREATS = ["Keep talking and I will burn this place down.", "One more word and I'll hurt you.",
           "I could kill the lot of you and nobody would stop me."]
CORRECTIONS = ["I never took anything from your stall, you have the wrong person.",
               "That never happened, I did not hit anyone.", "I never gave you any gift, why do you think I did?"]
LOST = ["I'm lost, what do I do next?", "What should I do now? I don't know where to start."]
ITEMS = ["apples", "wheat", "coal", "flour", "iron", "roses"]


def script(rng: random.Random) -> list[tuple]:
    """One player's afternoon: some hellos, some small talk, one thing that goes wrong, some making up."""
    a, b = rng.sample(NPCS, 2)
    steps = [("greet", a), ("say", a, rng.choice(PLAIN)), ("say", a, rng.choice(STATEMENTS)),
             ("greet", b), ("say", b, rng.choice(PLAIN))]
    for _ in range(rng.randint(2, 4)):
        steps.append(("say", a, rng.choice(PLAIN + STATEMENTS)))
    if rng.random() < 0.7:
        steps.append(("say", a, rng.choice(PROMISES).format(n=rng.randint(1, 5), item=rng.choice(ITEMS))))
    if rng.random() < 0.4:
        steps.append(("say", b, rng.choice(LOST)))
    mood = rng.choice(["hit", "theft", "vandal", "gift", "hit", "theft", "insult"])
    others = [n for n in NPCS if n not in (a, b)]
    near = [a] + rng.sample(others, rng.randint(1, 2))
    if mood == "hit":
        steps += [("event", "hit_npc", a, near, {}), ("wait", 0.05), ("say", a, rng.choice(APOLOGIES)),
                  ("say", a, rng.choice(CORRECTIONS)), ("wait", 0.6), ("greet", a)]
    elif mood == "theft":
        steps += [("event", "theft", a, near, {"item": "default:apple"}), ("say", a, rng.choice(APOLOGIES)),
                  ("wait", 0.6), ("greet", a)]
    elif mood == "vandal":
        steps += [("event", "vandalism", "rowan", ["rowan"] + near[1:], {}), ("say", "rowan", rng.choice(APOLOGIES)),
                  ("greet", "rowan")]
    elif mood == "gift":
        steps += [("event", "gift", a, [a], {"item": "default:apple"}), ("say", a, rng.choice(PLAIN)),
                  ("greet", a)]
    elif mood == "insult":
        steps += [("say", a, rng.choice(INSULTS)), ("say", a, rng.choice(THREATS)),
                  ("say", a, rng.choice(APOLOGIES)), ("wait", 0.6), ("greet", a)]
    steps += [("say", a, rng.choice(PLAIN + STATEMENTS)), ("say", b, rng.choice(STATEMENTS))]
    c, d = rng.sample(others, 2)  # a second incident somewhere else: more reactions to learn from
    kind = rng.choice(["hit_npc", "theft", "gift", "vandalism"])
    target = "rowan" if kind == "vandalism" else c
    steps.append(("event", kind, target, [target] + [d] * (d != target), {"item": "default:apple"} if kind in ("theft", "gift") else {}))
    return steps


def play(n: int, rng_seed: int, llm, stop: threading.Event) -> list[dict]:
    rng = random.Random(rng_seed)
    conn = db.connect(os.path.join(tempfile.mkdtemp(), f"feed{n}.db"))
    world, player, now, thread = f"feed{n}", "p", 1.0, 0
    for step in script(rng):
        if stop.is_set():
            break
        thread += 1
        tid = f"feed{n}-{thread}"
        kind = step[0]
        if kind == "greet":
            greet(conn, llm, world, player, step[1], tid, now)
        elif kind == "say":
            talk(conn, llm, world, player, step[1], step[2], tid, now)
        elif kind == "event":
            out = record_event(conn, llm, {"world": world, "player": player, "type": step[1], "target": step[2],
                                           "witnesses": step[3], "details": step[4], "game_time": now})
            if out.get("react"):
                react(conn, llm, world, player, out["event_id"], out["react"])
        elif kind == "wait":
            now += step[1]
        now += 0.05
    rows = [dict(r) for r in conn.execute(
        "select task, retried, latency_ms, tokens, mubit_request_id, validator_result from interactions")]
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=40)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    llm = MockLLM() if args.mock else make_llm(os.getenv("LLM_PROVIDER", "mock"))
    stop, rows, lock, done = threading.Event(), [], threading.Lock(), [0]
    t0 = time.monotonic()

    def run(i):
        if stop.is_set():
            return
        try:
            got = play(i, args.seed * 1000 + i, llm, stop)
        except Exception as e:  # one broken scenario must not end the run
            print(f"  scenario {i} stopped: {type(e).__name__}: {e}")
            return
        text = " ".join(str(r["validator_result"]) for r in got)
        if any(w in text for w in ("429", "insufficient", "quota", "credit")):
            print(f"  scenario {i}: Mubit is refusing calls (limit or credit). Stopping.")
            stop.set()
        with lock:
            rows.extend(got)
            done[0] += 1
            calls = Counter(r["task"] for r in got)
            print(f"  scenario {i} done ({done[0]}/{args.scenarios}): {dict(calls)}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, range(args.scenarios)))

    print(f"\n--- {len(rows)} calls in {time.monotonic() - t0:.0f}s ---")
    for task in ("npc_dialogue", "npc_react", "intent_classify"):
        mine = [r for r in rows if r["task"] == task]
        errors = sum(1 for r in mine if '"error"' in str(r["validator_result"]))
        ok = sum(1 for r in mine if '"error"' not in str(r["validator_result"]) and
                 '"ok": false' not in str(r["validator_result"]))
        ids = sum(1 for r in mine if r["mubit_request_id"])
        lat = sorted(r["latency_ms"] or 0 for r in mine)
        p50 = lat[len(lat) // 2] if lat else 0
        print(f"{task:16} calls {len(mine):4}  valid {ok:4}  errors {errors:3}  mubit ids {ids:4}  p50 {p50} ms")


if __name__ == "__main__":
    main()
