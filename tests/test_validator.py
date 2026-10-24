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
    assert "wrong_task" in r["errors"] and r["drop_quest"]
    coal = v({"reply": "Bring coal.", "claims": [], "quest_offer": {"item": "coal", "count": 2, "reward": "apple"}})
    assert "wrong_task" in coal["errors"]


def test_a_different_chore_is_rejected():
    ctx = {"memories": [], "items": ["apple", "coal", "bread"],
           "facts": {"need": {"item": "apple", "what": "3 apple", "payment": "2 steel ingot"}, "stock": ["apple", "bread"]}}
    assert "wrong_task" in validate("npc_dialogue", {"reply": "Bring me coal.", "claims": []}, ctx)["errors"]
    assert "wrong_task" not in validate("npc_dialogue",
                                        {"reply": "Three apples from the orchard would help.", "claims": []}, ctx)["errors"]


def test_errand_cannot_promise_a_different_payment():
    ctx = {"memories": [], "facts": {"ask": {"kind": "errand", "item": "apple", "reward": "2 steel ingot"},
                                    "stock": ["apple", "bread"]}}
    lied = {"reply": "Bring me three apples and I'll give you bread.", "claims": []}
    assert "wrong_reward" in validate("npc_dialogue", lied, ctx)["errors"]
    honest = {"reply": "Bring me three apples and I'll give you 2 steel ingots.", "claims": []}
    assert "wrong_reward" not in validate("npc_dialogue", honest, ctx)["errors"]


def test_an_honest_ask_in_natural_words_passes():
    ctx = {"memories": [], "items": ["flower", "bread"],
           "facts": {"need": {"item": "flower", "what": "3 roses", "payment": "3 bread"}, "stock": ["bread"]}}
    ask = {"reply": "Could you bring me 3 roses from the meadow? I'll give you 3 bread for them.", "claims": []}
    assert validate("npc_dialogue", ask, ctx)["errors"] == []


def test_a_cheerful_reply_from_an_angry_villager_is_rejected():
    ctx = {"memories": [], "facts": {"stance": {"mood": "angry", "strength": "strong", "cause": "you hit me"}}}
    warm = {"reply": "Welcome, friend! Lovely to see you.", "claims": []}
    assert "tone_mismatch" in validate("npc_dialogue", warm, ctx)["errors"]
    cold = {"reply": "Get away from my stall.", "claims": []}
    assert validate("npc_dialogue", cold, ctx)["errors"] == []
