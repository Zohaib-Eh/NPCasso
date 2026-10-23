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
    assert c.get("/interactions", params={"npc_id": "elise"}).json()[0]["task"] == "npc_react"


def test_event_unknown_type_422(db_path):
    assert client(db_path).post("/event", json={**EV, "type": "teleport"}).status_code == 422


def test_npcs_list(db_path):
    assert client(db_path).get("/npcs").json()["elise"] == {"name": "Elise", "role": "Merchant"}


TALK = {"world": "w", "player": "p", "npc_id": "elise", "message": "hello", "thread_id": "t", "game_time": 1.0}


def test_talk_ok(db_path):
    r = client(db_path).post("/talk", json=TALK)
    assert r.status_code == 200 and r.json()["reply"]


def test_talk_rejects_bad_message(db_path):
    c = client(db_path)
    for m in ("", "   ", "x" * 501):
        assert c.post("/talk", json={**TALK, "message": m}).status_code == 422
    assert c.post("/talk", json={**TALK, "npc_id": "bob"}).status_code == 422
