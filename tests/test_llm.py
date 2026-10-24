import json

import httpx
import pytest

from backend.llm import SYSTEM_PROMPTS, MockLLM, OpenAICompatLLM, make_llm


def classify(msg):
    return MockLLM().complete("intent_classify", {"player_message": msg}, "t").data


def test_mock_classify():
    assert classify("sorry about that")["intent"] == "apology"
    p = classify("I'll bring you 2 iron tomorrow")
    assert p["intent"] == "promise" and p["promise"] == {"item": "iron", "count": 2, "deadline_days": 1}
    c = classify("I never gave you bread")
    assert c["intent"] == "correction" and c["claim"] == {"type": "gift", "item": "bread"}
    assert classify("I will burn your stall")["intent"] == "threat"
    assert classify("nice weather")["intent"] == "question"


def test_mock_dialogue_claims_memory():
    ctx = {"memories": [{"event_id": 7, "type": "theft", "text": "Saw them take an apple.", "how": "witnessed",
                         "reliability": 1.0}], "player_message": "hi"}
    d = MockLLM().complete("npc_dialogue", ctx, "t").data
    assert d["claims"] == [{"event_id": 7, "type": "theft", "how": "witnessed"}]
    assert "Saw them take an apple." in d["reply"]


def test_mock_dialogue_rumour_is_told():
    ctx = {"memories": [{"event_id": 3, "type": "theft", "text": "x", "how": "told_by:elise", "reliability": 0.5}]}
    assert MockLLM().complete("npc_dialogue", ctx, "t").data["claims"][0]["how"] == "told"


def test_mock_dialogue_no_memories():
    d = MockLLM().complete("npc_dialogue", {"memories": []}, "t").data
    assert d["claims"] == [] and d["reply"]


def test_mock_react():
    d = MockLLM().complete("npc_react", {"event": {"id": 4, "type": "theft"}}, "t").data
    assert d["shout"] and d["claims"] == [{"event_id": 4, "type": "theft", "how": "witnessed"}]


def fake_client(content, seen):
    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, headers={"x-middleware-request-id": "mreq_" + "a" * 32}, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compat_sends_metadata_and_reads_request_id():
    seen = {}
    llm = OpenAICompatLLM("http://x/v1", "k", "m", send_metadata=True,
                          http_client=fake_client('{"reply": "hi", "claims": []}', seen))
    r = llm.complete("npc_dialogue", {"player_message": "hi"}, "thread-1")
    assert r.request_id.startswith("mreq_") and r.data["reply"] == "hi" and r.tokens == 2 and r.error is None
    assert seen["body"]["metadata"] == {"thread_id": "thread-1"}
    assert seen["body"]["messages"][0]["content"] == SYSTEM_PROMPTS["npc_dialogue"]
    assert json.loads(seen["body"]["messages"][1]["content"]) == {"player_message": "hi"}


def test_openai_compat_local_omits_metadata():
    seen = {}
    OpenAICompatLLM("http://x/v1", "k", "m", send_metadata=False,
                    http_client=fake_client("{}", seen)).complete("npc_dialogue", {}, "t")
    assert "metadata" not in seen["body"]


def test_openai_compat_can_omit_json_object():
    seen = {}
    OpenAICompatLLM("http://x/v1", "k", "m", send_metadata=False, force_json=False,
                    http_client=fake_client("{}", seen)).complete("npc_dialogue", {}, "t")
    assert "response_format" not in seen["body"]


def test_openai_compat_bad_json_is_error():
    r = OpenAICompatLLM("http://x/v1", "k", "m", send_metadata=False,
                        http_client=fake_client("not json", {})).complete("npc_dialogue", {}, "t")
    assert r.data is None and r.error


def test_openai_compat_strips_markdown_fence():
    r = OpenAICompatLLM("http://x/v1", "k", "m", send_metadata=False,
                        http_client=fake_client('```json\n{"reply": "hi"}\n```', {})).complete("npc_dialogue", {}, "t")
    assert r.data == {"reply": "hi"} and r.error is None


def test_make_llm():
    assert isinstance(make_llm("mock"), MockLLM)
    with pytest.raises(ValueError):
        make_llm("nope")


def test_make_llm_mubit(monkeypatch):
    monkeypatch.setenv("MUBIT_API_KEY", "mbt_test")
    monkeypatch.delenv("MUBIT_MODEL", raising=False)
    llm = make_llm("mubit")
    assert isinstance(llm, OpenAICompatLLM)
    assert llm.model == "gpt-6-luna" and llm.send_metadata is False and llm.force_json is True
    assert str(llm.client.base_url).rstrip("/").endswith("api.mubit.ai/openai/v1")


def test_make_llm_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    llm = make_llm("claude")
    assert isinstance(llm, OpenAICompatLLM)
    assert llm.model == "claude-haiku-4-5" and llm.send_metadata is False and llm.force_json is False
