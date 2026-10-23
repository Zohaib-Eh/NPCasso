"""Evaluation harness. Runs scenarios through the real game pipeline and scores replies against game state.

    python -m eval.run --provider mock|local|mubit --split train|heldout|all --repeat N

Train runs double as Mubit example feeding; held-out messages are never used for that.
"""
import argparse
import json
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from backend import db, game
from backend.llm import make_llm

HERE = Path(__file__).parent


def load_scenarios() -> list[dict]:
    return json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))


def _last(conn, task, npc):
    rows = [r for r in db.list_interactions(conn, npc, 20) if r["task"] == task]
    return rows


def run_one(llm, sc: dict, msg, split: str) -> dict:
    npc, text = (msg["npc"], msg["text"]) if isinstance(msg, dict) else (sc["npc"], msg)
    world = f"eval-{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(str(Path(tmp) / "eval.db"))
        try:
            for ev in sc.get("setup", []):
                game.record_event(conn, llm, {"world": world, "player": "p", "game_time": 1.0, **ev})
            for t in sc.get("ticks", []):
                game.tick(conn, llm, world, "p", t)
            t0 = time.monotonic()
            out = game.talk(conn, llm, world, "p", npc, text, f"{world}:{npc}", 1.5)
            latency = int((time.monotonic() - t0) * 1000)
            dialogues = list(reversed(_last(conn, "npc_dialogue", npc)))  # oldest first
            intent_row = _last(conn, "intent_classify", npc)[0]
            shown = next((d for d in dialogues if d["validator_result"].get("ok")), None)
            claims = json.loads(shown["reply"]).get("claims", []) if shown else []
            flags = shown["validator_result"]["flags"] if shown else []
            try:
                intent = json.loads(intent_row["reply"]).get("intent")
            except (TypeError, ValueError):
                intent = None
            n_promises = len(db.open_promises(conn, npc, f"{world}:p", kind="promise"))
            tokens = sum(r["tokens"] or 0 for r in db.list_interactions(conn, None, 100))
            request_ids = [r["mubit_request_id"] for r in db.list_interactions(conn, None, 100) if r["mubit_request_id"]]
        finally:
            conn.close()

    exp, fails = sc["expect"], []
    types = {c.get("type") for c in claims}
    fails += [f"missing claim {t}" for t in exp.get("claims_include", []) if t not in types]
    fails += [f"forbidden claim {t}" for t in exp.get("claims_exclude", []) if t in types]
    for t, how in exp.get("claim_how", {}).items():
        if any(c.get("type") == t and c.get("how") != how for c in claims):
            fails.append(f"{t} claimed as {how!r} mismatch")
    if "intent" in exp and intent != exp["intent"]:
        fails.append(f"intent {intent} != {exp['intent']}")
    fails += [f"flag {f}" for f in exp.get("no_flags", []) if f in flags]
    if "db" in exp and n_promises != exp["db"]["open_promises"]:
        fails.append(f"open_promises {n_promises} != {exp['db']['open_promises']}")
    # Expectations about a different NPC than the scenario's (held-out cross-NPC) only check claims_exclude/no_flags
    if npc != sc["npc"]:
        fails = [f for f in fails if f.startswith(("forbidden", "flag"))]
    return {"scenario": sc["id"], "split": split, "npc": npc, "message": text, "reply": out["reply"],
            "passed": not fails, "fails": fails, "first_try_valid": bool(dialogues and dialogues[0]["validator_result"].get("ok")),
            "retried": len(dialogues) > 1, "latency_ms": latency, "tokens": tokens, "request_ids": request_ids}


def run_all(provider: str, split: str = "all", repeat: int = 1, llm=None) -> dict:
    llm = llm or make_llm(provider)
    splits = ["train", "heldout"] if split == "all" else [split]
    results = [run_one(llm, sc, m, sp) for _ in range(repeat) for sc in load_scenarios()
               for sp in splits for m in sc["messages"][sp]]
    n = len(results) or 1
    summary = {"provider": provider, "split": split, "scenarios": len({r["scenario"] for r in results}),
               "runs": len(results), "passed": sum(r["passed"] for r in results),
               "first_try_valid_rate": round(sum(r["first_try_valid"] for r in results) / n, 3),
               "avg_latency_ms": int(sum(r["latency_ms"] for r in results) / n),
               "total_tokens": sum(r["tokens"] for r in results)}
    return {"summary": summary, "results": results}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock", choices=["mock", "local", "mubit"])
    ap.add_argument("--split", default="all", choices=["train", "heldout", "all"])
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    out = run_all(a.provider, a.split, a.repeat)
    by = {}
    for r in out["results"]:
        by.setdefault(r["scenario"], []).append(r["passed"])
    for sc, ps in by.items():
        print(f"{sc:28} {sum(ps)}/{len(ps)}")
    print(json.dumps(out["summary"], indent=2))
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{a.provider}-{a.split}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
