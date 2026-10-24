"""SQLite state: schema, seeding from npcs.json, and small query helpers."""
import json
import sqlite3
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("npcs.json")

SCHEMA = """
create table if not exists npcs (id text primary key, name text, role text, config text);
create table if not exists relationships (
  npc_id text, player text, trust integer, flags text default '{}', primary key (npc_id, player));
create table if not exists events (
  id integer primary key, ts real, game_time real, player text, actor text, target text, type text,
  details text, witnesses text, verified integer, source text, confidence real);
create table if not exists memories (
  id integer primary key, ts real, npc_id text, player text, event_id integer, type text, text text,
  how text, reliability real, severity integer, gossiped integer default 0, learned_at real);
create table if not exists situations (
  id integer primary key, player text, opener text, involves text, text text, opened_at real,
  status text default 'open', event_id integer);
create table if not exists promises (
  id integer primary key, kind text, npc_id text, player text, item text, count integer,
  deadline real, reward text, status text default 'open');
create table if not exists players (
  player text primary key, xp integer default 0, harvest_day integer default -1, harvest_count integer default 0);
create table if not exists interactions (
  id integer primary key, ts real, task text, npc_id text, player text, thread_id text, request text,
  reply text, mubit_request_id text, latency_ms integer, tokens integer, validator_result text,
  retried integer, outcome text, prev_id integer);
"""

JSON_COLS = {"details", "witnesses", "flags", "request", "validator_result", "config"}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def open_db(path: str) -> sqlite3.Connection:
    """A plain connection. One per request, so slow LLM calls never block other requests."""
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def connect(path: str) -> sqlite3.Connection:
    """Open, create the schema and seed NPCs from config. Run once at startup (and in tests)."""
    conn = open_db(path)
    conn.execute("pragma journal_mode=wal")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    for npc_id, cfg in load_config()["npcs"].items():
        conn.execute("insert or replace into npcs values (?,?,?,?)",
                     (npc_id, cfg["name"], cfg["role"], json.dumps(cfg)))
    conn.commit()
    return conn


# Columns added after v1. "create table if not exists" won't add them to an existing save, so add them here.
LATER_COLUMNS = {"memories": {"learned_at": "real"},
                 "situations": {"told": "text", "motive": "text", "hidden_from": "text"},
                 "promises": {"title": "text", "xp": "integer", "trust": "integer", "quest_id": "text",
                              "target": "text", "total": "integer"}}


def _add_missing_columns(conn):
    for table, cols in LATER_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"pragma table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"alter table {table} add column {col} {typ}")
    conn.commit()


def _row(r) -> dict:
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def _insert(conn, table: str, row: dict) -> int:
    row = {k: json.dumps(v) if k in JSON_COLS else v for k, v in row.items()}
    cur = conn.execute(f"insert into {table} ({','.join(row)}) values ({','.join('?' * len(row))})",
                       list(row.values()))
    conn.commit()
    return cur.lastrowid


def add_event(conn, ev: dict) -> int:
    return _insert(conn, "events", {"ts": time.time(), **ev})


def _ensure_rel(conn, npc_id, player):
    conn.execute("insert or ignore into relationships (npc_id, player, trust) values (?,?,?)",
                 (npc_id, player, load_config()["start_trust"]))


def get_trust(conn, npc_id, player) -> int:
    r = conn.execute("select trust from relationships where npc_id=? and player=?", (npc_id, player)).fetchone()
    return r["trust"] if r else load_config()["start_trust"]


def add_trust(conn, npc_id, player, delta) -> int:
    _ensure_rel(conn, npc_id, player)
    conn.execute("update relationships set trust = max(-100, min(100, trust + ?)) where npc_id=? and player=?",
                 (delta, npc_id, player))  # atomic: concurrent requests can't lose an update
    conn.commit()
    return get_trust(conn, npc_id, player)


def get_flag(conn, npc_id, player, key):
    r = conn.execute("select flags from relationships where npc_id=? and player=?", (npc_id, player)).fetchone()
    return json.loads(r["flags"]).get(key) if r else None


def set_flag(conn, npc_id, player, key, value):
    _ensure_rel(conn, npc_id, player)
    r = conn.execute("select flags from relationships where npc_id=? and player=?", (npc_id, player)).fetchone()
    flags = {**json.loads(r["flags"]), key: value}
    conn.execute("update relationships set flags=? where npc_id=? and player=?", (json.dumps(flags), npc_id, player))
    conn.commit()


def add_memory(conn, npc_id, player, event_id, type, text, how, reliability, severity, learned_at=None) -> int:
    return _insert(conn, "memories", {"ts": time.time(), "npc_id": npc_id, "player": player, "event_id": event_id,
                                      "type": type, "text": text, "how": how, "reliability": reliability,
                                      "severity": severity, "learned_at": learned_at})


def top_memories(conn, npc_id, player, limit=5) -> list[dict]:
    # ponytail: severity+recency ranking, no embeddings; add semantic retrieval if memories grow past ~100/NPC
    rows = conn.execute("select event_id, type, text, how, reliability, learned_at from memories where npc_id=? and player=? "
                        "and type != 'walk_away' order by severity desc, ts desc, id desc limit ?",
                        (npc_id, player, limit))
    return [dict(r) for r in rows]


def recent_turns(conn, npc_id, player, limit=6) -> list[dict]:
    """The last lines of this one conversation, oldest first. Scenes and event shouts are not conversation."""
    rows = conn.execute(
        "select request, reply from interactions where npc_id=? and player=? and task='npc_dialogue' "
        "and ifnull(retried,0)=0 and thread_id not like '%:scene:%' and validator_result like '%\"ok\": true%' "
        "order by id desc limit ?", (npc_id, player, limit)).fetchall()
    turns = []
    for r in reversed(rows):
        try:
            said = json.loads(r["request"]).get("player_message")
            reply = json.loads(r["reply"]).get("reply")
        except (TypeError, ValueError, AttributeError):
            continue
        if said:
            turns.append({"who": "you", "text": said})
        if reply:
            turns.append({"who": "them", "text": reply})
    return turns[-limit:]


def add_interaction(conn, row: dict) -> int:
    return _insert(conn, "interactions", {"ts": time.time(), **row})


def list_interactions(conn, npc_id=None, limit=50) -> list[dict]:
    q, args = "select * from interactions", []
    if npc_id:
        q, args = q + " where npc_id=?", [npc_id]
    return [_row(r) for r in conn.execute(q + " order by id desc limit ?", [*args, limit])]


def add_promise(conn, kind, npc_id, player, item, count, deadline, reward=None, **extra) -> int:
    """extra: title, xp, trust, quest_id, target, total (quest fields)."""
    return _insert(conn, "promises", {"kind": kind, "npc_id": npc_id, "player": player, "item": item,
                                      "count": count, "deadline": deadline, "reward": reward, **extra})


def open_promises(conn, npc_id=None, player=None, kind=None) -> list[dict]:
    q, args = "select * from promises where status='open'", []
    for col, val in (("npc_id", npc_id), ("player", player), ("kind", kind)):
        if val is not None:
            q += f" and {col}=?"
            args.append(val)
    return [dict(r) for r in conn.execute(q + " order by id", args)]


def update_promise(conn, id, **fields):
    conn.execute(f"update promises set {','.join(f'{k}=?' for k in fields)} where id=?", [*fields.values(), id])
    conn.commit()
