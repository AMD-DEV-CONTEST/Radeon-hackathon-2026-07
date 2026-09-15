"""Tests for the backend agentic chat (agentic.py + /agent/* endpoints).

Everything runs against the MockAgentLLMClient — no network, no sample media,
no real LLM.  The DB is redirected to a per-test tmp file (same pattern as
test_demo.py).  Run with:

    pytest -q test_agentic.py
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agentic
import ai_clients
import main
from ai_clients import AgentLLMResponse, MockAgentLLMClient
from test_demo import _insert_test_video

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_config_singletons():
    """Config is a module-level singleton; reset it before/after every test."""
    ai_clients._AI_CONFIG = None
    ai_clients._AGENT_CONFIG = None
    yield
    ai_clients._AI_CONFIG = None
    ai_clients._AGENT_CONFIG = None


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "videos.db"
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setenv("MOCK_MODE", "true")   # safety net: never hit a real agent LLM
    main.init_db()
    return db_path


def _runtime(db_path, responder, max_turns=8):
    """Build an AgentRuntime wired to the real tools but a scripted LLM."""
    store = agentic.AgentSessionStore(db_path)
    memory = agentic.AgentMemory(db_path)
    feedback = agentic.AgentFeedback(db_path)
    return agentic.AgentRuntime(
        llm_client=MockAgentLLMClient(responder=responder),
        tool_schemas=main._AGENT_TOOL_SCHEMAS,
        tool_impls=main._build_agent_tool_impls(memory, feedback),
        store=store,
        memory=memory,
        max_turns=max_turns,
    )


# --------------------------------------------------------------------------- #
# JSON ReAct protocol parsing
# --------------------------------------------------------------------------- #

def test_parse_agent_json_reply():
    r = ai_clients.parse_agent_json('{"action": "reply", "content": "hi"}')
    assert r.kind == "reply" and r.content == "hi"


def test_parse_agent_json_code_fence():
    r = ai_clients.parse_agent_json('```json\n{"action":"reply","content":"hi"}\n```')
    assert r.kind == "reply" and r.content == "hi"


def test_parse_agent_json_tool_with_prose():
    r = ai_clients.parse_agent_json(
        'I will search. {"action":"tool","tool":"search_transcriptions",'
        '"arguments":{"q":"cat"}}'
    )
    assert r.kind == "tool_call"
    assert r.tool == "search_transcriptions"
    assert r.arguments == {"q": "cat"}


def test_parse_agent_json_invalid():
    # Plain natural-language text -> a plain conversational reply (fallback),
    # NOT an error.
    r = ai_clients.parse_agent_json("I'm not sure, let me think about it.")
    assert r.kind == "reply"
    assert r.plain is True
    assert r.content == "I'm not sure, let me think about it."


def test_parse_agent_json_unknown_action():
    with pytest.raises(ai_clients.AgentProtocolError):
        ai_clients.parse_agent_json('{"action": "dance"}')


def test_parse_agent_json_lenient_pretty_printed():
    """Models often emit pretty-printed JSON with literal newlines + unescaped
    quotes inside content — the lenient fallback recovers it (this is what
    DeepSeek actually sends)."""
    sample = (
        '{"action": "reply", "content": "Hi! I can help you find moments.\n'
        'For example, you can ask things like:\n'
        '- \\"Where is the webcam?\\"\n- what was on the desk."}'
    )
    r = ai_clients.parse_agent_json(sample)
    assert r.kind == "reply"
    assert r.content.startswith("Hi! I can help you find moments.")
    assert "webcam" in r.content

    # Pretty-printed tool call with a valid arguments object.
    tool = (
        '{\n  "action": "tool",\n  "tool": "search_transcriptions",\n'
        '  "arguments": {\n    "q": "webcam",\n    "limit": 5\n  }\n}'
    )
    r2 = ai_clients.parse_agent_json(tool)
    assert r2.kind == "tool_call"
    assert r2.tool == "search_transcriptions"
    assert r2.arguments == {"q": "webcam", "limit": 5}


# --------------------------------------------------------------------------- #
# Native OpenAI function calling + plain-conversation fallback
# --------------------------------------------------------------------------- #

class _FakeResp:
    """Stands in for requests.Response with a canned JSON body."""
    def __init__(self, message):
        self._message = message
    def raise_for_status(self):
        return None
    def json(self):
        return {"choices": [{"message": self._message}]}


def test_agent_llm_client_parses_native_tool_calls(monkeypatch):
    """Native OpenAI message.tool_calls (used by DeepSeek etc.) are honoured."""
    monkeypatch.setattr(ai_clients.requests, "post", lambda *a, **k: _FakeResp({
        "content": None,
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "search_transcriptions",
                         "arguments": '{"q": "webcam"}'},
        }],
    }))
    cfg = ai_clients.AgentConfig()
    cfg.mock_mode = False
    cfg.stream = False
    resp = ai_clients.AgentLLMClient(cfg).chat(
        [{"role": "user", "content": "hi"}], [{"type": "function"}]
    )
    assert resp.kind == "tool_call"
    assert resp.tool == "search_transcriptions"
    assert resp.arguments == {"q": "webcam"}


def test_agent_llm_client_plain_text_fallback(monkeypatch):
    """Non-JSON plain text from the model -> a plain reply, never an error."""
    monkeypatch.setattr(ai_clients.requests, "post", lambda *a, **k: _FakeResp({
        "content": "Here is my plain answer.", "tool_calls": None,
    }))
    cfg = ai_clients.AgentConfig()
    cfg.mock_mode = False
    cfg.stream = False
    resp = ai_clients.AgentLLMClient(cfg).chat(
        [{"role": "user", "content": "hi"}], []
    )
    assert resp.kind == "reply"
    assert resp.plain is True
    assert resp.content == "Here is my plain answer."


def test_agent_llm_client_streaming_sse(monkeypatch):
    """Streamed SSE output: content deltas accumulate AND fragmented native
    tool_calls are reassembled."""
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo "}}]}',
        'data: {"choices":[{"delta":{"content":"world"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"search_transcriptions"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":\\"mou"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"se\\"}"}}]}}]}',
        'data: [DONE]',
    ]

    class _FakeStreamResp:
        def raise_for_status(self):
            return None
        def iter_lines(self, **k):
            return iter(lines)

    monkeypatch.setattr(ai_clients.requests, "post", lambda *a, **k: _FakeStreamResp())
    cfg = ai_clients.AgentConfig()
    cfg.mock_mode = False
    cfg.stream = True
    resp = ai_clients.AgentLLMClient(cfg).chat(
        [{"role": "user", "content": "find the mouse"}], [{"type": "function"}]
    )
    assert resp.kind == "tool_call"
    assert resp.tool == "search_transcriptions"
    assert resp.arguments == {"q": "mouse"}


def test_agent_llm_client_retries_on_protocol_error(monkeypatch):
    """A parse/protocol error is retried, then succeeds on a later attempt."""
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp({"content": "{this is invalid json}", "tool_calls": None})
        return _FakeResp({"content": '{"action":"reply","content":"ok"}', "tool_calls": None})

    monkeypatch.setattr(ai_clients.requests, "post", fake_post)
    cfg = ai_clients.AgentConfig()
    cfg.mock_mode = False
    cfg.stream = False
    cfg.max_retries = 2
    resp = ai_clients.AgentLLMClient(cfg).chat([{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 2
    assert resp.kind == "reply" and resp.content == "ok"


def test_agent_llm_client_exhausts_retries(monkeypatch):
    """After max retries the exception is re-raised with retry count + raw."""
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return _FakeResp({"content": "{bad json}", "tool_calls": None})

    monkeypatch.setattr(ai_clients.requests, "post", fake_post)
    cfg = ai_clients.AgentConfig()
    cfg.mock_mode = False
    cfg.stream = False
    cfg.max_retries = 2
    with pytest.raises(ai_clients.AgentProtocolError) as ei:
        ai_clients.AgentLLMClient(cfg).chat([{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 2
    assert getattr(ei.value, "retries", 0) == 2
    assert getattr(ei.value, "raw", "") == "{bad json}"


def test_llm_error_reply_is_specific():
    """The user-facing error reports retry count + a raw-output snippet."""
    exc = ai_clients.AgentProtocolError("invalid JSON in agent output: x", raw="a cat")
    exc.retries = 3
    reply = agentic._llm_error_reply(exc)
    assert "malformed output after 3 attempt(s)" in reply
    assert "'a cat'" in reply


def test_to_llm_messages_native_round_trip(db):
    """Tool results are fed back in the native tool role with tool_call_id."""
    store = agentic.AgentSessionStore(db)
    sid = store.create("t")["session_id"]
    store.add_message(sid, "user", "find it")
    store.add_message(
        sid, "assistant",
        '{"action":"tool_call","tool":"search_transcriptions","arguments":{"q":"cat"}}',
        tool_call_json='{"tool":"search_transcriptions","arguments":{"q":"cat"},"tool_call_id":"call_x"}',
    )
    store.add_message(
        sid, "tool",
        '[{"play_url":"/media/x#t=1"}]',
        tool_call_json='{"tool":"search_transcriptions","tool_call_id":"call_x"}',
    )
    msgs = agentic.AgentRuntime._to_llm_messages(store.get_messages(sid))
    tool_call_msg = next(m for m in msgs if m["role"] == "assistant" and "tool_calls" in m)
    assert tool_call_msg["tool_calls"][0]["id"] == "call_x"
    assert tool_call_msg["tool_calls"][0]["function"]["name"] == "search_transcriptions"
    tool_msg = next(m for m in msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_x"
    assert tool_msg["content"].startswith("[Tool result: search_transcriptions]")


def test_plain_conversation_fallback_runtime(db):
    """When the model answers in plain text (no tool call), the runtime still
    appends best-effort search results so retrieval works."""
    vid = "p" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 2.0, "description": "a cat on the sofa"}],
        "transcriptions": [],
    })
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        return AgentLLMResponse("reply", content="I think there's a cat somewhere.",
                                plain=True)

    res = _runtime(db, responder).run(sess["session_id"], "where is the cat?")
    assert res["kind"] == "reply"
    assert "I think there's a cat somewhere." in res["reply"]
    # The stopword-filtered fallback query hit the cat frame.
    assert "I searched for 'cat'" in res["reply"]
    assert "/media/" in res["reply"]


def test_session_title_from_first_user_prompt_then_llm_summary(db):
    """An empty-titled session gets a placeholder from the first prompt, then the
    LLM-summarized first answer becomes the title (tool calls are NOT used)."""
    sess = agentic.AgentSessionStore(db).create("")  # empty title (frontend flow)
    calls = []

    def responder(messages, tools):
        calls.append({"tools": tools, "messages": messages})
        if tools == []:
            return AgentLLMResponse("reply", content="Finding the red and black webcam")
        return AgentLLMResponse("tool_call", tool="list_videos", arguments={})

    rt = _runtime(db, responder)
    res = rt.run(sess["session_id"], "where is my ipod?")
    assert res["kind"] == "reply"

    updated = agentic.AgentSessionStore(db).get(sess["session_id"])
    assert updated["title"] == "Finding the red and black webcam"
    # The title call passed NO tools (model could not call tools for the title).
    title_call = calls[-1]
    assert title_call["tools"] == []


def test_session_title_not_overwritten_when_explicit(db):
    """A session created with a user-provided title keeps it."""
    sess = agentic.AgentSessionStore(db).create("my custom title")

    def responder(messages, tools):
        return AgentLLMResponse("reply", content="found it")

    _runtime(db, responder).run(sess["session_id"], "find the thing")
    assert agentic.AgentSessionStore(db).get(sess["session_id"])["title"] == "my custom title"


def test_session_title_only_first_reply(db):
    """The title is generated once; later turns never touch it."""
    sess = agentic.AgentSessionStore(db).create("")
    calls = []

    def responder(messages, tools):
        calls.append(tools)
        if tools == []:
            return AgentLLMResponse("reply", content="First summary")
        return AgentLLMResponse("reply", content="answer")

    rt = _runtime(db, responder)
    rt.run(sess["session_id"], "first")
    rt.run(sess["session_id"], "second")

    store = agentic.AgentSessionStore(db)
    assert store.get(sess["session_id"])["title"] == "First summary"
    # Only the first turn triggered a title ([] tools) call.
    assert calls.count([]) == 1


# --------------------------------------------------------------------------- #
# Agent LLM config — separate from VLM/ASR
# --------------------------------------------------------------------------- #

def test_agent_config_reads_separate_keys(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_API_URL", "http://example.test/v1/chat/completions")
    monkeypatch.setenv("AGENT_LLM_MODEL", "agent-model-x")
    monkeypatch.setenv("AGENT_LLM_MAX_TURNS", "3")
    monkeypatch.setenv("AGENT_LLM_MOCK", "true")
    cfg = ai_clients.get_agent_config()
    assert cfg.api_url == "http://example.test/v1/chat/completions"
    assert cfg.model_name == "agent-model-x"
    assert cfg.max_turns == 3
    assert cfg.mock_mode is True
    # agentic config does not collide with VLM/ASR keys
    assert cfg.api_url != ai_clients.Config().vlm_api_url


def test_agent_llm_mock_follows_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.delenv("AGENT_LLM_MOCK", raising=False)
    cfg = ai_clients.get_agent_config()
    assert cfg.mock_mode is True
    assert isinstance(ai_clients.agent_llm_client(cfg), MockAgentLLMClient)


def test_agent_llm_real_client_when_not_mock(monkeypatch):
    monkeypatch.delenv("MOCK_MODE", raising=False)
    monkeypatch.setenv("AGENT_LLM_MOCK", "false")
    cfg = ai_clients.get_agent_config()
    assert cfg.mock_mode is False
    assert isinstance(ai_clients.agent_llm_client(cfg), ai_clients.AgentLLMClient)


# --------------------------------------------------------------------------- #
# Session lifecycle (HTTP)
# --------------------------------------------------------------------------- #

def test_session_lifecycle(db):
    r = client.post("/agent/sessions", json={"title": "find things"})
    assert r.status_code == 201
    body = r.json()
    sid = body["session_id"]
    assert body["title"] == "find things"

    assert any(s["id"] == sid for s in client.get("/agent/sessions").json())

    got = client.get(f"/agent/sessions/{sid}").json()
    assert got["session"]["id"] == sid
    assert got["messages"] == []

    assert client.delete(f"/agent/sessions/{sid}").status_code == 204
    assert client.get(f"/agent/sessions/{sid}").status_code == 404
    assert client.delete(f"/agent/sessions/{sid}").status_code == 404


# --------------------------------------------------------------------------- #
# Agent loop behaviour (unit, against a scripted LLM)
# --------------------------------------------------------------------------- #

def test_agent_uses_search_tool(db):
    vid = "a" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 3.0, "description": "a cat sits on a desk"}],
        "transcriptions": [],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            result = json.loads(last["content"].split("\n", 1)[1])
            assert result and result[0]["timestamp"] == 3.0
            assert result[0]["play_url"].endswith("#t=3.0")
            return AgentLLMResponse("reply", content="The cat is at 3s: " + result[0]["play_url"])
        return AgentLLMResponse("tool_call", tool="search_transcriptions", arguments={"q": "cat"})

    sess = agentic.AgentSessionStore(db).create("t")
    res = _runtime(db, responder).run(sess["session_id"], "where is the cat?")

    assert res["kind"] == "reply"
    assert "/media/" in res["reply"]
    assert res["tool_calls"] == [{"tool": "search_transcriptions", "arguments": {"q": "cat"}}]
    assert res["turns"] == 2


def test_history_persists_across_turns(db):
    sess = agentic.AgentSessionStore(db).create("t")
    calls = []

    def responder(messages, tools):
        calls.append(messages)
        if any(m["role"] == "tool" and m["content"].startswith("[Tool result")
               for m in messages):
            return AgentLLMResponse("reply", content="done")
        return AgentLLMResponse("tool_call", tool="list_videos", arguments={})

    rt = _runtime(db, responder)
    r1 = rt.run(sess["session_id"], "hi")
    assert r1["kind"] == "reply"
    r2 = rt.run(sess["session_id"], "again")
    assert r2["kind"] == "reply"

    # Second turn sees the full first-turn conversation.
    assert any(m["role"] == "user" and m["content"] == "hi" for m in calls[-1])
    assert any(m["role"] == "tool" and m["content"].startswith("[Tool result: list_videos]")
               for m in calls[-1])

    # Everything persisted in the DB (user/assistant/tool rows).
    msgs = agentic.AgentSessionStore(db).get_messages(sess["session_id"])
    roles = [m["role"] for m in msgs]
    assert roles.count("user") == 2
    assert roles.count("tool") == 1
    assert roles.count("assistant") == 3  # tool-call decision + 2 replies


def test_agent_uses_memory(db):
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: memory_store]"):
            return AgentLLMResponse("tool_call", tool="memory_get", arguments={"key": "cat_alias"})
        if last["role"] == "tool" and last["content"].startswith("[Tool result: memory_get]"):
            return AgentLLMResponse("reply", content="remembered: " + last["content"].split("\n", 1)[1])
        return AgentLLMResponse("tool_call", tool="memory_store",
                                arguments={"key": "cat_alias", "value": "小猫"})

    res = _runtime(db, responder).run(sess["session_id"], "remember the cat alias")

    assert res["kind"] == "reply"
    assert "小猫" in res["reply"]
    assert {t["tool"] for t in res["tool_calls"]} == {"memory_store", "memory_get"}
    # Persisted in agent_memory.
    assert agentic.AgentMemory(db).get("cat_alias") == {"key": "cat_alias", "value": "小猫"}


def test_max_turns_cap(db):
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        return AgentLLMResponse("tool_call", tool="list_videos", arguments={})

    res = _runtime(db, responder, max_turns=3).run(sess["session_id"], "loop forever")
    assert res["truncated"] is True
    assert res["turns"] == 3
    assert len(res["tool_calls"]) == 3
    # The reply explicitly says the agent stopped at its max iteration limit.
    assert "maximum iteration limit" in res["reply"]
    assert "3 tool calls" in res["reply"]


def test_max_turns_forces_final_answer_with_no_tools(db):
    """On the turn cap the runtime makes ONE final LLM call with tools disabled
    ([]), so the model cannot burn more tool calls and must write an answer."""
    sess = agentic.AgentSessionStore(db).create("t")
    mock = MockAgentLLMClient()

    def responder(messages, tools):
        if tools == []:
            return AgentLLMResponse("reply", content="FORCED: best evidence answer")
        return AgentLLMResponse("tool_call", tool="list_videos", arguments={})

    mock._responder = responder
    store = agentic.AgentSessionStore(db)
    memory = agentic.AgentMemory(db)
    feedback = agentic.AgentFeedback(db)
    runtime = agentic.AgentRuntime(
        llm_client=mock,
        tool_schemas=main._AGENT_TOOL_SCHEMAS,
        tool_impls=main._build_agent_tool_impls(memory, feedback),
        store=store,
        memory=memory,
        max_turns=3,
    )
    res = runtime.run(sess["session_id"], "loop forever")
    assert res["truncated"] is True
    assert res["reply"] == "FORCED: best evidence answer"
    # The final (forced) call passed an empty tool list.
    assert mock.calls[-1]["tools_schema"] == []
    # And the forced reply is persisted so the transcript shows it.
    roles = [m["role"] for m in store.get_messages(sess["session_id"])]
    assert roles[-1] == "assistant"
    assert store.get_messages(sess["session_id"])[-1]["content"] == "FORCED: best evidence answer"


def test_max_turns_forced_answer_failure_falls_back(db):
    """If the forced no-tools LLM call fails, the deterministic best-evidence
    fallback (recovered from the tool trace) is used instead — never a crash."""
    vid = "w" * 32
    _insert_test_video(db, vid, name="desk", location="desk", duration=30.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 3.0, "description": "a small dark lens mounted on the monitor"},
        ],
        "transcriptions": [],
    })

    sess = agentic.AgentSessionStore(db).create("t")
    mock = MockAgentLLMClient()

    def responder(messages, tools):
        if tools == []:
            raise RuntimeError("forced answer blew up")
        return AgentLLMResponse(
            "tool_call", tool="suggest_likely_moments",
            arguments={"target": "webcam", "features": ["lens", "mounted", "monitor"]},
        )

    mock._responder = responder
    store = agentic.AgentSessionStore(db)
    memory = agentic.AgentMemory(db)
    feedback = agentic.AgentFeedback(db)
    runtime = agentic.AgentRuntime(
        llm_client=mock,
        tool_schemas=main._AGENT_TOOL_SCHEMAS,
        tool_impls=main._build_agent_tool_impls(memory, feedback),
        store=store,
        memory=memory,
        max_turns=3,
    )
    res = runtime.run(sess["session_id"], "find the webcam")
    assert res["truncated"] is True
    assert "most likely" in res["reply"]           # deterministic fallback
    assert "not a confirmed match" in res["reply"]
    assert "/media/" in res["reply"]
    # Fallback reply also persisted.
    assert store.get_messages(sess["session_id"])[-1]["role"] == "assistant"


def test_tool_error_fed_back_to_agent(db):
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: get_video_keywords]"):
            result = json.loads(last["content"].split("\n", 1)[1])
            assert result == {"error": "tool get_video_keywords failed: video not found: nosuch"}
            return AgentLLMResponse("reply", content="video not found, moving on")
        return AgentLLMResponse("tool_call", tool="get_video_keywords",
                                arguments={"video_id": "nosuch"})

    res = _runtime(db, responder).run(sess["session_id"], "summarize nosuch")
    assert res["kind"] == "reply"
    assert "moving on" in res["reply"]


def test_malformed_llm_output_is_graceful(db):
    """Non-JSON model output is surfaced as a plain conversational reply —
    never a crash or a misleading 'parse error'."""
    sess = agentic.AgentSessionStore(db).create("t")
    mock = MockAgentLLMClient(responses=["this is not json {{{"])
    store = agentic.AgentSessionStore(db)
    memory = agentic.AgentMemory(db)
    feedback = agentic.AgentFeedback(db)
    rt = agentic.AgentRuntime(
        llm_client=mock,
        tool_schemas=main._AGENT_TOOL_SCHEMAS,
        tool_impls=main._build_agent_tool_impls(memory, feedback),
        store=store, memory=memory, max_turns=8,
    )
    res = rt.run(sess["session_id"], "hello?")
    assert res["kind"] == "reply"
    # The malformed text is returned verbatim (plain fallback), no crash.
    assert "this is not json" in res["reply"]
    assert "error" not in res
    assert "parse" not in res["reply"].lower()


def test_agent_asks_clarification(db):
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        return AgentLLMResponse("ask", content="Do you mean the cat or the hat?")

    res = _runtime(db, responder).run(sess["session_id"], "find it")
    assert res["kind"] == "ask"
    assert res["reply"] == "Do you mean the cat or the hat?"
    msgs = agentic.AgentSessionStore(db).get_messages(sess["session_id"])
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "Do you mean the cat or the hat?"


# --------------------------------------------------------------------------- #
# Keyword tool + tokenizer
# --------------------------------------------------------------------------- #

def test_tokenize_mixed_language():
    toks = main._tokenize_text("红色 umbrella by the 大门")
    assert "umbrella" in toks
    assert "红色" in toks
    assert "大门" in toks


def test_agent_video_keywords_tool(db):
    vid = "c" * 32
    _insert_test_video(db, vid)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 1.0, "description": "red umbrella on the desk"},
            {"timestamp": 2.0, "description": "red umbrella and blue lamp"},
        ],
        "transcriptions": [],
    })
    kws = main._agent_video_keywords(vid, limit=10)
    terms = [k["term"] for k in kws]
    assert kws[0]["term"] == "red" and kws[0]["count"] == 2
    assert "umbrella" in terms
    assert "the" not in terms   # stopword filtered


# --------------------------------------------------------------------------- #
# Memory CRUD (HTTP)
# --------------------------------------------------------------------------- #

def test_memory_crud_http(db):
    r = client.post("/agent/memory", json={"key": "k1", "value": "v1"})
    assert r.status_code == 201

    entries = client.get("/agent/memory").json()["entries"]
    assert any(e["key"] == "k1" and e["value"] == "v1" for e in entries)

    # upsert updates in place (no duplicate)
    client.post("/agent/memory", json={"key": "k1", "value": "v2"})
    entries = client.get("/agent/memory").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["value"] == "v2"

    assert client.delete("/agent/memory/k1").status_code == 204
    assert client.delete("/agent/memory/k1").status_code == 404


# --------------------------------------------------------------------------- #
# Chat HTTP endpoint
# --------------------------------------------------------------------------- #

def test_agent_chat_http_end_to_end(db, monkeypatch):
    vid = "b" * 32
    _insert_test_video(db, vid, name="living-room cam", location="living-room", duration=10.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 4.0, "description": "a red umbrella by the door"}],
        "transcriptions": [{"index": 1, "start_seconds": 5.0, "end_seconds": 6.0,
                            "text": "the umbrella is red"}],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            result = json.loads(last["content"].split("\n", 1)[1])
            return AgentLLMResponse(
                "reply",
                content=f"Found at {result[0]['timestamp']}s: {result[0]['play_url']}",
            )
        return AgentLLMResponse("tool_call", tool="search_transcriptions",
                                arguments={"q": "umbrella"})

    monkeypatch.setattr(main, "agent_llm_client", lambda cfg: MockAgentLLMClient(responder=responder))

    sid = client.post("/agent/sessions", json={"title": "e2e"}).json()["session_id"]
    r = client.post(f"/agent/sessions/{sid}/chat", json={"message": "where is the umbrella?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert body["kind"] == "reply"
    assert body["tool_calls"] == [{"tool": "search_transcriptions", "arguments": {"q": "umbrella"}}]
    assert body["reply"] == f"Found at 4.0s: /media/{vid}#t=4.0"

    # Full history is stored for the frontend to render later.
    got = client.get(f"/agent/sessions/{sid}").json()
    roles = [m["role"] for m in got["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_agent_chat_unknown_session_404(db):
    r = client.post("/agent/sessions/nosuchid/chat", json={"message": "hi"})
    assert r.status_code == 404


def test_agent_chat_empty_message_422(db):
    sid = client.post("/agent/sessions", json={}).json()["session_id"]
    r = client.post(f"/agent/sessions/{sid}/chat", json={"message": ""})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Attached context (images / audio transcribed to text, structured into context)
# --------------------------------------------------------------------------- #

def test_build_user_content_structures_attachments():
    content = agentic.AgentRuntime._build_user_content(
        "where is this?",
        [
            agentic.Attachment("image", "红色雨伞 在门口", "umbrella.jpg"),
            agentic.Attachment("audio", "我要找那把红伞", "clip.m4a"),
        ],
    )
    assert "--- attached context (transcribed to text) ---" in content
    assert "[attached image (umbrella.jpg) #1]" in content
    assert "红色雨伞 在门口" in content
    assert "[attached audio (clip.m4a) #2]" in content
    assert "我要找那把红伞" in content


def test_agent_sees_attachments_and_intent_first(db):
    """The agent receives the structured context + intent-first prompt, then
    derives query terms from the attached context and searches."""
    vid = "e" * 32
    _insert_test_video(db, vid, name="kitchen", location="kitchen", duration=10.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 2.0, "description": "a red umbrella by the door"}],
        "transcriptions": [],
    })

    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        sys_msg = messages[0]
        user_msg = next(
            m for m in messages
            if m["role"] == "user" and "attached context" in m["content"]
        )
        # Structured context is present and labelled per attachment.
        assert "[attached image (umbrella.jpg) #1]" in user_msg["content"]
        assert "红色雨伞" in user_msg["content"]
        assert "[attached audio (clip.m4a) #2]" in user_msg["content"]
        # Intent-first guidance is in the system prompt.
        assert "intent" in sys_msg["content"].lower()
        assert "attached context" in sys_msg["content"]
        # Agent derives a query term from the attached context.
        return AgentLLMResponse("tool_call", tool="search_transcriptions",
                                arguments={"q": "umbrella"})

    res = _runtime(db, responder).run(
        sess["session_id"],
        "where is this?",
        attachments=[
            agentic.Attachment("image", "红色雨伞 在门口", "umbrella.jpg"),
            agentic.Attachment("audio", "我要找那把红伞", "clip.m4a"),
        ],
    )
    assert res["tool_calls"][0]["arguments"]["q"] == "umbrella"
    # The persisted user message holds the structured context for history.
    msgs = agentic.AgentSessionStore(db).get_messages(sess["session_id"])
    assert "--- attached context (transcribed to text) ---" in msgs[0]["content"]


def test_agent_chat_http_with_attachments(db, monkeypatch):
    vid = "d" * 32
    _insert_test_video(db, vid, name="garage", location="garage", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 1.0, "description": "a blue box on the shelf"}],
        "transcriptions": [],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="Found the box in the garage.")
        return AgentLLMResponse("tool_call", tool="search_transcriptions",
                                arguments={"q": "box"})

    monkeypatch.setattr(main, "agent_llm_client", lambda cfg: MockAgentLLMClient(responder=responder))

    sid = client.post("/agent/sessions", json={"title": "ctx"}).json()["session_id"]
    r = client.post(f"/agent/sessions/{sid}/chat", json={
        "message": "find this object",
        "attachments": [
            {"kind": "image", "name": "box.png", "text": "蓝色盒子 在架子上"},
        ],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "reply"
    assert body["tool_calls"][0]["arguments"]["q"] == "box"

    # History retains the structured attachment context.
    msgs = client.get(f"/agent/sessions/{sid}").json()["messages"]
    user_msg = msgs[0]
    assert user_msg["role"] == "user"
    assert "--- attached context (transcribed to text) ---" in user_msg["content"]
    assert "[attached image (box.png) #1]" in user_msg["content"]


def test_agent_chat_attachment_validation(db):
    sid = client.post("/agent/sessions", json={}).json()["session_id"]
    # Unknown kind -> 422
    r = client.post(f"/agent/sessions/{sid}/chat", json={
        "message": "x",
        "attachments": [{"kind": "video", "text": "nope"}],
    })
    assert r.status_code == 422
    # Empty attachment text -> 422
    r = client.post(f"/agent/sessions/{sid}/chat", json={
        "message": "x",
        "attachments": [{"kind": "image", "text": ""}],
    })
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Per-item feedback (thumbs up / down)
# --------------------------------------------------------------------------- #

def _mk_session(db):
    return client.post("/agent/sessions", json={"title": "fb"}).json()["session_id"]


def test_feedback_upsert_toggle(db):
    sid = _mk_session(db)
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "frame",
        "timestamp": 3.0, "rating": 1,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["rating"] == 1
    assert body["video_id"] == "v1"

    # Thumbs up then down on the same item -> single row, updated rating.
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "frame",
        "timestamp": 3.0, "rating": -1,
    })
    assert r.status_code == 201
    assert r.json()["rating"] == -1

    entries = agentic.AgentFeedback(db).get_for_session(sid)
    assert len(entries) == 1
    assert entries[0]["rating"] == -1


def test_feedback_derives_context_from_session(db):
    """When the client omits message/reply, context is snapshotted from the
    session's last user question and agent answer."""
    vid = "h" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 1.0, "description": "a cat on the sofa"}],
        "transcriptions": [],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="The cat is on the sofa @ 1s.")
        return AgentLLMResponse("tool_call", tool="search_transcriptions", arguments={"q": "cat"})

    sid = _mk_session(db)
    _runtime(db, responder).run(sid, "where is the cat?")

    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": vid, "source": "frame",
        "timestamp": 1.0, "rating": 1,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["user_message"] == "where is the cat?"
    assert body["agent_reply"] == "The cat is on the sofa @ 1s."
    # The search query terms used are captured too.
    assert body["tool_arguments"] == '{"q": "cat"}'
    assert body["rating"] == 1


def test_feedback_http_list_and_delete(db):
    sid = _mk_session(db)
    client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "audio",
        "timestamp": 5.0, "rating": 1,
    })

    entries = client.get(f"/agent/feedback?session_id={sid}").json()["feedback"]
    assert len(entries) == 1
    assert entries[0]["source"] == "audio"

    # Global listing across sessions (what the agent sees).
    all_entries = client.get("/agent/feedback").json()["feedback"]
    assert len(all_entries) == 1

    # rating 0 via POST removes the rating.
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "audio",
        "timestamp": 5.0, "rating": 0,
    })
    assert r.status_code == 201
    assert r.json() == {"deleted": True}
    assert client.get(f"/agent/feedback?session_id={sid}").json()["feedback"] == []


def test_feedback_validation(db):
    sid = _mk_session(db)
    # rating out of range
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "frame",
        "timestamp": 1.0, "rating": 2,
    })
    assert r.status_code == 422
    # unknown session
    r = client.post("/agent/feedback", json={
        "session_id": "nosuch", "video_id": "v1", "source": "frame",
        "timestamp": 1.0, "rating": 1,
    })
    assert r.status_code == 404
    # bad source
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "video",
        "timestamp": 1.0, "rating": 1,
    })
    assert r.status_code == 422


def test_feedback_anchors_round_trip(db):
    """The same item surfaced across different timestamps (4.5 vs 4.500) maps
    to the same normalized anchor."""
    sid = _mk_session(db)
    for ts in (4.5, 4.5001):
        r = client.post("/agent/feedback", json={
            "session_id": sid, "video_id": "v1", "source": "frame",
            "timestamp": ts, "rating": 1,
        })
        assert r.status_code == 201
    assert len(agentic.AgentFeedback(db).get_for_session(sid)) == 1


def test_agent_consults_feedback_history(db):
    """The agent calls get_feedback_history to learn from a past rejection and
    refines its query terms."""
    vid = "i" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 1.0, "description": "a cat on the sofa"}],
        "transcriptions": [],
    })

    # --- Seed a rejected item from a real past search (another session) ---
    other_sid = _mk_session(db)
    def seeder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="the cat is at 2s")
        return AgentLLMResponse("tool_call", tool="search_transcriptions",
                                arguments={"q": "kitten"})
    _runtime(db, seeder).run(other_sid, "find the cat")
    # User thumbs down the item; context (question, answer, query terms) is
    # derived from the session history.
    r = client.post("/agent/feedback", json={
        "session_id": other_sid, "video_id": vid, "source": "frame",
        "timestamp": 2.0, "rating": -1,
    })
    assert r.status_code == 201
    seeded = r.json()
    assert seeded["user_message"] == "find the cat"
    assert seeded["agent_reply"] == "the cat is at 2s"
    assert seeded["tool_arguments"] == '{"q": "kitten"}'

    # --- Main session: agent consults feedback history, learns, refines ---
    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: get_feedback_history]"):
            result = json.loads(last["content"].split("\n", 1)[1])
            # Agent sees the past rejection and the query terms that were used.
            assert result["feedback"][0]["rating"] == -1
            assert result["feedback"][0]["tool_arguments"] == '{"q": "kitten"}'
            return AgentLLMResponse("tool_call", tool="search_transcriptions",
                                    arguments={"q": "cat"})
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="Found it in the den.")
        return AgentLLMResponse("tool_call", tool="get_feedback_history",
                                arguments={"rating": -1})

    sid = _mk_session(db)
    res = _runtime(db, responder).run(sid, "where is the cat?")
    assert res["kind"] == "reply"
    tools = [t["tool"] for t in res["tool_calls"]]
    assert tools == ["get_feedback_history", "search_transcriptions"]
    assert res["tool_calls"][1]["arguments"]["q"] == "cat"  # refined away from "kitten"


# --------------------------------------------------------------------------- #
# Incognito mode + agent-side edit/delete of memory & feedback
# --------------------------------------------------------------------------- #

def test_incognito_session_blocks_feedback_and_memory_tools(db):
    """An incognito session exposes only read-only transcription tools and the
    incognito system prompt."""
    sid = client.post("/agent/sessions", json={"incognito": True}).json()["session_id"]
    got = client.get(f"/agent/sessions/{sid}").json()
    assert got["session"]["incognito"] is True

    # HTTP: feedback writes are rejected.
    r = client.post("/agent/feedback", json={
        "session_id": sid, "video_id": "v1", "source": "frame",
        "timestamp": 1.0, "rating": 1,
    })
    assert r.status_code == 409
    # GET returns empty feedback.
    assert client.get(f"/agent/feedback?session_id={sid}").json()["feedback"] == []

    # Agent runtime: private tools are filtered out; prompt is incognito.
    rt = _build_runtime_for(sid, incognito=True, db=db)
    names = [s["function"]["name"] for s in rt.tool_schemas]
    assert "search_transcriptions" in names
    assert "get_media_url" in names
    for private in ("memory_store", "memory_list", "memory_delete_where",
                    "get_feedback_history", "feedback_set", "feedback_delete"):
        assert private not in names
    assert "INCOGNITO" in rt.system_prompt.upper()
    assert "read-only" in rt.system_prompt.lower()
    # The incognito prompt never advertises the private tools.
    for tool in ("get_feedback_history", "feedback_set", "feedback_delete", "memory_store", "memory_list"):
        assert tool not in rt.system_prompt.lower()


def _build_runtime_for(sid, incognito, db):
    return agentic.AgentRuntime(
        llm_client=MockAgentLLMClient(responses=[
            AgentLLMResponse("reply", content="[mock] done"),
        ]),
        tool_schemas=main._agent_schemas(incognito=incognito),
        tool_impls=main._build_agent_tool_impls(
            agentic.AgentMemory(db), agentic.AgentFeedback(db),
            session_id=sid, incognito=incognito,
        ),
        store=agentic.AgentSessionStore(db),
        memory=agentic.AgentMemory(db),
        max_turns=8,
        system_prompt=agentic.SYSTEM_PROMPT_INCOGNITO if incognito else agentic.SYSTEM_PROMPT,
    )


def test_incognito_agent_cannot_call_private_tools(db):
    """Even if the incognito model tried to call a private tool, the runtime
    has no impl for it and reports it as an error."""
    sid = client.post("/agent/sessions", json={"incognito": True}).json()["session_id"]
    rt = _build_runtime_for(sid, incognito=True, db=db)
    assert "memory_list" not in rt.tool_impls
    assert "get_feedback_history" not in rt.tool_impls
    # Attempting an unknown tool yields a ToolError-shaped tool result, no crash.
    with pytest.raises(agentic.ToolError):
        rt._execute_tool("memory_list", {})


def test_incognito_flag_per_turn_and_normal_session(db):
    """A normal session can run a single incognito turn (masks memory/feedback)."""
    sid = client.post("/agent/sessions", json={}).json()["session_id"]
    assert client.get(f"/agent/sessions/{sid}").json()["session"]["incognito"] is False

    # Per-turn incognito on a normal session: runtime gets incognito prompt/tools.
    rt = _build_runtime_for(sid, incognito=True, db=db)
    assert "memory_list" not in rt.tool_impls


def test_agent_feedback_set_tool_edits_rating(db):
    """The agent can record/edit a rating via feedback_set."""
    sid = _mk_session(db)
    responder_seq = [
        AgentLLMResponse("tool_call", tool="feedback_set", arguments={
            "video_id": "v1", "source": "frame", "timestamp": 2.0, "rating": 1,
        }),
        AgentLLMResponse("reply", content="rated it up"),
    ]
    # Runtime bound to this session so feedback_set targets it.
    rt = _build_runtime_for(sid, incognito=False, db=db)
    rt.llm_client = MockAgentLLMClient(responses=responder_seq)
    res = rt.run(sid, "mark item up")
    assert res["kind"] == "reply"
    entries = agentic.AgentFeedback(db).get_for_session(sid)
    assert len(entries) == 1
    assert entries[0]["rating"] == 1 and entries[0]["video_id"] == "v1"


def test_agent_feedback_delete_tool_bulk(db):
    """The agent can discard every feedback row matching a term, across chats."""
    s1 = _mk_session(db)
    s2 = _mk_session(db)
    for s in (s1, s2):
        client.post("/agent/feedback", json={
            "session_id": s, "video_id": "v1", "source": "frame",
            "timestamp": 2.0, "rating": 1, "user_message": "find the ipod",
            "agent_reply": "the ipod is at 2s",
        })
    # Unrelated feedback stays.
    client.post("/agent/feedback", json={
        "session_id": s1, "video_id": "v2", "source": "audio",
        "timestamp": 9.0, "rating": -1, "user_message": "find the mug",
        "agent_reply": "mug not found",
    })

    impls = main._build_agent_tool_impls(agentic.AgentMemory(db), agentic.AgentFeedback(db))
    res = impls["feedback_delete"](query="ipod")
    assert res["deleted"] == 2
    # Only the unrelated row remains.
    remaining = agentic.AgentFeedback(db).list()
    assert len(remaining) == 1
    assert "mug" in remaining[0]["user_message"]


def test_agent_memory_delete_where_tool(db):
    sid = _mk_session(db)
    client.post("/agent/memory", json={"key": "ipod_alias", "value": "mp3 player"})
    client.post("/agent/memory", json={"key": "cat_alias", "value": "小猫"})

    impls = main._build_agent_tool_impls(agentic.AgentMemory(db), agentic.AgentFeedback(db))
    res = impls["memory_delete_where"](contains="ipod")
    assert res["deleted"] == 1
    assert agentic.AgentMemory(db).get("ipod_alias") is None
    assert agentic.AgentMemory(db).get("cat_alias") is not None


def test_agent_cleanup_before_search(db, monkeypatch):
    """The full 'discard every feedback and memory related to ipod' flow:
    the agent deletes matching feedback + memory, then searches."""
    # Pre-seed some ipod-related feedback + memory (from a previous chat).
    other = _mk_session(db)
    client.post("/agent/feedback", json={
        "session_id": other, "video_id": "v0", "source": "frame",
        "timestamp": 2.0, "rating": -1, "user_message": "find the ipod",
        "agent_reply": "could not find",
    })
    client.post("/agent/memory", json={"key": "ipod_term", "value": "apple music player"})

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: memory_delete_where]"):
            res = json.loads(last["content"].split("\n", 1)[1])
            assert res["deleted"] == 1
            return AgentLLMResponse("tool_call", tool="search_transcriptions", arguments={"q": "ipod"})
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="searched after cleanup")
        if last["role"] == "tool" and last["content"].startswith("[Tool result: feedback_delete]"):
            res = json.loads(last["content"].split("\n", 1)[1])
            assert res["deleted"] == 1
            return AgentLLMResponse("tool_call", tool="memory_delete_where", arguments={"contains": "ipod"})
        return AgentLLMResponse("tool_call", tool="feedback_delete", arguments={"query": "ipod"})

    sid = _mk_session(db)
    rt = _build_runtime_for(sid, incognito=False, db=db)
    rt.llm_client = MockAgentLLMClient(responder=responder)
    res = rt.run(sid, "i want you to discard every feedback and memory related to ipod before searching ipod")
    assert res["kind"] == "reply"
    assert [t["tool"] for t in res["tool_calls"]] == [
        "feedback_delete", "memory_delete_where", "search_transcriptions",
    ]
    # Both stores are clean of ipod now.
    assert agentic.AgentMemory(db).get("ipod_term") is None
    assert agentic.AgentFeedback(db).list(query="ipod") == []


# --------------------------------------------------------------------------- #
# Token streaming + SSE chat endpoint
# --------------------------------------------------------------------------- #

def test_runtime_on_token_streams_reply(db):
    """The runtime forwards streamed reply content to on_token, and tool
    activity to on_tool."""
    vid = "q" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 2.0, "description": "a cat on the sofa"}],
        "transcriptions": [],
    })
    sess = agentic.AgentSessionStore(db).create("t")

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="Found the cat **at 2s**.")
        return AgentLLMResponse("tool_call", tool="search_transcriptions", arguments={"q": "cat"})

    tokens, tools = [], []
    rt = _runtime(db, responder)
    res = rt.run(
        sess["session_id"], "where is the cat?",
        on_token=lambda d: tokens.append(d),
        on_tool=lambda t, a: tools.append(t),
    )
    assert res["kind"] == "reply"
    # The reply content is streamed via on_token.
    assert "".join(tokens) == "Found the cat **at 2s**."
    # Tool activity is reported via on_tool.
    assert tools == ["search_transcriptions"]


def test_agent_chat_stream_endpoint(db, monkeypatch):
    """POST /chat/stream emits SSE token + done events (agent does a tool call
    then streams the reply)."""
    vid = "r" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=5.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 2.0, "description": "a cat on the sofa"}],
        "transcriptions": [],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: search_transcriptions]"):
            return AgentLLMResponse("reply", content="I found a **cat** here.")
        return AgentLLMResponse("tool_call", tool="search_transcriptions", arguments={"q": "cat"})

    monkeypatch.setattr(main, "agent_llm_client", lambda cfg: MockAgentLLMClient(responder=responder))

    sid = client.post("/agent/sessions", json={}).json()["session_id"]

    events = []
    with client.stream(
        "POST", f"/agent/sessions/{sid}/chat/stream",
        json={"message": "where is the cat?"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        block = None
        for line in resp.iter_lines():
            if not line:
                # blank line ends an SSE event
                if block is not None:
                    events.append(block)
                    block = None
                continue
            block = (block + "\n" + line) if block else line

    event_map = {}
    for ev in events:
        ev_type = ""
        data = ""
        for ln in ev.split("\n"):
            if ln.startswith("event:"):
                ev_type = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        event_map.setdefault(ev_type, []).append(data)

    # A tool event fired (agent searched).
    assert "tool" in event_map
    assert json.loads(event_map["tool"][0])["tool"] == "search_transcriptions"
    # The reply was streamed as token events.
    streamed = "".join(json.loads(d)["delta"] for d in event_map.get("token", []))
    assert streamed == "I found a **cat** here."
    # A done event carried the final result.
    assert "done" in event_map
    done = json.loads(event_map["done"][0])
    assert done["reply"] == "I found a **cat** here."
    assert done["kind"] == "reply"


def test_agent_chat_stream_404_unknown_session(db):
    with client.stream("POST", "/agent/sessions/nosuch/chat/stream", json={"message": "hi"}) as resp:
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Phenomenological fallback (suggest_likely_moments)
# --------------------------------------------------------------------------- #

def test_suggest_likely_moments_ranks_by_features(db):
    """The tool aggregates feature-based hits and ranks moments by how many
    typical features they match (a 'webcam' described phenomenologically)."""
    vid = "s" * 32
    _insert_test_video(db, vid, name="desk", location="desk", duration=30.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 8.0, "description": "a dark glossy lens mounted on top of the monitor"},
            {"timestamp": 15.0, "description": "a black box on the desk with cables"},
            {"timestamp": 20.0, "description": "a small round glass circle above the display"},
        ],
        "transcriptions": [],
    })

    res = main._agent_suggest_likely_moments(
        "webcam",
        ["lens", "mounted", "above the display", "circular", "small", "dark"],
    )
    assert res["candidates"], res
    cands = res["candidates"]
    # The 8s moment (lens + mounted + dark + monitor) ranks highest.
    assert cands[0]["timestamp"] == 8.0
    assert cands[0]["feature_count"] >= 3
    # Uncertainty is explicitly surfaced.
    assert "uncertainty" in res
    assert "NOT confirmed" in res["uncertainty"]
    assert res["candidates"][0]["play_url"] == f"/media/{vid}#t=8.0"


def test_suggest_likely_moments_no_features_errors(db):
    with pytest.raises(agentic.ToolError):
        main._agent_suggest_likely_moments("webcam", [])


def test_video_transcriptions_windowed_by_start(db):
    """get_video_transcriptions only returns the requested 30s window, not the
    whole video — frames/audio outside are excluded; video metadata included."""
    vid = "w1" + "a" * 30
    _insert_test_video(db, vid, name="hall", location="hall", duration=90.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 5.0, "description": "frame at 5s"},
            {"timestamp": 25.0, "description": "frame at 25s"},
            {"timestamp": 45.0, "description": "frame at 45s"},
            {"timestamp": 80.0, "description": "frame at 80s"},
        ],
        "transcriptions": [
            {"index": 1, "start_seconds": 5.0, "end_seconds": 15.0, "text": "audio early"},
            {"index": 2, "start_seconds": 40.0, "end_seconds": 50.0, "text": "audio mid"},
        ],
    })

    # Default window is 0–30s (start_sec defaults to 0).
    res = main._agent_video_transcriptions(vid)
    assert [f["timestamp"] for f in res["frame_descriptions"]] == [5.0, 25.0]
    assert [a["text"] for a in res["transcriptions"]] == ["audio early"]
    assert res["window"]["start_sec"] == 0.0
    assert res["window"]["end_sec"] == 30.0
    assert res["window"]["window_sec"] == 30
    # Video metadata (incl. duration) is included so the agent knows how many
    # windows to scan.
    assert res["metadata"]["duration"] == 90.0
    assert res["metadata"]["location"] == "hall"

    # A later window returns only its own content.
    res2 = main._agent_video_transcriptions(vid, start_sec=30.0)
    assert [f["timestamp"] for f in res2["frame_descriptions"]] == [45.0]
    assert [a["text"] for a in res2["transcriptions"]] == ["audio mid"]


def test_video_transcriptions_window_clamped_to_30(db):
    """The window is clamped to at most 30s even if a bigger window is asked for."""
    vid = "w2" + "b" * 30
    _insert_test_video(db, vid, name="garage", location="garage", duration=120.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 10.0, "description": "f1"},
            {"timestamp": 50.0, "description": "f2"},
        ],
        "transcriptions": [],
    })

    res = main._agent_video_transcriptions(vid, start_sec=0.0, window_sec=999)
    assert res["window"]["window_sec"] == 30
    assert res["window"]["end_sec"] == 30.0
    assert [f["timestamp"] for f in res["frame_descriptions"]] == [10.0]

    res2 = main._agent_video_transcriptions(vid, start_sec=40.0, window_sec=999)
    assert res2["window"]["start_sec"] == 40.0
    assert res2["window"]["end_sec"] == 70.0
    assert [f["timestamp"] for f in res2["frame_descriptions"]] == [50.0]


def test_video_transcriptions_unknown_video_errors(db):
    with pytest.raises(agentic.ToolError):
        main._agent_video_transcriptions("nope" + "x" * 28)


def test_agent_uses_phenomenological_fallback(db):
    """When a direct name search fails, the agent calls suggest_likely_moments
    and answers with a likely-but-uncertain candidate instead of refusing."""
    vid = "t" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=20.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 5.0, "description": "a small dark lens clipped to the top of the monitor"},
            {"timestamp": 9.0, "description": "someone opens a book on the desk"},
        ],
        "transcriptions": [],
    })

    def responder(messages, tools):
        last = messages[-1]
        if last["role"] == "tool" and last["content"].startswith("[Tool result: suggest_likely_moments]"):
            result = json.loads(last["content"].split("\n", 1)[1])
            assert result["candidates"]
            assert result["candidates"][0]["timestamp"] == 5.0
            return AgentLLMResponse(
                "reply",
                content="I couldn't find a device explicitly called a webcam, but the most "
                        "likely candidate is at 5s (small dark lens clipped on the monitor). "
                        "This is an inference, not a confirmed match — please verify visually.",
            )
        return AgentLLMResponse(
            "tool_call", tool="suggest_likely_moments",
            arguments={"target": "webcam",
                       "features": ["lens", "clipped", "monitor", "small", "dark"]},
        )

    sess = agentic.AgentSessionStore(db).create("t")
    res = _runtime(db, responder).run(sess["session_id"], "find the webcam")
    assert res["kind"] == "reply"
    assert [t["tool"] for t in res["tool_calls"]] == ["suggest_likely_moments"]
    # The answer expresses uncertainty instead of refusing.
    assert "not a confirmed match" in res["reply"]
    assert "likely" in res["reply"]


def test_prompts_contain_phenomenological_fallback():
    assert "PHENOMENOLOGICAL FALLBACK" in agentic.SYSTEM_PROMPT
    assert "suggest_likely_moments" in agentic.SYSTEM_PROMPT
    assert "PHENOMENOLOGICAL FALLBACK" in agentic.SYSTEM_PROMPT_INCOGNITO
    assert "suggest_likely_moments" in agentic.SYSTEM_PROMPT_INCOGNITO


def test_turn_limit_fallback_presents_likely_candidates(db):
    """If the agent keeps searching and never replies, the runtime still
    presents the most likely candidates (never a bare refusal)."""
    vid = "u" * 32
    _insert_test_video(db, vid, name="desk", location="desk", duration=30.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [
            {"timestamp": 3.0, "description": "a small dark lens mounted on the monitor"},
            {"timestamp": 12.0, "description": "a stack of books on the desk"},
        ],
        "transcriptions": [],
    })

    def responder(messages, tools):
        # Always request a search — never give a final answer, forcing the cap.
        return AgentLLMResponse(
            "tool_call", tool="suggest_likely_moments",
            arguments={"target": "webcam",
                       "features": ["lens", "mounted", "monitor", "small", "dark"]},
        )

    sess = agentic.AgentSessionStore(db).create("t")
    res = _runtime(db, responder, max_turns=3).run(sess["session_id"], "find the webcam")
    assert res["truncated"] is True
    # The fallback surfaces the likely candidate with uncertainty.
    assert "most likely" in res["reply"]
    assert "not a confirmed match" in res["reply"]
    assert "/media/" in res["reply"]
    assert "webcam" in res["reply"]


def test_turn_limit_fallback_empty_candidates_is_honest(db):
    """When the feature search genuinely finds nothing, the fallback says so
    plainly (what was searched) instead of a generic refusal."""
    vid = "v" * 32
    _insert_test_video(db, vid, name="den", location="den", duration=10.0)
    client.post(f"/videos/{vid}/transcriptions/import", json={
        "frame_descriptions": [{"timestamp": 1.0, "description": "a couch and a lamp"}],
        "transcriptions": [],
    })

    def responder(messages, tools):
        return AgentLLMResponse(
            "tool_call", tool="suggest_likely_moments",
            arguments={"target": "webcam",
                       "features": ["lens", "mounted", "monitor", "circular"]},
        )

    sess = agentic.AgentSessionStore(db).create("t")
    res = _runtime(db, responder, max_turns=3).run(sess["session_id"], "find the webcam")
    assert res["truncated"] is True
    assert "webcam" in res["reply"]
    assert "found no matching moments" in res["reply"]
    assert "not present" in res["reply"]
