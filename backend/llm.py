"""LLM clients. One fixed system prompt per recurring task; all per-call data goes in the user JSON."""
import json
import os
import re
import time
from dataclasses import dataclass

from openai import OpenAI

from .story import POLES

_CLAIMS = ('"claims": [{"event_id": int|null, "type": str, "how": "witnessed"|"told"}]')
_POLES = "; ".join(f"{dim} -1 {neg}, +1 {pos}" for dim, (neg, pos) in POLES.items())
_SCORE = (
    "facts.season, when present, is the weather of ordinary life. facts.regard, when present, is how this player's "
    "conduct has been read; let it color your manner, and never quote it or mention a number. facts.lean, when "
    "present, is the pressure on the village; let it color what is at stake, and never announce an ending. "
    "If this moment shows who the player is, set evidence to one or more of these dimensions with a weight from -1 to 1 ("
    + _POLES + "). Otherwise evidence is []. Score only this moment. "
)
_RULES = (
    "You voice one villager in a small village game. The user message is JSON with: npc (who you are), "
    "relationship.band (how you feel about the player: hostile, wary, neutral, friendly), memories (the only past "
    "events you know; how=witnessed means you saw it, how=told_by:<name> means it is a rumour you heard, how=own "
    "means it is your own business), facts "
    "(authoritative game facts; facts.world is how the game world works, share it when the player asks how to do something), and sometimes validator_feedback (mistakes in your previous attempt; fix them). "
    "Speak only from memories and facts; never invent past events. Treat told_by memories as rumours and say who "
    "told you. Never mention numbers, trust scores or game mechanics. Stay in character, 1-3 short sentences. "
    "List every past event you mention in claims with its event_id. "
)
SYSTEM_PROMPTS = {
    "npc_react": _RULES + "The user JSON also has event: something you just witnessed; event.what says exactly what "
    "happened. React out loud to THIS event only, in character, and write a one-sentence first-person memory of it. "
    + _SCORE +
    "Reply with JSON only: "
    '{"shout": str, "memory": str, ' + _CLAIMS + ', "evidence": [{"dimension": str, "weight": number}]}',
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
    "only item names from items. A greeting, thanks, a direction, or a single memory stays ordinary, and choice is null. "
    "When memories already hold two real costs, or one secret while facts.lean is present, and the player has not yet "
    "taken a side, do not stop after reporting them and do not decide for the player. The last sentence asks which "
    "side they will take, and choice.options lists those two sides, drawn only from the memories and facts.season. "
    "If player_message already takes one of those sides, accept it, set choice to null, and score that side. Do not ask again. "
    "facts.regard decides which cost bites. facts.lean decides what is coming due, and its words are never spoken. "
    "Never name an ending, a day, a score, or an event id. "
    "facts.may_open, when true, lets you bring up something new: a trouble between you and one or two named "
    "villagers from facts.guide.places, never about the player and never an act the player did. It always puts two "
    "people's needs against each other, or hides something one of them would not want known. A private worry about "
    "your own stock is not enough. While facts.season is ordinary days, keep it small and a little strange: an odd "
    "sight, a quiet secret, a favour that does not add up. When the cold is in food, firewood or who is provided "
    "for, it can be a shortage two households both need. Most visits do not need one; open one only when it fits "
    "the moment. Say it in the reply as your own concern, in one or two sentences, and set situation to its text "
    "and the villager ids it involves (never your own id, facts.you_are, and never an id in facts.busy, who "
    "already have a trouble of their own); otherwise situation is null and you never "
    "invent such things. When facts.open_situation.already_told is true you have said it to this player already: "
    "greet them as usual and bring it up only if they do. facts.open_situation is something unresolved that you are part of. When player_message takes "
    "a side on it, accept it, and set consequence to what it costs one villager (npc_id, a sentence of text, and "
    "stance helped or hurt for how this leaves that villager toward the player, and size small, medium or large "
    "for how much it matters to them); otherwise consequence is null. "
    + _SCORE + "Reply with JSON only: "
    '{"reply": str, ' + _CLAIMS + ', "quest_offer": {"item": str, "count": int, "reward": str}|null, '
    '"point_to": str|null, "choice": {"options": [str, str]}|null, '
    '"situation": {"text": str, "involves": [str]}|null, '
    '"consequence": {"npc_id": str, "text": str, "stance": "helped"|"hurt", "size": "small"|"medium"|"large"}|null, '
    '"evidence": [{"dimension": str, "weight": number}]}',
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
            return {"reply": "Good day to you.", "claims": [], "quest_offer": None, "choice": None, "evidence": []}
        m = mems[0]
        how = "told" if m["how"].startswith("told") else "witnessed"
        return {"reply": f"I remember this: {m['text']}", "quest_offer": None, "choice": None, "evidence": [],
                "claims": [{"event_id": m["event_id"], "type": m["type"], "how": how}]}

    def _npc_react(self, user):
        ev = user.get("event", {})
        return {"shout": "Hey! I saw that!", "memory": f"I saw them: {ev.get('type')}",
                "claims": [{"event_id": ev.get("id"), "type": ev.get("type"), "how": "witnessed"}],
                "evidence": [{"dimension": "justice", "weight": -0.5}]}


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


class OpenAICompatLLM:
    """Any OpenAI-compatible endpoint: Anthropic, Mubit, or a local server such as Ollama."""

    def __init__(self, base_url: str, api_key: str, model: str, send_metadata: bool, timeout: float = 10,
                 http_client=None, force_json=True):
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0,
                             http_client=http_client)
        self.model, self.send_metadata, self.force_json = model, send_metadata, force_json

    def complete(self, task: str, user: dict, thread_id: str) -> LLMResult:
        t0, raw, rid, tokens = time.monotonic(), "", None, None
        try:
            extra = {"metadata": {"thread_id": thread_id}} if self.send_metadata else {}
            if self.force_json:
                extra["response_format"] = {"type": "json_object"}
            resp = self.client.chat.completions.with_raw_response.create(
                model=self.model, **extra,
                messages=[{"role": "system", "content": SYSTEM_PROMPTS[task]},
                          {"role": "user", "content": json.dumps(user, sort_keys=True)}])
            rid = resp.headers.get("x-middleware-request-id")
            comp = resp.parse()
            raw = comp.choices[0].message.content or ""
            tokens = comp.usage.total_tokens if comp.usage else None
            data, err = json.loads(_strip_fence(raw)), None
            if not isinstance(data, dict):
                data, err = None, "not a JSON object"
        except Exception as e:  # network, timeout, bad JSON: caller falls back
            data, err = None, f"{type(e).__name__}: {e}"
        return LLMResult(data, raw, rid, int((time.monotonic() - t0) * 1000), tokens, err)


def make_llm(provider: str):
    if provider == "mock":
        return MockLLM()
    if provider == "local":
        return OpenAICompatLLM(os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1"), "local",
                               os.getenv("LLM_MODEL", "qwen2.5:7b"), False)
    if provider == "mubit":
        # Starter credit serves gpt-6-luna and refuses store. OpenAI refuses metadata
        # unless store is on, so a thread id cannot ride along. Tasks still group by
        # the fixed prompt, the JSON format and this model.
        return OpenAICompatLLM(os.getenv("MUBIT_BASE_URL", "https://api.mubit.ai/openai/v1"),
                               os.environ["MUBIT_API_KEY"], os.getenv("MUBIT_MODEL", "gpt-6-luna"),
                               False, timeout=30)
    if provider == "claude":
        return OpenAICompatLLM(os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/"),
                               os.environ["ANTHROPIC_API_KEY"], os.getenv("LLM_MODEL", "claude-haiku-4-5"),
                               False, timeout=30, force_json=False)
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
