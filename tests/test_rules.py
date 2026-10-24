from backend.db import load_config
from backend.rules import apology_allowed, band, gift_pref, short_item, trade_terms, trust_delta


def test_deltas():
    assert trust_delta("theft") == -30
    assert trust_delta("theft", "told_by:elise") == -15
    assert trust_delta("gift", gift_pref="loved") == 20
    assert trust_delta("walk_away") == 0


def test_band_edges():
    assert [band(t) for t in (-50, -49, -11, -10, 29, 30)] == ["hostile", "wary", "wary", "neutral", "neutral", "friendly"]


def test_trade_terms():
    elise, rowan = load_config()["npcs"]["elise"], load_config()["npcs"]["rowan"]
    assert trade_terms(elise, 40)["cost"] == {"item": "iron", "count": 1}
    assert trade_terms(elise, 40)["give"] == {"item": "apple", "count": 3}
    assert trade_terms(elise, -20)["cost"]["count"] == 3
    assert trade_terms(elise, -60) == {"ok": False, "reason": "hostile"}
    assert trade_terms(rowan, 40, work_block_present=False) == {"ok": False, "reason": "no_work_block"}
    assert trade_terms(elise, 40, work_block_present=False)["ok"]


def test_gift_pref_and_items():
    elise = load_config()["npcs"]["elise"]
    assert gift_pref(elise, "gold_apple") == "loved"
    assert gift_pref(elise, "coal") == "disliked"
    assert gift_pref(elise, None) == "neutral"
    assert short_item("default:steel_ingot") == "iron"
    assert short_item("default:dirt") is None


def test_apology_once_per_day():
    assert apology_allowed(None, 3.0)
    assert not apology_allowed(2.5, 3.0)
    assert apology_allowed(2.0, 3.0)


def test_no_trade_villager():
    assert trade_terms(load_config()["npcs"]["pip"], 50) == {"ok": False, "reason": "no_trade"}


def test_every_villager_has_one_main_quest_with_known_item():
    cfg = load_config()
    for npc_id, npc in cfg["npcs"].items():
        mains = [q for q in npc["quests"] if q["main"]]
        assert len(mains) == 1, npc_id
        assert mains[0]["kind"] == "slay" or mains[0]["item"] in cfg["items"], npc_id
        assert 0 <= npc["chattiness"] <= 1


def test_main_quests_are_short():
    for npc_id, npc in load_config()["npcs"].items():
        main = next(q for q in npc["quests"] if q["main"])
        assert main["count"] <= 5, npc_id
