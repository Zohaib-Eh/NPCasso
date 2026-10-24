from backend import db, stance
from backend.game import record_event
from tests.conftest import ScriptedLLM


def _hit(conn, victim, witnesses, t):
    record_event(conn, ScriptedLLM([]), {"world": "w", "player": "p", "type": "hit_npc", "target": victim,
                                         "witnesses": witnesses, "game_time": t, "details": {}})


def test_when_words():
    assert [stance.when(a) for a in (0.01, 0.3, 1.0, 3.0)] == ["moments ago", "earlier", "yesterday", "days ago"]


def test_a_hit_is_felt_then_cools_into_a_scar(conn):
    _hit(conn, "elise", ["elise", "nell"], 1.0)
    first = stance.of(conn, "elise", "w:p", 1.01)
    assert first["mood"] == "angry" and first["strength"] != "faint" and first["cause"] == "you hit me"
    later = stance.of(conn, "elise", "w:p", 4.0)
    assert later["mood"] == "guarded" and later["cause"] == "you hit me"  # never fully gone


def test_a_timid_villager_is_afraid_and_a_witness_disapproves(conn):
    _hit(conn, "pip", ["pip", "nell"], 1.0)
    assert stance.of(conn, "pip", "w:p", 1.01)["mood"] == "afraid"
    seen = stance.of(conn, "nell", "w:p", 1.01)
    assert seen["mood"] == "cold" and seen["cause"] == "I saw you hit Pip"


def test_amends_cool_it_faster(conn):
    _hit(conn, "elise", ["elise"], 1.0)
    before = stance.of(conn, "elise", "w:p", 1.1)["heat"]
    db.add_memory(conn, "elise", "w:p", None, "apology", "the newcomer apologised to me", "witnessed", 1.0, 10, 1.1)
    assert stance.of(conn, "elise", "w:p", 1.1)["heat"] < before


def test_nothing_to_feel_is_neutral(conn):
    assert stance.of(conn, "mira", "w:p", 1.0)["mood"] == "neutral"


def test_standing_words():
    assert [stance.standing(m) for m in ([], ["neutral"], ["warm", "fond"], ["angry"], ["angry", "afraid"])] == \
        ["Unknown", "Newcomer", "Trusted", "Watched", "Feared"]
