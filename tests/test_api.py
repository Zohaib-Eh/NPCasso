from fastapi.testclient import TestClient

from backend.app import create_app
from backend.llm import MockLLM

EV = {"world": "w", "player": "p", "type": "theft", "target": "elise", "details": {"item": "default:apple"},
      "witnesses": ["elise"], "game_time": 1.0}


def client(db_path):
    return TestClient(create_app(db_path, MockLLM()))


def test_health(db_path):
    assert client(db_path).get("/health").json() == {"ok": True, "provider": "MockLLM"}


def test_event_and_npc(db_path):
    c = client(db_path)
    r = c.post("/event", json=EV)
    assert r.status_code == 200 and r.json()["notices"] == ["Elise will remember that."]
    s = c.get("/npc/elise", params={"world": "w", "player": "p"}).json()
    assert s["band"] == "wary" and len(s["memories"]) == 1
    react = c.post("/react", json={"world": "w", "player": "p", "event_id": r.json()["event_id"],
                                   "npc_ids": r.json()["react"]}).json()
    assert react["shouts"][0]["npc_id"] == "elise"
    assert c.get("/interactions", params={"npc_id": "elise"}).json()[0]["task"] == "npc_react"


def test_event_unknown_type_422(db_path):
    assert client(db_path).post("/event", json={**EV, "type": "teleport"}).status_code == 422


def test_npcs_list(db_path):
    n = client(db_path).get("/npcs").json()
    assert n["elise"]["name"] == "Elise" and n["elise"]["role"] == "Merchant"
    assert n["rowan"]["work_block"] == "cottages:anvil"


TALK = {"world": "w", "player": "p", "npc_id": "elise", "message": "hello", "thread_id": "t", "game_time": 1.0}


def test_talk_ok(db_path):
    r = client(db_path).post("/talk", json=TALK)
    assert r.status_code == 200 and r.json()["reply"]


def test_talk_rejects_bad_message(db_path):
    c = client(db_path)
    for m in ("", "   ", "x" * 501):
        assert c.post("/talk", json={**TALK, "message": m}).status_code == 422
    assert c.post("/talk", json={**TALK, "npc_id": "bob"}).status_code == 422


def test_trade_and_tick_routes(db_path):
    c = client(db_path)
    assert c.post("/trade", json={"world": "w", "player": "p", "npc_id": "elise", "work_block_present": True}).json()["ok"]
    assert c.post("/tick", json={"world": "w", "player": "p", "game_time": 1.0}).json() == {"notices": [], "shouts": []}


def test_event_accepts_lua_empty_tables(db_path):
    c = client(db_path)
    for empty in ({}, None):
        r = c.post("/event", json={**EV, "type": "gift", "witnesses": empty, "details": {"item": "flowers:rose"}})
        assert r.status_code == 200, r.text
    r = c.post("/event", json={**EV, "type": "walk_away", "witnesses": {}, "details": []})
    assert r.status_code == 200, r.text


def test_greet(db_path):
    c = client(db_path)
    e = c.post("/event", json=EV).json()
    c.post("/react", json={"world": "w", "player": "p", "event_id": e["event_id"], "npc_ids": e["react"]})
    r = c.post("/greet", json={"world": "w", "player": "p", "npc_id": "elise", "thread_id": "g", "game_time": 1.2})
    assert r.status_code == 200 and "the newcomer took apple from my stall without paying" in r.json()["reply"]


def test_quest_routes(db_path):
    c = client(db_path)
    assert c.get("/quests", params={"world": "w", "player": "p"}).json()["available"]
    assert c.post("/quest/accept", json={"world": "w", "player": "p", "quest_id": "find_apples"}).status_code == 200
    assert c.post("/quest/accept", json={"world": "w", "player": "p", "quest_id": "find_apples"}).status_code == 422
    r = c.post("/quest/handin", json={"world": "w", "player": "p", "npc_id": "elise", "items": {"default:apple": 5},
                                      "game_time": 1.0}).json()
    assert r["consumed"] == {"default:apple": 3}
    p = c.get("/player", params={"world": "w", "player": "p"}).json()
    assert p["xp"] == 30 and p["quests"]["done"][0]["id"] == "find_apples"


def test_npcs_have_kind_and_sign(db_path):
    n = client(db_path).get("/npcs").json()
    assert n["elise"]["kind"] == "trader" and n["pip"]["kind"] == "villager"
    assert n["elise"]["sign"]
