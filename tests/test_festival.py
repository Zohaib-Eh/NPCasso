import pytest

from backend import db, game, progress
from tests.conftest import ScriptedLLM


def make_eligible(conn, player="w:p"):
    for npc_id, cfg in db.load_config()["npcs"].items():
        q = next(q for q in cfg["quests"] if q["main"])
        db.add_promise(conn, "quest", npc_id, player, q.get("item"), 0, None, "[]", quest_id=q["id"], title=q["title"],
                       total=q["count"])
        conn.execute("update promises set status='done' where quest_id=?", (q["id"],))
    progress.add_xp(conn, player, 300, "test")


def test_vote_thresholds():
    assert [game.vote(t) for t in (30, 29, -10, -11)] == ["for", "abstain", "abstain", "against"]


def test_endings():
    assert game.ending(["for"] * 9 + ["abstain"] * 3) == "hero"
    assert game.ending(["for"] * 9 + ["against"]) == "accepted"
    assert game.ending(["for"] * 3 + ["against"] * 3) == "turned_away"


def test_festival_once_and_gated(conn):
    assert not game.festival_status(conn, "w:p")["eligible"]
    with pytest.raises(ValueError):
        game.hold_festival(conn, ScriptedLLM([]), "w", "p", 5.0)
    make_eligible(conn)
    assert game.festival_status(conn, "w:p")["eligible"]
    game.hold_festival(conn, ScriptedLLM([]), "w", "p", 5.0)
    assert game.festival_status(conn, "w:p")["held"]
    with pytest.raises(ValueError):
        game.hold_festival(conn, ScriptedLLM([]), "w", "p", 5.1)


def test_festival_vote_then_speeches_on_demand(conn):
    make_eligible(conn)
    for npc in ("elise", "mira", "tobin"):
        db.add_trust(conn, npc, "w:p", 40)
    for npc in ("rowan", "dax"):
        db.add_trust(conn, npc, "w:p", -40)
    llm = ScriptedLLM([{"reply": "You kept faith with me. I vote for you.", "claims": []}, None])
    r = game.hold_festival(conn, llm, "w", "p", 5.0)
    assert llm.calls == [] and len(r["votes"]) == 12 and r["ending"] == "accepted"
    v = {x["npc_id"]: x for x in r["votes"]}
    assert v["elise"]["vote"] == "for" and v["rowan"]["vote"] == "against"
    assert game.festival_speech(conn, llm, "w", "p", "elise") == {"speech": "You kept faith with me. I vote for you."}
    assert game.festival_speech(conn, llm, "w", "p", "pip") == {"speech": "I abstain."}  # LLM failed: fallback
    assert "you vote for" in llm.calls[0][1]["facts"]["situation"]
    assert any(m["text"] == "at the Harvest Festival the village accepted the newcomer"
               for m in db.top_memories(conn, "pip", "w:p", limit=20))


def test_festival_needs_level_3_only(conn):
    make_eligible(conn)
    conn.execute("update players set xp = 150")
    assert game.festival_status(conn, "w:p")["eligible"] and game.FESTIVAL_LEVEL == 3
