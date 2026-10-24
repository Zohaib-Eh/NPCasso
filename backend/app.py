"""FastAPI routes. Thin: validation and wiring only; logic lives in game.py."""
import logging
import os
from contextlib import closing

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import db, game, progress, rules
from .llm import make_llm

log = logging.getLogger("npcasso")


class EventIn(BaseModel):
    world: str
    player: str
    type: str
    target: str | None = None
    details: dict = Field(default_factory=dict)
    witnesses: list[str] = Field(default_factory=list)
    game_time: float

    # Lua's JSON writer turns an empty table into {} or null, never [].
    @field_validator("witnesses", mode="before")
    @classmethod
    def lua_empty_list(cls, v):
        return v if isinstance(v, list) else []

    @field_validator("details", mode="before")
    @classmethod
    def lua_empty_dict(cls, v):
        return v if isinstance(v, dict) else {}


class ReactIn(BaseModel):
    world: str
    player: str
    event_id: int
    npc_ids: list[str] = Field(default_factory=list)

    @field_validator("npc_ids", mode="before")
    @classmethod
    def lua_empty_list(cls, v):
        return v if isinstance(v, list) else []


class AcceptIn(BaseModel):
    world: str
    player: str
    quest_id: str


class HandinIn(BaseModel):
    world: str
    player: str
    npc_id: str
    items: dict[str, int] = Field(default_factory=dict)
    game_time: float

    @field_validator("items", mode="before")
    @classmethod
    def lua_empty_dict(cls, v):
        return v if isinstance(v, dict) else {}


class FestivalIn(BaseModel):
    world: str
    player: str
    game_time: float


class GossipIn(BaseModel):
    world: str
    player: str
    teller: str
    listener: str
    game_time: float
    audible: bool = False  # a player is close enough to hear: voice it through the LLM


class SpeechIn(BaseModel):
    world: str
    player: str
    npc_id: str


class GreetIn(BaseModel):
    world: str
    player: str
    npc_id: str
    thread_id: str
    game_time: float


class TalkIn(BaseModel):
    world: str
    player: str
    npc_id: str
    message: str = Field(min_length=1, max_length=500)
    thread_id: str
    game_time: float

    @field_validator("message")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("message is blank")
        return v.strip()


class TradeIn(BaseModel):
    world: str
    player: str
    npc_id: str
    work_block_present: bool = True


class TickIn(BaseModel):
    world: str
    player: str
    game_time: float


def create_app(db_path: str, llm) -> FastAPI:
    app = FastAPI(title="NPCasso")
    db.connect(db_path).close()  # create schema + seed once

    def run(fn, *args):
        # A connection per request (sqlite WAL): a slow LLM call in one request never stalls another.
        with closing(db.open_db(db_path)) as conn:
            try:
                return fn(conn, *args)
            except ValueError as e:
                raise HTTPException(422, str(e))

    @app.get("/health")
    def health():
        return {"ok": True, "provider": type(llm).__name__}

    @app.get("/npcs")
    def npcs():
        return {k: {"name": v["name"], "role": v["role"], "skin": v.get("skin"),
                    "work_block": v.get("work_block")} for k, v in game.CONFIG["npcs"].items()}

    @app.post("/event")
    def event(ev: EventIn):
        out = run(game.record_event, llm, ev.model_dump())
        log.info("event %s -> %s", ev.type, out)
        return out

    @app.post("/talk")
    def talk(t: TalkIn):
        out = run(game.talk, llm, t.world, t.player, t.npc_id, t.message, t.thread_id, t.game_time)
        log.info("talk %s: %r -> %r", t.npc_id, t.message, out["reply"])
        return out

    @app.post("/react")
    def react(r: ReactIn):
        out = run(game.react, llm, r.world, r.player, r.event_id, r.npc_ids)
        log.info("react %s -> %s", r.event_id, out)
        return out

    @app.get("/festival")
    def festival_status(world: str, player: str):
        return run(lambda c: game.festival_status(c, f"{world}:{player}"))

    @app.post("/festival")
    def festival(f: FestivalIn):
        out = run(game.hold_festival, llm, f.world, f.player, f.game_time)
        log.info("festival -> %s", out["ending"])
        return out

    @app.post("/festival/speech")
    def festival_speech(s: SpeechIn):
        return run(game.festival_speech, llm, s.world, s.player, s.npc_id)

    @app.post("/gossip")
    def gossip(g: GossipIn):
        out = run(game.gossip, g.world, g.player, g.teller, g.listener, g.game_time, None, llm, g.audible)
        if out["shared"]:
            log.info("gossip %s -> %s: %s", g.teller, g.listener, out["line"])
        return out

    @app.get("/moods")
    def moods(world: str, player: str, game_time: float):
        return run(game.moods, world, player, game_time)

    @app.post("/greet")
    def greet(g: GreetIn):
        out = run(game.greet, llm, g.world, g.player, g.npc_id, g.thread_id, g.game_time)
        log.info("greet %s -> %r", g.npc_id, out["reply"])
        return out

    @app.post("/trade")
    def trade(t: TradeIn):
        return run(game.trade_quote, t.world, t.player, t.npc_id, t.work_block_present)

    @app.post("/tick")
    def tick(t: TickIn):
        return run(game.tick, llm, t.world, t.player, t.game_time)

    @app.get("/npc/{npc_id}")
    def npc_state(npc_id: str, world: str, player: str):
        def state(c):
            p = f"{world}:{player}"
            trust = db.get_trust(c, npc_id, p)
            return {"npc": game.npc_cfg(npc_id), "trust": trust, "band": rules.band(trust),
                    "memories": db.top_memories(c, npc_id, p, limit=20), "open_promises": db.open_promises(c, npc_id, p)}
        return run(state)

    @app.get("/player")
    def player(world: str, player: str):
        return run(lambda c: {**progress.player_state(c, f"{world}:{player}"),
                              "quests": game.journal(c, f"{world}:{player}")})

    @app.get("/quests")
    def quests(world: str, player: str):
        p = f"{world}:{player}"
        return run(lambda c: {"available": game.available_quests(c, p), "journal": game.journal(c, p)})

    @app.post("/quest/accept")
    def quest_accept(a: AcceptIn):
        return run(game.accept_quest, f"{a.world}:{a.player}", a.quest_id)

    @app.post("/quest/handin")
    def quest_handin(h: HandinIn):
        return run(game.handin, h.world, h.player, h.npc_id, h.items, h.game_time)

    @app.get("/interactions")
    def interactions(npc_id: str | None = None, limit: int = 50):
        return run(lambda c: db.list_interactions(c, npc_id, limit))

    return app


def main() -> FastAPI:
    """uvicorn backend.app:main --factory"""
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    return create_app(os.getenv("NPCASSO_DB", "npcasso.db"), make_llm(os.getenv("LLM_PROVIDER", "mock")))
