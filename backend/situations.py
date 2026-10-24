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


def _ids(raw) -> list:
    if not raw:
        return []
    return json.loads(raw) if isinstance(raw, str) else list(raw)


def _knows(row, npc) -> bool:
    """The opener and the people they let in. Someone a secret is kept from does not know it."""
    return row["opener"] == npc or npc in _ids(row["involves"])


def _mine(conn, player, npc):
    return next((r for r in _open_rows(conn, player) if _knows(r, npc)), None)


def facts(conn, player: str, npc: str, game_time: float) -> dict:
    """What this villager may do about situations right now."""
    out = {"you_are": npc}
    out["busy"] = sorted({who for r in _open_rows(conn, player) for who in [r["opener"], *_ids(r["involves"])]})
    mine = _mine(conn, player, npc)
    if mine:
        out["open_situation"] = {"text": mine["text"], "involves": _ids(mine["involves"]),
                                 "hidden_from": _ids(mine["hidden_from"]), "motive": mine["motive"] or None,
                                 "already_told": npc in _ids(mine["told"])}
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
        you = facts.get("you_are")
        hidden = s.get("hidden_from") or [] if isinstance(s, dict) else []
        motive = s.get("motive") if isinstance(s, dict) else None
        known = s.get("involves") if isinstance(s, dict) else None
        if not facts.get("may_open"):
            out.append("situation_not_allowed")
        elif not (isinstance(s, dict) and isinstance(s.get("text"), str) and 0 < len(s["text"].strip()) <= 240
                  and isinstance(known, list) and 1 <= len(known) <= 2
                  and all(i in npc_ids and i != you for i in known)
                  and isinstance(hidden, list) and len(hidden) <= 2
                  and all(i in npc_ids and i != you and i not in known for i in hidden)
                  and isinstance(motive, str) and 8 <= len(motive.strip()) <= 200):
            out.append("situation_malformed")
        elif any(p in motive.lower() for p in ("don't know", "do not know", "no reason", "not sure", "haven't told")):
            out.append("situation_no_motive")
        elif "newcomer" in s["text"].lower() or "newcomer" in motive.lower():
            out.append("situation_about_player")
        elif set(known) & set(facts.get("busy") or []):
            out.append("situation_duplicate")
    gap = output.get("motive")
    if gap is not None and not (isinstance(gap, str) and 8 <= len(gap.strip()) <= 200):
        out.append("motive_malformed")
    c = output.get("consequence")
    if c is not None:
        if not facts.get("open_situation"):
            out.append("consequence_not_allowed")
        elif not (isinstance(c, dict) and c.get("npc_id") in npc_ids and c.get("stance") in STANCE
                  and c.get("size") in (None, *SIZE)
                  and isinstance(c.get("text"), str) and 0 < len(c["text"].strip()) <= 240):
            out.append("consequence_malformed")
        else:
            sit = facts.get("open_situation") or {}
            know = {facts.get("you_are"), *(sit.get("involves") or [])} - set(sit.get("hidden_from") or [])
            if c.get("npc_id") not in know:
                out.append("consequence_hidden")
    return out


def take(conn, player: str, npc: str, data: dict | None, game_time: float, allowed: dict,
         greeting: bool = False) -> None:
    """Store a validated situation or consequence as events and memories. A greeting that carries an open
    situation counts as that villager having told it, so the next greeting does not repeat it."""
    data = data or {}
    s, c = data.get("situation"), data.get("consequence")
    if s and allowed.get("may_open"):
        text = s["text"].strip()
        motive = s["motive"].strip()
        involves = [i for i in s["involves"] if i != npc]
        hidden = [i for i in (s.get("hidden_from") or []) if i != npc and i not in involves]
        remembered = f"{text} Reason: {motive}"
        eid = db.add_event(conn, {"player": player, "actor": npc, "target": None, "type": "situation",
                                  "details": {"text": text, "involves": involves, "hidden_from": hidden,
                                              "motive": motive},
                                  "witnesses": [npc, *involves],
                                  "game_time": game_time, "source": "model", "verified": False, "confidence": None})
        conn.execute("insert into situations (player, opener, involves, hidden_from, motive, text, opened_at, "
                     "event_id) values (?,?,?,?,?,?,?,?)",
                     (player, npc, json.dumps(involves), json.dumps(hidden), motive, text, game_time, eid))
        conn.commit()
        for who in {npc, *involves}:  # hidden_from learns nothing until someone tells them
            db.add_memory(conn, who, player, eid, "situation", remembered, "own", 1.0, SEVERITY, game_time)
    mine = _mine(conn, player, npc)
    know = {mine["opener"], *_ids(mine["involves"])} if mine else set()
    if c and allowed.get("open_situation") and mine and c.get("npc_id") in know:
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
    gap = data.get("motive")
    if isinstance(gap, str) and mine and not (mine["motive"] or "").strip() and 8 <= len(gap.strip()) <= 200:
        motive = gap.strip()
        conn.execute("update situations set motive=? where id=?", (motive, mine["id"]))
        conn.commit()
        for who in {mine["opener"], *_ids(mine["involves"])}:
            db.add_memory(conn, who, player, mine["event_id"], "situation", f"The reason: {motive}",
                          "own", 1.0, SEVERITY, game_time)
        mine = _mine(conn, player, npc)
    if greeting and mine:
        told = json.loads(mine["told"] or "[]")
        if npc not in told:
            conn.execute("update situations set told=? where id=?", (json.dumps([*told, npc]), mine["id"]))
            conn.commit()
