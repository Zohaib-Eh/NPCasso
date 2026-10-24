"""Game orchestration: events, talk, trade, tick. Owns every state change; the model proposes words and a score."""
import json
import random
import time

from . import db, finale, progress, rules, situations, stance
from .story import add_evidence, end_run, report as story_report, story_facts
from .validator import validate

CONFIG = db.load_config()
GAME_EVENTS = {"theft", "gift", "vandalism", "repair", "hit_npc", "trade", "walk_away", "return", "slay", "harvest"}
XP_FOR = {"trade": 2, "slay": 5, "promise_kept": 10}
REACT_EVENTS = {"theft", "vandalism", "hit_npc"}
TARGET_KNOWS = {"gift", "hit_npc", "trade", "return"}
SPECIAL_NOTICE = {"return": "{name} noticed you put it back."}
CRIME = {"theft", "vandalism", "hit_npc"}
# What villagers read about the player from a deed they know of. Unseen deeds score nothing.
EVENT_EVIDENCE = {"hit_npc": (("compassion", -0.8), ("justice", -0.3)), "theft": (("justice", -0.6),),
                  "vandalism": (("justice", -0.5), ("compassion", -0.2)),
                  "gift": (("compassion", 0.5), ("selflessness", 0.4)),
                  "repair": (("justice", 0.4), ("selflessness", 0.3))}
MAX_SPEAKERS = 2  # villagers who voice a reaction through the LLM; others just turn and look
GOSSIP_DELAY = 0.1  # game-days a villager must have known something before retelling it
# A rumour may retell a deed someone saw. A quest, a promise, and a secret never travel this way.
PUBLIC_RUMOUR = {"theft", "gift", "vandalism", "repair", "hit_npc", "trade", "return"}
# Keys the model is allowed to see. Anything else in the context stays with the game.
_FACT_KEYS = {"world", "stock", "guide", "open_promises", "situation", "ask", "season", "may_open",
              "you_are", "open_situation", "new_promise", "correction", "need", "lost", "directions",
              "bent", "ease", "heard_as", "sign", "stance", "recent", "lean"}
# A spread, not two camps. The middle moves with how this player has treated them.
_BENT_ORDER = ("own", "mixed", "others")
BENT = {"elise": "own", "rowan": "own", "dax": "own", "corin": "own",
        "nell": "others", "hazel": "others", "bram": "others", "lottie": "others",
        "tobin": "mixed", "mira": "mixed", "wren": "mixed", "pip": "mixed"}
BENT_WORDS = {"own": "you are looking out for your own work",
              "mixed": "you are pulled both ways, between your own work and the people who will go without",
              "others": "you are trying to keep other people fed and warm"}
STRAIN = "food, fuel, and materials are thin"
NEED_PLACE = {"apple": "orchard", "iron": "mine", "iron_ore": "mine", "coal": "mine", "wheat": "wheat_field",
              "flour": "wheat_field", "seeds": "farm", "flower": "meadow", "bread": "nell"}
NEED_WORD = {"apple": "apples", "iron": "iron ingots", "flower": "roses", "wheat": "wheat", "bread": "loaves of bread",
             "flour": "flour", "seeds": "wheat seeds", "coal": "coal", "monster": "monsters"}
NEED_HOW = {
    "apple": "Pick them from the apple trees.",
    "iron": "Mine iron ore from stone with a pickaxe, then smelt it in a furnace with coal.",
    "flower": "Pick roses in the meadow.",
    "wheat": "Till soil near water with a hoe, plant wheat seeds, and harvest the wheat when it turns golden.",
    "bread": "Grind wheat into flour, then bake the flour in a furnace.",
    "flour": "Grind wheat into flour on the crafting grid.",
    "seeds": "Cut tall grass to find wheat seeds.",
    "coal": "Dig coal from the rock in the mine.",
    "monster": "Monsters come out at night outside the village. The village itself is safe.",
}
LOST_WORDS = ("lost", "what do i do", "what should i do", "what now", "what next", "where do i go",
              "where should i go", "where do i start", "i'm stuck", "i am stuck", "what can i do",
              "don't know what", "do not know what")
REACT_COOLDOWN_S = 5  # spam-clicking records every event but the NPC reacts (LLM call + notice) once


def npc_cfg(npc_id: str) -> dict:
    if npc_id not in CONFIG["npcs"]:
        raise ValueError(f"unknown npc {npc_id!r}")
    return CONFIG["npcs"][npc_id]


def name(npc_id: str) -> str:
    return npc_cfg(npc_id)["name"]


def living_bent(conn, npc_id, player) -> str:
    """Who they are, unless they are the sort of person who shifts with how you treat them."""
    base = BENT.get(npc_id, "mixed")
    spot = _BENT_ORDER.index(base)
    if base == "mixed":
        trust = db.get_trust(conn, npc_id, player)
        spot = 0 if trust < 0 else 2 if trust >= 20 else 1
    return BENT_WORDS[_BENT_ORDER[spot]]


def a_sign(conn, npc_id, player) -> str | None:
    """One small sight at this villager's place. It changes from one meeting to the next."""
    signs = npc_cfg(npc_id).get("signs") or []
    if not signs:
        return None
    met = conn.execute("select count(*) from interactions where player=? and npc_id=? and task='npc_dialogue' "
                       "and ifnull(retried,0)=0", (player, npc_id)).fetchone()[0]
    return signs[met % len(signs)]


def _dated(memories: list[dict], game_time) -> list[dict]:
    """The model reads 'earlier' or 'days ago', never a raw clock."""
    out = []
    for m in memories:
        m = dict(m)
        learned = m.pop("learned_at", None)
        if game_time is not None and learned is not None:
            m["when"] = stance.when(game_time - learned)
        out.append(m)
    return out


def build_context(conn, npc_id, player, message=None, extra_facts=None, game_time=None) -> dict:
    cfg = npc_cfg(npc_id)
    promises = db.open_promises(conn, npc_id, player)
    strip = lambda p: {k: p[k] for k in ("item", "count", "reward") if p.get(k) is not None}
    return {
        "npc": {k: cfg[k] for k in ("name", "role", "persona", "voice", "background", "location",
                                    "loves", "likes", "dislikes") if k in cfg},
        "relationship": {"band": rules.band(db.get_trust(conn, npc_id, player))},
        "memories": _dated(db.top_memories(conn, npc_id, player), game_time),
        "facts": {"world": CONFIG.get("world_knowledge", []) + cfg.get("expertise", []),
                  "stock": rules.stock(cfg),
                  "guide": guide(conn, player),
                  "open_promises": [strip(p) for p in promises if p["kind"] == "promise"],
                  "strain": STRAIN,
                  "recent": db.recent_turns(conn, npc_id, player),
                  "sign": a_sign(conn, npc_id, player),
                  "bent": living_bent(conn, npc_id, player),
                  **({"stance": stance.of(conn, npc_id, player, game_time)} if game_time is not None else {}),
                  **(extra_facts or {})},
        "items": list(CONFIG["items"]),
        "player": {"title": progress.title(progress.player_state(conn, player)["level"])},
        "player_message": message,
    }


def guide(conn, player) -> dict:
    """Where people and places are. The quest board is the player's; a villager is not handed it."""
    places = {**{n: f"{c['name']}: {c.get('location', '')}" for n, c in CONFIG["npcs"].items()},
              **CONFIG.get("places", {})}
    return {"places": places}


def guidance_line(ctx, speaker) -> tuple[str, str | None]:
    """When the model fails, a lost player still gets this villager's own directions."""
    facts = ctx.get("facts") or {}
    mood = (facts.get("stance") or {}).get("mood")
    if mood in stance.HARMFUL or mood == "guarded":
        return stance.FALLBACK[mood], None
    if facts.get("lost") and facts.get("directions"):
        place = (facts.get("need") or {}).get("place")
        places = (facts.get("guide") or {}).get("places") or {}
        return facts["directions"], place if place in places else None
    return "Sorry, say that once more.", None


def take_evidence(conn, player: str, data: dict | None, event_id: int | None = None) -> None:
    """Keep the dimensions a reply scored. A bad entry is dropped; the line still stands."""
    for item in (data or {}).get("evidence") or []:
        if not isinstance(item, dict) or "weight" not in item:
            continue
        try:
            add_evidence(conn, player, item.get("dimension"), float(item["weight"]), event_id, "spoken")
        except (TypeError, ValueError):
            continue


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


def _scene(conn, player, victim, saw, heard, game_time) -> dict:
    """Who moves when someone cries out. The game decides; the world plays it.

    Anyone in earshot can come to help. Only a villager who saw it has anything to tell the guard."""
    role = {n: CONFIG["npcs"][n].get("reacts_as", "wary") for n in saw + heard if n != victim}
    pick = lambda r, pool: [n for n in pool if n in role and role[n] == r]
    return {"victim": victim, "victim_mood": stance.of(conn, victim, player, game_time)["mood"],
            "rescuers": pick("protector", saw + heard), "tattlers": pick("tattler", saw),
            "guard": next(iter(pick("guard", saw + heard)), None)}


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
    out = {"event_id": eid, "notices": [], "shouts": [], "give": [], "react": [], "xp_gained": 0, "level_up": None}
    if ev["type"] == "harvest":
        progress.merge(out, progress.harvest_xp(conn, player, ev["game_time"]))
    if ev["type"] in XP_FOR:
        progress.merge(out, progress.add_xp(conn, player, XP_FOR[ev["type"]], ev["type"]))
    if ev["type"] in ("slay", "harvest"):  # progress only: no memories, no trust
        _slay_progress(conn, player, ev, out)
        return out
    # The victim (if they saw it) and the nearest witnesses voice a reaction through the LLM, up to MAX_SPEAKERS
    # (Lua sends witnesses nearest first). Everyone who knows still gets the memory and the trust change.
    ordered = ([target] if target in witnesses else []) + [w for w in witnesses if w != target]
    speakers = set(ordered[:MAX_SPEAKERS])
    if ev["type"] == "walk_away":  # leaving a chat is not a memory; the window just closes
        return out

    knowers = list(dict.fromkeys(witnesses + ([target] if target and ev["type"] in TARGET_KNOWS else [])))
    if knowers:
        for dim, weight in EVENT_EVIDENCE.get(ev["type"], ()):
            add_evidence(conn, player, dim, weight, eid, ev["type"])
    item = rules.short_item(ev.get("details", {}).get("item", ""))
    for npc in knowers:
        delta = rules.trust_delta(ev["type"], "witnessed", rules.gift_pref(npc_cfg(npc), item))
        db.add_trust(conn, npc, player, delta)
        what, text = describe(ev["type"], npc, target, item)
        fresh = time.time() - (db.get_flag(conn, npc, player, "last_react") or 0) > REACT_COOLDOWN_S
        if ev["type"] in REACT_EVENTS and fresh:
            db.set_flag(conn, npc, player, "last_react", time.time())
            if npc in speakers:
                out["react"].append(npc)  # spoken reactions are fetched separately (/react), so this returns at once
        db.add_memory(conn, npc, player, eid, ev["type"], text, "witnessed", 1.0, abs(delta), ev["game_time"])
        if abs(delta) >= 10 and (fresh or ev["type"] not in REACT_EVENTS):
            notice = SPECIAL_NOTICE.get(ev["type"], "{name} will remember that.")
            out["notices"].append(notice.format(name=name(npc)))
    out["react"].sort(key=ordered.index)  # victim first, then nearest
    if ev["type"] in CRIME and out["notices"]:
        out["notices"].append("Word will spread.")
    if ev["type"] == "hit_npc" and target:
        earshot = [h for h in ev.get("heard", []) if h in CONFIG["npcs"] and h not in knowers]
        for npc in earshot:
            db.add_memory(conn, npc, player, eid, "cry", f"I heard {name(target)} cry out", "heard", 1.0, 5,
                          ev["game_time"])
        out["scene"] = _scene(conn, player, target, knowers, earshot, ev["game_time"])
        guard = out["scene"]["guard"]
        if guard and guard not in out["react"]:
            out["react"].append(guard)
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
        heard_only = npc not in json.loads(row["witnesses"]) + [row["target"]]
        if heard_only and not conn.execute("select 1 from memories where npc_id=? and player=? and event_id=? "
                                           "and how='heard'", (npc, player, event_id)).fetchone():
            continue
        what = (f"you heard {name(row['target'])} cry out, and you did not see who or why" if heard_only else
                describe(row["type"], npc, row["target"], rules.short_item(details.get("item", "")))[0])
        ctx = build_context(conn, npc, player, game_time=row["game_time"])
        ctx["facts"].update(_sky(conn, player, row["game_time"]))
        ctx["event"] = {"id": event_id, "type": row["type"], "what": what}
        thread = f"{player}:{npc}:event:{event_id}"
        heard = _heard(ctx)
        res = llm.complete("npc_react", heard, thread)
        vres = validate("npc_react", res.data, ctx)
        log_call(conn, "npc_react", npc, player, thread, heard, res, vres)
        if vres["ok"]:
            take_evidence(conn, player, res.data, event_id)
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
    brought = (p["item"] or "what I needed").replace("_", " ")
    _internal_event(conn, player, p["npc_id"], "quest_done", game_time, f"the newcomer brought me {brought}",
                    details={"title": title, "item": p["item"]},
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


GREET_SITUATION = ("the newcomer comes up to you again and you speak first. You know them a little by now. "
                   "Something has been weighing on you in your own work and place, and it colours how you "
                   "talk. Let it show in a detail or a mood. If facts.need is there, a request can come out "
                   "of that worry when it feels natural")
EASE_GREET = {
    "introduce": ("a stranger has walked up while you were busy at your own place, and you speak first. Meet "
                  "them the way you would meet any stranger, in your own manner. Let your name and your work "
                  "come out through what you are doing, then leave them room to answer"),
    "hint": ("the newcomer is back and you speak first. You have met, and you greet them the way you would "
             "someone you have seen around. One thing about how the days are going may show in passing, "
             "in a few words"),
    "open": GREET_SITUATION,
}
STANCE_GREET = {
    "angry": ("the newcomer comes up and you speak first. You are angry with them and they know why "
              "(facts.stance.cause). Speak as an angry person would. No pleasantries, and ask nothing of them"),
    "afraid": ("the newcomer comes up and you speak first. You are frightened of them "
               "(facts.stance.cause). Keep your distance and speak shortly. Ask nothing of them"),
    "hurt": ("the newcomer comes up and you speak first. They hurt you (facts.stance.cause) and it still "
             "stings. Be quiet and short with them. Ask nothing of them"),
    "cold": ("the newcomer comes up and you speak first. You have not forgiven what they did "
             "(facts.stance.cause). Be civil at most, and cold. Ask nothing of them"),
    "guarded": ("the newcomer comes up and you speak first. You remember what happened between you "
                "(facts.stance.cause). It has cooled, but you are wary and you let it show"),
}


def _met(conn, player, npc_id) -> int:
    """How many times this villager has spoken with the player, a greeting or a reply each."""
    return conn.execute("select count(*) from interactions where player=? and npc_id=? and task='npc_dialogue' "
                        "and ifnull(retried,0)=0", (player, npc_id)).fetchone()[0]


def _ease(conn, player, npc_id) -> str:
    """Every villager is met for the first time once. The shortage comes in as they get to know you."""
    met = _met(conn, player, npc_id)
    return "introduce" if met < 1 else "hint" if met < 2 else "open"


def _sky(conn, player, game_time) -> dict:
    """The season is the weather. How the player has acted, and where the story leans, stay out of this packet."""
    season = story_facts(conn, player, game_time).get("season")
    return {"season": season} if season else {}


def _heard(ctx) -> dict:
    """The only object a villager's model call may receive.

    Their own memories, the world's rules, their stock, and the map. Not the player's pack, title,
    quests, or anyone else's secret. The validator still sees the full context.
    """
    facts = ctx.get("facts") or {}
    kept = {k: facts[k] for k in _FACT_KEYS if k in facts}
    if "guide" in kept:
        places = kept["guide"].get("places") if isinstance(kept["guide"], dict) else {}
        kept["guide"] = {"places": places or {}}
    st = kept.get("stance")
    if st:
        kept["stance"] = {k: v for k, v in st.items() if k != "heat"}
        if st["mood"] in stance.HARMFUL or st["mood"] == "guarded":
            kept.pop("ease", None)  # how they feel outweighs the pacing
    if not kept.get("recent"):
        kept.pop("recent", None)
    ease = kept.get("ease")
    if not kept.get("lean") or ease != "open":
        kept.pop("lean", None)
    if ease == "introduce" and not kept.get("lost"):
        for key in ("bent", "need"):
            kept.pop(key, None)
    elif ease == "hint" and not kept.get("lost"):
        kept.pop("need", None)
    if ease in (None, "introduce") or not kept.get("sign"):
        kept.pop("sign", None)
    heard = {"npc": dict(ctx.get("npc") or {})}
    for key in ("relationship", "memories", "player_message", "event", "validator_feedback"):
        if key in ctx:
            heard[key] = ctx[key]
    heard["facts"] = kept
    return heard


def player_ask(conn, player, npc_id, game_time) -> dict | None:
    """A villager does not carry the quest list. Hostility is the only thing they are told to lead with."""
    st = stance.of(conn, npc_id, player, game_time)
    if st["mood"] in ("angry", "afraid") and st["heat"] >= 0.5:
        return {"kind": "refuse", "text": "Tell them to leave you alone."}
    if rules.band(db.get_trust(conn, npc_id, player)) == "hostile":
        return {"kind": "refuse", "text": "Tell them to leave you alone."}
    return None


PAY_NAME = {"default:pick_steel": "steel pickaxe", "default:sword_steel": "steel sword"}


def _payment(reward) -> str:
    parts = []
    for entry in reward or []:
        if isinstance(entry, str):
            item, _, count = entry.partition(" ")
            n = int(count or 1)
        else:
            item, n = entry.get("item", ""), entry.get("count") or 1
        word = PAY_NAME.get(item) or item.split(':')[-1].replace('_', ' ')
        parts.append(f"{n} {word}")
    return " and ".join(parts)


def own_need(conn, player, npc_id) -> dict | None:
    """The one thing this villager wants. Not the board, and not anyone else's."""
    quests = npc_cfg(npc_id).get("quests") or []
    if not quests:
        return None
    rows = {r["quest_id"]: r["status"] for r in conn.execute(
        "select quest_id, status from promises where player=? and npc_id=? and kind='quest'", (player, npc_id))}
    ordered = [c for c in quests if c.get("main")] + [c for c in quests if not c.get("main")]
    q = next((c for c in ordered if rows.get(c["id"]) != "done"), None)
    if not q:
        return None
    count = q.get("count") or 1
    if q.get("kind") == "slay":
        item = "monster"
    else:
        item = q.get("item") or ""
    word = NEED_WORD.get(item, item.replace("_", " "))
    what = f"{count} {word}"
    place = NEED_PLACE.get(item)
    where = CONFIG.get("places", {}).get(place, "")
    if item == "monster":
        steps = f"{NEED_HOW['monster']} Deal with {what}, then come back to me."
    else:
        steps = " ".join(bit for bit in (NEED_HOW.get(item, ""),
                                         f"That is {where}." if where else "",
                                         f"Bring {what} back to me.") if bit)
    need = {"what": what, "item": item, "payment": _payment(q.get("reward")), "place": place, "steps": steps}
    if rows.get(q["id"]) == "open":
        need["waiting"] = True
    return need


HELP_WORDS = ("help", "work", "job", "task", "errand", "need", "worr", "wrong", "trouble", "problem",
              "anything i can", "going on", "bother")


def _wants_help(message: str) -> bool:
    text = (message or "").lower()
    return any(word in text for word in HELP_WORDS)


def _lost(message: str) -> bool:
    text = (message or "").lower()
    return any(phrase in text for phrase in LOST_WORDS)


def _directions(npc_id, need) -> str:
    if need and need.get("steps"):
        return need["steps"]
    tips = npc_cfg(npc_id).get("expertise") or []
    return tips[0] if tips else "The village square is in the middle of everything."


def take_gift(conn, npc_id, player, data, game_time) -> list:
    """Hand over an item the villager actually keeps. Once per item per game-day."""
    g = (data or {}).get("give_item")
    if not isinstance(g, dict):
        return []
    item, count = g.get("item"), g.get("count") or 1
    if item not in rules.stock(npc_cfg(npc_id)) or not isinstance(count, int) or not 1 <= count <= 4:
        return []
    itemstring = CONFIG["items"].get(item)
    if not itemstring:
        return []
    last = db.get_flag(conn, npc_id, player, f"gave:{item}")
    if last is not None and game_time - float(last) < 1:
        return []
    db.set_flag(conn, npc_id, player, f"gave:{item}", game_time)
    return [{"item": itemstring, "count": count}]


ASK_EVERY = 0.5  # game-days between a villager's unprompted requests


def _may_ask(conn, player, npc_id, game_time) -> bool:
    """A villager has to know you before leaning on you, and does not ask at every hello."""
    last = db.get_flag(conn, npc_id, player, "asked_at")
    return _met(conn, player, npc_id) >= 2 and (last is None or game_time - float(last) >= ASK_EVERY)


LEAN_AT, NEED_AT = 3, 6  # exchanges before a villager's own shortage colours the talk, then before they ask
LACK = {"monster": "something moving in the woods after dark"}


def _steer(conn, player, npc_id, game_time, mine, quiet) -> tuple[dict | None, dict | None]:
    """A long talk drifts toward the villager's own trouble: first a worry, later the ask. Returns (lean, need)."""
    if not mine or quiet or mine.get("waiting"):
        return None, None
    met = _met(conn, player, npc_id)
    if met >= NEED_AT and _may_ask(conn, player, npc_id, game_time):
        return None, mine
    if met >= LEAN_AT:
        return {"short_of": LACK.get(mine["item"]) or mine["what"].partition(" ")[2]}, None
    return None, None


def greet(conn, llm, world, player, npc_id, thread_id, game_time) -> dict:
    """NPC speaks first when the player approaches. Same npc_dialogue task, no player message."""
    player = f"{world}:{player}"
    ease = _ease(conn, player, npc_id)
    felt = stance.of(conn, npc_id, player, game_time)
    db.set_flag(conn, npc_id, player, "last_mood", felt["mood"])
    situation = STANCE_GREET.get(felt["mood"]) or EASE_GREET[ease]
    ask = player_ask(conn, player, npc_id, game_time)
    harmful = felt["mood"] in stance.HARMFUL
    need = None if ask or harmful or not _may_ask(conn, player, npc_id, game_time) else own_need(conn, player, npc_id)
    done = conn.execute("select e.details from events e where e.player=? and e.target=? and e.type='quest_done' "
                        "and ? - e.game_time <= 0.05 order by e.id desc limit 1", (player, npc_id, game_time)).fetchone()
    if done:  # the player just handed over what this villager asked for
        brought = (json.loads(done["details"]).get("item") or "something").replace("_", " ")
        situation = (f"the player has just handed you {brought}; thank them for that, in character, "
                     "and say what it means to you. Do not name a task or a payment; speak first")
        ask, need = None, None
    ctx = build_context(conn, npc_id, player, None, {"situation": situation, "ask": ask, "need": need, "ease": ease,
                                                     **_sky(conn, player, game_time),
                                                     **situations.facts(conn, player, npc_id, game_time)},
                         game_time)
    prev = None
    for attempt in range(2):  # one retry with the validator's feedback, like talk()
        heard = _heard(ctx)
        res = llm.complete("npc_dialogue", heard, thread_id)
        vres = validate("npc_dialogue", res.data, ctx)
        prev = log_call(conn, "npc_dialogue", npc_id, player, thread_id, heard, res, vres, attempt > 0, prev)
        if vres["ok"]:
            take_evidence(conn, player, res.data)
            if need:
                db.set_flag(conn, npc_id, player, "asked_at", game_time)
            situations.take(conn, player, npc_id, res.data, game_time, ctx["facts"], greeting=True)
            places = ctx["facts"]["guide"]["places"]
            said = res.data.get("point_to")
            return {"reply": res.data["reply"], "notices": [],
                    "point_to": said if isinstance(said, str) and said in places else None,
                    "give": take_gift(conn, npc_id, player, res.data, game_time)}
        if res.data is None and res.error:
            break
        ctx = {**ctx, "validator_feedback": vres["errors"]}
    return {"reply": stance.FALLBACK[felt["mood"]], "notices": [], "point_to": None, "give": []}


def _voice(conn, llm, npc, player, situation, fallback, game_time=None) -> str:
    """One LLM line from `npc` in the given situation (npc_dialogue task), or the fallback if it fails."""
    extra = {"situation": situation}
    if game_time is not None:
        extra.update(_sky(conn, player, game_time))
    ctx = build_context(conn, npc, player, None, extra, game_time)
    heard = _heard(ctx)
    thread = f"{player}:{npc}:scene:{time.time():.0f}"
    res = llm.complete("npc_dialogue", heard, thread)
    vres = validate("npc_dialogue", res.data, ctx)
    log_call(conn, "npc_dialogue", npc, player, thread, heard, res, vres)
    if vres["ok"]:
        take_evidence(conn, player, res.data)
    return res.data["reply"] if vres["ok"] else fallback


def gossip(conn, world, player, teller, listener, game_time, roll: float | None = None, llm=None,
           voice: bool = False) -> dict:
    """Two villagers met. The teller may pass on one thing about the player the listener doesn't know yet.
    The rumour always spreads; it is voiced through the LLM only when a player can hear it (voice=True)."""
    player = f"{world}:{player}"
    npc_cfg(teller), npc_cfg(listener)
    none = {"shared": False, "line": None, "reply": None}
    m = conn.execute(
        "select m.*, e.target, e.details from memories m join events e on e.id = m.event_id "
        "where m.npc_id=? and m.player=? and m.severity>=10 and m.reliability>=0.25 "
        f"and m.type in ({','.join('?' * len(PUBLIC_RUMOUR))}) "
        "and (m.learned_at is null or ? - m.learned_at >= ? or e.target = m.npc_id) "
        "and m.event_id not in (select event_id from memories where npc_id=? and player=?) "
        "order by m.severity desc, m.id limit 1",
        (teller, player, *sorted(PUBLIC_RUMOUR), game_time, GOSSIP_DELAY, listener, player)).fetchone()
    if not m:
        return none
    roll = random.random() if roll is None else roll
    victim = m["target"] == teller
    if roll >= npc_cfg(teller).get("chattiness", 0.5) and not victim and not (m["type"] in CRIME and listener == "wren"):
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
    if not (voice and llm):
        return {"shared": True, "line": None, "reply": None}
    line = _voice(conn, llm, teller, player,
                  f"you meet {name(listener)} in the village and pass on a rumour about the newcomer: {what}. "
                  "Say it to them in one sentence, as gossip, in your own voice", f"Psst... {what}.", game_time)
    reply = _voice(conn, llm, listener, player,
                   f'{name(teller)} just told you: "{line}". React to {name(teller)} in one short sentence',
                   "Really?!", game_time)
    return {"shared": True, "line": line, "reply": reply}


def moods(conn, world, player, game_time) -> dict:
    """Behaviour-only mood per villager (never shown to the player): how they feel, and whether they shun you."""
    player = f"{world}:{player}"
    out = {}
    for n in CONFIG["npcs"]:
        s = stance.of(conn, n, player, game_time)
        out[n] = {"mood": s["mood"], "shun": stance.shunning(s)}
    return out


def trade_quote(conn, world, player, npc_id, work_block_present: bool, game_time=None) -> dict:
    min_level = (npc_cfg(npc_id).get("trade") or {}).get("min_level", 1)
    if progress.player_state(conn, f"{world}:{player}")["level"] < min_level:
        return {"ok": False, "reason": "level", "min_level": min_level}
    if game_time is not None and stance.shunning(stance.of(conn, npc_id, f"{world}:{player}", game_time)):
        return {"ok": False, "reason": "shunned"}
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

    out.update(story_report(conn, player, game_time))
    if out.get("offer"):
        out["offer_text"] = finale.ENDINGS[out["ending"]]["offer"]
    return out


def people(conn, world, player) -> dict:
    """Who the player has met and how that last meeting left them. Not live: off-screen feelings stay off-screen."""
    player = f"{world}:{player}"
    met = []
    for npc_id, cfg in CONFIG["npcs"].items():
        mood = db.get_flag(conn, npc_id, player, "last_mood")
        if mood:
            met.append({"npc_id": npc_id, "name": cfg["name"], "role": cfg["role"], "mood": mood})
    return {"met": met, "standing": stance.standing([m["mood"] for m in met])}


def accept_ending(conn, llm, world, player, game_time) -> dict:
    """The player stands with the village. The run ends, and the ending plays as a short scene."""
    player = f"{world}:{player}"
    rep = story_report(conn, player, game_time)
    ending = rep.get("ending")
    if rep["phase"] != "closing" or not ending:
        raise ValueError("no ending is being offered")
    end_run(conn, player, ending)
    e = finale.ENDINGS[ending]
    lines = []
    for npc in finale.speakers(conn, player, list(CONFIG["npcs"])):
        situation = (f"the last gathering of the story: {e['gather']}. Do not greet or welcome the newcomer; "
                     "you are already together. Say one or two sentences to them about what you carry of them, "
                     "using only what you remember, and nothing about what comes next")
        lines.append((name(npc), _voice(conn, llm, npc, player, situation, e["fallback"], game_time)))
    return {"ending": ending, "title": e["title"], "tint": e["tint"], "slides": finale.slides(ending, lines)}


def refuse_ending(conn, world, player, game_time) -> dict:
    """The player walks away from the gathering. They are not offered it again for a while."""
    player = f"{world}:{player}"
    db.add_event(conn, {"player": player, "actor": player, "target": None, "type": "ending_refused",
                        "details": {}, "witnesses": [], "game_time": game_time, "source": "game",
                        "verified": True, "confidence": None})
    return {"ok": True}


# Harvest Festival ---------------------------------------------------------------------------------

FESTIVAL_LEVEL = 3  # short hackathon game
FESTIVAL_HOST = "bram"
VOTE_TEMPLATE = {"for": "I vote for.", "abstain": "I abstain.", "against": "I vote against."}


def vote(trust: int) -> str:
    return "for" if trust >= 30 else "against" if trust < -10 else "abstain"


def ending(votes: list[str]) -> str:
    f, a = votes.count("for"), votes.count("against")
    if f * 3 >= 2 * len(votes) and a == 0:
        return "hero"
    return "accepted" if f > a else "turned_away"


def festival_status(conn, player) -> dict:
    done = {r["quest_id"] for r in conn.execute(
        "select quest_id from promises where player=? and status='done' and quest_id is not null", (player,))}
    missing = [q["title"] for c in CONFIG["npcs"].values() for q in c.get("quests", []) if q["main"] and q["id"] not in done]
    level = progress.player_state(conn, player)["level"]
    held = conn.execute("select 1 from events where player=? and type='festival'", (player,)).fetchone() is not None
    return {"eligible": not missing and level >= FESTIVAL_LEVEL and not held, "held": held, "missing_main": missing,
            "level": level, "level_needed": FESTIVAL_LEVEL}


def hold_festival(conn, llm, world, player, game_time) -> dict:
    """The village votes on the player. Votes come from hidden trust; only a few villagers speak through the LLM."""
    player = f"{world}:{player}"
    if not festival_status(conn, player)["eligible"]:
        raise ValueError("the festival can't be held yet")
    trust = {n: db.get_trust(conn, n, player) for n in CONFIG["npcs"]}
    votes = {n: vote(t) for n, t in trust.items()}
    # Votes and the ending are decided here, instantly. Speeches are generated one by one on demand
    # (festival_speech), so the player reads one while the next is being written.
    result = [{"npc_id": n, "name": name(n), "vote": votes[n]} for n in CONFIG["npcs"]]
    end = ending(list(votes.values()))
    eid = db.add_event(conn, {"player": player, "actor": player, "target": None, "type": "festival",
                              "details": {"ending": end, "votes": votes}, "witnesses": list(CONFIG["npcs"]),
                              "game_time": game_time, "source": "game", "verified": True, "confidence": None})
    words = {"hero": "welcomed the newcomer as a hero", "accepted": "accepted the newcomer",
             "turned_away": "turned the newcomer away"}[end]
    for n in CONFIG["npcs"]:
        db.add_memory(conn, n, player, eid, "festival", f"at the Harvest Festival the village {words}", "witnessed",
                      1.0, 30, game_time)
    return {"votes": result, "ending": end}


def festival_speech(conn, llm, world, player, npc_id) -> dict:
    player = f"{world}:{player}"
    row = conn.execute("select details from events where player=? and type='festival'", (player,)).fetchone()
    if not row:
        raise ValueError("no festival held yet")
    v = json.loads(row["details"])["votes"][npc_cfg(npc_id) and npc_id]
    return {"speech": _voice(conn, llm, npc_id, player,
                             f"the village festival vote; you vote {v}; explain why in one or two sentences, "
                             "citing what you remember about the newcomer", VOTE_TEMPLATE[v])}


NEUTRAL_LINE = "Hm. Let me think on that."
MIN_CONFIDENCE = 0.6


def _apply_intent(conn, intent: dict, npc_id, player, game_time, notices) -> dict:
    """Turns a classified intent into deterministic effects. Returns extra facts for the dialogue context."""
    kind = intent.get("intent")
    conf = intent.get("confidence") or 0
    if kind not in ("threat", "insult", "apology", "promise", "correction") or conf < MIN_CONFIDENCE:
        return {}
    eid = db.add_event(conn, {"player": player, "actor": player, "target": npc_id, "type": kind, "details": intent,
                              "witnesses": [npc_id], "game_time": game_time, "source": "llm_classified",
                              "verified": False, "confidence": conf})
    if kind in ("threat", "insult"):
        delta = rules.trust_delta(kind)
        db.add_trust(conn, npc_id, player, delta)
        db.add_memory(conn, npc_id, player, eid, kind,
                      "the newcomer insulted me" if kind == "insult" else "the newcomer threatened me",
                      "witnessed", 1.0, abs(delta), game_time)
        return {"heard_as": kind}
    elif kind == "apology":
        if rules.apology_allowed(db.get_flag(conn, npc_id, player, "last_apology"), game_time):
            delta = rules.trust_delta("apology")
            db.add_trust(conn, npc_id, player, delta)
            db.add_memory(conn, npc_id, player, eid, "apology", "the newcomer apologised to me",
                          "witnessed", 1.0, delta, game_time)
            db.set_flag(conn, npc_id, player, "last_apology", game_time)
            notices.append(f"{name(npc_id)} noticed your apology.")
        return {"heard_as": "apology"}
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


PLAIN_BLOCK = ("fool", "idiot", "stupid", "useless", "kill", "burn", "hurt", "hit ", "die", "sorry", "apolog",
               "forgive", "promise", "i'll", "i will", "bring you", "liar", "thief", "stole", "didn't", "did not",
               "never")


def _plain(message: str) -> bool:
    """A short question or hello with nothing in it for the classifier. Saves a model call and about 3 s."""
    text = message.strip().lower()
    words = text.split()
    greeting = bool(words) and words[0].strip(",.!") in ("hello", "hi", "hey", "good", "greetings")
    return len(words) <= 12 and (text.endswith("?") or greeting) and not any(w in text for w in PLAIN_BLOCK)


def talk(conn, llm, world, player, npc_id, message, thread_id, game_time) -> dict:
    cfg, player = npc_cfg(npc_id), f"{world}:{player}"
    notices = []
    extra = {}
    if not _plain(message):
        cin = {"npc": {"name": cfg["name"], "role": cfg["role"]}, "player_message": message}
        cres = llm.complete("intent_classify", cin, thread_id)
        log_call(conn, "intent_classify", npc_id, player, thread_id, cin, cres)
        try:
            extra = _apply_intent(conn, cres.data or {}, npc_id, player, game_time, notices)
        except (TypeError, ValueError, AttributeError):  # well-formed JSON with wrong value types from the LLM
            extra = {}

    ask = player_ask(conn, player, npc_id, game_time)
    mine = None if ask else own_need(conn, player, npc_id)
    lost = _lost(message) and not ask
    abused = extra.get("heard_as") in ("insult", "threat")
    # A request surfaces when the talk turns to help or work. Someone just insulted asks nothing of the insulter.
    felt = stance.of(conn, npc_id, player, game_time)
    db.set_flag(conn, npc_id, player, "last_mood", felt["mood"])
    harmful = felt["mood"] in stance.HARMFUL
    need = mine if mine and not abused and not harmful and (lost or _wants_help(message)) else None
    lean = None
    if not need:
        lean, need = _steer(conn, player, npc_id, game_time, mine,
                            quiet=bool(ask) or abused or harmful or felt["mood"] == "guarded")
    ctx = build_context(conn, npc_id, player, message, {**extra, "ask": ask, "need": need, "lean": lean,
                                                        "ease": _ease(conn, player, npc_id),
                                                        "lost": lost or None,
                                                        "directions": _directions(npc_id, mine) if lost else None,
                                                        **_sky(conn, player, game_time),
                                                        **situations.facts(conn, player, npc_id, game_time)},
                         game_time)
    reply, point_to = guidance_line(ctx, npc_id)
    prev, spoken = None, None
    for attempt in range(2):
        heard = _heard(ctx)
        res = llm.complete("npc_dialogue", heard, thread_id)
        vres = validate("npc_dialogue", res.data, ctx)
        prev = log_call(conn, "npc_dialogue", npc_id, player, thread_id, heard, res, vres, attempt > 0, prev)
        if res.data is None and res.error:
            break  # timeout or network error: retrying would blow the game's HTTP budget
        if vres["ok"]:
            take_evidence(conn, player, res.data)
            if need:
                db.set_flag(conn, npc_id, player, "asked_at", game_time)
            situations.take(conn, player, npc_id, res.data, game_time, ctx["facts"])
            reply = res.data["reply"]
            said = res.data.get("point_to")
            places = ctx["facts"]["guide"]["places"]
            point_to = said if isinstance(said, str) and said in places else None
            spoken = res.data
            break
        ctx = {**ctx, "validator_feedback": vres["errors"]}
    return {"reply": reply, "notices": notices, "quest_offer": None, "point_to": point_to,
            "give": take_gift(conn, npc_id, player, spoken, game_time)}
