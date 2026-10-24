"""LLM clients. One fixed system prompt per recurring task; all per-call data goes in the user JSON."""
import json
import os
import re
import time
from dataclasses import dataclass

from openai import OpenAI

_CLAIMS = ('"claims": [{"event_id": int|null, "type": str, "how": "witnessed"|"told"}]')
_RULES = (
    "You voice one villager in a small village game. The user message is JSON with: npc (who you are), "
    "relationship.band (how you feel about the player: hostile, wary, neutral, friendly), memories (the only past "
    "events you know; how=witnessed means you saw it, how=told_by:<name> means it is a rumour you heard), facts "
    "(authoritative game facts; facts.world is how the game world works, share it when the player asks how to do something), and sometimes validator_feedback (mistakes in your previous attempt; fix them). "
    "Speak only from memories and facts; never invent past events. Treat told_by memories as rumours and say who "
    "told you. Never mention numbers, trust scores or game mechanics. Stay in character, 1-3 short sentences. "
    "List every past event you mention in claims with its event_id. "
)
SYSTEM_PROMPTS = {
    "npc_react": _RULES + "The user JSON also has event: something you just witnessed; event.what says exactly what "
    "happened. React out loud to THIS event only, in character, and write a one-sentence first-person memory of it. "
    "Reply with JSON only: "
    '{"shout": str, "memory": str, ' + _CLAIMS + "}",
    "intent_classify": "Classify a player's chat message to a villager in a game. The user message is JSON with "
    "npc and player_message. Reply with JSON only: "
    '{"intent": "threat"|"apology"|"insult"|"promise"|"question"|"trade"|"correction"|"other", '
    '"confidence": number 0-1, "promise": {"item": str, "count": int, "deadline_days": number}|null, '
    '"claim": {"type": str, "item": str|null}|null}. '
    "promise is set only when the player commits to bring something (item as a short lowercase noun, "
    "deadline_days default 1). claim is set only for correction: the event the player says did NOT happen "
    "(type one of gift, theft, vandalism, hit_npc, trade).",
    "npc_dialogue": _RULES + "facts.guide says what the player can do next (active and suggested quests, the "
    "festival) and where every villager and place is. When the player asks what to do, how something works, or where "
    "something is, guide them concretely and helpfully using facts.guide and facts.world, and set point_to to the "
    "matching key of facts.guide.places (a villager id or a place) so the game can show them the way; otherwise "
    "point_to is null. Reply to player_message; if it is null, speak first as facts.situation says, "
    "greeting the player in a way that reflects your memories and how you feel. facts may include new_promise (the player just promised "
    "something) or correction (confirmed=true means the player rightly corrected you; apologise for the mistake; "
    "confirmed=false means the player denies something that really happened). You may offer a small quest using "
    "only item names from items. Reply with JSON only: "
    '{"reply": str, ' + _CLAIMS + ', "quest_offer": {"item": str, "count": int, "reward": str}|null, '
    '"point_to": str|null}',
}


@dataclass
class LLMResult:
    data: dict | None
    raw: str
    request_id: str | None
    latency_ms: int
    tokens: int | None
    error: str | None


class MockLLM:
    """Deterministic offline stand-in. Behaves like a well-behaved model."""

    def complete(self, task: str, user: dict, thread_id: str) -> LLMResult:
        data = getattr(self, "_" + task)(user)
        return LLMResult(data, json.dumps(data), None, 0, None, None)

    def _intent_classify(self, user):
        msg = user.get("player_message", "").lower()
        out = {"intent": "question", "confidence": 0.5, "promise": None, "claim": None}
        if re.search(r"sorry|apolog", msg):
            out.update(intent="apology", confidence=0.9)
        elif re.search(r"never gave|didn't give|did not give", msg):
            m = re.search(r"(?:gave|give) you (?:a |an |any |the )?(\w+)", msg)
            out.update(intent="correction", confidence=0.9, claim={"type": "gift", "item": m and m.group(1)})
        elif re.search(r"i'll bring|i will bring|promise", msg):
            m = re.search(r"(\d+)\s+(\w+)", msg)
            out.update(intent="promise", confidence=0.9,
                       promise={"item": m.group(2) if m else "apple", "count": int(m.group(1)) if m else 1,
                                "deadline_days": 1})
        elif re.search(r"kill|hurt|burn", msg):
            out.update(intent="threat", confidence=0.8)
        return out

    def _npc_dialogue(self, user):
        mems = user.get("memories") or []
        if not mems:
            return {"reply": "Good day to you.", "claims": [], "quest_offer": None}
        m = mems[0]
        how = "told" if m["how"].startswith("told") else "witnessed"
        return {"reply": f"I remember this: {m['text']}", "quest_offer": None,
                "claims": [{"event_id": m["event_id"], "type": m["type"], "how": how}]}

    def _npc_react(self, user):
        ev = user.get("event", {})
        return {"shout": "Hey! I saw that!", "memory": f"I saw them: {ev.get('type')}",
                "claims": [{"event_id": ev.get("id"), "type": ev.get("type"), "how": "witnessed"}]}


class OpenAICompatLLM:
    """Any OpenAI-compatible endpoint: Mubit's proxy or a local server such as Ollama."""

    def __init__(self, base_url: str, api_key: str, model: str, send_metadata: bool, timeout: float = 10,
                 http_client=None):
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0,
                             http_client=http_client)
        self.model, self.send_metadata = model, send_metadata

    def complete(self, task: str, user: dict, thread_id: str) -> LLMResult:
        t0, raw, rid, tokens = time.monotonic(), "", None, None
        try:
            extra = {"metadata": {"thread_id": thread_id}} if self.send_metadata else {}
            resp = self.client.chat.completions.with_raw_response.create(
                model=self.model, response_format={"type": "json_object"}, **extra,
                messages=[{"role": "system", "content": SYSTEM_PROMPTS[task]},
                          {"role": "user", "content": json.dumps(user, sort_keys=True)}])
            rid = resp.headers.get("x-middleware-request-id")
            comp = resp.parse()
            raw = comp.choices[0].message.content or ""
            tokens = comp.usage.total_tokens if comp.usage else None
            data, err = json.loads(raw), None
            if not isinstance(data, dict):
                data, err = None, "not a JSON object"
        except Exception as e:  # network, timeout, bad JSON: caller falls back
            data, err = None, f"{type(e).__name__}: {e}"
        return LLMResult(data, raw, rid, int((time.monotonic() - t0) * 1000), tokens, err)


def make_llm(provider: str):
    model = os.getenv("LLM_MODEL", "qwen2.5:7b")
    if provider == "mock":
        return MockLLM()
    if provider == "local":
        return OpenAICompatLLM(os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1"), "local", model, False)
    if provider == "mubit":
        return OpenAICompatLLM(os.getenv("MUBIT_BASE_URL", "https://api.mubit.ai/openai/v1"),
                               os.environ["MUBIT_API_KEY"], model, True)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
