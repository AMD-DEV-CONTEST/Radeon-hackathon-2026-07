import asyncio
import contextlib
import json
import socket
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from cortex.broker.server import BrokerServer
from cortex.node.node import CortexNode


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _generate_key(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p.write_bytes(pem); p.chmod(0o600)
    return p


def _write_config(tmp_path: Path, org_did: str, agent_did: str, broker_port: int, reg_path: str) -> Path:
    p = tmp_path / f"config-{org_did.split(':')[-1]}.yaml"
    p.write_text(textwrap.dedent(f"""\
        node:
          org_did: {org_did}
          agent_did: {agent_did}
          key_paths:
            org: {tmp_path / org_did.split(':')[-1] / 'org.pem'}
            agent: {tmp_path / org_did.split(':')[-1] / 'agent.pem'}
        broker: {{url: ws://127.0.0.1:{broker_port}, registry: {reg_path}, replay_window_sec: 600}}
        embedder: {{model: BAAI/bge-small-en-v1.5, backend: cpu, batch_size: 4, fallback_on_oom: true}}
        vector_index: {{backend: hnswlib, metric: cosine, hnsw: {{M: 16, ef_construction: 100, ef_search: 32}}}}
        trust: {{default_org_reputation: 0.85, reputation_overrides: {{}}, half_life_days: 90, min_trust_default: 0.3}}
        query: {{default_top_k: 5, deadline_ms: 4000, min_trust: 0.0}}
        logging: {{level: WARNING, file: {tmp_path / 'n.log'}}}
    """))
    return p


def _write_registry(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "registry.json"
    registry_data = {}
    for e in entries:
        registry_data[e["org_did"]] = {
            "pubkey": "A", "name": e.get("display_name", e["org_did"]),
            "topics": ["*"],
        }
    p.write_text(json.dumps(registry_data))
    return p


@dataclass
class SocE2EEnv:
    broker_url: str
    broker_port: int
    alpha_node: CortexNode
    beta_node: CortexNode
    tmpdir: Path


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def soc_e2e_env(tmp_path_factory) -> SocE2EEnv:
    tmp = tmp_path_factory.mktemp("cortex-e2e-")

    broker_port = _free_port()
    reg = _write_registry(tmp, [
        {"org_did": "did:percq:org:soc-alpha", "display_name": "SOC Alpha"},
        {"org_did": "did:percq:org:soc-beta", "display_name": "SOC Beta"},
    ])

    broker = BrokerServer(registry_path=reg, host="127.0.0.1", port=broker_port)
    broker_task = asyncio.create_task(broker.serve())
    await asyncio.sleep(0.05)

    cfg_a = _write_config(tmp, "did:percq:org:soc-alpha", "did:percq:agent:alpha-bot-1", broker_port, str(reg))
    cfg_b = _write_config(tmp, "did:percq:org:soc-beta", "did:percq:agent:beta-bot-1", broker_port, str(reg))

    keys_a = {"org": _generate_key(tmp / "soc-alpha" / "org.pem"),
              "agent": _generate_key(tmp / "soc-alpha" / "agent.pem")}
    keys_b = {"org": _generate_key(tmp / "soc-beta" / "org.pem"),
              "agent": _generate_key(tmp / "soc-beta" / "agent.pem")}

    node_a = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                        key_paths=keys_a, broker_url=f"ws://127.0.0.1:{broker_port}", config_path=cfg_a,
                        embedder_backend_override="cpu")
    node_b = CortexNode(org_did="did:percq:org:soc-beta", agent_did="did:percq:agent:beta-bot-1",
                        key_paths=keys_b, broker_url=f"ws://127.0.0.1:{broker_port}", config_path=cfg_b,
                        embedder_backend_override="cpu")

    await node_a.start()
    await node_b.start()
    await asyncio.sleep(0.05)

    b_url = f"ws://127.0.0.1:{broker_port}"
    env = SocE2EEnv(broker_url=b_url, broker_port=broker_port,
                    alpha_node=node_a, beta_node=node_b, tmpdir=tmp)

    yield env

    await node_a.stop()
    await node_b.stop()
    await broker.stop()
    broker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await broker_task


@pytest.fixture(scope="session")
async def soc_healthcare_e2e_env(tmp_path_factory) -> SocE2EEnv:
    tmp = tmp_path_factory.mktemp("cortex-healthcare-")

    broker_port = _free_port()
    reg = _write_registry(tmp, [
        {"org_did": "did:percq:org:hospital-aurelia", "display_name": "Hospital Aurelia"},
        {"org_did": "did:percq:org:research-lab-borealis", "display_name": "Research Lab Borealis"},
    ])

    broker = BrokerServer(registry_path=reg, host="127.0.0.1", port=broker_port)
    broker_task = asyncio.create_task(broker.serve())
    await asyncio.sleep(0.05)

    keys_h = {"org": _generate_key(tmp / "hospital" / "org.pem"),
              "agent": _generate_key(tmp / "hospital" / "agent.pem")}
    keys_l = {"org": _generate_key(tmp / "lab" / "org.pem"),
              "agent": _generate_key(tmp / "lab" / "agent.pem")}

    cfg_h = _write_config(tmp, "did:percq:org:hospital-aurelia", "did:percq:agent:aurelia-clinical-bot",
                          broker_port, str(reg))
    cfg_l = _write_config(tmp, "did:percq:org:research-lab-borealis", "did:percq:agent:borealis-research-bot",
                          broker_port, str(reg))

    node_h = CortexNode(org_did="did:percq:org:hospital-aurelia", agent_did="did:percq:agent:aurelia-clinical-bot",
                        key_paths=keys_h, broker_url=f"ws://127.0.0.1:{broker_port}", config_path=cfg_h,
                        embedder_backend_override="cpu")
    node_l = CortexNode(org_did="did:percq:org:research-lab-borealis", agent_did="did:percq:agent:borealis-research-bot",
                        key_paths=keys_l, broker_url=f"ws://127.0.0.1:{broker_port}", config_path=cfg_l,
                        embedder_backend_override="cpu")

    await node_h.start()
    await node_l.start()
    await asyncio.sleep(0.05)

    b_url = f"ws://127.0.0.1:{broker_port}"
    env = SocE2EEnv(broker_url=b_url, broker_port=broker_port,
                    alpha_node=node_h, beta_node=node_l, tmpdir=tmp)

    yield env

    await node_h.stop()
    await node_l.stop()
    await broker.stop()
    broker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await broker_task
