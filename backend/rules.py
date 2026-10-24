"""Deterministic game rules. The LLM never changes state; only these do."""
from .db import load_config

CONFIG = load_config()
BAND_MULT = {"friendly": 1, "neutral": 2, "wary": 3}


def trust_delta(event_type: str, how: str = "witnessed", gift_pref: str | None = None) -> int:
    key = f"gift_{gift_pref or 'neutral'}" if event_type == "gift" else event_type
    delta = CONFIG["deltas"].get(key, 0)
    return int(delta / 2) if how.startswith("told") else delta


def band(trust: int) -> str:
    if trust <= -50:
        return "hostile"
    if trust < -10:
        return "wary"
    return "neutral" if trust < 30 else "friendly"


def gift_pref(npc_cfg: dict, item: str | None) -> str:
    for pref in ("loves", "likes", "dislikes"):
        if item in npc_cfg.get(pref, []):
            return {"loves": "loved", "likes": "liked", "dislikes": "disliked"}[pref]
    return "neutral"


def short_item(itemstring: str) -> str | None:
    return next((k for k, v in CONFIG["items"].items() if v == itemstring), None)


def trade_terms(npc_cfg: dict, trust: int, work_block_present: bool = True) -> dict:
    if npc_cfg.get("work_block") and not work_block_present:
        return {"ok": False, "reason": "no_work_block"}
    if not npc_cfg.get("trade"):
        return {"ok": False, "reason": "no_trade"}
    b = band(trust)
    if b == "hostile":
        return {"ok": False, "reason": "hostile"}
    t = npc_cfg["trade"]
    return {"ok": True, "give": {"item": t["give"], "count": t["count"]},
            "cost": {"item": t["cost"], "count": t["base_price"] * BAND_MULT[b]}}


def apology_allowed(last_game_time: float | None, now: float) -> bool:
    return last_game_time is None or now - last_game_time >= 1.0
