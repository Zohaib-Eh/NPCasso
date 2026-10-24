import json

import pytest

from backend import db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def conn(db_path):
    c = db.connect(db_path)
    yield c
    c.close()


class ScriptedLLM:
    """Returns the given outputs in order; None simulates an LLM error."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, task, user, thread_id):
        from backend.llm import LLMResult
        self.calls.append((task, user))
        data = self.responses.pop(0)
        return LLMResult(data, json.dumps(data) if data is not None else "", "mreq_test", 1, 1, None if data is not None else "boom")
