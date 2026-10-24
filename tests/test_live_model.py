"""Does the new behaviour hold with a live model? Run with NPCASSO_E2E=mubit (or ollama).

A live model is not deterministic, so these tests hold the invariants the game depends on and print the rates
that show how often the model gets there on its own: lines that pass validation, troubles that open, choices that
are asked, and ending scenes that use the villagers' own words. Credits are spent here; the default suite never runs
this file.

Run:  $env:NPCASSO_E2E="mubit"; .venv\\Scripts\\python -m pytest tests/test_live_model.py -q -s
"""
import json
import statistics

import pytest

from backend import db, game, situations
from backend.finale import ENDINGS
from backend.story import DIMENSIONS, SIGNATURES, add_evidence, anchor
from tests.test_endings_e2e import MODE, live_llm

pytestmark = pytest.mark.skipif(MODE not in ("ollama", "mubit"), reason="set NPCASSO_E2E=ollama or mubit")

P = "w:p"
CAST = ["elise", "rowan", "mira", "tobin", "wren", "pip", "bram", "nell", "corin", "hazel", "dax", "lottie"]


@pytest.fixture(scope="module")
def llm():
    return live_llm()


def calls(conn, task=None):
    rows = conn.execute("select * from interactions order by id").fetchall()
    return [r for r in rows if task is None or r["task"] == task]


def raw_json(row):
    try:
        return json.loads(row["reply"])
    except (TypeError, ValueError):
        return {}


def report(label, **stats):
    print(f"\n[live {MODE}] {label}: " + json.dumps(stats, ensure_ascii=False))


def test_an_ordinary_first_day_stays_ordinary(conn, llm):
    """Day one, nothing has happened: a hello is a hello. No hard choice, no score, no new trouble."""
    anchor(conn, P, 0.0)
    asked = 0
    for i, npc in enumerate(CAST[:5]):
        out = game.greet(conn, llm, "w", "p", npc, f"g{i}", 0.1 + i * 0.2)
        assert isinstance(out["reply"], str)
    for row in calls(conn, "npc_dialogue"):
        asked += bool((raw_json(row).get("choice") or {}).get("options"))
    open_now = conn.execute("select count(*) c from situations where player=?", (P,)).fetchone()["c"]
    report("day 1 greets", greets=5, choices_asked=asked, troubles_opened=open_now)
    assert open_now <= situations.CAP["open"]  # the cap holds whatever the model does
    assert asked <= 2  # a hello is not a dilemma; a rare slip is tolerated, a pattern is not


def test_troubles_open_between_two_people_and_hold_their_shape(conn, llm):
    """In the pressure season villagers raise troubles. Whatever they raise obeys the game's rules."""
    anchor(conn, P, 0.0)
    for i, npc in enumerate(CAST[:6]):
        game.greet(conn, llm, "w", "p", npc, f"g{i}", 2.1 + i * 0.25)
    rows = conn.execute("select * from situations where player=?", (P,)).fetchall()
    seen = set()
    for r in rows:
        involves = json.loads(r["involves"])
        assert 1 <= len(involves) <= 2 and r["opener"] not in involves
        assert not set(involves) & seen and r["opener"] not in seen  # nobody is in two open troubles
        seen |= {r["opener"], *involves}
        assert "newcomer" not in r["text"].lower() and r["text"].strip()
    assert len(rows) <= situations.CAP["pressure"]
    report("pressure greets", greets=6, troubles_opened=len(rows), cast=sorted(seen))
    assert rows, "six pressure-season greetings opened no trouble at all"


def test_an_answer_is_accepted_and_scored(conn, llm):
    """The player takes a side. The villager answers, the score is written, trust moves only by a fixed size."""
    anchor(conn, P, 0.0)
    for i, npc in enumerate(CAST[:6]):
        game.greet(conn, llm, "w", "p", npc, f"g{i}", 2.1 + i * 0.25)
    row = conn.execute("select * from situations where player=? and status='open' order by id", (P,)).fetchone()
    assert row, "no trouble opened to answer"
    involves = json.loads(row["involves"])
    side = involves[0]
    before = {n: db.get_trust(conn, n, P) for n in CAST}
    out = game.talk(conn, llm, "w", "p", row["opener"],
                    f"I will take it to {side.capitalize()}. They need it more than anyone, whatever it costs me.",
                    "ans", 3.8)
    assert out["reply"].strip()
    moved = {n: db.get_trust(conn, n, P) - before[n] for n in CAST}
    assert all(abs(d) <= max(situations.SIZE.values()) for d in moved.values())  # a consequence is bounded
    evidence = conn.execute("select dimension, weight from evidence where player=?", (P,)).fetchall()
    assert all(e["dimension"] in DIMENSIONS and -1 <= e["weight"] <= 1 for e in evidence)
    resolved = conn.execute("select status from situations where id=?", (row["id"],)).fetchone()["status"]
    report("answer", reply_ok=True, scored=len(evidence), resolved=resolved == "resolved",
           trust_moved={n: d for n, d in moved.items() if d})


@pytest.mark.parametrize("ending", list(SIGNATURES))
def test_each_ending_scene_with_the_live_model(conn, llm, ending):
    """The scene's frame is fixed; the villagers' lines are the model's, built from this run's memories."""
    anchor(conn, P, 0.0)
    for dim, sign in SIGNATURES[ending].items():
        add_evidence(conn, P, dim, float(sign), None, "live")
    db.add_memory(conn, "elise", P, 1, "gift", "the newcomer gave me bread", "witnessed", 1.0, 20, 1.0)
    db.add_memory(conn, "rowan", P, 2, "repair", "the newcomer put my anvil back", "witnessed", 1.0, 15, 2.0)
    db.add_memory(conn, "mira", P, 3, "gift", "the newcomer gave me roses", "witnessed", 1.0, 10, 3.0)
    scene = game.accept_ending(conn, llm, "w", "p", 6.5)
    assert scene["ending"] == ending and scene["slides"][-1]["text"] == ENDINGS[ending]["title"]
    lines = [s["text"] for s in scene["slides"] if s["kind"] == "line"]
    assert len(lines) == 3 and all(t.strip() for t in lines)
    fallback = sum(t == ENDINGS[ending]["fallback"] for t in lines)
    greeted = sum(t.lower().startswith(("welcome", "hello", "hi ")) for t in lines)
    report(f"ending {ending}", lines=len(lines), fallbacks=fallback, greetings=greeted,
           sample=lines[0][:90])
    assert fallback < 3, "every villager fell back to the fixed line: the model never spoke"


def test_a_whole_run_on_the_live_model(conn, llm):
    """Ten days at game speed: greetings, a gift and a theft, talk, a trouble answered, the gathering, the end.

    Reports how the model held up across the run: validation pass rate, retries, latency, tokens.
    """
    anchor(conn, P, 0.0)
    gift = game.record_event(conn, llm, {"world": "w", "player": "p", "type": "gift", "target": "elise",
                                         "details": {"item": "default:apple"}, "witnesses": ["elise"],
                                         "game_time": 0.2})
    game.react(conn, llm, "w", "p", gift["event_id"], gift["react"])
    theft = game.record_event(conn, llm, {"world": "w", "player": "p", "type": "theft", "target": "rowan",
                                          "details": {"item": "default:steel_ingot"}, "witnesses": ["rowan", "mira"],
                                          "game_time": 0.6})
    game.react(conn, llm, "w", "p", theft["event_id"], theft["react"])
    game.talk(conn, llm, "w", "p", "elise", "Where can I find the smith?", "t0", 0.7)
    t = 2.2
    for i, npc in enumerate(CAST[:6]):
        game.greet(conn, llm, "w", "p", npc, f"g{i}", t)
        t += 0.25
    opener = conn.execute("select opener from situations where player=? and status='open'", (P,)).fetchone()
    if opener:
        game.talk(conn, llm, "w", "p", opener["opener"], "I will help whoever has the least.", "ans", t)
    for dim, sign in SIGNATURES["last_place_at_the_table"].items():
        add_evidence(conn, P, dim, float(sign), None, "live")
    tick = game.tick(conn, llm, "w", "p", 7.2)
    assert tick["phase"] == "closing" and tick["offer"] is True
    scene = game.accept_ending(conn, llm, "w", "p", 7.2)
    assert scene["slides"][-1]["kind"] == "title"
    assert game.tick(conn, llm, "w", "p", 7.3)["phase"] == "ended"

    rows = calls(conn)
    dialogue = [r for r in rows if r["task"] == "npc_dialogue"]
    ok = [r for r in dialogue if (json.loads(r["validator_result"] or "null") or {}).get("ok")]
    retried = [r for r in dialogue if r["retried"]]
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
    errors = [r for r in rows if "error" in (json.loads(r["validator_result"] or "null") or {})]
    routed = [r for r in rows if r["mubit_request_id"]]
    report("whole run", calls=len(rows), dialogue=len(dialogue), valid=len(ok), retried=len(retried),
           transport_errors=len(errors), median_ms=int(statistics.median(latencies)),
           max_ms=max(latencies), tokens=sum(r["tokens"] or 0 for r in rows),
           with_mubit_request_id=len(routed))
    assert not errors, "transport errors against the live model"
    assert len(ok) >= 0.6 * len(dialogue), "fewer than 60% of dialogue lines passed validation"
    if MODE == "mubit":
        assert len(routed) == len(rows), "a call went out without a Mubit request id"
