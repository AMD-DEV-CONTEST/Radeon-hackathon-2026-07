# Perciqa Cortex — Judge-Facing README

**Track:** AMD AI DevMaster Hackathon 2026 — Track 2 (Radeon/ROCm)

**One-line pitch:** A decentralized, cryptographically-proven agent-memory fabric
where two sovereign organizations' agents share findings without ever exchanging
raw data — every article carries its source hash, its producer DID, and a
machine-verifiable trust score.

## Submission artifacts

| Artifact | Path |
|---|---|
| Pitch deck outline | [`./slides_outline.md`](./slides_outline.md) |
| End-to-end smoke test | `pytest tests/e2e/test_demo_e2e_smoke.py` |
| Source code | [scenarios/soc_consortium/](../../scenarios/soc_consortium/) |
| Demo narration script | [scenarios/soc_consortium/demo_script.md](../../scenarios/soc_consortium/demo_script.md) |

## Architecture in one paragraph

Two tenant nodes (one per org) embed, sign, store, query, and derive memory
articles locally on AMD Radeon GPUs via ROCm. A single WebSocket broker routes
envelopes with topic+scope ACLs.

## Running the demo locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python scenarios/soc_consortium/demo_run.py --no-record-optional
```

## AMD angle (the 40-point axis)

- Embeddings: BAAI/bge-small-en-v1.5 on ROCm via PyTorch-on-ROCm
- Reasoning: Llama-3 8B via vLLM-on-ROCm (routed through `CortexAgent`'s reasoner)
- Bench: per-node sidecar measures Radeon vs CPU throughput for both the embed
  model and the reasoner

## Roadmap (post-hackathon)

1. Open-source the fabric protocol as `perciqa-cortex-spec`
2. Ship a hosted ISAC offering for SOC consortium customers
3. Extend to healthcare (RWE loop) and finance (fraud intel) registries
