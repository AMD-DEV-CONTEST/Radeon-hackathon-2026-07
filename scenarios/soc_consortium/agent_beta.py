"""SOC Beta agent: query → publish 2 corroborating findings → derive WARNING."""
import argparse
import json
from pathlib import Path

from cortex.sdk.llm import ScriptedReasoner

CORROBORATING = [
    {"cve_id":"CVE-2023-40121",
     "description":"Lockbit affiliate chained T1486 after T1190 foothold on Exchange 2019 OWA.",
     "attack_id":"T1486","actor":"Lockbit","severity":"critical","published_year":2023},
    {"cve_id":"CVE-2024-50012",
     "description":"Lockbit-v3 reused stolen RDP creds (T1078) then deployed T1486.",
     "attack_id":"T1486","actor":"Lockbit","severity":"high","published_year":2024},
]


def _cve_already_stored(node, cve_id: str) -> bool:
    if node.store is None:
        return False
    for art_id in node.store.iter_ids():
        row = node.store.get(art_id)
        if row is None:
            continue
        try:
            payload = json.loads(row["payload_json"])
            if isinstance(payload, dict) and payload.get("cve_id") == cve_id:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def publish_two_findings(client, node) -> list[str]:
    new_ids: list[str] = []
    for rec in CORROBORATING:
        content = f"{rec['cve_id']} — {rec['description']}"
        payload = {
            "cve_id": rec["cve_id"], "attack_id": rec["attack_id"],
            "actor": rec["actor"], "severity": rec["severity"],
            "published_year": rec["published_year"],
        }
        article_id = client.publish_finding(
            content=content, payload=payload, scope="public",
        )
        new_ids.append(article_id)
    return new_ids


def fetch_alpha_insight(client):
    """Find Alpha's INSIGHT article from the fabric."""
    hits = client.search("APT29 T1059.001 insight", scopes={"public"}, top_k=10, min_trust=0.0)
    for r in hits:
        if r.article.type == "insight":
            return r.article_id
    raise RuntimeError("no Alpha INSIGHT in fabric yet")


def emit_warning(client, insight_id: str, finding_ids: list[str]) -> str:
    from uuid import uuid4

    from cortex.core.article import ArticleType, MemoryArticle
    from cortex.sdk.provenance import ProvenanceHelpers

    sources = [insight_id, *finding_ids]
    reasoner = ScriptedReasoner(
        steps=[{"final": "WARNING: Lockbit ransomware T1486 activity detected."}]
    )
    body = reasoner.step({}, [])["final"]
    payload = {"attack_id": "T1486", "actor": "Lockbit", "severity": "critical",
               "source_article_ids": sources}

    article = MemoryArticle(
        id=str(uuid4()), type=ArticleType.WARNING, content=body,
        payload=payload, scope="public",
        provenance=ProvenanceHelpers._build_provenance(client.node),
        agent_signature=b"", cites=sources,
    )
    return client.node.derive(article, sources)


def run(client, node) -> dict:
    """Run agent beta: query → publish 2 findings → derive WARNING."""
    hits = client.search(
        "ransomware techniques Lockbit T1486",
        scopes={"public"}, top_k=5, min_trust=0.0,
    )
    new_findings = publish_two_findings(client, node)
    insight_id = fetch_alpha_insight(client)
    warning_id = emit_warning(client, insight_id, new_findings)
    return {
        "query_hits": [r.article_id for r in hits],
        "new_findings": new_findings,
        "insight_article_id": insight_id,
        "warning_article_id": warning_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--reasoner", choices=["scripted", "vllm"], default="scripted")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import asyncio

    from cortex.node.keys import ensure_keys
    from cortex.node.node import CortexNode

    async def _run():
        keys = {"org": ensure_keys(Path("/tmp/cortex-beta/org.pem")),
                "agent": ensure_keys(Path("/tmp/cortex-beta/agent.pem"), kind="agent")}
        tmp = Path("/tmp/cortex-beta")
        tmp.mkdir(parents=True, exist_ok=True)
        reg = tmp / "reg.json"
        reg.write_text('{"did:percq:org:soc-beta":{"pubkey":"A","name":"Beta","topics":["*"]}}')

        cfg = tmp / "beta.yaml"
        cfg.write_text(f"""\
node:
  org_did: did:percq:org:soc-beta
  agent_did: did:percq:agent:beta-bot-1
  key_paths:
    org: {keys['org']}
    agent: {keys['agent']}
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
  file: /tmp/cortex-beta/n.log
""")

        from cortex.sdk.client import CortexClient
        node = CortexNode(
            org_did="did:percq:org:soc-beta",
            agent_did="did:percq:agent:beta-bot-1",
            key_paths=keys, broker_url=args.broker, config_path=cfg,
            embedder_backend_override="cpu",
        )
        await node.start()
        client = CortexClient(node)
        result = run(client, node)
        Path(args.out).write_text(json.dumps(result, indent=2))
        print("beta query hits:", result["query_hits"])
        print("beta new findings:", result["new_findings"])
        print("warning published:", result["warning_article_id"])
        await node.stop()
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
