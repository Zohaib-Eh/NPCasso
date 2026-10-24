"""Situations a villager opens in conversation. The model invents them; the game keeps them, so the village
remembers and the model cannot rewrite what was said. Pacing is decided here, in code."""
import json

from . import db
from .story import report

CAP = {"open": 1, "pressure": 3, "closing": 3}  # open situations at once, per phase
COOLDOWN = 0.5  # game-days before the same villager may open another
GAP = 0.2  # game-days before anyone may open another, so the village does not unload at once
SEVERITY = 25  # high enough that the memory stays in a villager's top five
STANCE = {"helped": 1, "hurt": -1}  # which way a consequence moves trust
SIZE = {"small": 3, "medium": 6, "large": 10}  # how far; the model picks the word, this sets the number


def trust_change(c: dict) -> int:
    return STANCE[c["stance"]] * SIZE[c.get("size") or "small"]


def _open_rows(conn, player):
    return conn.execute("select * from situations where player=? and status='open' order by id", (player,)).fetchall()


def _mine(conn, player, npc):
    return next((r for r in _open_rows(conn, player)
                 if r["opener"] == npc or npc in json.loads(r["involves"])), None)


def facts(conn, player: str, npc: str, game_time: float) -> dict:
    """What this villager may do about situations right now."""
    out = {"you_are": npc}
    out["busy"] = sorted({who for r in _open_rows(conn, player) for who in [r["opener"], *json.loads(r["involves"])]})
    mine = _mine(conn, player, npc)
    if mine:
        out["open_situation"] = {"text": mine["text"], "involves": json.loads(mine["involves"]),
                                 "already_told": npc in json.loads(mine["told"] or "[]")}
    cap = CAP.get(report(conn, player, game_time)["phase"], 0)
    recent = conn.execute("select 1 from situations where player=? and ((opener=? and ? - opened_at < ?) "
                          "or ? - opened_at < ?)", (player, npc, game_time, COOLDOWN, game_time, GAP)).fetchone()
    if not mine and not recent and len(_open_rows(conn, player)) < cap:
        out["may_open"] = True
    return out


def errors(output: dict, facts: dict, npc_ids) -> list[str]:
    """Validator hook: a situation or consequence the game did not allow, or one that is malformed."""
    out = []
    s = output.get("situation")
    if s is not None:
        if not facts.get("may_open"):
            out.append("situation_not_allowed")
        elif not (isinstance(s, dict) and isinstance(s.get("text"), str) and 0 < len(s["text"].strip()) <= 240
                  and isinstance(s.get("involves"), list) and 1 <= len(s["involves"]) <= 2
                  and all(i in npc_ids and i != facts.get("you_are") for i in s["involves"])):
            out.append("situation_malformed")
        elif "newcomer" in s["text"].lower():
            out.append("situation_about_player")
        elif set(s["involves"]) & set(facts.get("busy") or []):
            out.append("situation_duplicate")
    c = output.get("consequence")
    if c is not None:
        if not facts.get("open_situation"):
            out.append("consequence_not_allowed")
        elif not (isinstance(c, dict) and c.get("npc_id") in npc_ids and c.get("stance") in STANCE
                  and c.get("size") in (None, *SIZE)
                  and isinstance(c.get("text"), str) and 0 < len(c["text"].strip()) <= 240):
            out.append("consequence_malformed")
    return out


def take(conn, player: str, npc: str, data: dict | None, game_time: float, allowed: dict,
         greeting: bool = False) -> None:
    """Store a validated situation or consequence as events and memories. A greeting that carries an open
    situation counts as that villager having told it, so the next greeting does not repeat it."""
    data = data or {}
    s, c = data.get("situation"), data.get("consequence")
    if s and allowed.get("may_open"):
        text = s["text"].strip()
        involves = [i for i in s["involves"] if i != npc]
        eid = db.add_event(conn, {"player": player, "actor": npc, "target": None, "type": "situation",
                                  "details": {"text": text, "involves": involves}, "witnesses": [npc, *involves],
                                  "game_time": game_time, "source": "model", "verified": False, "confidence": None})
        conn.execute("insert into situations (player, opener, involves, text, opened_at, event_id) values (?,?,?,?,?,?)",
                     (player, npc, json.dumps(involves), text, game_time, eid))
        conn.commit()
        for who in {npc, *involves}:
            db.add_memory(conn, who, player, eid, "situation", text, "own", 1.0, SEVERITY, game_time)
    mine = _mine(conn, player, npc)
    if c and allowed.get("open_situation") and mine:
        text = c["text"].strip()
        eid = db.add_event(conn, {"player": player, "actor": player, "target": c["npc_id"], "type": "consequence",
                                  "details": {"text": text, "stance": c["stance"], "size": c.get("size") or "small",
                                              "situation": mine["id"]},
                                  "witnesses": [npc, c["npc_id"]], "game_time": game_time, "source": "model",
                                  "verified": False, "confidence": None})
        db.add_memory(conn, c["npc_id"], player, eid, "consequence", text, "own", 1.0, SEVERITY, game_time)
        db.add_trust(conn, c["npc_id"], player, trust_change(c))
        conn.execute("update situations set status='resolved' where id=?", (mine["id"],))
        conn.commit()
        return
    mine = _mine(conn, player, npc)
    if greeting and mine:
        told = json.loads(mine["told"] or "[]")
        if npc not in told:
            conn.execute("update situations set told=? where id=?", (json.dumps([*told, npc]), mine["id"]))
            conn.commit()
