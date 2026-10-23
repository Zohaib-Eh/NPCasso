"""FastAPI routes. Thin: validation and wiring only; logic lives in game.py."""
import logging
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db, game, rules
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


def create_app(db_path: str, llm) -> FastAPI:
    app = FastAPI(title="NPCasso")
    conn = db.connect(db_path)
    lock = threading.Lock()  # ponytail: one global lock over one sqlite conn; fine for a single local player

    def run(fn, *args):
        with lock:
            try:
                return fn(conn, *args)
            except ValueError as e:
                raise HTTPException(422, str(e))

    @app.get("/health")
    def health():
        return {"ok": True, "provider": type(llm).__name__}

    @app.get("/npcs")
    def npcs():
        return {k: {"name": v["name"], "role": v["role"]} for k, v in game.CONFIG["npcs"].items()}

    @app.post("/event")
    def event(ev: EventIn):
        out = run(game.record_event, llm, ev.model_dump())
        log.info("event %s -> %s", ev.type, out)
        return out

    @app.get("/npc/{npc_id}")
    def npc_state(npc_id: str, world: str, player: str):
        def state(c):
            p = f"{world}:{player}"
            trust = db.get_trust(c, npc_id, p)
            return {"npc": game.npc_cfg(npc_id), "trust": trust, "band": rules.band(trust),
                    "memories": db.top_memories(c, npc_id, p, limit=20), "open_promises": db.open_promises(c, npc_id, p)}
        return run(state)

    @app.get("/interactions")
    def interactions(npc_id: str | None = None, limit: int = 50):
        return run(lambda c: db.list_interactions(c, npc_id, limit))

    return app


def main() -> FastAPI:
    """uvicorn backend.app:main --factory"""
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    return create_app(os.getenv("NPCASSO_DB", "npcasso.db"), make_llm(os.getenv("LLM_PROVIDER", "mock")))
