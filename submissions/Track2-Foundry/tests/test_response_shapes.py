"""Regression tests: llama-server response-shape drift.

Pinned llama.cpp (b9766) returns message.content as a plain string.
Builds from master can return the OpenAI-style list of typed parts, or
null. Both shapes must yield identical downstream text, and the JSON
parser must return an error tuple — never raise — on non-string input.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundry.task import _balanced_json
from foundry.teacher import TeacherClient, content_to_text

PAYLOAD = '{"ticket": "nobody can log in", "category": "outage", "priority": "P1"}'

# --- fixtures: the two real response bodies -----------------------------

RESPONSE_B9766 = {  # pinned build: content is a string
    "choices": [{"message": {"role": "assistant", "content": PAYLOAD}}]
}

RESPONSE_MASTER_PARTS = {  # master build: content is a list of typed parts
    "choices": [{"message": {"role": "assistant",
                             "content": [{"type": "text", "text": PAYLOAD}]}}]
}


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, body):
        self._body = body

    def post(self, *a, **k):
        return _FakeResponse(self._body)


def _client_with(body):
    client = TeacherClient("http://test/v1")
    client.session = _FakeSession(body)
    return client


# --- content normalization ----------------------------------------------

def test_content_string_passthrough():
    assert content_to_text(PAYLOAD) == PAYLOAD


def test_content_parts_list():
    assert content_to_text([{"type": "text", "text": PAYLOAD}]) == PAYLOAD


def test_content_multiple_parts_join():
    assert content_to_text([{"type": "text", "text": "{\"a\":"},
                            {"type": "text", "text": " 1}"}]) == '{"a": 1}'


def test_content_none_is_empty_string():
    assert content_to_text(None) == ""


# --- end to end through the client, both shapes -------------------------

def test_chat_pinned_shape():
    assert _client_with(RESPONSE_B9766).chat([]) == PAYLOAD


def test_chat_master_parts_shape():
    assert _client_with(RESPONSE_MASTER_PARTS).chat([]) == PAYLOAD


def test_chat_full_normalizes_content():
    msg = _client_with(RESPONSE_MASTER_PARTS).chat_full([])
    assert msg["content"] == PAYLOAD


# --- parser never raises on bad shapes ----------------------------------

def test_balanced_json_accepts_string():
    obj, reason = _balanced_json(PAYLOAD)
    assert reason is None and obj["category"] == "outage"


def test_balanced_json_rejects_list_without_raising():
    obj, reason = _balanced_json([{"type": "text", "text": PAYLOAD}])
    assert obj is None and reason.startswith("non_string_response")


def test_balanced_json_rejects_none_without_raising():
    obj, reason = _balanced_json(None)
    assert obj is None and reason.startswith("non_string_response")


def test_balanced_json_array_string_takes_first_object():
    # A string containing a top-level JSON array: current semantics grab
    # the first balanced object — pin that behavior.
    arr = json.dumps([json.loads(PAYLOAD), {"ticket": "x"}])
    obj, reason = _balanced_json(arr)
    assert reason is None and obj["priority"] == "P1"
