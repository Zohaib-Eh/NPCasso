"""Game orchestration: events, talk, trade, tick. Owns every state change; the LLM only proposes text."""
import json

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


NEUTRAL_LINE = "Hm. Let me think on that."
MIN_CONFIDENCE = 0.6


def _apply_intent(conn, intent: dict, npc_id, player, game_time, notices) -> dict:
    """Turns a classified intent into deterministic effects. Returns extra facts for the dialogue context."""
    kind = intent.get("intent")
    conf = intent.get("confidence") or 0
    if kind not in ("threat", "insult", "apology", "promise", "correction") or conf < MIN_CONFIDENCE:
        return {}
    db.add_event(conn, {"player": player, "actor": player, "target": npc_id, "type": kind, "details": intent,
                        "witnesses": [npc_id], "game_time": game_time, "source": "llm_classified",
                        "verified": False, "confidence": conf})
    if kind in ("threat", "insult"):
        db.add_trust(conn, npc_id, player, rules.trust_delta(kind))
    elif kind == "apology":
        if rules.apology_allowed(db.get_flag(conn, npc_id, player, "last_apology"), game_time):
            db.add_trust(conn, npc_id, player, rules.trust_delta("apology"))
            db.set_flag(conn, npc_id, player, "last_apology", game_time)
            notices.append(f"{name(npc_id)} noticed your apology.")
    elif kind == "promise":
        p = intent.get("promise") or {}
        if p.get("item") in CONFIG["items"] and isinstance(p.get("count"), int) and p["count"] > 0:
            db.add_promise(conn, "promise", npc_id, player, p["item"], p["count"],
                           game_time + float(p.get("deadline_days") or 1))
            return {"new_promise": {"item": p["item"], "count": p["count"]}}
    elif kind == "correction":
        claim = intent.get("claim") or {}
        rows = conn.execute("select details from events where type=? and target=? and player=? and source='game'",
                            (claim.get("type"), npc_id, player)).fetchall()
        item = claim.get("item")
        happened = any(item is None or rules.short_item(json.loads(r["details"]).get("item", "")) == item
                       for r in rows)
        if not happened:
            db.add_trust(conn, npc_id, player, rules.trust_delta("correction_confirmed"))
            conn.execute("update interactions set outcome='corrected' where id = (select max(id) from interactions "
                         "where task='npc_dialogue' and npc_id=? and player=?)", (npc_id, player))
            conn.commit()
        return {"correction": {"confirmed": not happened, "claim": claim}}
    return {}


def talk(conn, llm, world, player, npc_id, message, thread_id, game_time) -> dict:
    cfg, player = npc_cfg(npc_id), f"{world}:{player}"
    notices = []
    cin = {"npc": {"name": cfg["name"], "role": cfg["role"]}, "player_message": message}
    cres = llm.complete("intent_classify", cin, thread_id)
    log_call(conn, "intent_classify", npc_id, player, thread_id, cin, cres)
    extra = _apply_intent(conn, cres.data or {}, npc_id, player, game_time, notices)

    ctx = build_context(conn, npc_id, player, message, extra)
    reply, offer, prev = NEUTRAL_LINE, None, None
    for attempt in range(2):
        res = llm.complete("npc_dialogue", ctx, thread_id)
        vres = validate("npc_dialogue", res.data, ctx)
        prev = log_call(conn, "npc_dialogue", npc_id, player, thread_id, ctx, res, vres, attempt > 0, prev)
        if vres["ok"]:
            reply = res.data["reply"]
            if res.data.get("quest_offer") and not vres["drop_quest"]:
                offer = res.data["quest_offer"]
            break
        ctx = {**ctx, "validator_feedback": vres["errors"]}
    if offer:
        db.add_promise(conn, "quest", npc_id, player, offer["item"], int(offer.get("count") or 1),
                       game_time + 2, offer.get("reward"))
    return {"reply": reply, "notices": notices, "quest_offer": offer}
