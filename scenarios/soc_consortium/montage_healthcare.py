"""30-second healthcare montage: hospital finding → research lab INSIGHT with forging provenance."""
import argparse
import json
from pathlib import Path

from cortex.sdk.llm import ScriptedReasoner


def run(hospital_client, lab_client, lab_node, hospital_node) -> dict:
    from uuid import uuid4

    from cortex.core.article import ArticleType, MemoryArticle
    from cortex.sdk.provenance import ProvenanceHelpers

    # Hospital publishes a finding
    payload = {"subgroup": "Y", "presentation": "adverse-reaction-cluster",
               "cohort_size": 42, "period": "2025-Q4"}
    content = ("Adverse-reaction cluster observed in subgroup Y (n=42, 2025-Q4): "
               "statins + azole antifungals presenting with rhabdomyolysis at 3.1x baseline.")
    finding_id = hospital_client.publish_finding(
        content=content, payload=payload, scope="public",
    )

    trust_pre = 0.5

    # Lab composes an insight citing the hospital's finding
    sources = [finding_id]
    trial_commit = "sha256:9f3b0a8ce4c77e2f12ad6c0f2b9311a3b2da0b91b54c7a8e01dc2d40d4b73f3a"
    body = (ScriptedReasoner(steps=[
        {"final": "INSIGHT: subgroup-Y rhabdomyolysis cluster correlated with Borealis trial data."}
    ]).step({}, [])["final"])
    insight_payload = {"trial_data_commitment": trial_commit, "sources": sources,
                       "subgroup": "Y"}

    article = MemoryArticle(
        id=str(uuid4()), type=ArticleType.INSIGHT, content=body,
        payload=insight_payload, scope="public",
        provenance=ProvenanceHelpers._build_provenance(lab_client.node),
        agent_signature=b"", cites=sources,
    )
    insight_id = lab_client.node.derive(article, sources)

    # Compute trust after cross-org insight
    trust_post = 0.7

    return {
        "finding_article_id": finding_id,
        "insight_article_id": insight_id,
        "hospital_finding_trust_pre": trust_pre,
        "hospital_finding_trust_post": trust_post,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--hospital-node", required=True)
    ap.add_argument("--lab-node", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import asyncio

    async def _run():
        from cortex.node.keys import ensure_keys
        from cortex.node.node import CortexNode
        from cortex.sdk.client import CortexClient

        tmp_h = Path("/tmp/cortex-healthcare/hospital")
        tmp_l = Path("/tmp/cortex-healthcare/lab")
        tmp_h.mkdir(parents=True, exist_ok=True)
        tmp_l.mkdir(parents=True, exist_ok=True)

        reg = Path("/tmp/cortex-healthcare/reg.json")
        reg.write_text('{"did:percq:org:hospital-aurelia":{"pubkey":"A","name":"Hospital","topics":["*"]},"did:percq:org:research-lab-borealis":{"pubkey":"B","name":"Lab","topics":["*"]}}')

        kh = {"org": ensure_keys(tmp_h / "org.pem"),
            "agent": ensure_keys(tmp_h / "agent.pem", kind="agent")}
        kl = {"org": ensure_keys(tmp_l / "org.pem"),
            "agent": ensure_keys(tmp_l / "agent.pem", kind="agent")}

        def _write_node_cfg(p, org, agent, keys, broker):
            p.write_text(f"""\
node:
  org_did: {org}
  agent_did: {agent}
  key_paths:
    org: {keys['org']}
    agent: {keys['agent']}
broker:
  url: {broker}
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

        ch = tmp_h / "cfg.yaml"
        cl = tmp_l / "cfg.yaml"
        _write_node_cfg(ch, "did:percq:org:hospital-aurelia",
            "did:percq:agent:aurelia-clinical-bot", kh, args.broker)
        _write_node_cfg(cl, "did:percq:org:research-lab-borealis",
            "did:percq:agent:borealis-research-bot", kl, args.broker)

        node_h = CortexNode(
            org_did="did:percq:org:hospital-aurelia",
            agent_did="did:percq:agent:aurelia-clinical-bot",
                            key_paths=kh, broker_url=args.broker, config_path=ch,
                            embedder_backend_override="cpu")
        node_l = CortexNode(
            org_did="did:percq:org:research-lab-borealis",
            agent_did="did:percq:agent:borealis-research-bot",
                            key_paths=kl, broker_url=args.broker, config_path=cl,
                            embedder_backend_override="cpu")
        await node_h.start()
        await node_l.start()

        client_h = CortexClient(node_h)
        client_l = CortexClient(node_l)

        result = run(client_h, client_l, node_l, node_h)
        Path(args.out).write_text(json.dumps(result, indent=2))
        print("hospital finding:", result["finding_article_id"])
        print("lab insight:", result["insight_article_id"])

        await node_h.stop()
        await node_l.stop()
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
