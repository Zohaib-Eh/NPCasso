import pytest

from backend import db
from backend.game import react, record_event
from backend.llm import MockLLM
from tests.conftest import ScriptedLLM


def fire(conn, llm, e):
    """Record an event, then run the NPC reactions the way the game does (two calls)."""
    r = record_event(conn, llm, e)
    r["shouts"] = react(conn, llm, e["world"], e["player"], r["event_id"], r["react"])["shouts"]
    return r


def ev(t, **kw):
    return {"world": "w", "player": "p", "type": t, "target": "elise", "details": {"item": "default:apple"},
            "witnesses": [], "game_time": 1.0, **kw}


def test_witnessed_theft(conn):
    r = fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    assert db.get_trust(conn, "elise", "w:p") == -20
    assert r["notices"] == ["Elise will remember that."]
    assert r["shouts"] == [{"npc_id": "elise", "text": "Hey! I saw that!"}]
    mem = db.top_memories(conn, "elise", "w:p")[0]
    assert mem["how"] == "witnessed" and mem["text"] == "the newcomer took apple from my stall without paying"
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
    r = fire(conn, ScriptedLLM([None]), ev("theft", witnesses=["elise"]))
    assert r["shouts"] == []
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer took apple from my stall without paying"


def test_react_invalid_output_uses_template(conn):
    bad = {"shout": "Thief!", "memory": "m", "claims": [{"event_id": 999, "type": "gift", "how": "witnessed"}]}
    r = fire(conn, ScriptedLLM([bad]), ev("theft", witnesses=["elise"]))
    assert r["shouts"] == [] and db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer took apple from my stall without paying"


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
    assert "the newcomer took apple from my stall without paying" in r["reply"]
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


from backend.game import gossip, moods, tick, trade_quote


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


# --- final review fixes ---

@pytest.mark.parametrize("intent", [
    {"intent": "threat", "confidence": "high"},
    {"intent": "correction", "confidence": 0.9, "claim": "gift"},
    {"intent": "promise", "confidence": 0.9, "promise": {"item": "iron", "count": 2, "deadline_days": "tomorrow"}},
])
def test_talk_survives_wrong_types_in_intent(conn, intent):
    r = talk(conn, ScriptedLLM([intent, {"reply": "Hm.", "claims": []}]), "w", "p", "elise", "hi", "t", 1.0)
    assert r["reply"] == "Hm."


def test_talk_survives_wrong_types_in_dialogue(conn):
    bad_claim = {"reply": "x", "claims": [{"event_id": [1], "type": "gift", "how": "witnessed"}]}
    bad_quest = {"reply": "Bring coal.", "claims": [], "quest_offer": {"item": "coal", "count": "two", "reward": "bread"}}
    assert talk(conn, ScriptedLLM([Q, bad_claim, bad_claim]), "w", "p", "elise", "hi", "t", 1.0)["reply"] == NEUTRAL_LINE
    r = talk(conn, ScriptedLLM([Q, bad_quest]), "w", "p", "elise", "hi", "t", 1.0)
    assert r["reply"] == "Bring coal." and r["quest_offer"] is None


def test_react_memory_wrong_type_uses_template(conn):
    out = {"shout": "Oi!", "memory": {"x": 1}, "claims": []}
    fire(conn, ScriptedLLM([out]), ev("theft", witnesses=["elise"]))
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer took apple from my stall without paying"


def test_false_corrections_cannot_farm_trust(conn):
    for t in (1.0, 1.1, 1.2):
        talk(conn, MockLLM(), "w", "p", "elise", "I never gave you iron", "t", t)
    assert db.get_trust(conn, "elise", "w:p") == 15


def test_no_retry_after_llm_error(conn):
    llm = ScriptedLLM([Q, None, {"reply": "late", "claims": []}])
    assert talk(conn, llm, "w", "p", "elise", "hi", "t", 1.0)["reply"] == NEUTRAL_LINE
    assert len([c for c in llm.calls if c[0] == "npc_dialogue"]) == 1


from backend.game import greet


def test_greet_uses_dialogue_task_without_player_message(conn):
    llm = ScriptedLLM([{"reply": "Oh. It's you.", "claims": []}])
    r = greet(conn, llm, "w", "p", "elise", "g", 1.0)
    assert r["reply"] == "Oh. It's you."
    task, user = llm.calls[0]
    assert task == "npc_dialogue" and user["player_message"] is None
    assert user["facts"]["situation"] == "the player walks up to you; speak first"


def test_greet_invalid_returns_empty(conn):
    bad = {"reply": "x", "claims": [{"event_id": 5, "type": "gift", "how": "witnessed"}]}
    assert greet(conn, ScriptedLLM([bad]), "w", "p", "elise", "g", 1.0)["reply"] == ""


def test_react_memory_is_authoritative_and_event_described(conn):
    out = {"shout": "Ow!", "memory": "they stole my apple", "claims": []}
    llm = ScriptedLLM([out])
    fire(conn, llm, ev("hit_npc", witnesses=["elise"]))
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer hit me"
    assert llm.calls[0][1]["event"]["what"] == "the newcomer hit you"


def test_rapid_events_react_once(conn):
    llm = MockLLM()
    r1 = fire(conn, llm, ev("hit_npc", witnesses=["elise"]))
    r2 = fire(conn, llm, ev("hit_npc", witnesses=["elise"]))
    assert r1["shouts"] and r1["notices"] and r2["shouts"] == [] and r2["notices"] == []
    assert db.get_trust(conn, "elise", "w:p") == 10 - 25 - 25
    assert len([i for i in db.list_interactions(conn, "elise") if i["task"] == "npc_react"]) == 1


def test_record_event_makes_no_llm_call(conn):
    llm = ScriptedLLM([])
    r = record_event(conn, llm, ev("theft", witnesses=["elise", "mira"]))
    assert llm.calls == [] and r["react"] == ["elise"] and r["notices"]


def test_returning_stolen_goods(conn):
    r = record_event(conn, MockLLM(), ev("return", details={"item": "default:apple", "count": 3}))
    assert db.get_trust(conn, "elise", "w:p") == 20
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer put apple back in my stall"
    assert r["notices"] == ["Elise noticed you put it back."]


def test_context_has_world_knowledge(conn):
    from backend.game import build_context
    rowan = build_context(conn, "rowan", "w:p")["facts"]["world"]
    elise = build_context(conn, "elise", "w:p")["facts"]["world"]
    assert any("hoe" in k for k in elise) and any("iron" in k for k in rowan)
    assert any("Elise" in k for k in rowan)  # everyone knows who trades what


# --- v2: face-to-face gossip, primary witness, moods ---

def test_gossip_needs_meeting(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    tick(conn, MockLLM(), "w", "p", 5.0)
    assert db.top_memories(conn, "mira", "w:p") == []


def test_gossip_delay_and_once(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    assert gossip(conn, "w", "p", "elise", "mira", 1.05, roll=0)["line"] is None
    g = gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0)
    assert g["line"].startswith("Psst...") and "Elise's stall" in g["line"] and g["reply"]
    m = db.top_memories(conn, "mira", "w:p")[0]
    assert m["how"] == "told_by:elise" and m["reliability"] == 0.5
    assert db.get_trust(conn, "mira", "w:p") == 10 - 15
    assert gossip(conn, "w", "p", "elise", "mira", 1.3, roll=0)["line"] is None


def test_gossip_reliability_halves(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0)
    assert gossip(conn, "w", "p", "mira", "rowan", 1.25, roll=0)["line"] is None  # mira only just heard
    assert gossip(conn, "w", "p", "mira", "rowan", 1.35, roll=0)["line"]
    assert db.top_memories(conn, "rowan", "w:p")[0]["reliability"] == 0.25


def test_low_chattiness_still_tells_wren_crimes(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["rowan"]))
    assert gossip(conn, "w", "p", "rowan", "mira", 1.2, roll=0.9)["line"] is None
    assert gossip(conn, "w", "p", "rowan", "wren", 1.2, roll=0.9)["line"]


def test_gossip_noop(conn):
    assert gossip(conn, "w", "p", "elise", "mira", 3.0, roll=0) == {"line": None, "reply": None}


def test_only_primary_witness_reacts(conn):
    r = record_event(conn, MockLLM(), ev("theft", witnesses=["mira", "elise"]))
    assert r["react"] == ["elise"] and set(r["witness_lines"]) == {"mira"}
    assert db.get_trust(conn, "mira", "w:p") < 10 and db.get_trust(conn, "elise", "w:p") < 10


def test_nearest_witness_when_target_absent(conn):
    r = record_event(conn, MockLLM(), ev("theft", witnesses=["mira", "rowan"]))
    assert r["react"] == ["mira"] and set(r["witness_lines"]) == {"rowan"}


def test_moods(conn):
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"]))
    m = moods(conn, "w", "p", 1.2)
    assert m["elise"] == "afraid" and m["mira"] == "neutral"
    assert moods(conn, "w", "p", 2.0)["elise"] == "wary"
