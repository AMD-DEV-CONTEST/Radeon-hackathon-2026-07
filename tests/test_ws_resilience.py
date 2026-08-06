"""The listening socket must outlive a failed turn.

`process_utterance` reaches STT, the agent, Neo4j and TTS — any of which can be
down. If that exception escapes `reply_to_utterance`, it unwinds past the
`ws.receive()` loop in `ws_listen` and the connection closes, so the browser sits
on "thinking" until its reconnect timer fires and whatever the user said next is
dropped. The turn is allowed to fail; the session is not.

No server or network here: the socket and the pipeline are both stand-ins.
"""

import json

import pytest

import server


class FakeWS:
    """Records what the server sent to the client."""

    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def kinds(self):
        return [m.get("type") for m in self.sent]


class FakeHandler:
    """Stands in for StreamHandler — only `resume` is reached from a reply."""

    def __init__(self):
        self.resumed = 0

    def resume(self):
        self.resumed += 1


@pytest.fixture
def ws():
    return FakeWS()


@pytest.fixture
def handler():
    return FakeHandler()


def test_failed_turn_answers_instead_of_raising(monkeypatch, ws, handler):
    """A pipeline blowup becomes a spoken apology, not a dropped connection."""

    def boom(_b64):
        raise RuntimeError("Neo4j is down")

    monkeypatch.setattr(server, "process_utterance", boom)

    server.reply_to_utterance(ws, handler, "ZmFrZSB3YXY=")

    assert ws.kinds() == ["processing", "result"]
    result = ws.sent[-1]
    assert result["answer"] == server.TURN_FAILED_MESSAGE
    assert result["text"] == ""
    assert result["audio_b64"] is None


def test_failed_turn_still_resumes_the_stream(monkeypatch, ws, handler):
    """The VAD is un-paused after a failure, so the next utterance is captured."""
    monkeypatch.setattr(
        server, "process_utterance", lambda _b64: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    server.reply_to_utterance(ws, handler, "ZmFrZSB3YXY=")

    assert handler.resumed == 1


def test_successful_turn_is_forwarded_verbatim(monkeypatch, ws, handler):
    """The happy path passes text, answer and audio through untouched."""
    monkeypatch.setattr(
        server,
        "process_utterance",
        lambda _b64: {"text": "谁导演了黑客帝国", "answer": "沃卓斯基姐妹", "audio_b64": "QUJD"},
    )

    server.reply_to_utterance(ws, handler, "ZmFrZSB3YXY=")

    assert ws.kinds() == ["processing", "result"]
    result = ws.sent[-1]
    assert result["text"] == "谁导演了黑客帝国"
    assert result["answer"] == "沃卓斯基姐妹"
    assert result["audio_b64"] == "QUJD"
    assert handler.resumed == 1


def test_partial_result_does_not_crash_the_send(monkeypatch, ws, handler):
    """A pipeline that returns only some keys still produces a well-formed frame."""
    monkeypatch.setattr(server, "process_utterance", lambda _b64: {"answer": "只有答案"})

    server.reply_to_utterance(ws, handler, "ZmFrZSB3YXY=")

    result = ws.sent[-1]
    assert result == {"type": "result", "text": "", "answer": "只有答案", "audio_b64": None}
