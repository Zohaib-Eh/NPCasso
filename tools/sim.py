"""Plays a scripted player against the real villagers on a throwaway database and prints what they said.

    python tools/sim.py thug|saint|lost|troll [--mock]

--mock uses the offline MockLLM, so the harness itself can be checked without a network.
"""
import json
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from backend import db  # noqa: E402
from backend.game import gossip, greet, name, react, record_event, talk  # noqa: E402
from backend.llm import MockLLM, make_llm  # noqa: E402

REQUEST = re.compile(r"bring me|could you bring|would you bring|i need you to|can you fetch", re.I)

SCENARIOS = {
    "thug": [("greet", "elise"), ("greet", "nell"), ("hit", "elise", ["elise", "nell"]),
             ("say", "elise", "hello?"), ("say", "elise", "sorry about that"), ("greet", "nell"),
             ("say", "nell", "what happened to Elise?"), ("wait", 1.0), ("greet", "elise"), ("greet", "mira"),
             ("gossip", "elise", "mira"), ("greet", "mira")],
    "saint": [("greet", "nell"), ("greet", "nell"), ("greet", "nell"), ("say", "nell", "anything I can help with?"),
              ("gift", "nell"), ("greet", "nell"), ("wait", 1.0), ("greet", "nell")],
    "lost": [("greet", "hazel"), ("say", "hazel", "I'm lost, what do I do?"), ("greet", "bram"),
             ("say", "bram", "where do I go?"), ("say", "bram", "what should I do next?")],
    "troll": [("greet", "elise"), ("say", "elise", "you're useless, you fool"), ("say", "elise", "I'll burn your stall"),
              ("say", "elise", "hello?"), ("say", "elise", "sorry, I didn't mean it"), ("wait", 1.0),
              ("greet", "elise")],
}


def words(text):
    return set(re.findall(r"[a-z']+", text.lower()))


def main(argv):
    mock = "--mock" in argv
    scenario = next((a for a in argv if a in SCENARIOS), None)
    if not scenario:
        sys.exit(__doc__)
    load_dotenv()
    llm = MockLLM() if mock else make_llm(os.getenv("LLM_PROVIDER", "mock"))
    conn = db.connect(os.path.join(tempfile.mkdtemp(), "sim.db"))
    now, lines, step_no = 1.0, [], 0

    def say_line(who, text):
        lines.append((who, text))
        print(f"  {who}: {text}")

    for step in SCENARIOS[scenario]:
        step_no += 1
        kind = step[0]
        thread = f"sim{step_no}"
        print(f"[t={now:.2f}] {' '.join(str(s) for s in step)}")
        if kind == "greet":
            say_line(name(step[1]), greet(conn, llm, "w", "p", step[1], thread, now)["reply"])
        elif kind == "say":
            print(f"  you: {step[2]}")
            say_line(name(step[1]), talk(conn, llm, "w", "p", step[1], step[2], thread, now)["reply"])
        elif kind in ("hit", "gift"):
            victim = step[1]
            e = {"world": "w", "player": "p", "type": "hit_npc" if kind == "hit" else "gift", "target": victim,
                 "witnesses": step[2] if kind == "hit" else [victim], "game_time": now,
                 "details": {"item": "default:apple"} if kind == "gift" else {}}
            r = record_event(conn, llm, e)
            for s in react(conn, llm, "w", "p", r["event_id"], r["react"])["shouts"]:
                say_line(name(s["npc_id"]), s["text"])
        elif kind == "gossip":
            g = gossip(conn, "w", "p", step[1], step[2], now, roll=0.0, llm=llm)
            print(f"  shared: {g['shared']}")
        elif kind == "wait":
            now += step[1]
        now += 0.02

    rows = conn.execute("select reply, latency_ms, validator_result from interactions "
                        "where task='npc_dialogue' and ifnull(retried,0)=0").fetchall()
    failed = sum(1 for r in rows if r["validator_result"] and '"ok": false' in r["validator_result"])
    lat = sorted(r["latency_ms"] or 0 for r in rows)
    texts = [t for who, t in lines if t]
    overlaps = [len(words(a) & words(b)) / max(1, len(words(a) | words(b)))
                for i, a in enumerate(texts) for b in texts[i + 1:]]
    print("\n--- measures ---")
    print(f"silent replies:      {sum(1 for _, t in lines if not t)}")
    print(f"validator failures:  {failed} of {len(rows)} calls")
    if lat:
        print(f"latency ms:          p50 {lat[len(lat) // 2]}  p95 {lat[min(len(lat) - 1, int(len(lat) * .95))]}")
    print(f"repetition (jaccard): {statistics.mean(overlaps):.2f}" if overlaps else "repetition: n/a")
    print(f"lines with a request: {sum(1 for t in texts if REQUEST.search(t))}")
    print(f"requests to model:   {len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1:])
