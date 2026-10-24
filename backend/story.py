"""Winter clock and the hidden score that names an ending.

Days are counted from the player's arrival. The clock may show the day. It never shows these thresholds.
Day 1 open, days 2–5 pressure, days 6–9 closing, day 10 the cold cannot be survived.
"""
import math

DIMENSIONS = (
    "candor", "bravery", "compassion", "selflessness", "ambition", "ingenuity",
    "loyalty", "pragmatism", "curiosity", "justice", "forgiveness", "independence",
)

# Sign is the direction that leans the ending. Tie-break is this order.
SIGNATURES = {
    "names_we_buried": {"candor": 1, "bravery": 1, "loyalty": 1},
    "last_place_at_the_table": {"compassion": 1, "selflessness": 1, "loyalty": 1},
    "the_peace_you_made": {"ambition": 1, "pragmatism": 1, "ingenuity": 1},
    "the_last_departure": {"independence": 1, "ambition": -1, "loyalty": -1},
    "the_end_of_all_things": {"forgiveness": -1, "compassion": -1, "independence": 1},
}

PRESSURE_DAY, CLOSING_DAY, FINAL_DAY = 2, 6, 10
OFFER_DAY = 7  # the village gathers from here, after the steer has had a day to build
REOFFER = 0.5  # game-days of quiet after the player walks away from the gathering


def _refused_lately(conn, player: str, game_time: float) -> bool:
    return conn.execute("select 1 from events where player=? and type='ending_refused' and ? - game_time < ?",
                        (player, game_time, REOFFER)).fetchone() is not None


def end_run(conn, player: str, ending: str) -> None:
    """The player stood with the village. The run is over and `ending` is the one they reached."""
    if ending not in SIGNATURES:
        raise ValueError(f"unknown ending {ending!r}")
    _ensure(conn)
    conn.execute("update runs set choice=? where player=?", (ending, player))
    conn.commit()


def _ensure(conn):
    conn.execute("""create table if not exists evidence (
        id integer primary key, player text, dimension text, weight real,
        event_id integer, note text)""")
    conn.execute("""create table if not exists runs (
        player text primary key, start_time real, choice text)""")


def add_evidence(conn, player: str, dimension: str, weight: float, event_id: int | None, note: str | None) -> None:
    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown dimension {dimension!r}")
    if not -1 <= weight <= 1:
        raise ValueError("weight must be from -1 to 1")
    _ensure(conn)
    conn.execute("insert into evidence (player, dimension, weight, event_id, note) values (?,?,?,?,?)",
                 (player, dimension, weight, event_id, note))
    conn.commit()


def _means(conn, player: str) -> dict[str, float]:
    _ensure(conn)
    rows = conn.execute("select dimension, weight from evidence where player=?", (player,)).fetchall()
    buckets: dict[str, list[float]] = {}
    for row in rows:
        buckets.setdefault(row["dimension"], []).append(row["weight"])
    return {dim: sum(weights) / len(weights) for dim, weights in buckets.items()}


def profile(conn, player: str) -> list[dict]:
    """Where the player stands on each dimension, -1 to +1, in the fixed order. A dimension with no evidence is 0."""
    means = _means(conn, player)
    _ensure(conn)
    counts = {r["dimension"]: r["n"] for r in conn.execute(
        "select dimension, count(*) as n from evidence where player=? group by dimension", (player,))}
    return [{"dimension": dim, "value": round(means.get(dim, 0.0), 3), "n": counts.get(dim, 0)}
            for dim in DIMENSIONS]


def leading_ending(conn, player: str) -> str | None:
    means = _means(conn, player)
    if not means:
        return None
    best, best_i = None, None
    for i, (ending, sig) in enumerate(SIGNATURES.items()):
        score = sum(means.get(dim, 0) * sign for dim, sign in sig.items()) / len(sig)
        if score > 0 and (best is None or score > best or (score == best and i < best_i)):
            best, best_i = score, i
            chosen = ending
    return chosen if best is not None else None


# First pole is the negative weight, second is the positive. The player never sees these words.
POLES = {
    "candor": ("hides what happened", "says the hard thing"),
    "bravery": ("steps back from the risk", "takes the risk"),
    "compassion": ("walks past suffering", "is moved by suffering"),
    "selflessness": ("keeps the gain", "gives the gain up"),
    "ambition": ("accepts a small place", "reaches for a mark"),
    "ingenuity": ("uses the usual way", "finds another way"),
    "loyalty": ("drops a commitment", "stands by someone"),
    "pragmatism": ("holds out for the ideal", "takes the workable outcome"),
    "curiosity": ("leaves the surface as it is", "looks underneath"),
    "justice": ("lets a wrong stand", "asks for an account"),
    "forgiveness": ("keeps the grievance", "lets the grievance go"),
    "independence": ("stays with the village", "goes their own way"),
}
LEAN = {
    "names_we_buried": "a buried truth is coming due",
    "last_place_at_the_table": "someone may be left out of what little remains",
    "the_peace_you_made": "a hard bargain could hold the village together",
    "the_last_departure": "leaving is becoming the honest choice",
    "the_end_of_all_things": "trust is failing and the village may not hold",
}
SEASON = {
    "open": "ordinary days, before the cold is a problem",
    "pressure": "the cold is getting into food, firewood, and who is provided for",
    "closing": "winter is closing in",
    "frozen": "the cold is past surviving",
    "ended": "the run is over",
}


def conduct(conn, player: str) -> str | None:
    """How this player's acts read, in words. No numbers."""
    ranked = sorted(_means(conn, player).items(), key=lambda item: abs(item[1]), reverse=True)
    phrases = []
    for dim, mean in ranked:
        if abs(mean) < 0.25:
            break
        phrases.append(POLES[dim][1 if mean > 0 else 0])
        if len(phrases) == 2:
            break
    return "the player " + " and ".join(phrases) if phrases else None


def story_facts(conn, player: str, game_time: float) -> dict:
    """What the model may know about the season and the run. No day number, no score."""
    rep = report(conn, player, game_time)
    out = {"season": SEASON[rep["phase"]]}
    line = conduct(conn, player)
    if line:
        out["regard"] = line
    if rep["phase"] == "closing" and rep.get("ending"):
        out["lean"] = LEAN[rep["ending"]]
    return out


def clock_day(elapsed: float) -> int:
    return int(math.floor(elapsed)) + 1


def phase(elapsed: float) -> str:
    day = clock_day(elapsed)
    if day >= FINAL_DAY:
        return "frozen"
    if day >= CLOSING_DAY:
        return "closing"
    if day >= PRESSURE_DAY:
        return "pressure"
    return "open"


def cold_rate(elapsed: float) -> float:
    """Hit points lost per second. Nothing before day 6. Steeper as day 10 gets close. Day 10 is immediate."""
    if clock_day(elapsed) >= FINAL_DAY:
        return 20.0
    if clock_day(elapsed) < CLOSING_DAY:
        return 0.0
    # 0 at the first moment of day 6 (elapsed 5), 1 at the first moment of day 10 (elapsed 9).
    t = min(1.0, max(0.0, (elapsed - (CLOSING_DAY - 1)) / (FINAL_DAY - CLOSING_DAY)))
    return 0.02 * (20 ** t)


def clock_time(world_frac: float) -> str:
    minutes = int(world_frac * 24 * 60 + 1e-6) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def mark_died(conn, player: str) -> dict:
    """The player died. The run is over, and it is not one of the five endings."""
    _ensure(conn)
    row = conn.execute("select start_time from runs where player=?", (player,)).fetchone()
    if row is None:
        conn.execute("insert into runs (player, start_time, choice) values (?,0,'died')", (player,))
    else:
        conn.execute("update runs set choice='died' where player=?", (player,))
    conn.commit()
    return {"ok": True}


def anchor(conn, player: str, game_time: float) -> None:
    """Pin the start of this player's count. The first real tick does this itself."""
    _ensure(conn)
    conn.execute("insert or ignore into runs (player, start_time, choice) values (?,?,null)", (player, game_time))
    conn.commit()


def report(conn, player: str, game_time: float) -> dict:
    _ensure(conn)
    row = conn.execute("select start_time, choice from runs where player=?", (player,)).fetchone()
    if row is None:
        anchor(conn, player, game_time)
        start, choice = game_time, None
    else:
        start, choice = row["start_time"], row["choice"]
    elapsed = max(0.0, game_time - start)
    out = {
        "phase": "ended" if choice == "died" or choice not in (None, "refused") else phase(elapsed),
        "day": clock_day(elapsed),
        "time": clock_time(game_time % 1),
        "cold": 0.0,
        "sustain": True,
        "winter": 0.0,
    }
    if choice == "died":
        return out
    if choice not in (None, "refused"):
        out["ending"] = choice
        return out
    ph = out["phase"]
    out["winter"] = round(min(1.0, elapsed / (FINAL_DAY - 1)), 3)  # the world's look: 0 on arrival, 1 on day 10
    if ph in ("closing", "frozen"):
        out["cold"] = cold_rate(elapsed)
        ending = leading_ending(conn, player)
        if ph == "closing" and ending:
            out["ending"] = ending
            if clock_day(elapsed) >= OFFER_DAY and not _refused_lately(conn, player, game_time):
                out["offer"] = True  # the village gathers; the player may stand with them or walk away
    if ph == "frozen":
        out["sustain"] = False
        out["cold"] = 20.0
    return out
