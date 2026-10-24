"""End-to-end checks for every ending this build can reach.

Luanti is a native window, so Playwright cannot click it. These tests drive the same HTTP routes the
mod calls. The app is built with a live model client chosen by NPCASSO_E2E:

  ollama  a local Ollama (qwen2.5:3b). Nothing is read from .env, so no paid key is used.
  mubit   the Mubit route from .env (MUBIT_API_KEY). The Claude key is never used.

One greet proves the model actually answers. Naming an ending is what /tick returns after the
score is recorded. A spoken line can write that score; this test seeds it so the ending does not
depend on how the model weighs one greeting.

Run:  NPCASSO_E2E=ollama .venv\\Scripts\\python -m pytest tests/test_endings_e2e.py -q
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.app import create_app
from backend.finale import ENDINGS, SPEAKERS
from backend.llm import OpenAICompatLLM, make_llm
from backend.story import SIGNATURES, add_evidence, anchor

MODE = os.getenv("NPCASSO_E2E")
pytestmark = pytest.mark.skipif(MODE not in ("ollama", "mubit"), reason="set NPCASSO_E2E=ollama or mubit")

OLLAMA = "http://127.0.0.1:11434/v1"


def live_llm():
    """The model client for this run. Mubit reads .env; Ollama never does."""
    if MODE == "mubit":
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        client = make_llm("mubit")
        assert "api.mubit.ai" in str(client.client.base_url)
        return client
    client = OpenAICompatLLM(OLLAMA, "ollama", "qwen2.5:3b", send_metadata=False, timeout=60, force_json=True)
    assert "11434" in str(client.client.base_url)
    assert "anthropic" not in str(client.client.base_url)
    return client


@pytest.fixture(scope="module")
def llm():
    return live_llm()


@pytest.fixture(scope="module")
def ollama_spoke(llm, tmp_path_factory):
    """One real greet. The validator may drop the line; the model still has to answer from Ollama."""
    path = str(tmp_path_factory.mktemp("ollama") / "t.db")
    res = TestClient(create_app(path, llm)).post("/greet", json={
        "world": "w", "player": "p", "npc_id": "elise", "thread_id": "e2e", "game_time": 0.1,
    })
    assert res.status_code == 200, res.text
    conn = db.connect(path)
    try:
        rows = conn.execute("select reply, latency_ms from interactions").fetchall()
    finally:
        conn.close()
    assert rows, "Ollama was never called"
    assert any((r["reply"] or "").strip() for r in rows), "Ollama returned an empty reply"
    assert all(r["latency_ms"] and r["latency_ms"] > 0 for r in rows)
    return True


def _arrive(db_path, llm, weights, game_time):
    client = TestClient(create_app(db_path, llm))
    event = client.post("/event", json={
        "world": "w", "player": "p", "type": "gift", "target": "elise",
        "details": {"item": "default:apple"}, "witnesses": ["elise"], "game_time": 0.2,
    })
    assert event.status_code == 200, event.text
    conn = db.connect(db_path)
    try:
        anchor(conn, "w:p", 0)
        for dim, weight in weights:
            add_evidence(conn, "w:p", dim, weight, event.json()["event_id"], "e2e")
    finally:
        conn.close()
    tick = client.post("/tick", json={"world": "w", "player": "p", "game_time": game_time})
    assert tick.status_code == 200, tick.text
    return tick.json()


@pytest.mark.parametrize("ending", list(SIGNATURES))
def test_steered_ending(db_path, llm, ollama_spoke, ending):
    weights = [(dim, float(sign)) for dim, sign in SIGNATURES[ending].items()]
    out = _arrive(db_path, llm, weights, 6.5)
    assert out["phase"] == "closing"
    assert out["ending"] == ending
    assert out["day"] == 7 and out["time"] == "12:00"
    assert out["sustain"] is True and out["cold"] > 0


@pytest.mark.parametrize("ending", list(SIGNATURES))
def test_standing_with_the_village_plays_the_ending(db_path, llm, ollama_spoke, ending):
    """Steer, the village gathers, the player stands with them, the scene plays, the run is over."""
    weights = [(dim, float(sign)) for dim, sign in SIGNATURES[ending].items()]
    tick = _arrive(db_path, llm, weights, 6.5)
    assert tick["offer"] is True and tick["offer_text"] == ENDINGS[ending]["offer"]
    assert ENDINGS[ending]["title"] not in tick["offer_text"]
    client = TestClient(create_app(db_path, llm))
    res = client.post("/ending/accept", json={"world": "w", "player": "p", "game_time": 6.5})
    assert res.status_code == 200, res.text
    scene = res.json()
    assert scene["ending"] == ending and scene["title"] == ENDINGS[ending]["title"]
    kinds = [s["kind"] for s in scene["slides"]]
    assert kinds[-1] == "title" and kinds.count("line") == SPEAKERS and kinds[0] == "narration"
    assert all(s["text"].strip() for s in scene["slides"])
    after = client.post("/tick", json={"world": "w", "player": "p", "game_time": 6.6}).json()
    assert after["phase"] == "ended" and after["ending"] == ending and after["cold"] == 0
    assert after["sustain"] is True and "offer" not in after
    assert client.post("/ending/accept", json={"world": "w", "player": "p", "game_time": 6.7}).status_code == 422


def test_walking_away_from_the_village_ends_in_the_freeze(db_path, llm, ollama_spoke):
    """Refuse the gathering, hear nothing more for half a day, and the cold takes the run on day ten."""
    weights = [("candor", 1.0), ("bravery", 1.0), ("loyalty", 1.0)]
    assert _arrive(db_path, llm, weights, 6.5)["offer"] is True
    client = TestClient(create_app(db_path, llm))
    refused = client.post("/ending/refuse", json={"world": "w", "player": "p", "game_time": 6.5})
    assert refused.json() == {"ok": True}
    quiet = client.post("/tick", json={"world": "w", "player": "p", "game_time": 6.7}).json()
    assert "offer" not in quiet and quiet["phase"] == "closing" and quiet["sustain"] is True
    assert client.post("/tick", json={"world": "w", "player": "p", "game_time": 7.2}).json()["offer"] is True
    out = client.post("/tick", json={"world": "w", "player": "p", "game_time": 9}).json()
    assert out["phase"] == "frozen" and out["day"] == 10 and out["time"] == "00:00"
    assert out["sustain"] is False and out["cold"] == 20
    assert "ending" not in out and "offer" not in out
    assert client.post("/ending/accept", json={"world": "w", "player": "p", "game_time": 9}).status_code == 422


def test_dying_ends_the_run_with_no_ending(db_path, llm, ollama_spoke):
    _arrive(db_path, llm, [("candor", 1.0), ("bravery", 1.0), ("loyalty", 1.0)], 6.5)
    client = TestClient(create_app(db_path, llm))
    assert client.post("/die", json={"world": "w", "player": "p"}).json() == {"ok": True}
    out = client.post("/tick", json={"world": "w", "player": "p", "game_time": 6.6}).json()
    assert out["phase"] == "ended" and "ending" not in out and "offer" not in out and out["cold"] == 0
    assert client.post("/ending/accept", json={"world": "w", "player": "p", "game_time": 6.7}).status_code == 422


def test_a_whole_run_through_the_local_model(db_path, llm, ollama_spoke):
    """Arrive, meet people, talk in the pressure season, then close the run through the gathering.

    The model's wording is Ollama's and may fail validation; every route must still answer and keep its shape.
    """
    client = TestClient(create_app(db_path, llm))
    base = {"world": "w", "player": "p"}
    assert client.post("/tick", json={**base, "game_time": 0.1}).json()["phase"] == "open"
    gift = client.post("/event", json={**base, "type": "gift", "target": "elise", "details": {"item": "default:apple"},
                                      "witnesses": ["elise"], "game_time": 0.2})
    assert gift.status_code == 200
    assert client.post("/react", json={**base, "event_id": gift.json()["event_id"],
                                       "npc_ids": gift.json()["react"]}).status_code == 200
    day3 = {**base, "game_time": 2.4}
    assert client.post("/tick", json=day3).json()["phase"] == "pressure"
    for npc in ("elise", "rowan", "mira"):
        greet = client.post("/greet", json={**day3, "npc_id": npc, "thread_id": f"g-{npc}"})
        assert greet.status_code == 200 and "reply" in greet.json()
    talk = client.post("/talk", json={**day3, "npc_id": "elise", "message": "How is everyone coping with the cold?",
                                      "thread_id": "t1"})
    assert talk.status_code == 200 and talk.json()["reply"].strip()
    conn = db.connect(db_path)
    try:
        for dim, sign in SIGNATURES["last_place_at_the_table"].items():
            add_evidence(conn, "w:p", dim, float(sign), None, "e2e")
    finally:
        conn.close()
    gathering = client.post("/tick", json={**base, "game_time": 6.5}).json()
    assert gathering["phase"] == "closing" and gathering["ending"] == "last_place_at_the_table"
    assert gathering["offer"] is True
    scene = client.post("/ending/accept", json={**base, "game_time": 6.5}).json()
    assert scene["title"] == "The Last Place at the Table" and scene["slides"][-1]["kind"] == "title"
    assert client.post("/tick", json={**base, "game_time": 6.6}).json()["phase"] == "ended"


def test_open_day_does_not_name_an_ending(db_path, llm, ollama_spoke):
    out = _arrive(db_path, llm, [("candor", 1.0), ("bravery", 1.0), ("loyalty", 1.0)], 0.4)
    assert out["phase"] == "open" and out["day"] == 1 and out["cold"] == 0 and out["sustain"] is True
    assert "ending" not in out
