import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import websockets
import yaml


def write_registry(tmp_path: Path) -> Path:
    p = tmp_path / "org_registry.json"
    p.write_text(json.dumps({
        "did:percq:org:soc-alpha": {"pubkey": "A", "name": "Alpha", "topics": ["threat-intel"]},
    }))
    return p


def test_config_parser_reads_broker_section(tmp_path):
    from cortex.broker.config import load_config
    cfg_path = tmp_path / "broker.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "broker": {
            "host": "127.0.0.1", "port": 7600,
            "registry": str(tmp_path / "org_registry.json"),
            "replay_window_sec": 600,
            "event_channel_max_clients": 16,
            "metrics_channel_max_clients": 16,
        }
    }))
    cfg = load_config(cfg_path)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 7600
    assert cfg.replay_window_sec == 600


def test_cli_starts_server_and_serves_subscribers(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    cfg_path = tmp_path / "broker.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "broker": {
            "host": "127.0.0.1", "port": unused_tcp_port,
            "registry": str(registry_path),
            "replay_window_sec": 600,
            "event_channel_max_clients": 2,
            "metrics_channel_max_clients": 2,
        }
    }))
    proc = subprocess.Popen(
        [sys.executable, "-m", "cortex.broker", "--config", str(cfg_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 5.0
        last_exc = None
        while time.time() < deadline:
            try:
                async def try_connect():
                    async with websockets.connect(f"ws://127.0.0.1:{unused_tcp_port}") as ws:
                        await ws.send(json.dumps({
                            "type": "subscribe", "msg_id": "probe",
                            "src": "did:percq:org:soc-alpha", "dst": "broker",
                            "ts": "2026-07-18T12:00:00Z",
                            "payload": {"node_id": "probe", "topics": [],
                                        "scopes": []},
                        }))
                        return await asyncio.wait_for(ws.recv(), timeout=2.0)
                ack = asyncio.run(try_connect())
                parsed = json.loads(ack)
                assert parsed["type"] == "ack"
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(0.1)
        else:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"server never bound: {last_exc}\nstderr={stderr}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
