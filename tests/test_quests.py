import pytest

from backend import db, game, progress
from backend.llm import MockLLM


def test_available_and_accept(conn):
    av = game.available_quests(conn, "w:p")
    assert {q["id"] for q in av} >= {"find_apples", "slay_monsters"}
    game.accept_quest(conn, "w:p", "find_apples")
    assert "find_apples" not in {q["id"] for q in game.available_quests(conn, "w:p")}
    j = game.journal(conn, "w:p")
    assert j["active"][0]["title"] == "Find 3 apples for Elise" and j["active"][0]["progress"] == "0/3"


def test_cannot_accept_twice_or_unknown(conn):
    game.accept_quest(conn, "w:p", "find_apples")
    with pytest.raises(ValueError):
        game.accept_quest(conn, "w:p", "find_apples")
    with pytest.raises(ValueError):
        game.accept_quest(conn, "w:p", "nope")


def test_accept_and_handin_completes(conn):
    game.accept_quest(conn, "w:p", "find_apples")
    r = game.handin(conn, "w", "p", "elise", {"default:apple": 3}, 1.0)
    assert r["consumed"] == {"default:apple": 3} and r["completed"] == ["Find 3 apples for Elise"]
    assert r["give"] == [{"item": "default:steel_ingot", "count": 2}]
    assert "Quest complete: Find 3 apples for Elise" in r["notices"]
    assert r["xp_gained"] == 30 and db.get_trust(conn, "elise", "w:p") == 10 + 15
    assert game.journal(conn, "w:p")["done"][0]["id"] == "find_apples"


def test_handin_takes_only_needed(conn):
    game.accept_quest(conn, "w:p", "find_apples")
    r = game.handin(conn, "w", "p", "elise", {"default:apple": 10, "default:dirt": 5}, 1.0)
    assert r["consumed"] == {"default:apple": 3}


def test_partial_handin(conn):
    game.accept_quest(conn, "w:p", "find_apples")
    r = game.handin(conn, "w", "p", "elise", {"default:apple": 2}, 1.0)
    assert r["completed"] == [] and game.journal(conn, "w:p")["active"][0]["progress"] == "2/3"


def test_handin_two_quests_same_item(conn):
    db.add_promise(conn, "quest", "elise", "w:p", "apple", 2, None, '["default:torch"]', title="first", xp=5,
                   trust=5, total=2)
    game.accept_quest(conn, "w:p", "find_apples")
    r = game.handin(conn, "w", "p", "elise", {"default:apple": 3}, 1.0)
    assert r["consumed"] == {"default:apple": 3} and r["completed"] == ["first"]
    assert game.journal(conn, "w:p")["active"][0]["progress"] == "1/3"


def test_slay_quest_progress(conn):
    game.accept_quest(conn, "w:p", "slay_monsters")
    for i in range(2):
        r = game.record_event(conn, MockLLM(), {"world": "w", "player": "p", "type": "slay", "target": None,
                                                 "details": {"mob": "mobs_monster:dirt_monster"}, "witnesses": [],
                                                 "game_time": 1.0})
    assert "Quest complete: Slay 2 monsters for Wren" in r["notices"]
    assert r["give"] == [{"item": "default:sword_steel", "count": 1}] and r["xp_gained"] == 5 + 60


def test_quests_never_expire(conn):
    game.accept_quest(conn, "w:p", "find_apples")
    game.tick(conn, MockLLM(), "w", "p", 99.0)
    assert game.journal(conn, "w:p")["active"] and db.get_trust(conn, "elise", "w:p") == 10
