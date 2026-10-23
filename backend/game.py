"""Game orchestration: events, talk, trade, tick. Owns every state change; the LLM only proposes text."""
from . import db, rules
from .validator import validate

CONFIG = db.load_config()
GAME_EVENTS = {"theft", "gift", "vandalism", "repair", "hit_npc", "trade", "walk_away"}
REACT_EVENTS = {"theft", "vandalism", "hit_npc"}
TARGET_KNOWS = {"gift", "hit_npc", "trade"}


def npc_cfg(npc_id: str) -> dict:
    if npc_id not in CONFIG["npcs"]:
        raise ValueError(f"unknown npc {npc_id!r}")
    return CONFIG["npcs"][npc_id]


def name(npc_id: str) -> str:
    return npc_cfg(npc_id)["name"]


def build_context(conn, npc_id, player, message=None, extra_facts=None) -> dict:
    cfg = npc_cfg(npc_id)
    promises = db.open_promises(conn, npc_id, player)
    strip = lambda p: {k: p[k] for k in ("item", "count", "reward") if p.get(k) is not None}
    return {
        "npc": {k: cfg[k] for k in ("name", "role", "persona", "background", "loves", "likes", "dislikes")},
        "relationship": {"band": rules.band(db.get_trust(conn, npc_id, player))},
        "memories": db.top_memories(conn, npc_id, player),
        "facts": {"open_promises": [strip(p) for p in promises if p["kind"] == "promise"],
                  "open_quests": [strip(p) for p in promises if p["kind"] == "quest"], **(extra_facts or {})},
        "items": list(CONFIG["items"]),
        "player_message": message,
    }


def log_call(conn, task, npc_id, player, thread_id, user, res, vres=None, retried=False, prev_id=None) -> int:
    return db.add_interaction(conn, {
        "task": task, "npc_id": npc_id, "player": player, "thread_id": thread_id, "request": user,
        "reply": res.raw, "mubit_request_id": res.request_id, "latency_ms": res.latency_ms, "tokens": res.tokens,
        "validator_result": vres or ({"error": res.error} if res.error else None), "retried": retried,
        "outcome": None, "prev_id": prev_id})


def record_event(conn, llm, ev: dict) -> dict:
    if ev["type"] not in GAME_EVENTS:
        raise ValueError(f"unknown event type {ev['type']!r}")
    player = f"{ev['world']}:{ev['player']}"
    witnesses = [w for w in ev.get("witnesses", []) if npc_cfg(w)]
    target = ev.get("target")
    if target:
        npc_cfg(target)
    eid = db.add_event(conn, {"player": player, "actor": player, "target": target, "type": ev["type"],
                              "details": ev.get("details", {}), "witnesses": witnesses,
                              "game_time": ev["game_time"], "source": "game", "verified": True, "confidence": None})
    out = {"event_id": eid, "notices": [], "shouts": [], "give": []}
    if ev["type"] == "walk_away":  # weak signal: logged, never a label or a state change
        return out

    knowers = list(dict.fromkeys(witnesses + ([target] if target and ev["type"] in TARGET_KNOWS else [])))
    item = rules.short_item(ev.get("details", {}).get("item", ""))
    for npc in knowers:
        delta = rules.trust_delta(ev["type"], "witnessed", rules.gift_pref(npc_cfg(npc), item))
        db.add_trust(conn, npc, player, delta)
        text = f"{ev['type']} by the newcomer"
        if ev["type"] in REACT_EVENTS:
            ctx = build_context(conn, npc, player)
            ctx["event"] = {"id": eid, "type": ev["type"], "details": ev.get("details", {})}
            thread = f"{player}:{npc}:event:{eid}"
            res = llm.complete("npc_react", ctx, thread)
            vres = validate("npc_react", res.data, ctx)
            log_call(conn, "npc_react", npc, player, thread, ctx, res, vres)
            if vres["ok"]:
                text = res.data.get("memory") or text
                out["shouts"].append({"npc_id": npc, "text": res.data["shout"]})
        elif ev["type"] == "gift" and item:
            text = f"the newcomer gave me {item}"
        db.add_memory(conn, npc, player, eid, ev["type"], text, "witnessed", 1.0, abs(delta))
        if abs(delta) >= 10:
            out["notices"].append(f"{name(npc)} will remember that.")
    return out
