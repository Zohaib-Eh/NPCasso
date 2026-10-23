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


import json

from backend.game import NEUTRAL_LINE, talk

Q = {"intent": "question", "confidence": 0.5, "promise": None, "claim": None}


def dialogue_rows(conn):
    return [i for i in db.list_interactions(conn, "elise") if i["task"] == "npc_dialogue"]


def test_talk_recalls_theft(conn):
    record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    r = talk(conn, MockLLM(), "w", "p", "elise", "hello", "th1", 1.1)
    assert "I saw them: theft" in r["reply"]
    assert dialogue_rows(conn)[0]["validator_result"]["ok"]


def test_talk_retries_then_passes(conn):
    bad = {"reply": "Thanks for the bread!", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}]}
    good = {"reply": "Hello.", "claims": []}
    llm = ScriptedLLM([Q, bad, good])
    r = talk(conn, llm, "w", "p", "elise", "hi", "th1", 1.0)
    assert r["reply"] == "Hello."
    rows = dialogue_rows(conn)
    assert len(rows) == 2 and rows[0]["retried"] and rows[0]["prev_id"] == rows[1]["id"]
    assert llm.calls[2][1]["validator_feedback"] == ["invented_event:99"]


def test_talk_two_failures_neutral(conn):
    bad = {"reply": "x", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}]}
    assert talk(conn, ScriptedLLM([Q, bad, bad]), "w", "p", "elise", "hi", "th1", 1.0)["reply"] == NEUTRAL_LINE


def test_talk_malformed_llm_neutral(conn):
    assert talk(conn, ScriptedLLM([None, None, None]), "w", "p", "elise", "hi", "th1", 1.0)["reply"] == NEUTRAL_LINE


def test_apology_once_per_day(conn):
    r = talk(conn, MockLLM(), "w", "p", "elise", "sorry", "t", 1.0)
    assert r["notices"] == ["Elise noticed your apology."]
    assert talk(conn, MockLLM(), "w", "p", "elise", "so sorry", "t", 1.2)["notices"] == []
    assert db.get_trust(conn, "elise", "w:p") == 20
    talk(conn, MockLLM(), "w", "p", "elise", "sorry again", "t", 2.1)
    assert db.get_trust(conn, "elise", "w:p") == 30
    assert conn.execute("select source, verified from events where type='apology'").fetchone()["source"] == "llm_classified"


def test_promise_created(conn):
    talk(conn, MockLLM(), "w", "p", "elise", "I'll bring you 2 iron tomorrow", "t", 1.0)
    p = db.open_promises(conn, "elise", "w:p")[0]
    assert (p["kind"], p["item"], p["count"], p["deadline"]) == ("promise", "iron", 2, 2.0)


def test_unknown_promise_item_ignored(conn):
    talk(conn, MockLLM(), "w", "p", "elise", "I promise 3 dragons", "t", 1.0)
    assert db.open_promises(conn, "elise", "w:p") == []


def test_correction_confirmed(conn):
    talk(conn, MockLLM(), "w", "p", "elise", "hi", "t", 1.0)
    talk(conn, MockLLM(), "w", "p", "elise", "I never gave you bread", "t", 1.1)
    assert db.get_trust(conn, "elise", "w:p") == 15
    assert dialogue_rows(conn)[1]["outcome"] == "corrected"


def test_correction_rejected_when_event_true(conn):
    record_event(conn, MockLLM(), ev("gift", details={"item": "farming:bread"}))
    before = db.get_trust(conn, "elise", "w:p")
    llm = MockLLM()
    talk(conn, llm, "w", "p", "elise", "I never gave you bread", "t", 1.1)
    assert db.get_trust(conn, "elise", "w:p") == before


def test_low_confidence_ignored(conn):
    t = {"intent": "threat", "confidence": 0.4, "promise": None, "claim": None}
    talk(conn, ScriptedLLM([t, {"reply": "Hm.", "claims": []}]), "w", "p", "elise", "grr", "t", 1.0)
    assert db.get_trust(conn, "elise", "w:p") == 10


def test_threat_lowers_trust(conn):
    talk(conn, MockLLM(), "w", "p", "elise", "I will burn your stall", "t", 1.0)
    assert db.get_trust(conn, "elise", "w:p") == -5


def test_quest_offer_recorded(conn):
    offer = {"reply": "Bring coal.", "claims": [], "quest_offer": {"item": "coal", "count": 2, "reward": "bread"}}
    r = talk(conn, ScriptedLLM([Q, offer]), "w", "p", "elise", "any work?", "t", 1.0)
    q = db.open_promises(conn, "elise", "w:p", kind="quest")[0]
    assert r["quest_offer"]["item"] == "coal" and (q["count"], q["deadline"], q["reward"]) == (2, 3.0, "bread")


from backend.game import tick, trade_quote


def test_gossip_spreads_once(conn):
    record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    tick(conn, MockLLM(), "w", "p", 1.2)
    m = db.top_memories(conn, "mira", "w:p")[0]
    assert m["how"] == "told_by:elise" and m["reliability"] == 0.5 and m["type"] == "theft"
    assert db.get_trust(conn, "mira", "w:p") == -5
    tick(conn, MockLLM(), "w", "p", 1.3)
    assert len(db.top_memories(conn, "mira", "w:p")) == 1


def test_gossip_skips_npc_who_already_knows(conn):
    record_event(conn, MockLLM(), ev("theft", witnesses=["elise", "rowan"]))
    tick(conn, MockLLM(), "w", "p", 1.2)
    assert [m["how"] for m in db.top_memories(conn, "rowan", "w:p")] == ["witnessed"]


def test_unwitnessed_never_gossiped(conn):
    record_event(conn, MockLLM(), ev("theft"))
    tick(conn, MockLLM(), "w", "p", 1.2)
    assert db.top_memories(conn, "mira", "w:p") == []


def test_promise_kept_by_gifts(conn):
    db.add_promise(conn, "promise", "elise", "w:p", "iron", 2, 2.0)
    record_event(conn, MockLLM(), ev("gift", details={"item": "default:steel_ingot"}))
    r = record_event(conn, MockLLM(), ev("gift", details={"item": "default:steel_ingot"}))
    assert "Elise noticed you kept your word." in r["notices"]
    assert db.open_promises(conn, "elise", "w:p") == []
    assert db.get_trust(conn, "elise", "w:p") == 10 + 5 + 5 + 15


def test_promise_broken_after_deadline(conn):
    db.add_promise(conn, "promise", "elise", "w:p", "iron", 2, 2.0)
    assert tick(conn, MockLLM(), "w", "p", 1.9)["notices"] == []
    r = tick(conn, MockLLM(), "w", "p", 2.1)
    assert r["notices"] == ["Elise will remember that."]
    assert db.get_trust(conn, "elise", "w:p") == -10
    assert conn.execute("select status from promises").fetchone()["status"] == "broken"


def test_quest_done_gives_reward(conn):
    db.add_promise(conn, "quest", "rowan", "w:p", "coal", 1, 3.0, reward="pickaxe")
    r = record_event(conn, MockLLM(), ev("gift", target="rowan", details={"item": "default:coal_lump"}))
    assert r["give"] == [{"item": "default:pick_steel", "count": 1}]
    assert conn.execute("select status from promises").fetchone()["status"] == "done"


def test_quest_failed_after_deadline(conn):
    db.add_promise(conn, "quest", "rowan", "w:p", "coal", 1, 3.0, reward="pickaxe")
    tick(conn, MockLLM(), "w", "p", 3.5)
    assert db.get_trust(conn, "rowan", "w:p") == 0


def test_trade_quote_itemstrings(conn):
    q = trade_quote(conn, "w", "p", "elise", True)
    assert q == {"ok": True, "give": {"item": "default:apple", "count": 3},
                 "cost": {"item": "default:steel_ingot", "count": 2}}
    assert trade_quote(conn, "w", "p", "rowan", False) == {"ok": False, "reason": "no_work_block"}
