"""Boot broker → nodes → seed → agents → console; record optionally."""
import argparse
import asyncio
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def run_demo(state_dir: Path, video_dir: Path, no_record: bool = False) -> dict:
    import tempfile

    from cortex.broker.server import BrokerServer
    tmp = Path(tempfile.mkdtemp(prefix="cortex-demo-"))

    print("starting broker...")
    broker_port = _free_port()
    reg = tmp / "reg.json"
    reg.write_text(json.dumps({
        "did:percq:org:soc-alpha": {"pubkey": "A", "name": "Alpha", "topics": ["*"]},
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta", "topics": ["*"]},
    }))
    broker = BrokerServer(registry_path=reg, host="127.0.0.1", port=broker_port)
    asyncio.create_task(broker.serve())
    await asyncio.sleep(0.1)
    print("broker started")

    def _write_node_cfg(p, org, agent, keys, b_url):
        p.write_text(f"""\
node:
  org_did: {org}
  agent_did: {agent}
  key_paths:
    org: {keys['org']}
    agent: {keys['agent']}
broker:
  url: {b_url}
  registry: {reg}
  replay_window_sec: 600
embedder:
  model: BAAI/bge-small-en-v1.5
  backend: cpu
  batch_size: 4
  fallback_on_oom: true
vector_index:
  backend: hnswlib
  metric: cosine
  hnsw:
    M: 16
    ef_construction: 100
    ef_search: 32
trust:
  default_org_reputation: 0.85
  half_life_days: 90
  min_trust_default: 0.3
query:
  default_top_k: 5
  deadline_ms: 4000
  min_trust: 0.0
logging:
  level: WARNING
  file: {p / 'n.log'}
""")

    from cortex.node.keys import ensure_keys
    from cortex.node.node import CortexNode
    from cortex.sdk.client import CortexClient
    from scenarios.soc_consortium.seed import seed_articles

    b_url = f"ws://127.0.0.1:{broker_port}"

    keys_a = {"org": ensure_keys(tmp / "alpha" / "org.pem"),
              "agent": ensure_keys(tmp / "alpha" / "agent.pem", kind="agent")}
    keys_b = {"org": ensure_keys(tmp / "beta" / "org.pem"),
              "agent": ensure_keys(tmp / "beta" / "agent.pem", kind="agent")}

    cfg_a = tmp / "alpha-demo" / "node.yaml"
    cfg_b = tmp / "beta-demo" / "node.yaml"
    cfg_a.parent.mkdir(parents=True, exist_ok=True)
    cfg_b.parent.mkdir(parents=True, exist_ok=True)
    _write_node_cfg(cfg_a, "did:percq:org:soc-alpha", "did:percq:agent:alpha-bot-1", keys_a, b_url)
    _write_node_cfg(cfg_b, "did:percq:org:soc-beta", "did:percq:agent:beta-bot-1", keys_b, b_url)

    node_a = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                        key_paths=keys_a, broker_url=b_url, config_path=cfg_a,
                        embedder_backend_override="cpu")
    node_b = CortexNode(org_did="did:percq:org:soc-beta", agent_did="did:percq:agent:beta-bot-1",
                        key_paths=keys_b, broker_url=b_url, config_path=cfg_b,
                        embedder_backend_override="cpu")
    print("starting node-alpha...")
    await node_a.start()
    print("node-alpha started")
    print("starting node-beta...")
    await node_b.start()
    print("node-beta started")

    await asyncio.sleep(1.0)

    print("seeding...")
    ids = seed_articles(node_a, node_b)
    print(f"seed done ({len(ids)} articles)")

    from scenarios.soc_consortium.agent_alpha import run as alpha_run
    from scenarios.soc_consortium.agent_beta import run as beta_run

    print("running agent-alpha...")
    client_a = CortexClient(node_a)
    alpha_result = alpha_run(client_a, step="all")
    print(f"alpha done (insight: {alpha_result.get('insight_article_id', 'N/A')})")

    print("running agent-beta...")
    client_b = CortexClient(node_a)
    beta_result = beta_run(client_b, node_a)
    print(f"beta done (warning: {beta_result.get('warning_article_id', 'N/A')})")

    print("console up")
    await asyncio.sleep(1.0)

    state = {
        "started": ["broker", "node-alpha", "node-beta", "seed", "alpha", "beta", "console"],
        "seed_article_count": len(ids),
        "alpha_result": alpha_result,
        "beta_result": beta_result,
    }
    (state_dir / "demo_state.json").write_text(json.dumps(state, indent=2))
    print("teardown complete")
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-record-optional", action="store_true",
                    help="Skip recorder (used by tests).")
    args = ap.parse_args()

    state_dir = Path(os.environ.get("DEMO_STATE_DIR", str(REPO / "docs" / "submission")))
    video_dir = Path(os.environ.get("DEMO_VIDEO_DIR", str(state_dir)))
    state_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    async def _run():
        await run_demo(state_dir, video_dir, no_record=args.no_record_optional)
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
