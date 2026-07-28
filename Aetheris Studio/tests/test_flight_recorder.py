"""Fase A test plan (see the approved plan file): hash-chain tamper
detection, cancellation still writes turn_end, disabled flag = no-op,
and the standalone verifier runs isolated from core/.

No pytest-asyncio dependency -- async pieces are driven directly via
asyncio.run() inside plain sync test functions.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.audit import flight_recorder as fr


@pytest.fixture(autouse=True)
def _isolate_audit_dir(tmp_path, monkeypatch):
    """Every test gets its own throwaway AUDIT_DIR and a clean recorder
    cache -- flight_recorder.py binds AUDIT_DIR at import time, so we
    monkeypatch the module attribute directly rather than the env var
    (which would be read too late)."""
    monkeypatch.setattr(fr, "AUDIT_DIR", str(tmp_path))
    fr._recorders.clear()
    yield
    fr._recorders.clear()


def test_append_and_verify_chain_ok():
    rec = fr.get_recorder("sess-ok")
    for i in range(5):
        rec.append("tool_call", {"i": i})
    ok, errors = fr.verify_chain(fr.log_path_for("sess-ok"))
    assert ok
    assert errors == []


def test_tamper_detected_at_exact_entry():
    rec = fr.get_recorder("sess-tamper")
    for i in range(5):
        rec.append("tool_call", {"i": i})

    log_path = Path(fr.log_path_for("sess-tamper"))
    lines = log_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])  # seq=3
    entry["payload"]["i"] = 999  # mutate content, leave "hash" as-is -- a real tamper
    lines[2] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, errors = fr.verify_chain(str(log_path))
    assert not ok
    assert any("seq 3" in e for e in errors)

    # The standalone CLI (scripts/audit_verify.py) must catch the exact
    # same tamper independently -- it duplicates this logic on purpose.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import audit_verify
        ok2, count2, first_bad, errors2 = audit_verify.verify(str(log_path))
    finally:
        sys.path.pop(0)
    assert not ok2
    assert first_bad == 3


def test_reordering_detected():
    rec = fr.get_recorder("sess-reorder")
    for i in range(4):
        rec.append("tool_call", {"i": i})
    log_path = Path(fr.log_path_for("sess-reorder"))
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, errors = fr.verify_chain(str(log_path))
    assert not ok


def test_session_isolation():
    fr.get_recorder("a").append("tool_call", {})
    fr.get_recorder("b").append("tool_call", {})
    a_entries = fr.get_recorder("a").read_all()
    b_entries = fr.get_recorder("b").read_all()
    assert len(a_entries) == 1 and a_entries[0]["session_id"] == "a"
    assert len(b_entries) == 1 and b_entries[0]["session_id"] == "b"


def test_no_raw_content_in_log_invariant_i5():
    """The log must never contain the actual file/command content, only
    digests and lengths (invariant I5)."""
    secret_content = "SUPER_SECRET_FILE_BODY_12345"

    async def handler(content, owner, session_id):
        return {"output": "wrote it", "exit_code": 0}

    async def _run():
        return await fr.audited_tool_call("sess-i5", "write_file", secret_content, "kyuubyN", handler)

    result = asyncio.run(_run())
    assert result["exit_code"] == 0

    raw_log = Path(fr.log_path_for("sess-i5")).read_text(encoding="utf-8")
    assert secret_content not in raw_log
    assert "wrote it" not in raw_log


def test_audited_tool_call_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("AETHERIS_AUDIT_ENABLED", "false")

    async def handler(content, owner, session_id):
        return {"output": "ok", "exit_code": 0}

    async def _run():
        return await fr.audited_tool_call("sess-disabled", "bash", "ls", "kyuubyN", handler)

    result = asyncio.run(_run())
    assert result == {"output": "ok", "exit_code": 0}
    assert fr.get_recorder("sess-disabled").read_all() == []


class _FakeDisconnectingRequest:
    """Reports disconnected on every poll -- mirrors real Starlette Request
    behavior closely enough for stream_agent's is_disconnected() checks."""

    async def is_disconnected(self):
        return True


async def _fake_stream_generate_hangs(model, messages, temperature=0.3, max_tokens=4096,
                                       guided_choices=None, guided_choice_trigger="```"):
    yield ("content", "hello ")
    await asyncio.sleep(5)  # never reached -- disconnect fires on the next 1s poll
    yield ("content", "world")  # pragma: no cover


def test_cancelled_turn_still_writes_turn_end(monkeypatch):
    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "stream_generate", _fake_stream_generate_hangs)

    from core.utils.agent import stream_agent

    async def _drive():
        gen = stream_agent(
            model="dummy", messages=[{"role": "user", "content": "hi"}],
            owner="tester", request=_FakeDisconnectingRequest(), session_id="sess-cancel",
        )
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
        return chunks

    asyncio.run(_drive())

    entries = fr.get_recorder("sess-cancel").read_all()
    types = [e["type"] for e in entries]
    assert types[0] == "turn_start"
    # The invariant this test exists for: turn_end is ALWAYS written, even
    # when the round loop exits through the disconnect-triggered `return`
    # deep inside the try block (the whole reason for wrapping the loop in
    # try/finally instead of relying on the normal fall-through to the
    # final `yield "data: [DONE]"`).
    assert "turn_end" in types
    turn_end = next(e for e in entries if e["type"] == "turn_end")
    # This originally caught a real, independently-fixed race:
    # next_task.cancel() immediately followed by await token_gen.aclose()
    # (no await in between) could raise "aclose(): asynchronous generator
    # is already running" whenever the cancelled task hadn't unwound yet,
    # which the outer `except Exception` used to catch and mistag as
    # "error". Fixed via agent.py's _cancel_and_close() helper (awaits the
    # cancelled task before closing the generator) -- this now reliably
    # reports "disconnected".
    assert turn_end["payload"]["reason"] == "disconnected"


async def _fake_stream_generate_plain_reply(model, messages, temperature=0.3, max_tokens=4096,
                                             guided_choices=None, guided_choice_trigger="```"):
    yield ("content", "Just a plain reply, no tool call here.")


def test_disabled_flag_produces_no_audit_sse_events(monkeypatch):
    """Regression check for AETHERIS_AUDIT_ENABLED=false: no audit_entry
    SSE events, and nothing lands in the recorder for this session."""
    monkeypatch.setenv("AETHERIS_AUDIT_ENABLED", "false")

    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "stream_generate", _fake_stream_generate_plain_reply)

    from core.utils.agent import stream_agent

    class _NeverDisconnects:
        async def is_disconnected(self):
            return False

    async def _drive():
        gen = stream_agent(
            model="dummy", messages=[{"role": "user", "content": "hi"}],
            owner="tester", request=_NeverDisconnects(), session_id="sess-off",
        )
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_drive())
    assert not any('"type": "audit_entry"' in c or '"type":"audit_entry"' in c for c in chunks)
    assert fr.get_recorder("sess-off").read_all() == []


def test_standalone_verifier_runs_isolated(tmp_path):
    """scripts/audit_verify.py must run with zero imports from core/ --
    proven here by invoking it as a real subprocess with only stdlib
    available, not by trusting the source code doesn't import core."""
    rec = fr.get_recorder("sess-standalone")
    for i in range(3):
        rec.append("tool_call", {"i": i})
    log_path = fr.log_path_for("sess-standalone")

    script = Path(__file__).resolve().parent.parent / "scripts" / "audit_verify.py"
    proc = subprocess.run(
        [sys.executable, str(script), log_path],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout
