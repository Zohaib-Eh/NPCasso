"""Game orchestration: events, talk, trade, tick. Owns every state change; the LLM only proposes text."""
import json
import random
import time

from . import db, progress, rules
from .validator import validate

CONFIG = db.load_config()
GAME_EVENTS = {"theft", "gift", "vandalism", "repair", "hit_npc", "trade", "walk_away", "return", "slay", "harvest"}
XP_FOR = {"trade": 2, "slay": 5, "promise_kept": 10}
REACT_EVENTS = {"theft", "vandalism", "hit_npc"}
TARGET_KNOWS = {"gift", "hit_npc", "trade", "return"}
SPECIAL_NOTICE = {"return": "{name} noticed you put it back."}
CRIME = {"theft", "vandalism", "hit_npc"}
WITNESS_LINE = {"theft": "Did you see that?!", "vandalism": "Hey! Stop that!", "hit_npc": "Leave them alone!"}
GOSSIP_DELAY = 0.1  # game-days a villager must have known something before retelling it
REACT_COOLDOWN_S = 5  # spam-clicking records every event but the NPC reacts (LLM call + notice) once


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
        "facts": {"world": CONFIG.get("world_knowledge", []) + cfg.get("expertise", []),
                  "open_promises": [strip(p) for p in promises if p["kind"] == "promise"],
                  "open_quests": [strip(p) for p in promises if p["kind"] == "quest"], **(extra_facts or {})},
        "items": list(CONFIG["items"]),
        "player": {"title": progress.title(progress.player_state(conn, player)["level"])},
        "player_message": message,
    }


def log_call(conn, task, npc_id, player, thread_id, user, res, vres=None, retried=False, prev_id=None) -> int:
    return db.add_interaction(conn, {
        "task": task, "npc_id": npc_id, "player": player, "thread_id": thread_id, "request": user,
        "reply": res.raw, "mubit_request_id": res.request_id, "latency_ms": res.latency_ms, "tokens": res.tokens,
        "validator_result": vres or ({"error": res.error} if res.error else None), "retried": retried,
        "outcome": None, "prev_id": prev_id})


def describe(type, npc, target, item) -> tuple[str, str]:
    """Authoritative wording of an event: (what the NPC is told, the NPC's first-person memory)."""
    whose = "your" if npc == target else f"{name(target)}'s" if target else "the"
    thing = item or "something"
    you = "you" if npc == target else name(target) if target else "someone"
    what = {
        "theft": f"the newcomer took {thing} from {whose} stall without paying",
        "vandalism": f"the newcomer smashed {whose} anvil",
        "repair": f"the newcomer put {whose} anvil back",
        "hit_npc": f"the newcomer hit {you}",
        "gift": f"the newcomer gave {you} {thing}",
        "trade": f"the newcomer traded with {you}",
        "return": f"the newcomer put {thing} back in {whose} stall",
    }.get(type, f"{type} by the newcomer")
    memory = what.replace(" your ", " my ").replace(" you", " me")
    return what, memory


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
    out = {"event_id": eid, "notices": [], "shouts": [], "give": [], "react": [], "witness_lines": {},
           "xp_gained": 0, "level_up": None}
    if ev["type"] == "harvest":
        progress.merge(out, progress.harvest_xp(conn, player, ev["game_time"]))
    if ev["type"] in XP_FOR:
        progress.merge(out, progress.add_xp(conn, player, XP_FOR[ev["type"]], ev["type"]))
    if ev["type"] in ("slay", "harvest"):  # progress only: no memories, no trust
        _slay_progress(conn, player, ev, out)
        return out
    # Only one villager speaks through the LLM: the victim if they saw it, else the nearest witness (Lua sends
    # witnesses nearest first). Everyone who knows still gets the memory and the trust change.
    primary = target if target in witnesses else (witnesses[0] if witnesses else target)
    if ev["type"] == "walk_away":  # weak signal: logged, never a label or a state change
        return out

    knowers = list(dict.fromkeys(witnesses + ([target] if target and ev["type"] in TARGET_KNOWS else [])))
    item = rules.short_item(ev.get("details", {}).get("item", ""))
    for npc in knowers:
        delta = rules.trust_delta(ev["type"], "witnessed", rules.gift_pref(npc_cfg(npc), item))
        db.add_trust(conn, npc, player, delta)
        what, text = describe(ev["type"], npc, target, item)
        fresh = time.time() - (db.get_flag(conn, npc, player, "last_react") or 0) > REACT_COOLDOWN_S
        if ev["type"] in REACT_EVENTS and fresh:
            db.set_flag(conn, npc, player, "last_react", time.time())
            if npc == primary:
                out["react"].append(npc)  # spoken reaction is fetched separately (/react), so this returns at once
            else:
                out["witness_lines"][npc] = WITNESS_LINE[ev["type"]]
        db.add_memory(conn, npc, player, eid, ev["type"], text, "witnessed", 1.0, abs(delta), ev["game_time"])
        if abs(delta) >= 10 and (fresh or ev["type"] not in REACT_EVENTS):
            notice = SPECIAL_NOTICE.get(ev["type"], "{name} will remember that.")
            out["notices"].append(notice.format(name=name(npc)))
    if ev["type"] == "gift" and item and target:
        _gift_progress(conn, player, target, item, ev["game_time"], out)
    return out


def react(conn, llm, world, player, event_id, npc_ids) -> dict:
    """Spoken reactions to an already-recorded event. Memory text stays authoritative; the LLM only shouts."""
    player = f"{world}:{player}"
    row = conn.execute("select * from events where id=? and player=?", (event_id, player)).fetchone()
    out = {"shouts": []}
    if not row:
        return out
    details = json.loads(row["details"])
    for npc in npc_ids:
        if npc not in json.loads(row["witnesses"]) + [row["target"]]:
            continue
        what, _ = describe(row["type"], npc, row["target"], rules.short_item(details.get("item", "")))
        ctx = build_context(conn, npc, player)
        ctx["event"] = {"id": event_id, "type": row["type"], "what": what}
        thread = f"{player}:{npc}:event:{event_id}"
        res = llm.complete("npc_react", ctx, thread)
        vres = validate("npc_react", res.data, ctx)
        log_call(conn, "npc_react", npc, player, thread, ctx, res, vres)
        if vres["ok"]:
            out["shouts"].append({"npc_id": npc, "text": res.data["shout"]})
    return out


def _slay_progress(conn, player, ev, out):
    mob = ev.get("details", {}).get("mob") or ""
    if ev["type"] != "slay" or not mob:
        return
    for p in db.open_promises(conn, player=player, kind="quest"):
        if p["target"] and mob.startswith(p["target"]):
            if p["count"] <= 1:
                _complete_quest(conn, player, p, ev["game_time"], out)
            else:
                db.update_promise(conn, p["id"], count=p["count"] - 1)


def _internal_event(conn, player, npc_id, type, game_time, text, details=None, delta=None) -> int:
    """A game-derived event (promise kept/broken, quest done) the NPC always knows about."""
    eid = db.add_event(conn, {"player": player, "actor": player, "target": npc_id, "type": type,
                              "details": details or {}, "witnesses": [npc_id], "game_time": game_time,
                              "source": "game", "verified": True, "confidence": None})
    delta = rules.trust_delta(type) if delta is None else delta
    db.add_trust(conn, npc_id, player, delta)
    db.add_memory(conn, npc_id, player, eid, type, text, "witnessed", 1.0, abs(delta))
    return eid


def _gift_progress(conn, player, npc_id, item, game_time, out):
    for p in db.open_promises(conn, npc_id, player):
        if p["item"] != item:
            continue
        left = p["count"] - 1
        if left > 0:
            db.update_promise(conn, p["id"], count=left)
        elif p["kind"] == "promise":
            db.update_promise(conn, p["id"], count=0, status="kept")
            _internal_event(conn, player, npc_id, "promise_kept", game_time, f"the newcomer kept their word about {item}")
            out["notices"].append(f"{name(npc_id)} noticed you kept your word.")
            progress.merge(out, progress.add_xp(conn, player, XP_FOR["promise_kept"], "promise_kept"))
        else:
            db.update_promise(conn, p["id"], count=0)
            _complete_quest(conn, player, p, game_time, out)
        return  # one gift settles one promise


# Quests -----------------------------------------------------------------------------------------

def _rewards(p) -> list[dict]:
    """Quest reward column: a JSON list of itemstrings (starter/LLM quests) or a legacy short item name."""
    r = p["reward"]
    if not r:
        return []
    names = json.loads(r) if r.startswith("[") else [CONFIG["items"].get(r)]
    out = []
    for n in names:
        if n:
            name_, _, count = n.partition(" ")
            out.append({"item": name_, "count": int(count or 1)})
    return out


def _complete_quest(conn, player, p, game_time, out):
    db.update_promise(conn, p["id"], status="done", count=0)
    title = p["title"] or f"{p['item']} for {name(p['npc_id'])}"
    _internal_event(conn, player, p["npc_id"], "quest_done", game_time, f"the newcomer finished my task: {title}",
                    delta=p["trust"] if p["trust"] is not None else None)
    out["give"] += _rewards(p)
    out.setdefault("completed", []).append(title)
    out["notices"].append(f"Quest complete: {title}")
    progress.merge(out, progress.add_xp(conn, player, p["xp"] or 20, "quest"))


def _starter(quest_id):
    for npc_id, cfg in CONFIG["npcs"].items():
        for q in cfg.get("quests", []):
            if q["id"] == quest_id:
                return npc_id, q
    raise ValueError(f"unknown quest {quest_id!r}")


def available_quests(conn, player) -> list[dict]:
    taken = {r["quest_id"] for r in conn.execute("select quest_id from promises where player=? and quest_id is not null",
                                                 (player,))}
    return [{**q, "npc_id": n, "npc": c["name"]} for n, c in CONFIG["npcs"].items() for q in c.get("quests", [])
            if q["id"] not in taken]


def accept_quest(conn, player, quest_id) -> dict:
    npc_id, q = _starter(quest_id)
    if conn.execute("select 1 from promises where player=? and quest_id=?", (player, quest_id)).fetchone():
        raise ValueError("quest already taken")
    db.add_promise(conn, "quest", npc_id, player, q.get("item"), q["count"], None, json.dumps(q["reward"]),
                   title=q["title"], xp=q["xp"], trust=q["trust"], quest_id=q["id"], target=q.get("mob"),
                   total=q["count"])
    return {"accepted": q["title"]}


def journal(conn, player) -> dict:
    rows = [dict(r) for r in conn.execute("select * from promises where player=? and kind='quest' order by id",
                                          (player,))]
    def view(r):
        total = r["total"] or r["count"]
        return {"id": r["quest_id"], "npc_id": r["npc_id"], "npc": name(r["npc_id"]), "title": r["title"],
                "item": CONFIG["items"].get(r["item"]) if r["item"] else None, "mob": r["target"],
                "progress": f"{total - r['count']}/{total}", "reward": _rewards(r)}
    return {"active": [view(r) for r in rows if r["status"] == "open"],
            "done": [view(r) for r in rows if r["status"] == "done"]}


def handin(conn, world, player, npc_id, items: dict, game_time) -> dict:
    """Hand quest items to a villager. Fills that villager's open bring-quests oldest first, taking only what's needed."""
    player = f"{world}:{player}"
    npc_cfg(npc_id)
    out = {"consumed": {}, "completed": [], "give": [], "notices": [], "xp_gained": 0, "level_up": None}
    for p in db.open_promises(conn, npc_id, player, kind="quest"):
        itemstring = CONFIG["items"].get(p["item"] or "")
        have = int(items.get(itemstring, 0)) - out["consumed"].get(itemstring, 0) if itemstring else 0
        take = min(max(have, 0), p["count"])
        if take == 0:
            continue
        out["consumed"][itemstring] = out["consumed"].get(itemstring, 0) + take
        if take == p["count"]:
            _complete_quest(conn, player, p, game_time, out)
        else:
            db.update_promise(conn, p["id"], count=p["count"] - take)
    return out


GREET_SITUATION = "the player walks up to you; speak first"


def greet(conn, llm, world, player, npc_id, thread_id, game_time) -> dict:
    """NPC speaks first when the player approaches. Same npc_dialogue task, no player message."""
    player = f"{world}:{player}"
    ctx = build_context(conn, npc_id, player, None, {"situation": GREET_SITUATION})
    res = llm.complete("npc_dialogue", ctx, thread_id)
    vres = validate("npc_dialogue", res.data, ctx)
    log_call(conn, "npc_dialogue", npc_id, player, thread_id, ctx, res, vres)
    return {"reply": res.data["reply"] if vres["ok"] else ""}


def gossip(conn, world, player, teller, listener, game_time, roll: float | None = None) -> dict:
    """Two villagers met. The teller may pass on one thing about the player the listener doesn't know yet."""
    player = f"{world}:{player}"
    npc_cfg(teller), npc_cfg(listener)
    none = {"line": None, "reply": None}
    m = conn.execute(
        "select m.*, e.target, e.details from memories m join events e on e.id = m.event_id "
        "where m.npc_id=? and m.player=? and m.severity>=10 and m.reliability>=0.25 "
        "and (m.learned_at is null or ? - m.learned_at >= ?) "
        "and m.event_id not in (select event_id from memories where npc_id=? and player=?) "
        "order by m.severity desc, m.id limit 1",
        (teller, player, game_time, GOSSIP_DELAY, listener, player)).fetchone()
    if not m:
        return none
    roll = random.random() if roll is None else roll
    if roll >= npc_cfg(teller).get("chattiness", 0.5) and not (m["type"] in CRIME and listener == "wren"):
        return none
    reliability = m["reliability"] / 2
    item = rules.short_item(json.loads(m["details"]).get("item", ""))
    what, _ = describe(m["type"], None, m["target"], item)
    db.add_memory(conn, listener, player, m["event_id"], m["type"], f"{name(teller)} told me {what}",
                  f"told_by:{teller}", reliability, m["severity"] // 2, game_time)
    db.add_trust(conn, listener, player, round(rules.trust_delta(m["type"]) * reliability))
    db.add_event(conn, {"player": player, "actor": teller, "target": listener, "type": "told",
                        "details": {"event_id": m["event_id"]}, "witnesses": [listener], "game_time": game_time,
                        "source": "game", "verified": True, "confidence": None})
    return {"line": f"Psst... {what}.", "reply": "Really?!"}


AFRAID_FOR = 0.5  # game-days a villager stays afraid after being hit or threatened


def moods(conn, world, player, game_time) -> dict:
    """Behaviour-only mood per villager (never shown to the player)."""
    player = f"{world}:{player}"
    scared = {r["target"] for r in conn.execute(
        "select target from events where player=? and type in ('hit_npc', 'threat') and ? - game_time <= ?",
        (player, game_time, AFRAID_FOR))}
    return {n: "afraid" if n in scared else rules.band(db.get_trust(conn, n, player)) for n in CONFIG["npcs"]}


def trade_quote(conn, world, player, npc_id, work_block_present: bool) -> dict:
    min_level = (npc_cfg(npc_id).get("trade") or {}).get("min_level", 1)
    if progress.player_state(conn, f"{world}:{player}")["level"] < min_level:
        return {"ok": False, "reason": "level", "min_level": min_level}
    terms = rules.trade_terms(npc_cfg(npc_id), db.get_trust(conn, npc_id, f"{world}:{player}"), work_block_present)
    if terms["ok"]:
        for k in ("give", "cost"):
            terms[k] = {**terms[k], "item": CONFIG["items"][terms[k]["item"]]}
    return terms


def tick(conn, llm, world, player, game_time) -> dict:
    """Periodic world update: promise deadlines. Gossip happens only when villagers meet (gossip())."""
    player = f"{world}:{player}"
    out = {"notices": [], "shouts": []}
    for p in db.open_promises(conn, player=player, kind="promise"):  # quests never expire
        if p["deadline"] is None or p["deadline"] >= game_time:
            continue
        db.update_promise(conn, p["id"], status="broken")
        _internal_event(conn, player, p["npc_id"], "promise_broken", game_time,
                        f"the newcomer promised me {p['item']} and never brought it")
        out["notices"].append(f"{name(p['npc_id'])} will remember that.")

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
        # Reward a confirmed correction once per game day, so denying random events can't farm trust.
        if not happened and rules.apology_allowed(db.get_flag(conn, npc_id, player, "last_correction"), game_time):
            db.set_flag(conn, npc_id, player, "last_correction", game_time)
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
    try:
        extra = _apply_intent(conn, cres.data or {}, npc_id, player, game_time, notices)
    except (TypeError, ValueError, AttributeError):  # well-formed JSON with wrong value types from the LLM
        extra = {}

    ctx = build_context(conn, npc_id, player, message, extra)
    reply, offer, prev = NEUTRAL_LINE, None, None
    for attempt in range(2):
        res = llm.complete("npc_dialogue", ctx, thread_id)
        vres = validate("npc_dialogue", res.data, ctx)
        prev = log_call(conn, "npc_dialogue", npc_id, player, thread_id, ctx, res, vres, attempt > 0, prev)
        if res.data is None and res.error:
            break  # timeout or network error: retrying would blow the game's HTTP budget
        if vres["ok"]:
            reply = res.data["reply"]
            if res.data.get("quest_offer") and not vres["drop_quest"]:
                offer = res.data["quest_offer"]
            break
        ctx = {**ctx, "validator_feedback": vres["errors"]}
    if offer:
        count = int(offer.get("count") or 1)
        reward = CONFIG["items"].get(offer.get("reward") or "")
        db.add_promise(conn, "quest", npc_id, player, offer["item"], count, None,
                       json.dumps([reward] if reward else []), title=f"{count} {offer['item']} for {cfg['name']}",
                       xp=20, trust=20, total=count)
    return {"reply": reply, "notices": notices, "quest_offer": offer}
