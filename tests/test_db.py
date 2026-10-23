from backend import db


def theft(player="w:p"):
    return {"player": player, "type": "theft", "actor": player, "target": "elise",
            "details": {"item": "apple"}, "witnesses": ["elise"], "game_time": 1.0,
            "source": "game", "verified": True, "confidence": None}


def test_schema_and_seed(conn):
    names = {r["id"] for r in conn.execute("select id from npcs")}
    assert names == {"elise", "rowan", "mira"}
    assert db.get_trust(conn, "elise", "w:p") == 10


def test_trust_clamped(conn):
    assert db.add_trust(conn, "elise", "w:p", -500) == -100
    assert db.add_trust(conn, "elise", "w:p", 30) == -70


def test_persists_across_restart(db_path):
    c1 = db.connect(db_path)
    eid = db.add_event(c1, theft())
    db.add_memory(c1, "elise", "w:p", eid, "theft", "Saw them take an apple.", "witnessed", 1.0, 30)
    c1.close()
    c2 = db.connect(db_path)
    assert db.top_memories(c2, "elise", "w:p")[0]["event_id"] == eid
    c2.close()


def test_top_memories_order_and_limit(conn):
    for sev in range(5, 40, 5):
        eid = db.add_event(conn, theft())
        db.add_memory(conn, "elise", "w:p", eid, "theft", f"sev {sev}", "witnessed", 1.0, sev)
    mems = db.top_memories(conn, "elise", "w:p")
    assert len(mems) == 5
    assert [m["text"] for m in mems] == ["sev 35", "sev 30", "sev 25", "sev 20", "sev 15"]
    assert db.top_memories(conn, "elise", "other:p") == []


def test_new_npc_seeded_on_reconnect(db_path, monkeypatch):
    db.connect(db_path).close()
    cfg = db.load_config()
    cfg["npcs"]["tom"] = {**cfg["npcs"]["mira"], "name": "Tom"}
    monkeypatch.setattr(db, "load_config", lambda: cfg)
    c = db.connect(db_path)
    assert c.execute("select 1 from npcs where id='tom'").fetchone()
    c.close()


def test_promises_and_flags(conn):
    pid = db.add_promise(conn, "promise", "elise", "w:p", "iron", 2, 2.0)
    assert db.open_promises(conn, "elise", "w:p")[0]["count"] == 2
    db.update_promise(conn, pid, status="kept")
    assert db.open_promises(conn, "elise", "w:p") == []
    assert db.get_flag(conn, "elise", "w:p", "last_apology") is None
    db.set_flag(conn, "elise", "w:p", "last_apology", 1.5)
    assert db.get_flag(conn, "elise", "w:p", "last_apology") == 1.5


def test_interactions(conn):
    iid = db.add_interaction(conn, {"task": "npc_dialogue", "npc_id": "elise", "player": "w:p", "thread_id": "t",
                                    "request": {"a": 1}, "reply": "hi", "mubit_request_id": None,
                                    "latency_ms": 5, "tokens": None, "validator_result": {"ok": True},
                                    "retried": False, "outcome": None, "prev_id": None})
    assert db.list_interactions(conn, "elise")[0]["id"] == iid
