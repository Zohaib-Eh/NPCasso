"""How a villager feels about the player right now. Computed from their own memories; the model only voices it."""
from .db import load_config

CONFIG = load_config()
HALF_LIFE = 1.5  # game-days for a grievance to halve
HARM = {"hit_npc": 25, "theft": 30, "vandalism": 40, "threat": 15, "insult": 10}
AMENDS = {"apology", "gift", "repair", "return", "quest_done"}
GRAVE = {"hit_npc", "theft", "vandalism"}
HARMFUL = {"angry", "afraid", "hurt", "cold"}
MOOD = {  # what each kind of harm does to each temper, when it was done to them
    "hit_npc": {"hot": "angry", "steady": "angry", "timid": "afraid"},
    "threat": {"hot": "angry", "steady": "guarded", "timid": "afraid"},
    "theft": {"hot": "angry", "steady": "cold", "timid": "cold"},
    "vandalism": {"hot": "angry", "steady": "angry", "timid": "cold"},
    "insult": {"hot": "angry", "steady": "hurt", "timid": "hurt"},
}
SCALE = 40.0  # harm points that make a villager fully worked up
FALLBACK = {"neutral": "Hm. Morning.", "warm": "Good to see you.", "fond": "There you are. Good to see you.",
            "guarded": "Hm. You again.", "cold": "I've nothing to say to you.", "hurt": "...Not now.",
            "angry": "Leave me be.", "afraid": "Please... keep back."}


SHUN_HEAT = 0.3  # a villager this worked up will not trade


def shunning(s: dict) -> bool:
    return s["mood"] in HARMFUL and s["heat"] >= SHUN_HEAT


def standing(moods: list[str]) -> str:
    """One word for how the villagers you have met see you."""
    if not moods:
        return "Unknown"
    bad = sum(m in HARMFUL for m in moods)
    good = sum(m in ("warm", "fond") for m in moods)
    return "Feared" if bad >= 2 else "Watched" if bad else "Trusted" if good >= 2 else "Newcomer"


def when(age: float) -> str:
    if age < 0.05:
        return "moments ago"
    if age < 0.5:
        return "earlier"
    if age < 1.5:
        return "yesterday"
    return "days ago"


def _cause(row, me: str) -> str:
    text = row["text"].replace("the newcomer", "you")
    if row["how"].startswith("told"):
        return f"I heard {text}"
    return text if row["target"] in (me, None) else f"I saw {text}"


def of(conn, npc_id: str, player: str, game_time: float) -> dict:
    temper = CONFIG["npcs"][npc_id].get("temper", "steady")
    rows = conn.execute(
        "select m.type, m.text, m.how, m.severity, m.learned_at, e.target from memories m "
        "left join events e on e.id = m.event_id where m.npc_id=? and m.player=? and m.type != 'walk_away'",
        (npc_id, player)).fetchall()
    harm, amends, top, scar = 0.0, 0.0, None, False
    for r in rows:
        age = game_time - r["learned_at"] if r["learned_at"] is not None else 3.0
        fade = 0.5 ** (max(age, 0.0) / HALF_LIFE)
        if r["type"] in AMENDS:
            amends += (r["severity"] or 0) * fade
        elif r["type"] in HARM:
            mine = r["target"] in (npc_id, None)
            weight = HARM[r["type"]] * fade * (1.0 if mine else 0.6) * (0.5 if r["how"].startswith("told") else 1.0)
            harm += weight
            scar = scar or r["type"] in GRAVE
            if top is None or weight > top[0]:
                top = (weight, r, mine)
    heat = min(1.0, max(0.0, harm - amends) / SCALE)
    if top is None or (heat < 0.1 and not scar):
        rel = conn.execute("select trust from relationships where npc_id=? and player=?", (npc_id, player)).fetchone()
        trust = rel["trust"] if rel else CONFIG["start_trust"]
        mood = "fond" if trust >= 30 else "warm" if trust >= 15 else "neutral"
        return {"mood": mood, "strength": "faint", "cause": None, "heat": 0.0}
    _, row, mine = top
    if heat < 0.25:
        mood = "guarded"
    elif not mine:
        mood = "cold"
    else:
        mood = MOOD[row["type"]][temper]
    strength = "faint" if heat < 0.25 else "clear" if heat < 0.6 else "strong"
    return {"mood": mood, "strength": strength, "cause": _cause(row, npc_id), "heat": round(heat, 3)}
