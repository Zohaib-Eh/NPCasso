"""Player progression: XP, levels, titles. Deterministic; the LLM never touches these."""
HARVEST_XP_PER_DAY = 20


def _total_for(level: int) -> int:
    """Total XP needed to reach `level` (Lv1 = 0, Lv2 = 50, Lv3 = 150, Lv4 = 300, ...)."""
    return 50 * (level - 1) * level // 2


def level_for(xp: int) -> int:
    level = 1
    while xp >= _total_for(level + 1):
        level += 1
    return level


def title(level: int) -> str:
    return "newcomer" if level <= 1 else "villager" if level <= 3 else "friend of the village"


def _row(conn, player):
    conn.execute("insert or ignore into players (player, xp, harvest_day, harvest_count) values (?, 0, -1, 0)",
                 (player,))
    return conn.execute("select * from players where player=?", (player,)).fetchone()


def add_xp(conn, player, amount: int, reason: str) -> dict:
    before = level_for(_row(conn, player)["xp"])
    conn.execute("update players set xp = xp + ? where player=?", (amount, player))
    conn.commit()
    after = level_for(_row(conn, player)["xp"])
    return {"xp_gained": amount, "level_up": after if after > before else None}


def harvest_xp(conn, player, game_time: float) -> dict:
    row, day = _row(conn, player), int(game_time)
    count = row["harvest_count"] if row["harvest_day"] == day else 0
    if count >= HARVEST_XP_PER_DAY:
        return {"xp_gained": 0, "level_up": None}
    conn.execute("update players set harvest_day=?, harvest_count=? where player=?", (day, count + 1, player))
    return add_xp(conn, player, 1, "harvest")


def player_state(conn, player) -> dict:
    xp = _row(conn, player)["xp"]
    level = level_for(xp)
    return {"xp": xp, "level": level, "title": title(level), "level_xp": xp - _total_for(level),
            "next_level_xp": _total_for(level + 1) - _total_for(level)}


def merge(out: dict, res: dict) -> dict:
    """Fold an add_xp result into an API response."""
    out["xp_gained"] = out.get("xp_gained", 0) + res["xp_gained"]
    out["level_up"] = res["level_up"] or out.get("level_up")
    return out
