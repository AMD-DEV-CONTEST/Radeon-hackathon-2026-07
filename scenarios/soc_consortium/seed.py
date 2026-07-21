"""Idempotent loader: publishes 10 synthetic CVE findings across Alpha and Beta nodes."""
import argparse
import json
from pathlib import Path

from cortex.sdk.client import CortexClient

DATASET = Path(__file__).parent / "dataset" / "cves.jsonl"


def _cve_already_stored(node, cve_id: str) -> bool:
    """Check if a CVE is already stored in a node by scanning all articles."""
    if node.store is None:
        return False
    for art_id in node.store.iter_ids():
        row = node.store.get(art_id)
        if row is None:
            continue
        try:
            payload = json.loads(row["payload_json"]) if row is not None else {}
            if isinstance(payload, dict) and payload.get("cve_id") == cve_id:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def seed_articles(alpha_node, beta_node) -> list[str]:
    """Publish 10 CVE findings (5 via Alpha, 5 via Beta). Returns article IDs."""
    alpha_client = CortexClient(alpha_node)
    beta_client = CortexClient(beta_node)

    if not DATASET.exists():
        raise FileNotFoundError(f"missing dataset at {DATASET}")

    article_ids: list[str] = []
    for ln in DATASET.read_text().splitlines():
        if not ln.strip():
            continue
        cve = json.loads(ln)
        suffix = int(cve["cve_id"].split("-")[-1])
        is_even = suffix % 2 == 0
        node = alpha_node if is_even else beta_node
        client = alpha_client if is_even else beta_client

        if _cve_already_stored(node, cve["cve_id"]):
            continue

        content = f"{cve['cve_id']} — {cve['description']}"
        payload = {
            "cve_id": cve["cve_id"], "attack_id": cve["attack_id"],
            "actor": cve["actor"], "severity": cve["severity"],
            "published_year": cve["published_year"],
        }
        article_id = client.publish_finding(
            content=content, payload=payload, scope="public",
        )
        article_ids.append(article_id)

    return article_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--node-alpha", required=True)
    ap.add_argument("--node-beta", required=True)
    args = ap.parse_args()

    import asyncio

    from cortex.node.keys import ensure_keys
    from cortex.node.node import CortexNode

    async def _run():
        keys_a = {"org": ensure_keys(Path("/tmp/cortex-seed/alpha/org.pem")),
                  "agent": ensure_keys(Path("/tmp/cortex-seed/alpha/agent.pem"), kind="agent")}
        keys_b = {"org": ensure_keys(Path("/tmp/cortex-seed/beta/org.pem")),
                  "agent": ensure_keys(Path("/tmp/cortex-seed/beta/agent.pem"), kind="agent")}

        from pathlib import Path as _P
        tmp = _P("/tmp/cortex-seed")
        tmp.mkdir(parents=True, exist_ok=True)
        reg = tmp / "reg.json"
        reg.write_text('{"did:percq:org:soc-alpha":{"pubkey":"A","name":"Alpha","topics":["*"]},"did:percq:org:soc-beta":{"pubkey":"B","name":"Beta","topics":["*"]}}')

        cfg_a_path = tmp / "seed-alpha.yaml"
        cfg_b_path = tmp / "seed-beta.yaml"
        cfg_a_path.write_text(f"""\
node:
  org_did: did:percq:org:soc-alpha
  agent_did: did:percq:agent:alpha-bot-1
  key_paths:
    org: {keys_a['org']}
    agent: {keys_a['agent']}
broker:
  url: {args.broker}
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
  file: /tmp/cortex-seed/n.log
""")
        cfg_b_path.write_text(f"""\
node:
  org_did: did:percq:org:soc-beta
  agent_did: did:percq:agent:beta-bot-1
  key_paths:
    org: {keys_b['org']}
    agent: {keys_b['agent']}
broker:
  url: {args.broker}
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
  file: /tmp/cortex-seed/n.log
""")

        node_a = CortexNode(
            org_did="did:percq:org:soc-alpha",
            agent_did="did:percq:agent:alpha-bot-1",
                            key_paths=keys_a, broker_url=args.broker, config_path=cfg_a_path,
                            embedder_backend_override="cpu")
        node_b = CortexNode(
            org_did="did:percq:org:soc-beta",
            agent_did="did:percq:agent:beta-bot-1",
                            key_paths=keys_b, broker_url=args.broker, config_path=cfg_b_path,
                            embedder_backend_override="cpu")
        await node_a.start()
        await node_b.start()

        ids = seed_articles(node_a, node_b)
        for art_id in ids:
            print(f"article_id={art_id}")

        await node_a.stop()
        await node_b.stop()
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
