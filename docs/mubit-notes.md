# Mubit integration notes

Source: docs.mubit.ai (including `llms-full.txt`), read 2026-10-23. Only documented behaviour is used.

## How NPCasso uses Mubit

- **Proxy only.** `backend/llm.py` `OpenAICompatLLM` uses the official `openai` client with `base_url=https://api.mubit.ai/openai/v1` and `Authorization: Bearer mbt_...`. There's no Mubit SDK. Model ids are unchanged.
- **Three tasks** with fixed system prompts (`SYSTEM_PROMPTS`) and `response_format={"type": "json_object"}`. All per-call data (persona, memories, band, facts, player message) goes in the user message as sorted JSON, so new NPCs and new events land in the same task.
- **Model:** `MUBIT_MODEL`, default `gpt-6-luna`. The starter credit refuses other ids on this route (`400 starter_credit_model` lists the ones it serves).
- **Sessions:** the starter credit refuses `store`, and OpenAI refuses `metadata` unless `store` is on. Calls therefore omit `metadata.thread_id`. Mubit still groups a task by the fixed prompt, the JSON format and the model, and gives a call with no thread id its own session from that prompt plus its user message.
- **Request ids:** `x-middleware-request-id` (`mreq_...`) is stored in `interactions.mubit_request_id`, next to the validator result, retry flag and outcome (`corrected`).

## Verified facts (from docs)

| Area | Fact |
|---|---|
| Task grouping | Instructions + tools + tool choice + output format + model. Numbers, dates and ids don't split a task; other varying words do. |
| Sessions | `metadata.thread_id`, then `session_id`, then `conversation_id`. Used to hold out test cases. |
| Training | Automatic. First at 25 kept examples. Statuses: Collecting, Reviewing, Training, Testing. |
| Evaluation | Adapter vs the provider model's own answers: Passed, Below target (match %), Malformed tool calls, Prompt only, Not tested. |
| Recording control | `x-middleware-record: full\|metadata\|off`, `x-middleware-store: false` (reduce only). |
| Feedback | Console "Rate this reply" Good/Bad only. **No API.** |
| Using adapters | Console **Try models** only. **No adapter model id for app calls.** |
| Limits | Daily training limit and Try-models cap (reset 00:00 UTC), a pause between trainings, 3 adapter starts per org per UTC day. |

## What this means

- The adapter learns to imitate the frontier model on a task. It doesn't judge truth. NPCasso supplies the truth check (validator plus eval harness).
- Failed first drafts are stored, not suppressed, so they can be rated Bad in the console. Their ids are in `/interactions` where `validator_result.ok == false`.
- The game always calls the frontier model through Mubit. The adapter comparison happens in Try models.

## Open questions for Mubit office hours

1. Do Bad-rated calls get excluded from training, or weighted?
2. Is there a feedback API, or a route to call a passing adapter from code?
3. How is match % computed for free text vs JSON?
4. Which starter-credit models are adapter-eligible?

## Observed

- 2026-10-24: one `intent_classify`-shaped call to `gpt-6-luna` through `https://api.mubit.ai/openai/v1` returned JSON and an `mreq_` id. The same call with `metadata.thread_id` returned OpenAI's `metadata` / `store` 400. `store: true` returned Mubit's `starter_credit_option`. `qwen2.5:7b` and `claude-haiku-4-5` are not in the starter-credit list for this route.

- Local dev baseline (qwen2.5:7b via Ollama, not Mubit), held-out 2026-10-23: 19/20 runs passed, first-try-valid 0.70, average 6.3 s per turn. The one failure was a harness counting bug, since fixed.
