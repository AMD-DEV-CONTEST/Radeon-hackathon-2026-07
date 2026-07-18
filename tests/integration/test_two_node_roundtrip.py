import asyncio
import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
import websockets

from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.node import CortexNode


def write_config(tmp_path: Path, org_did: str, agent_did: str, broker_port: int) -> Path:
    p = tmp_path / f"config-{org_did.split(':')[-1]}.yaml"
    p.write_text(textwrap.dedent(f"""\
        node:
          org_did: {org_did}
          agent_did: {agent_did}
          key_paths:
            org: {tmp_path / org_did.split(':')[-1] / 'org.pem'}
            agent: {tmp_path / org_did.split(':')[-1] / 'agent.pem'}
        broker: {{url: ws://127.0.0.1:{broker_port}, registry: {tmp_path / 'registry.json'}, replay_window_sec: 600}}
        embedder: {{model: BAAI/bge-small-en-v1.5, backend: cpu, batch_size: 4, fallback_on_oom: true}}
        vector_index: {{backend: hnswlib, metric: cosine, hnsw: {{M: 16, ef_construction: 100, ef_search: 32}}}}
        trust: {{default_org_reputation: 0.85, reputation_overrides: {{}}, half_life_days: 90, min_trust_default: 0.3}}
        query: {{default_top_k: 5, deadline_ms: 400, min_trust: 0.3}}
        logging: {{level: INFO, file: {tmp_path / 'n.log'}}}
    """))
    return p


def generate_keys(p: Path) -> Path:
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


@pytest.mark.asyncio
async def test_two_node_roundtrip(tmp_path: Path) -> None:
    broker_received: list[dict] = []
    peers: list = []

    async def handler(ws):
        peers.append(ws)
        try:
            async for msg in ws:
                env = json.loads(msg)
                broker_received.append(env)
                for p in list(peers):
                    if p is not ws:
                        await p.send(msg)
                await ws.send(json.dumps({"type": "ack", "msg_id": env.get("msg_id", "?")}))
        except websockets.ConnectionClosed:
            pass
        finally:
            try: peers.remove(ws)
            except ValueError: pass

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    cfgA = write_config(tmp_path, "did:percq:org:soc-alpha", "did:percq:agent:alpha-1", port)
    cfgB = write_config(tmp_path, "did:percq:org:soc-beta", "did:percq:agent:beta-1", port)
    keysA = {"org": generate_keys(Path(cfgA.parent / "soc-alpha" / "org.pem")),
             "agent": generate_keys(Path(cfgA.parent / "soc-alpha" / "agent.pem"))}
    keysB = {"org": generate_keys(Path(cfgB.parent / "soc-beta" / "org.pem")),
             "agent": generate_keys(Path(cfgB.parent / "soc-beta" / "agent.pem"))}

    nodeA = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-1",
                      key_paths=keysA, broker_url=f"ws://127.0.0.1:{port}", config_path=cfgA,
                      embedder_backend_override="cpu")
    nodeB = CortexNode(org_did="did:percq:org:soc-beta", agent_did="did:percq:agent:beta-1",
                      key_paths=keysB, broker_url=f"ws://127.0.0.1:{port}", config_path=cfgB,
                      embedder_backend_override="cpu")
    await nodeA.start(); await nodeB.start()
    await asyncio.sleep(0.05)

    prov = Provenance(producer_agent="did:percq:agent:alpha-1", producer_org="did:percq:org:soc-alpha",
                      computation_ref=None, source_data_hash="h", source_data_schema=None,
                      run_id="r1", timestamp=datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
    art = MemoryArticle(id="", type=ArticleType.FINDING, content="cross-tenant finding APT29",
                       payload={"attack_id": "T1059.001"}, embedding=None, embedding_model=None,
                       provenance=prov, scope="public", agent_signature=b"", org_signature=None,
                       cites=[], trust_score=None, trust_expiration=None)
    art_id = nodeA.publish(art)
    await asyncio.sleep(0.1)
    assert any(e.get("type") == "publish" for e in broker_received), "broker did not receive publish"
    assert nodeA.store.get(art_id) is not None
    results = nodeA.query("APT29 powershell", topic_filter=[], scope_filter=["public"],
                          top_k=3, min_trust=0.0, deadline_ms=400)
    assert len(results) >= 1
    await nodeA.stop(); await nodeB.stop()
    server.close(); await server.wait_closed()
