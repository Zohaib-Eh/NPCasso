import pytest

from backend import db
from backend.game import record_event
from backend.llm import MockLLM
from tests.conftest import ScriptedLLM


def ev(t, **kw):
    return {"world": "w", "player": "p", "type": t, "target": "elise", "details": {"item": "default:apple"},
            "witnesses": [], "game_time": 1.0, **kw}


def test_witnessed_theft(conn):
    r = record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    assert db.get_trust(conn, "elise", "w:p") == -20
    assert r["notices"] == ["Elise will remember that."]
    assert r["shouts"] == [{"npc_id": "elise", "text": "Hey! I saw that!"}]
    mem = db.top_memories(conn, "elise", "w:p")[0]
    assert mem["how"] == "witnessed" and mem["text"] == "I saw them: theft"
    assert db.list_interactions(conn, "elise")[0]["task"] == "npc_react"


def test_unwitnessed_theft_unknown(conn):
    r = record_event(conn, MockLLM(), ev("theft"))
    assert db.get_trust(conn, "elise", "w:p") == 10 and r["notices"] == []
    assert db.top_memories(conn, "elise", "w:p") == []
    assert conn.execute("select count(*) from events").fetchone()[0] == 1


def test_loved_gift(conn):
    r = record_event(conn, MockLLM(), ev("gift", details={"item": "default:gold_ingot"}))
    assert db.get_trust(conn, "elise", "w:p") == 30 and r["notices"] == ["Elise will remember that."]
    assert db.top_memories(conn, "elise", "w:p")[0]["type"] == "gift"


def test_worlds_isolated(conn):
    record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    assert db.get_trust(conn, "elise", "w2:p") == 10


def test_react_llm_error_still_records(conn):
    r = record_event(conn, ScriptedLLM([None]), ev("theft", witnesses=["elise"]))
    assert r["shouts"] == []
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "theft by the newcomer"


def test_react_invalid_output_uses_template(conn):
    bad = {"shout": "Thief!", "memory": "m", "claims": [{"event_id": 999, "type": "gift", "how": "witnessed"}]}
    r = record_event(conn, ScriptedLLM([bad]), ev("theft", witnesses=["elise"]))
    assert r["shouts"] == [] and db.top_memories(conn, "elise", "w:p")[0]["text"] == "theft by the newcomer"


def test_walk_away_logged_only(conn):
    r = record_event(conn, MockLLM(), ev("walk_away", witnesses=["elise"]))
    assert r["notices"] == [] and db.top_memories(conn, "elise", "w:p") == []
    assert db.get_trust(conn, "elise", "w:p") == 10


def test_unknown_type_raises(conn):
    with pytest.raises(ValueError):
        record_event(conn, MockLLM(), ev("teleport"))
    with pytest.raises(ValueError):
        record_event(conn, MockLLM(), ev("theft", target="bob"))
