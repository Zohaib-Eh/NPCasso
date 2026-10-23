"""Deterministic check of an NPC output against what that NPC actually knows."""
import re

EVENT_WORDS = ("stole", "steal", "stolen", "theft", "thief", "gift", "gave", "broke", "smashed", "hit", "promise",
               "promised")
WARM_WORDS = ("friend", "dear", "lovely", "glad", "welcome")
TEXT_KEY = {"npc_dialogue": "reply", "npc_react": "shout"}


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
    if not claims:
        # Dialogue must back every event it mentions with a claim; a reaction is about the event itself.
        res["errors" if task == "npc_dialogue" else "flags"] += [f"unclaimed_mention:{w}" for w in EVENT_WORDS
                                                                 if w in words]
    if context.get("relationship", {}).get("band") in ("hostile", "wary") and words & set(WARM_WORDS):
        res["flags"].append("tone_mismatch")

    quest = output.get("quest_offer")
    if quest and (not isinstance(quest, dict) or quest.get("item") not in context.get("items", [])
                  or not isinstance(quest.get("count", 1), int) or quest.get("count", 1) < 1):
        res["drop_quest"] = True
    res["ok"] = not res["errors"]
    return res
