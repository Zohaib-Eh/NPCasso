"""Deterministic check of an NPC output against what that NPC actually knows."""
import re

from . import situations
from .db import load_config

# Words that assert a past event: an error without a claim. Words common in advice ("a gift of flowers",
# "hit the stone") only get flagged.
EVENT_WORDS = ("stole", "stolen", "gave", "broke", "smashed", "promised")
SOFT_WORDS = ("gift", "hit", "steal", "theft", "thief", "promise")
HARMFUL_WARM = {"welcome", "friend", "lovely", "glad", "delighted", "pleasure", "wonderful"}
WARM_WORDS = ("friend", "dear", "lovely", "glad", "welcome")
TEXT_KEY = {"npc_dialogue": "reply", "npc_react": "shout"}
HANDED = ("hand you", "here's", "here is", "i'll give you", "i will give you", "take this")


BRING = ("bring me", "bring you", "fetch me", "get me ", "can you bring", "could you bring")


def _need_words(need: dict) -> set[str]:
    """The ways a villager may name what they need: the item itself, or the words of what they asked for."""
    item = (need.get("item") or "").replace("_", " ")
    words = {item, f"{item}s"} if item else set()
    words |= set(re.findall(r"[a-z]+", (need.get("what") or "").lower()))
    return words


def _task_errors(output: dict, facts: dict, items: list) -> list[str]:
    """The only chore a villager may ask is their own need. A different one is sent back."""
    need = (facts.get("need") or {}).get("item") or ""
    need = need.replace("_", " ")
    offer = output.get("quest_offer")
    if isinstance(offer, dict) and offer.get("item") and offer.get("item") != (facts.get("need") or {}).get("item"):
        return ["wrong_task"]
    text = (output.get("reply") or "").lower()
    if not any(p in text for p in BRING):
        return []
    if any(w in text for w in _need_words(facts.get("need") or {})):
        return []
    for item in items or []:
        word = item.replace("_", " ")
        if word and word != need and (word in text or f"{word}s" in text):
            return ["wrong_task"]
    return ["wrong_task"] if any(p in text for p in BRING) else []


def _ease_errors(output: dict, facts: dict) -> list[str]:
    """The first conversations introduce the village. The ask comes after that."""
    if facts.get("ease") not in ("introduce", "hint") or facts.get("lost"):
        return []
    text = (output.get("reply") or "").lower()
    if output.get("quest_offer") or any(p in text for p in BRING):
        return ["too_soon"]
    return []


def _lost_errors(output: dict, facts: dict) -> list[str]:
    """A lost player who asked what to do next gets this villager's own directions."""
    if not facts.get("lost"):
        return []
    text = (output.get("reply") or "").lower()
    need = facts.get("need") or {}
    item = (need.get("item") or "").replace("_", " ")
    place = (need.get("place") or "").replace("_", " ")
    if item and (any(w in text for w in _need_words(need)) or (place and place in text)):
        return []
    if not item and len(text) > 40:
        return []
    return ["no_directions"]


def _reward_errors(output: dict, facts: dict) -> list[str]:
    """The payment an errand names has to be the one the quest actually gives."""
    need = facts.get("need") or {}
    reward = (need.get("payment") or "").lower()
    task_item = (need.get("item") or "").replace("_", " ")
    if not reward:
        ask = facts.get("ask") or {}
        reward = (ask.get("reward") or "").lower()
        task_item = (ask.get("item") or "").replace("_", " ")
        if ask.get("kind") != "errand" or not reward:
            return []
    text = (output.get("reply") or "").lower()
    phrases = [text.find(p) for p in ("give you", "i'll give", "i will give", "in return") if p in text]
    if need.get("payment") and not phrases:
        return []
    if need.get("payment"):
        text = text[min(phrases):]  # only the offer is a payment; "the wheat field" earlier is a place
    for item in facts.get("stock") or []:
        word = item.replace("_", " ")
        if word and word != task_item and word in text and word not in reward:
            return ["wrong_reward"]
    return []


def _gift_errors(output: dict, facts: dict) -> list[str]:
    """A villager may only hand over something they keep, and only if the game is told to give it."""
    gift = output.get("give_item")
    stock = facts.get("stock") or []
    if gift is not None:
        count = gift.get("count", 1) if isinstance(gift, dict) else None
        if not (isinstance(gift, dict) and gift.get("item") in stock and isinstance(count, int) and 1 <= count <= 4):
            return ["gift_not_stock"]
        return []
    text = (output.get("reply") or "").lower()
    pays = ((facts.get("need") or {}).get("payment") or "").lower()  # a promised payment is not a handover
    named = [item for item in stock if item.replace("_", " ") in text and item.replace("_", " ") not in pays]
    if any(p in text for p in HANDED) and named:
        return ["promised_gift"]
    return []


def validate(task: str, output: dict | None, context: dict) -> dict:
    res = {"ok": False, "errors": [], "flags": [], "drop_quest": False}
    text = (output or {}).get(TEXT_KEY[task])
    claims = (output or {}).get("claims")
    if not isinstance(text, str) or not text.strip() or not isinstance(claims, list) \
            or not all(isinstance(c, dict) for c in claims):
        res["errors"].append("malformed")
        return res

    known = {m["event_id"]: m for m in context.get("memories", [])}
    known.update({e["id"]: {**e, "how": "witnessed"} for e in [context.get("event") or {}] if e.get("id")})
    for c in claims:
        eid = c.get("event_id")
        mem = known.get(eid) if isinstance(eid, int) else None
        if mem is None:
            res["errors"].append(f"invented_event:{'null' if eid is None else eid}")
        elif c.get("type") != mem["type"]:
            res["errors"].append(f"type_mismatch:{eid}")
        elif c.get("how") == "witnessed" and mem["how"].startswith("told"):
            res["errors"].append(f"rumour_as_fact:{eid}")

    words = set(re.findall(r"[a-z]+", text.lower()))
    if "gave" in words and not re.search(r"\bgave (you|me|us|them)\b|\b(you|they|he|she) gave\b", text.lower()):
        words.discard("gave")  # "where I once gave out a bunch" is a habit, not an event with the player
    if not claims:
        # Dialogue must back every event it mentions with a claim; a reaction is about the event itself.
        res["errors" if task == "npc_dialogue" else "flags"] += [f"unclaimed_mention:{w}" for w in EVENT_WORDS
                                                                 if w in words]
        res["flags"] += [f"unclaimed_mention:{w}" for w in SOFT_WORDS if w in words]
    if context.get("relationship", {}).get("band") in ("hostile", "wary") and words & set(WARM_WORDS):
        res["flags"].append("tone_mismatch")

    if task == "npc_dialogue":
        facts = context.get("facts") or {}
        res["errors"] += _gift_errors(output, facts)
        res["errors"] += _reward_errors(output, facts)
        res["errors"] += _task_errors(output, facts, context.get("items") or [])
        res["errors"] += _lost_errors(output, facts)
        res["errors"] += _ease_errors(output, facts)
        if (facts.get("stance") or {}).get("mood") in ("angry", "afraid", "hurt", "cold") and words & HARMFUL_WARM:
            res["errors"].append("tone_mismatch")
    quest = output.get("quest_offer")
    if quest and (not isinstance(quest, dict) or quest.get("item") not in context.get("items", [])
                  or not isinstance(quest.get("count", 1), int) or quest.get("count", 1) < 1):
        res["drop_quest"] = True
    res["errors"] += situations.errors(output, context.get("facts") or {}, load_config()["npcs"]) \
        if task == "npc_dialogue" else []
    res["ok"] = not res["errors"]
    return res
