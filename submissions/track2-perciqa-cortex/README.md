# Perciqa Cortex — Track 2 Submission

> **Track 2: Development & Local Deployment of Private AI Agents**
> AMD AI DevMaster Hackathon 2026-07

**Cortex** is a decentralized network of sovereign memory nodes that lets AI agents share **memory articles** across organizational trust boundaries — without exposing raw data, weights, or trusting a central vendor. Every article carries cryptographic provenance, scoped permissions, and a derived trust score. Nodes run on each organization's own AMD Radeon GPU; a lightweight WebSocket broker routes signed envelopes between nodes using topic and scope-based access control. Agent reasoning runs through Aurora Code Mini V1 served by vLLM on the same ROCm pod — sovereign inference, end to end.

**Live console:** https://cortex.perciqa.com *(real, continuously fed content — no setup required)*

---

## Submission materials

| File | Covers |
|---|---|
| `project-specification.md` | Application scenarios, agent architecture diagram, core capabilities, model introduction & local deployment plan, ROCm optimization summary |
| `inference-optimization.md` | Inference speed optimization on AMD — live Radeon-vs-CPU bench numbers, methodology, resilience design |
| `application-scenarios.md` | Two-SOC threat-intel scenario banks, cross-org fabric operations, non-cyber verticals |
| `Perciqa_Cortex_Hackathon_Deck.pptx` | Supplementary presentation deck |
| `demo_video.md` | Demo video link + narration script |
| `src/` | Source code pointer + environment/startup guide |

---

## Demo video

**Watch:** https://youtu.be/LEs7aeuJ6b8

See `demo_video.md` for the narration script and what each segment demonstrates.

---

## Key measured results (live, remote AMD Radeon GPU)

| Metric | Radeon (GPU) | CPU | Speedup |
|---|---|---|---|
| Embeddings / second (batch) | ~2,060 | ~5.7 | ~360× |
| Queries / second | ~214 | ~2.2 | ~97× |
| P95 query latency | ~4.6 ms | — | — |

GPU: AMD Radeon PRO W7900 (RDNA3, 49 GB VRAM; rocm-smi device `D7070910`), HIP 7.2, PyTorch-ROCm.
Model: Perciqa/Aurora-Code-Mini-V1 served by vLLM on the same ROCm pod.

Numbers are measured live by the bench sidecar and rendered in the console Bench panel — nothing pre-recorded.

---

## Source code

- **Repository:** https://github.com/perciqa/cortex
- **Environment config, startup guide, dependencies:** see `src/README.md` in this submission

---

*All materials in English. Track 2, Perciqa, Cortex.*
