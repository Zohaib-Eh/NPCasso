import json

import pytest

from backend import db, situations
from backend.game import gossip, greet, talk
from backend.story import anchor
from backend.validator import validate
from tests.conftest import ScriptedLLM

Q = {"intent": "question", "confidence": 0.5, "promise": None, "claim": None}
WOOD = {"text": "Mira's boy is coughing and her house has no firewood, but Rowan keeps the last logs.",
        "involves": ["mira", "rowan"],
        "motive": "The boy is cold, and Rowan is holding the last logs for the forge."}


def opened(text="Rowan will not spare his logs, and Mira's boy is coughing.", **kw):
    return {"reply": text, "claims": [], "situation": WOOD, **kw}


def test_may_open_follows_the_season_and_the_cap(conn):
    anchor(conn, "w:p", 0.0)
    assert situations.facts(conn, "w:p", "elise", 0.4)["may_open"]  # day one: one early situation
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    assert "may_open" not in situations.facts(conn, "w:p", "tobin", 0.5)  # the day-one cap is one
    assert situations.facts(conn, "w:p", "tobin", 2.0)["may_open"] is True  # pressure allows three


def test_an_opened_situation_is_remembered_by_everyone_in_it(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    for who in ("elise", "mira", "rowan"):
        mem = db.top_memories(conn, who, "w:p")[0]
        assert mem["type"] == "situation" and mem["how"] == "own" and "firewood" in mem["text"]
    assert situations.facts(conn, "w:p", "mira", 0.5)["open_situation"]["involves"] == ["mira", "rowan"]


def test_a_situation_when_not_allowed_is_rejected_and_retried(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    llm = ScriptedLLM([opened("Another worry.", **{}), {"reply": "Morning.", "claims": []}])
    r = greet(conn, llm, "w", "p", "elise", "g2", 0.45)
    assert r["reply"] == "Morning." and "situation_not_allowed" in llm.calls[1][1]["validator_feedback"]


def test_nobody_else_opens_at_the_same_time(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 2.0)
    assert "may_open" not in situations.facts(conn, "w:p", "tobin", 2.1)
    assert situations.facts(conn, "w:p", "tobin", 2.3)["may_open"] is True


def test_a_greeting_marks_the_trouble_as_told(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    assert situations.facts(conn, "w:p", "elise", 0.9)["open_situation"]["already_told"] is True
    assert situations.facts(conn, "w:p", "mira", 0.9)["open_situation"]["already_told"] is False
    llm = ScriptedLLM([{"reply": "Morning again.", "claims": []}])
    greet(conn, llm, "w", "p", "mira", "g2", 0.9)
    assert llm.calls[0][1]["facts"]["open_situation"]["already_told"] is False
    assert situations.facts(conn, "w:p", "mira", 1.0)["open_situation"]["already_told"] is True


def test_a_villager_is_in_one_open_situation_at_a_time(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 2.0)
    assert situations.facts(conn, "w:p", "tobin", 2.3)["busy"] == ["elise", "mira", "rowan"]
    again = {"reply": "x", "claims": [], "situation": {"text": "More wood trouble.", "involves": ["mira"],
             "motive": "The kiln is cold and Mira still has the last stack."}}
    assert "situation_duplicate" in validate("npc_dialogue", again, {"facts": situations.facts(
        conn, "w:p", "tobin", 2.3), "memories": []})["errors"]


def test_a_situation_needs_someone_besides_the_opener(conn):
    ctx = {"facts": {"may_open": True, "you_are": "elise"}, "memories": []}
    solo = {"reply": "x", "claims": [], "situation": {"text": "My stock is low.", "involves": ["elise"]}}
    assert "situation_malformed" in validate("npc_dialogue", solo, ctx)["errors"]


def test_the_situation_cannot_be_about_the_player(conn):
    ctx = {"facts": {"may_open": True}, "memories": []}
    bad = {"reply": "x", "claims": [], "situation": {"text": "The newcomer stole wood.", "involves": ["rowan"],
           "motive": "The stall was short and someone had to answer for it."}}
    assert "situation_about_player" in validate("npc_dialogue", bad, ctx)["errors"]
    bad = {"reply": "x", "claims": [], "situation": {"text": "Wood is short.", "involves": ["nobody"]}}
    assert "situation_malformed" in validate("npc_dialogue", bad, ctx)["errors"]


def test_a_consequence_is_remembered_moves_trust_and_resolves(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    before = db.get_trust(conn, "mira", "w:p")
    answer = {"reply": "Then Mira's boy will be warm tonight.", "claims": [],
              "consequence": {"npc_id": "mira", "text": "the newcomer brought us logs for the boy", "stance": "helped"}}
    talk(conn, ScriptedLLM([Q, answer]), "w", "p", "elise", "Take the logs to Mira.", "t", 0.6)
    assert db.get_trust(conn, "mira", "w:p") == before + situations.SIZE["small"]  # no size given: small
    assert any(m["type"] == "consequence" for m in db.top_memories(conn, "mira", "w:p", limit=10))
    assert "open_situation" not in situations.facts(conn, "w:p", "elise", 0.7)


@pytest.mark.parametrize("stance,size,delta", [("helped", "large", 10), ("hurt", "medium", -6),
                                                ("hurt", "small", -3)])
def test_the_model_picks_the_size_and_the_code_sets_the_number(conn, stance, size, delta):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    before = db.get_trust(conn, "mira", "w:p")
    c = {"npc_id": "mira", "text": "it cost her the logs", "stance": stance, "size": size}
    talk(conn, ScriptedLLM([Q, {"reply": "So it is.", "claims": [], "consequence": c}]),
         "w", "p", "elise", "I take the logs.", "t", 0.6)
    assert db.get_trust(conn, "mira", "w:p") == before + delta


def test_an_unknown_size_is_rejected(conn):
    ctx = {"facts": {"open_situation": {"text": "x", "involves": ["mira"]}}, "memories": []}
    out = {"reply": "x", "claims": [],
           "consequence": {"npc_id": "mira", "text": "t", "stance": "hurt", "size": "enormous"}}
    assert "consequence_malformed" in validate("npc_dialogue", out, ctx)["errors"]


def test_a_consequence_needs_something_to_resolve(conn):
    ctx = {"facts": {}, "memories": []}
    out = {"reply": "x", "claims": [], "consequence": {"npc_id": "mira", "text": "t", "stance": "helped"}}
    assert "consequence_not_allowed" in validate("npc_dialogue", out, ctx)["errors"]


def test_a_secret_stays_with_the_people_who_know(conn):
    anchor(conn, "w:p", 0.0)
    secret = {"text": "Elise asked Nell to hide a sack of flour.", "involves": ["nell"], "hidden_from": ["rowan"],
              "motive": "Elise still owes Rowan for the anvil, and this flour is all she can spare."}
    greet(conn, ScriptedLLM([opened(situation=secret)]), "w", "p", "elise", "g", 0.4)
    assert db.top_memories(conn, "rowan", "w:p") == []
    assert "anvil" in db.top_memories(conn, "elise", "w:p")[0]["text"]
    assert "flour" in db.top_memories(conn, "nell", "w:p")[0]["text"]
    assert "open_situation" not in situations.facts(conn, "w:p", "rowan", 0.5)
    assert situations.facts(conn, "w:p", "nell", 0.5)["open_situation"]["hidden_from"] == ["rowan"]
    told = {"reply": "Rowan will feel this.", "claims": [],
            "consequence": {"npc_id": "rowan", "text": "Rowan finds the flour gone.", "stance": "hurt"}}
    facts = situations.facts(conn, "w:p", "elise", 0.5)
    assert "consequence_hidden" in validate("npc_dialogue", told, {"facts": facts, "memories": []})["errors"]
    situations.take(conn, "w:p", "elise", told, 0.6, facts)
    assert db.top_memories(conn, "rowan", "w:p") == []
    llm = ScriptedLLM([{"reply": "Morning.", "claims": []}])
    greet(conn, llm, "w", "p", "rowan", "g2", 0.8)
    assert "hide a sack of flour" not in json.dumps(llm.calls[0][1])


def test_saying_you_will_hand_something_over_must_give_it(conn):
    ctx = {"facts": {"stock": ["flour"]}, "memories": []}
    bare = {"reply": "I'll hand you the flour.", "claims": []}
    assert "promised_gift" in validate("npc_dialogue", bare, ctx)["errors"]
    given = {**bare, "give_item": {"item": "flour", "count": 1}}
    assert validate("npc_dialogue", given, ctx)["ok"]


def test_a_handed_item_arrives_once_per_day(conn):
    anchor(conn, "w:p", 0.0)
    line = {"reply": "I'll hand you the flour.", "claims": [], "give_item": {"item": "flour", "count": 1}}
    first = talk(conn, ScriptedLLM([Q, line]), "w", "p", "nell", "May I take the flour?", "t", 1.0)
    assert first["give"] == [{"item": "farming:flour", "count": 1}]
    second = talk(conn, ScriptedLLM([Q, line]), "w", "p", "nell", "Another sack?", "t", 1.2)
    assert second["give"] == []


def test_a_situation_is_never_passed_on_as_gossip(conn):
    anchor(conn, "w:p", 0.0)
    greet(conn, ScriptedLLM([opened()]), "w", "p", "elise", "g", 0.4)
    assert gossip(conn, "w", "p", "elise", "pip", 9.0, roll=0)["shared"] is False


def test_one_villagers_private_memory_never_reaches_another(conn):
    from backend.db import load_config
    from backend.game import _heard, build_context
    db.add_memory(conn, "elise", "w:p", None, "gift", "CANARY the newcomer gave me a ruby", "witnessed", 1.0, 5, 1.0)
    assert "CANARY" in json.dumps(_heard(build_context(conn, "elise", "w:p", game_time=1.0)))
    for n in (n for n in load_config()["npcs"] if n != "elise"):
        assert "CANARY" not in json.dumps(_heard(build_context(conn, n, "w:p", game_time=1.0)))
