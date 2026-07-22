"""Fase E groundwork: stream_agent() logs exactly one `first_token` audit
entry per turn, timestamped for TTFT computation by metrics_report.py."""

import asyncio

import pytest

from core.audit import flight_recorder as fr


@pytest.fixture(autouse=True)
def _isolate_audit_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "AUDIT_DIR", str(tmp_path))
    fr._recorders.clear()
    yield
    fr._recorders.clear()


async def _fake_stream_generate_multi_token(model, messages, temperature=0.3, max_tokens=4096,
                                             guided_choices=None, guided_choice_trigger="```"):
    yield ("content", "Hello ")
    yield ("content", "world.")


def test_first_token_logged_exactly_once(monkeypatch):
    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "stream_generate", _fake_stream_generate_multi_token)
    monkeypatch.setenv("AETHERIS_CARTOGRAPHER_AUTO_INJECT", "false")

    from core.utils.agent import stream_agent

    class _NeverDisconnects:
        async def is_disconnected(self):
            return False

    async def _drive():
        gen = stream_agent(
            model="dummy", messages=[{"role": "user", "content": "hi"}],
            owner="tester", request=_NeverDisconnects(), session_id="sess-ttft",
        )
        async for _ in gen:
            pass

    asyncio.run(_drive())

    entries = fr.get_recorder("sess-ttft").read_all()
    first_token_entries = [e for e in entries if e["type"] == "first_token"]
    assert len(first_token_entries) == 1

    turn_start = next(e for e in entries if e["type"] == "turn_start")
    assert first_token_entries[0]["ts"] >= turn_start["ts"]
    assert first_token_entries[0]["seq"] > turn_start["seq"]
