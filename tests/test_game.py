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
    assert r["notices"] == ["Elise will remember that.", "Word will spread."]
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


def test_walk_away_is_not_remembered(conn):
    r = record_event(conn, MockLLM(), ev("walk_away", witnesses=["elise"]))
    assert r["notices"] == [] and db.get_trust(conn, "elise", "w:p") == 10
    assert db.top_memories(conn, "elise", "w:p") == []


def test_unknown_type_raises(conn):
    with pytest.raises(ValueError):
        record_event(conn, MockLLM(), ev("teleport"))
    with pytest.raises(ValueError):
        record_event(conn, MockLLM(), ev("theft", target="bob"))


import json

from backend.game import talk

Q = {"intent": "question", "confidence": 0.5, "promise": None, "claim": None}
HARD = {"choice": {"options": ["help them", "refuse them"]}, "evidence": [{"dimension": "loyalty", "weight": 0.5}]}


def dialogue_rows(conn):
    return [i for i in db.list_interactions(conn, "elise") if i["task"] == "npc_dialogue"]


def test_talk_stores_the_score_and_drops_a_bad_dimension(conn):
    from backend.story import _ensure
    line = {"reply": "The woodpile will not last the two of them.", "claims": [], **HARD,
            "evidence": [{"dimension": "compassion", "weight": 1}, {"dimension": "evil", "weight": 1},
                         {"dimension": "loyalty", "weight": 3}]}
    r = talk(conn, ScriptedLLM([Q, line]), "w", "p", "elise", "hello", "th", 0.4)
    assert r["reply"].startswith("The woodpile")
    _ensure(conn)
    rows = conn.execute("select dimension, weight from evidence where player='w:p'").fetchall()
    assert [(row["dimension"], row["weight"]) for row in rows] == [("compassion", 1.0)]
    assert "season" in dialogue_rows(conn)[-1]["request"]["facts"]


def test_a_rejected_line_does_not_score(conn):
    from backend.story import _ensure
    bad = {"reply": "Thanks for the bread!", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}],
           "evidence": [{"dimension": "compassion", "weight": 1}]}
    talk(conn, ScriptedLLM([Q, bad, {"reply": "Hello.", "claims": []}]), "w", "p", "elise", "hi", "th", 1.0)
    _ensure(conn)
    assert conn.execute("select count(*) c from evidence").fetchone()["c"] == 0


def test_react_stores_the_score(conn):
    recorded = record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    eid = recorded["event_id"]
    shout = {"shout": "Hey! I saw that!", "memory": "m",
             "claims": [{"event_id": eid, "type": "theft", "how": "witnessed"}],
             "evidence": [{"dimension": "justice", "weight": -1}]}
    out = react(conn, ScriptedLLM([shout]), "w", "p", eid, ["elise"])
    assert out["shouts"][0]["text"] == "Hey! I saw that!"
    row = conn.execute("select dimension, weight from evidence where player='w:p' and note='spoken'").fetchone()
    assert (row["dimension"], row["weight"]) == ("justice", -1.0)


def test_talk_recalls_theft(conn):
    record_event(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    r = talk(conn, MockLLM(), "w", "p", "elise", "hello", "th1", 1.1)
    assert "the newcomer took apple from my stall without paying" in r["reply"]
    assert dialogue_rows(conn)[0]["validator_result"]["ok"]


def test_talk_retries_then_passes(conn):
    bad = {"reply": "Thanks for the bread!", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}]}
    good = {"reply": "Hello.", "claims": [], **HARD}
    llm = ScriptedLLM([bad, good])
    r = talk(conn, llm, "w", "p", "elise", "hi", "th1", 1.0)
    assert r["reply"] == "Hello."
    rows = dialogue_rows(conn)
    assert len(rows) == 2 and rows[0]["retried"] and rows[0]["prev_id"] == rows[1]["id"]
    assert "invented_event:99" in llm.calls[1][1]["validator_feedback"]


def test_talk_two_failures_neutral(conn):
    bad = {"reply": "x", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}]}
    assert talk(conn, ScriptedLLM([Q, bad, bad]), "w", "p", "elise", "hi", "th1", 1.0)["reply"] != "x"


def test_talk_malformed_llm_neutral(conn):
    assert talk(conn, ScriptedLLM([None, None, None]), "w", "p", "elise", "hi", "th1", 1.0)["reply"]


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
    talk(conn, ScriptedLLM([t, {"reply": "Hm.", "claims": [], **HARD}]), "w", "p", "elise", "grr", "t", 1.0)
    assert db.get_trust(conn, "elise", "w:p") == 10


def test_threat_lowers_trust(conn):
    talk(conn, MockLLM(), "w", "p", "elise", "I will burn your stall", "t", 1.0)
    assert db.get_trust(conn, "elise", "w:p") == -5


def test_a_made_up_chore_is_not_recorded(conn):
    bad = {"reply": "Bring me coal.", "claims": [], "quest_offer": {"item": "coal", "count": 2, "reward": "bread"}, **HARD}
    good = {"reply": "Three apples from the orchard would set the stall right.", "claims": [], **HARD}
    llm = ScriptedLLM([bad, good])
    r = talk(conn, llm, "w", "p", "elise", "any work?", "t", 1.0)
    assert r["reply"].startswith("Three apples") and r["quest_offer"] is None
    assert db.open_promises(conn, "elise", "w:p", kind="quest") == []
    assert "wrong_task" in llm.calls[1][1]["validator_feedback"]


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


def test_quests_do_not_fail(conn):
    db.add_promise(conn, "quest", "rowan", "w:p", "coal", 1, 3.0, reward="pickaxe")
    tick(conn, MockLLM(), "w", "p", 3.5)
    assert db.get_trust(conn, "rowan", "w:p") == 10


def test_trade_quote_itemstrings(conn):
    q = trade_quote(conn, "w", "p", "elise", True)
    assert q == {"ok": True, "give": {"item": "default:apple", "count": 3},
                 "cost": {"item": "default:steel_ingot", "count": 2}}
    from backend import progress
    progress.add_xp(conn, "w:p", 50, "test")  # Rowan only trades from Lv 2
    assert trade_quote(conn, "w", "p", "rowan", False) == {"ok": False, "reason": "no_work_block"}


# --- final review fixes ---

@pytest.mark.parametrize("intent", [
    {"intent": "threat", "confidence": "high"},
    {"intent": "correction", "confidence": 0.9, "claim": "gift"},
    {"intent": "promise", "confidence": 0.9, "promise": {"item": "iron", "count": 2, "deadline_days": "tomorrow"}},
])
def test_talk_survives_wrong_types_in_intent(conn, intent):
    r = talk(conn, ScriptedLLM([intent, {"reply": "Hm.", "claims": [], **HARD}]), "w", "p", "elise", "hi", "t", 1.0)
    assert r["reply"] == "Hm."


def test_talk_survives_wrong_types_in_dialogue(conn):
    bad_claim = {"reply": "x", "claims": [{"event_id": [1], "type": "gift", "how": "witnessed"}]}
    bad_quest = {"reply": "Bring coal.", "claims": [], **HARD,
                 "quest_offer": {"item": "coal", "count": "two", "reward": "bread"}}
    assert talk(conn, ScriptedLLM([Q, bad_claim, bad_claim]), "w", "p", "elise", "hi", "t", 1.0)["reply"] == "Sorry, say that once more."
    r = talk(conn, ScriptedLLM([Q, bad_quest, bad_quest]), "w", "p", "elise", "hi", "t", 1.0)
    assert r["reply"] == "Sorry, say that once more." and r["quest_offer"] is None


def test_react_memory_wrong_type_uses_template(conn):
    out = {"shout": "Oi!", "memory": {"x": 1}, "claims": []}
    fire(conn, ScriptedLLM([out]), ev("theft", witnesses=["elise"]))
    assert db.top_memories(conn, "elise", "w:p")[0]["text"] == "the newcomer took apple from my stall without paying"


def test_false_corrections_cannot_farm_trust(conn):
    for t in (1.0, 1.1, 1.2):
        talk(conn, MockLLM(), "w", "p", "elise", "I never gave you iron", "t", t)
    assert db.get_trust(conn, "elise", "w:p") == 15


def test_no_retry_after_llm_error(conn):
    llm = ScriptedLLM([None, {"reply": "late", "claims": []}])
    assert talk(conn, llm, "w", "p", "elise", "hi", "t", 1.0)["reply"] == "Sorry, say that once more."
    assert len([c for c in llm.calls if c[0] == "npc_dialogue"]) == 1


from backend.game import greet, journal


def test_greet_uses_dialogue_task_without_player_message(conn):
    llm = ScriptedLLM([{"reply": "Oh. It's you. Give Mira the wood, or keep it.", "claims": [],
                        "choice": {"options": ["give Mira the wood", "keep the wood"]}}])
    r = greet(conn, llm, "w", "p", "elise", "g", 1.0)
    assert r["reply"] == "Oh. It's you. Give Mira the wood, or keep it."
    task, user = llm.calls[0]
    assert task == "npc_dialogue" and user["player_message"] is None
    assert user["facts"]["situation"].startswith("a stranger has walked up")
    assert user["facts"]["ask"] is None
    assert user["facts"]["ease"] == "introduce"
    assert not {"need", "strain", "sign", "bent"} & set(user["facts"])
    assert user["npc"]["voice"] and user["npc"]["location"]
    assert journal(conn, "w:p")["active"] == []


def test_each_villager_is_met_for_the_first_time_once(conn):
    hello = {"reply": "Hello. I'm around.", "claims": []}
    greet(conn, ScriptedLLM([hello]), "w", "p", "elise", "g0", 1.0)
    fresh = ScriptedLLM([hello])
    greet(conn, fresh, "w", "p", "nell", "g1", 1.0)  # a different villager is still a stranger
    assert fresh.calls[0][1]["facts"].get("ease") == "introduce"
    again = ScriptedLLM([hello])
    greet(conn, again, "w", "p", "elise", "g2", 1.0)
    assert again.calls[0][1]["facts"]["ease"] == "hint" and not again.calls[0][1]["facts"].get("need")


def test_the_shortage_comes_with_acquaintance_and_not_at_every_hello(conn):
    hello = {"reply": "Hello. I'm around.", "claims": []}
    for i in range(2):
        greet(conn, ScriptedLLM([hello]), "w", "p", "nell", f"g{i}", 1.0 + i * 0.1)
    third = ScriptedLLM([hello])
    greet(conn, third, "w", "p", "nell", "g3", 1.3)
    facts = third.calls[0][1]["facts"]
    assert facts["ease"] == "open" and facts["need"]["item"] == "flour" and isinstance(facts["sign"], str)
    assert "strain" not in facts  # the shortage is shown through signs, never stated
    again = ScriptedLLM([hello])
    greet(conn, again, "w", "p", "nell", "g4", 1.4)
    assert not again.calls[0][1]["facts"].get("need")


def test_a_long_talk_drifts_from_small_talk_to_a_worry_to_the_ask(conn):
    llm = ScriptedLLM([{"reply": "Mm, busy day.", "claims": []}] * 8)
    for i in range(8):
        talk(conn, llm, "w", "p", "elise", "How is the shop?", "t", 1.0)
    seen = [call[1]["facts"] for call in llm.calls]
    assert [bool(f.get("lean")) for f in seen] == [False, False, False, True, True, True, False, True]
    assert seen[3]["lean"] == {"short_of": "apples"} and not seen[3].get("need")
    assert seen[6]["need"]["item"] == "apple" and seen[7].get("need") is None  # asked once; not again at once


def test_a_hit_villager_does_not_pitch_an_errand_or_start_over(conn):
    hello = {"reply": "Hello. I'm around.", "claims": []}
    for i in range(3):
        greet(conn, ScriptedLLM([hello]), "w", "p", "nell", f"g{i}", 1.0 + i * 0.01)
    record_event(conn, ScriptedLLM([]), ev("hit_npc", target="nell", witnesses=["nell"], game_time=1.1))
    llm = ScriptedLLM([hello])
    greet(conn, llm, "w", "p", "nell", "g9", 1.12)
    sent = llm.calls[0][1]
    assert sent["facts"]["stance"] == {"mood": "angry", "strength": "strong", "cause": "you hit me"}
    assert not sent["facts"].get("need") and "ease" not in sent["facts"] and "sign" not in sent["facts"]
    assert sent["memories"][0]["when"] == "moments ago"


def test_an_insult_is_heard_and_asks_nothing_of_the_insulter(conn):
    hello = {"reply": "Hello. I'm around.", "claims": []}
    for i in range(4):
        greet(conn, ScriptedLLM([hello]), "w", "p", "elise", f"g{i}", 1.0)
    insult = {"intent": "insult", "confidence": 0.95, "promise": None, "claim": None}
    llm = ScriptedLLM([insult, {"reply": "Mind your tongue.", "claims": []}])
    talk(conn, llm, "w", "p", "elise", "help me, you fool", "t", 1.0)
    facts = llm.calls[1][1]["facts"]
    assert facts["heard_as"] == "insult" and not facts.get("need")


def test_an_insult_leaves_a_memory_that_does_not_travel(conn):
    from backend.game import gossip
    insult = {"intent": "insult", "confidence": 0.95, "promise": None, "claim": None}
    talk(conn, ScriptedLLM([insult, {"reply": "Mind your tongue.", "claims": []}]), "w", "p", "corin", "you fool",
         "t", 1.0)
    assert db.top_memories(conn, "corin", "w:p")[0]["text"] == "the newcomer insulted me"
    assert not gossip(conn, "w", "p", "corin", "elise", 2.0, roll=0.0)["shared"]


def test_a_failed_greeting_is_never_silent(conn):
    bad = {"reply": "x", "claims": [{"event_id": 5, "type": "gift", "how": "witnessed"}]}
    assert greet(conn, ScriptedLLM([bad, bad]), "w", "p", "elise", "g", 1.0)["reply"]


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
    assert llm.calls == [] and r["react"] == ["elise", "mira"] and r["notices"]


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
    fire(conn, MockLLM(), ev("theft", target="tobin", witnesses=["elise"]))
    assert not gossip(conn, "w", "p", "elise", "mira", 1.05, roll=0)["shared"]
    g = gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0)
    assert g == {"shared": True, "line": None, "reply": None}  # out of earshot: no LLM, no line
    m = db.top_memories(conn, "mira", "w:p")[0]
    assert m["how"] == "told_by:elise" and m["reliability"] == 0.5
    assert db.get_trust(conn, "mira", "w:p") == 10 - 15
    assert not gossip(conn, "w", "p", "elise", "mira", 1.3, roll=0)["shared"]


def test_audible_gossip_is_voiced_by_llm(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    llm = ScriptedLLM([{"reply": "Mira, the newcomer pinched my apples!", "claims": []},
                       {"reply": "No! The cheek of it.", "claims": []}])
    g = gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0, llm=llm, voice=True)
    assert g == {"shared": True, "line": "Mira, the newcomer pinched my apples!", "reply": "No! The cheek of it."}
    assert [c[0] for c in llm.calls] == ["npc_dialogue", "npc_dialogue"]
    assert "rumour" in llm.calls[0][1]["facts"]["situation"]


def test_audible_gossip_falls_back_when_llm_fails(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    g = gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0, llm=ScriptedLLM([None, None]), voice=True)
    assert g["line"].startswith("Psst...") and g["reply"] == "Really?!"


def test_gossip_reliability_halves(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["elise"]))
    gossip(conn, "w", "p", "elise", "mira", 1.2, roll=0)
    assert not gossip(conn, "w", "p", "mira", "rowan", 1.25, roll=0)["shared"]  # mira only just heard
    assert gossip(conn, "w", "p", "mira", "rowan", 1.35, roll=0)["shared"]
    assert db.top_memories(conn, "rowan", "w:p")[0]["reliability"] == 0.25


def test_low_chattiness_still_tells_wren_crimes(conn):
    fire(conn, MockLLM(), ev("theft", witnesses=["rowan"]))
    assert not gossip(conn, "w", "p", "rowan", "mira", 1.2, roll=0.9)["shared"]
    assert gossip(conn, "w", "p", "rowan", "wren", 1.2, roll=0.9)["shared"]


def test_a_handover_is_not_retold(conn):
    from backend.game import accept_quest, handin
    accept_quest(conn, "w:p", "find_apples")
    handin(conn, "w", "p", "elise", {"default:apple": 3}, 1.0)
    assert gossip(conn, "w", "p", "elise", "rowan", 5.0, roll=0)["shared"] is False
    assert db.top_memories(conn, "rowan", "w:p") == []


def test_gossip_noop(conn):
    assert gossip(conn, "w", "p", "elise", "mira", 3.0, roll=0) == {"shared": False, "line": None, "reply": None}


def test_two_nearest_witnesses_speak(conn):
    r = record_event(conn, MockLLM(), ev("theft", witnesses=["mira", "rowan", "elise"]))
    assert r["react"] == ["elise", "mira"]  # victim first, then nearest; rowan only turns to look
    assert db.get_trust(conn, "mira", "w:p") < 10 and db.get_trust(conn, "elise", "w:p") < 10


def test_nearest_witness_when_target_absent(conn):
    r = record_event(conn, MockLLM(), ev("theft", witnesses=["mira", "rowan", "tobin"]))
    assert r["react"] == ["mira", "rowan"]


def test_moods_follow_stance_and_the_shunning_ends(conn):
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"]))
    m = moods(conn, "w", "p", 1.2)
    assert m["elise"] == {"mood": "angry", "shun": True} and m["mira"] == {"mood": "neutral", "shun": False}
    assert moods(conn, "w", "p", 4.0)["elise"] == {"mood": "guarded", "shun": False}


def test_a_shunned_villager_will_not_trade(conn):
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"]))
    assert trade_quote(conn, "w", "p", "elise", True, 1.2) == {"ok": False, "reason": "shunned"}


def test_greet_retries_once_on_invalid(conn):
    bad = {"reply": "You promised me iron!", "claims": []}
    good = {"reply": "Morning, newcomer. Give Mira the wood, or keep it.", "claims": [],
            "choice": {"options": ["give Mira the wood", "keep the wood"]}}
    llm = ScriptedLLM([bad, good])
    assert greet(conn, llm, "w", "p", "elise", "g", 1.0)["reply"] == "Morning, newcomer. Give Mira the wood, or keep it."
    assert "unclaimed_mention:promised" in llm.calls[1][1]["validator_feedback"]


# --- guidance and pointing ---

def test_context_has_guide(conn):
    from backend.game import accept_quest, build_context
    accept_quest(conn, "w:p", "find_apples")
    facts = build_context(conn, "rowan", "w:p")["facts"]
    assert "town_hall" in facts["guide"]["places"] and "rowan" in facts["guide"]["places"]
    assert "active_quests" not in facts["guide"] and "festival" not in facts["guide"]
    assert "open_quests" not in facts
    assert "Find 3 apples" not in json.dumps(facts)
    assert "own work" in facts["bent"]
    assert "other people" in build_context(conn, "nell", "w:p")["facts"]["bent"]
    assert "both ways" in build_context(conn, "tobin", "w:p")["facts"]["bent"]
    db.add_trust(conn, "tobin", "w:p", -20)
    assert "own work" in build_context(conn, "tobin", "w:p")["facts"]["bent"]
    db.add_trust(conn, "tobin", "w:p", 40)
    assert "other people" in build_context(conn, "tobin", "w:p")["facts"]["bent"]


def test_a_greeting_carries_only_that_villager(conn):
    llm = ScriptedLLM([{"reply": "Morning.", "claims": []}])
    greet(conn, llm, "w", "p", "elise", "g", 1.0)
    facts = llm.calls[0][1]["facts"]
    assert "busy" not in facts and "regard" not in facts and "lean" not in facts
    assert "items" not in llm.calls[0][1] and "player" not in llm.calls[0][1]
    assert set(facts["guide"]) == {"places"}


def test_talk_returns_valid_point_to(conn):
    ok = {"reply": "Rowan's forge is east of the square.", "claims": [], "point_to": "rowan"}
    assert talk(conn, ScriptedLLM([Q, ok]), "w", "p", "elise", "where is the smith?", "t", 1.0)["point_to"] == "rowan"
    bad = {"reply": "Over there.", "claims": [], "point_to": "narnia"}
    assert talk(conn, ScriptedLLM([Q, bad]), "w", "p", "elise", "where?", "t", 1.0)["point_to"] is None


def test_failed_reply_falls_back_to_guidance(conn):
    bad = {"reply": "x", "claims": [{"event_id": 99, "type": "gift", "how": "witnessed"}]}
    r = talk(conn, ScriptedLLM([Q, bad, bad]), "w", "p", "elise", "hello there", "t", 1.0)
    assert r["reply"] == "Sorry, say that once more." and r["point_to"] is None


def test_a_lost_player_is_told_where_to_go(conn):
    from backend.game import CONFIG, own_need
    for npc_id in CONFIG["npcs"]:
        need = own_need(conn, "w:p", npc_id)
        assert need and len(need["steps"]) > 20
    vague = {"reply": "Wander about, you'll find something.", "claims": []}
    clear = {"reply": "Head to the orchard and pick apples.", "claims": [], "point_to": "orchard"}
    llm = ScriptedLLM([vague, clear])
    r = talk(conn, llm, "w", "p", "elise", "I'm lost, what should I do?", "t", 1.0)
    assert r["reply"] == "Head to the orchard and pick apples." and r["point_to"] == "orchard"
    assert llm.calls[0][1]["facts"]["lost"] is True
    assert "orchard" in llm.calls[0][1]["facts"]["directions"]
    assert "no_directions" in llm.calls[1][1]["validator_feedback"]
    failed = talk(conn, ScriptedLLM([Q, vague, vague]), "w", "p", "rowan", "what do I do", "t", 1.0)
    assert "iron" in failed["reply"] and failed["point_to"] == "mine"


def test_the_model_is_given_the_conversation_so_far(conn):
    llm = ScriptedLLM([{"reply": "I'm Hazel.", "claims": []}, {"reply": "Pleased.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "who are you?", "t", 1.0)
    talk(conn, llm, "w", "p", "hazel", "is that your real name?", "t", 1.1)
    recent = [u for t, u in llm.calls if t == "npc_dialogue"][1]["facts"]["recent"]
    assert recent == [{"who": "you", "text": "who are you?"}, {"who": "them", "text": "I'm Hazel."}]


def test_a_victim_passes_it_on_the_first_time_they_meet_someone(conn):
    from backend.game import gossip
    record_event(conn, ScriptedLLM([]), {"world": "w", "player": "p", "type": "hit_npc", "target": "elise",
                                         "witnesses": ["elise"], "game_time": 1.0, "details": {}})
    # a bystander would wait out the delay; the victim does not, and is not shy
    assert gossip(conn, "w", "p", "elise", "mira", 1.0, roll=0.99)["shared"]
    assert db.top_memories(conn, "mira", "w:p")[0]["how"] == "told_by:elise"


CRY = {"world": "w", "player": "p", "type": "hit_npc", "target": "elise", "witnesses": ["elise", "pip"],
       "heard": ["nell", "wren", "mira"], "game_time": 1.0, "details": {}}


def test_a_cry_is_heard_and_the_game_decides_who_moves(conn):
    r = record_event(conn, ScriptedLLM([]), CRY)
    assert db.top_memories(conn, "nell", "w:p")[0]["text"] == "I heard Elise cry out"
    assert db.get_trust(conn, "nell", "w:p") == 10  # hearing is not seeing
    assert r["scene"] == {"victim": "elise", "victim_mood": "angry", "rescuers": ["nell"],
                          "tattlers": ["pip"], "guard": "wren"}  # Mira only heard: nothing to tell the guard
    assert r["react"] == ["elise", "pip", "wren"]  # the victim, a witness and the guard speak; the rest just move


def test_a_villager_who_only_heard_the_cry_is_not_told_who_did_it(conn):
    import json
    r = record_event(conn, ScriptedLLM([]), CRY)
    llm = ScriptedLLM([{"shout": "Elise? What happened?", "claims": []}])
    react(conn, llm, "w", "p", r["event_id"], ["wren"])
    sent = json.dumps(llm.calls[0][1])
    assert "Elise cry out" in sent and "newcomer hit" not in sent


def test_only_a_known_deed_costs_reputation(conn):
    from backend.story import profile
    record_event(conn, ScriptedLLM([]), ev("theft"))  # nobody saw
    assert not any(d["n"] for d in profile(conn, "w:p"))
    r = record_event(conn, ScriptedLLM([]), ev("hit_npc", witnesses=["elise"]))
    dims = {d["dimension"]: d["value"] for d in profile(conn, "w:p")}
    assert dims["compassion"] == -0.8 and "Word will spread." in r["notices"]


def test_people_lists_only_those_met_with_the_mood_of_the_last_meeting(conn):
    from backend.game import people
    assert people(conn, "w", "p")["met"] == []
    greet(conn, ScriptedLLM([{"reply": "Hello.", "claims": []}]), "w", "p", "elise", "g", 1.0)
    record_event(conn, MockLLM(), ev("hit_npc", witnesses=["elise"], game_time=1.1))  # off screen: not shown yet
    p = people(conn, "w", "p")
    assert [(m["npc_id"], m["mood"]) for m in p["met"]] == [("elise", "neutral")] and p["standing"] == "Newcomer"


def test_a_plain_question_skips_the_classifier(conn):
    llm = ScriptedLLM([{"reply": "I'm Hazel.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "who are you?", "t", 1.0)
    assert [t for t, _ in llm.calls] == ["npc_dialogue"]


def test_an_insulting_question_is_still_classified(conn):
    insult = {"intent": "insult", "confidence": 0.95, "promise": None, "claim": None}
    llm = ScriptedLLM([insult, {"reply": "Mind your tongue.", "claims": []}])
    talk(conn, llm, "w", "p", "hazel", "are you always this useless?", "t", 1.0)
    assert [t for t, _ in llm.calls][0] == "intent_classify"


def test_every_quest_tells_the_player_where_and_how():
    from backend.game import CONFIG, NEED_HOW, NEED_PLACE
    for npc, cfg in CONFIG["npcs"].items():
        for q in cfg.get("quests") or []:
            if q.get("kind") == "slay":
                continue
            item = q["item"]
            assert item in NEED_HOW, f"{npc}: no directions for {item}"
            place = NEED_PLACE.get(item)
            assert place is None or place in CONFIG["places"] or place in CONFIG["npcs"], f"{npc}: {item} -> {place}"
            assert (q.get("count") or 1) <= 12, f"{npc}: {item} count is too long a chore"
