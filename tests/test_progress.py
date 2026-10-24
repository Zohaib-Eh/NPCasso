from backend import db, progress
from backend.game import build_context, record_event, trade_quote
from backend.llm import MockLLM


def ev(t, **kw):
    return {"world": "w", "player": "p", "type": t, "target": "elise", "details": {}, "witnesses": [],
            "game_time": 1.0, **kw}


def test_levels():
    assert [progress.level_for(x) for x in (0, 49, 50, 149, 150, 299, 300)] == [1, 1, 2, 2, 3, 3, 4]
    assert progress.title(1) == "newcomer" and progress.title(3) == "villager" and progress.title(4) == "friend of the village"


def test_player_state_progress_within_level(conn):
    progress.add_xp(conn, "w:p", 90, "test")
    s = progress.player_state(conn, "w:p")
    assert (s["level"], s["level_xp"], s["next_level_xp"]) == (2, 40, 100)


def test_level_up_reported(conn):
    assert progress.add_xp(conn, "w:p", 30, "t") == {"xp_gained": 30, "level_up": None}
    assert progress.add_xp(conn, "w:p", 30, "t") == {"xp_gained": 30, "level_up": 2}


def test_event_xp(conn):
    r = record_event(conn, MockLLM(), ev("slay", target=None, details={"mob": "mobs_monster:dirt_monster"}))
    assert r["xp_gained"] == 5 and r["notices"] == []
    assert record_event(conn, MockLLM(), ev("trade", details={}))["xp_gained"] == 2


def test_harvest_cap(conn):
    total = sum(record_event(conn, MockLLM(), ev("harvest", target=None, details={"item": "farming:wheat_8"}))["xp_gained"]
                for _ in range(25))
    assert total == 20
    assert record_event(conn, MockLLM(), ev("harvest", target=None, game_time=2.1))["xp_gained"] == 1


def test_rowan_trade_needs_level(conn):
    assert trade_quote(conn, "w", "p", "rowan", True) == {"ok": False, "reason": "level", "min_level": 2}
    progress.add_xp(conn, "w:p", 50, "t")
    assert trade_quote(conn, "w", "p", "rowan", True)["ok"]


def test_title_in_context(conn):
    assert build_context(conn, "elise", "w:p")["player"] == {"title": "newcomer"}
