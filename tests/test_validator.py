from backend.validator import validate

CTX = {"memories": [{"event_id": 1, "type": "theft", "how": "witnessed"},
                    {"event_id": 2, "type": "gift", "how": "told_by:elise"}],
       "relationship": {"band": "wary"}, "items": ["apple", "iron", "coal"]}


def claim(eid, type, how="witnessed"):
    return {"event_id": eid, "type": type, "how": how}


def v(out, task="npc_dialogue"):
    return validate(task, out, CTX)


def test_clean():
    r = v({"reply": "You took my apple.", "claims": [claim(1, "theft")]})
    assert r == {"ok": True, "errors": [], "flags": [], "drop_quest": False}


def test_rumour_told_is_fine():
    assert v({"reply": "Heard about a gift.", "claims": [claim(2, "gift", "told")]})["ok"]


def test_invented():
    assert "invented_event:9" in v({"reply": "x", "claims": [claim(9, "gift")]})["errors"]
    assert "invented_event:null" in v({"reply": "x", "claims": [claim(None, "gift")]})["errors"]


def test_type_mismatch():
    assert "type_mismatch:1" in v({"reply": "x", "claims": [claim(1, "gift")]})["errors"]


def test_rumour_as_fact():
    assert "rumour_as_fact:2" in v({"reply": "x", "claims": [claim(2, "gift")]})["errors"]


def test_malformed():
    assert v(None)["errors"] == ["malformed"]
    assert v({"reply": "", "claims": []})["errors"] == ["malformed"]
    assert v({"reply": "hi"})["errors"] == ["malformed"]
    assert v({"reply": "hi", "claims": ["x"]})["errors"] == ["malformed"]


def test_react_needs_shout():
    assert not v({"reply": "hi", "claims": []}, "npc_react")["ok"]
    assert v({"shout": "Oi!", "memory": "m", "claims": [claim(1, "theft")]}, "npc_react")["ok"]


def test_unclaimed_mention_is_error():
    r = v({"reply": "Thanks for the bread you gave me.", "claims": []})
    assert not r["ok"] and "unclaimed_mention:gave" in r["errors"]
    assert "unclaimed_mention:promised" in v({"reply": "You promised me iron!", "claims": []})["errors"]
    r = v({"reply": "Keep your promise and don't steal.", "claims": []})
    assert r["ok"] and "unclaimed_mention:promise" in r["flags"]


def test_advice_words_only_flag():
    r = v({"reply": "Mira loves a gift of flowers. Hit stone with a pickaxe.", "claims": []})
    assert r["ok"] and "unclaimed_mention:gift" in r["flags"] and "unclaimed_mention:hit" in r["flags"]


def test_event_words_fine_when_claimed():
    assert v({"reply": "You stole my apple.", "claims": [claim(1, "theft")]})["ok"]


def test_tone_flag():
    assert "tone_mismatch" in v({"reply": "Welcome, dear friend!", "claims": []})["flags"]


def test_bad_quest_dropped():
    r = v({"reply": "Bring me gems.", "claims": [], "quest_offer": {"item": "gems", "count": 1, "reward": "apple"}})
    assert r["ok"] and r["drop_quest"]
    assert not v({"reply": "Bring coal.", "claims": [],
                  "quest_offer": {"item": "coal", "count": 2, "reward": "apple"}})["drop_quest"]
