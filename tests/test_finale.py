import pytest
from fastapi.testclient import TestClient

from backend import db, finale
from backend.app import create_app
from backend.game import accept_ending, refuse_ending, tick
from backend.llm import MockLLM
from backend.story import SIGNATURES, add_evidence, anchor, report
from tests.conftest import ScriptedLLM


def lean(conn, ending, player="w:p"):
    anchor(conn, player, 0.0)
    for dim, sign in SIGNATURES[ending].items():
        add_evidence(conn, player, dim, float(sign), None, "t")


def test_the_village_gathers_from_day_seven_not_before(conn):
    lean(conn, "names_we_buried")
    early = report(conn, "w:p", 5.5)  # day 6, closing: the steer shows, the gathering has not formed
    assert early["phase"] == "closing" and early["ending"] == "names_we_buried" and "offer" not in early
    assert report(conn, "w:p", 6.5)["offer"] is True
    out = tick(conn, MockLLM(), "w", "p", 6.5)
    assert out["offer_text"] == finale.ENDINGS["names_we_buried"]["offer"]
    assert "Names" not in out["offer_text"]  # the offer never names the ending


def test_no_lean_no_offer(conn):
    anchor(conn, "w:p", 0.0)
    assert "offer" not in report(conn, "w:p", 6.5)


def test_walking_away_quiets_the_offer_then_it_returns(conn):
    lean(conn, "the_peace_you_made")
    refuse_ending(conn, "w", "p", 6.5)
    assert "offer" not in report(conn, "w:p", 6.8)
    assert report(conn, "w:p", 7.2)["offer"] is True
    assert report(conn, "w:p", 6.8)["phase"] == "closing"


@pytest.mark.parametrize("ending", list(SIGNATURES))
def test_accepting_plays_the_ending_and_ends_the_run(conn, ending):
    lean(conn, ending)
    db.add_memory(conn, "elise", "w:p", 1, "gift", "the newcomer gave me bread", "witnessed", 1.0, 20, 1.0)
    scene = accept_ending(conn, MockLLM(), "w", "p", 6.5)
    e = finale.ENDINGS[ending]
    assert scene["ending"] == ending and scene["title"] == e["title"] and scene["tint"] == e["tint"]
    kinds = [s["kind"] for s in scene["slides"]]
    assert kinds[:2] == ["narration"] * 2 and kinds[-1] == "title" and kinds.count("line") == finale.SPEAKERS
    assert scene["slides"][-1]["text"] == e["title"]
    assert all(s["text"].strip() for s in scene["slides"])
    done = report(conn, "w:p", 6.6)
    assert done["phase"] == "ended" and done["ending"] == ending and done["cold"] == 0 and done["sustain"] is True


def test_the_villager_who_remembers_most_speaks_first(conn):
    lean(conn, "last_place_at_the_table")
    db.add_memory(conn, "rowan", "w:p", 1, "gift", "the newcomer gave me iron", "witnessed", 1.0, 40, 1.0)
    db.add_memory(conn, "elise", "w:p", 2, "gift", "the newcomer gave me bread", "witnessed", 1.0, 10, 1.0)
    scene = accept_ending(conn, MockLLM(), "w", "p", 6.5)
    assert [s["who"] for s in scene["slides"] if s["kind"] == "line"][:2] == ["Rowan", "Elise"]


def test_a_failed_voice_falls_back_to_the_fixed_line(conn):
    lean(conn, "the_last_departure")
    scene = accept_ending(conn, ScriptedLLM([None, None, None]), "w", "p", 6.5)
    lines = [s["text"] for s in scene["slides"] if s["kind"] == "line"]
    assert lines == [finale.ENDINGS["the_last_departure"]["fallback"]] * 3


def test_only_the_five_endings_exist():
    assert set(finale.ENDINGS) == set(SIGNATURES)


def test_cannot_accept_without_an_offer(conn):
    anchor(conn, "w:p", 0.0)
    with pytest.raises(ValueError):
        accept_ending(conn, MockLLM(), "w", "p", 6.5)
    lean(conn, "names_we_buried", "w:q")
    with pytest.raises(ValueError):
        accept_ending(conn, MockLLM(), "w", "q", 3.0)  # pressure, nothing is offered yet


def test_routes(db_path):
    c = TestClient(create_app(db_path, MockLLM()))
    body = {"world": "w", "player": "p", "game_time": 6.5}
    assert c.post("/ending/accept", json={**body, "player": "nobody"}).status_code == 422
    conn = db.connect(db_path)
    lean(conn, "names_we_buried")
    conn.close()
    assert c.post("/tick", json=body).json()["offer"] is True
    assert c.post("/ending/refuse", json=body).json() == {"ok": True}
    assert "offer" not in c.post("/tick", json={**body, "game_time": 6.7}).json()
    scene = c.post("/ending/accept", json={**body, "game_time": 7.3}).json()
    assert scene["ending"] == "names_we_buried" and scene["slides"][-1]["kind"] == "title"
    assert c.post("/tick", json={**body, "game_time": 7.4}).json()["phase"] == "ended"
