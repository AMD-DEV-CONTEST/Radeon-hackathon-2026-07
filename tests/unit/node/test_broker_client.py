import asyncio
import json
from pathlib import Path

import pytest

from cortex.node.broker_client import BrokerClient


class FakeWS:
    def __init__(self, send_log: list[str]) -> None:
        self.send_log = send_log
        self.closed = False

    async def send(self, msg: str) -> None:
        self.send_log.append(msg)

    async def recv(self) -> str:
        await asyncio.sleep(0.01)
        return json.dumps({"type": "ack", "msg_id": "x"})

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publish_envelope_enqueues_and_sends(monkeypatch, tmp_path: Path) -> None:
    sent: list[str] = []
    fake = FakeWS(sent)

    async def fake_connect(self):
        self._ws = fake
        self._connected = True

    monkeypatch.setattr(BrokerClient, "_connect_socket", fake_connect)
    client = BrokerClient(url="ws://localhost:7432", org_did="did:percq:org:soc-alpha",
                          registry_path=tmp_path / "reg.json", replay_window_sec=600,
                          on_event=lambda *_: None, on_metrics=lambda *_: None,
                          outbound_spill_dir=tmp_path / "outbound",
                          outbound_cap=5, spill_threshold=5)
    await client.connect()
    env = {"type": "publish", "msg_id": "1", "src": "did:percq:org:soc-alpha", "dst": "*", "ts": "2026-07-18T12:00:00Z", "payload": {}}
    await client.publish_envelope(env)
    await asyncio.sleep(0.05)
    await client.stop()
    assert any("\"msg_id\":\"1\"" in m.replace(" ", "") for m in sent)


@pytest.mark.asyncio
async def test_spill_when_queue_overflows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(BrokerClient, "_connect_socket",
                        lambda self: asyncio.sleep(0))
    client = BrokerClient(url="ws://localhost:7432", org_did="did:percq:org:soc-alpha",
                          registry_path=tmp_path / "reg.json", replay_window_sec=600,
                          on_event=lambda *_: None, on_metrics=lambda *_: None,
                          outbound_spill_dir=tmp_path / "outbound",
                          outbound_cap=3, spill_threshold=3)
    spill_dir = tmp_path / "outbound"
    spill_dir.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        env = {"type": "publish", "msg_id": str(i), "src": "x", "dst": "*", "ts": "t", "payload": {}}
        await client.publish_envelope(env)
    await asyncio.sleep(0.02)
    spilled = list(spill_dir.glob("*.json"))
    assert len(spilled) >= 1, f"expected spill files, got {spilled}"
