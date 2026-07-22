"""Fase D.2 integration check: stream_agent() actually publishes
chat_turn_start/chat_turn_end on the real EventBus, and Cartographer's
is_chat_busy() signal reflects that correctly across a turn -- this is
what lets the background worker yield within one file of a new message
arriving (the "Cartographer não-bloqueante" test in the approved plan)."""

import asyncio

import pytest

from core.rag import cartographer as carto


@pytest.fixture(autouse=True)
def _reset_busy_signal():
    carto._busy_since = None
    yield
    carto._busy_since = None


async def _fake_stream_generate_plain_reply(model, messages, temperature=0.3, max_tokens=4096,
                                             guided_choices=None, guided_choice_trigger="```"):
    yield ("content", "A plain reply, no tool call.")


def test_turn_start_and_end_toggle_is_chat_busy(monkeypatch):
    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "stream_generate", _fake_stream_generate_plain_reply)
    monkeypatch.setenv("AETHERIS_CARTOGRAPHER_AUTO_INJECT", "false")  # isolate the busy-signal check

    from core.utils.agent import stream_agent

    class _NeverDisconnects:
        async def is_disconnected(self):
            return False

    assert carto.is_chat_busy() is False

    busy_during_turn = []

    async def _drive():
        gen = stream_agent(
            model="dummy", messages=[{"role": "user", "content": "hi"}],
            owner="tester", request=_NeverDisconnects(), session_id=None,
        )
        async for _chunk in gen:
            busy_during_turn.append(carto.is_chat_busy())

    asyncio.run(_drive())

    assert any(busy_during_turn), "is_chat_busy() should have been True at some point during the turn"
    assert carto.is_chat_busy() is False, "must return to idle once the turn ends"


def test_worker_never_starts_mapping_while_turn_is_live(monkeypatch):
    """Directly exercises the bounded-interruption guarantee: once
    chat_turn_start fires, _map_one_pending_file must decline to start a
    new file (returns False) until chat_turn_end fires."""
    carto._on_turn_start()
    assert carto.is_chat_busy() is True

    async def _run():
        return await carto._map_one_pending_file("C:\\definitely\\not\\scanned\\anyway")

    # Busy -> immediately returns False without even trying to discover files.
    assert asyncio.run(_run()) is False

    carto._on_turn_end()
    assert carto.is_chat_busy() is False
