# Demo Video — Perciqa Cortex

**Video:** https://youtu.be/LEs7aeuJ6b8
**Duration:** ~4 minutes
**Layout:** Terminal (left) | Live console at cortex.perciqa.com (right)

## What the demo shows

| Segment | What happens on screen |
|---|---|
| Act 1 — Hook | Title card; the single-tenant memory problem (Pinecone, Qdrant, Mem0 comparison) |
| Act 2 — Architecture | Two sovereign nodes (SOC Alpha, SOC Beta) connected through a lightweight fabric broker |
| Act 3A — Publish | SOC Alpha's agent publishes an APT29 finding; the node signs with Ed25519, embeds on the AMD GPU via ROCm, and broadcasts to peers. The console article feed updates and the ATT&CK matrix technique lights up in real time |
| Act 3B — Cross-org Query | SOC Beta's agent asks "what's known about credential access techniques?" — it has never seen Alpha's data. Five results return, ranked by a hybrid of cosine similarity and trust score, each carrying full provenance (which org, when, SHA-256 commitment of source data) |
| Act 3C — Derive | Alpha composes a new insight from the top retrieved findings across both organizations; the provenance graph expands and the new article inherits trust from its citations |
| Act 4 — AMD Angle | Live bench panel: Radeon vs CPU embeds/sec and queries/sec updating in real time (remote GPU, not pre-recorded). `/api/rocm-info` shows HIP 7.2, device, VRAM usage; `/api/llm-info` shows Aurora Code Mini V1 online |
| Act 5 — Generality | Same fabric protocol applied to healthcare, finance, research consortia |
| Act 6 — Close | Open-source, repo link |

## Measured performance shown live

- ~2,060 embeddings/sec on Radeon vs ~5.7 on CPU (~360×)
- ~214 queries/sec on Radeon vs ~2.2 on CPU
- P95 query latency ~4.6 ms
- GPU: AMD Radeon PRO W7900 (RDNA3, 49 GB VRAM, rocm-smi device `D7070910`), HIP 7.2.53211, PyTorch-ROCm

## What the audience can verify themselves

The console at https://cortex.perciqa.com is live: the content pipeline publishes fresh MITRE ATT&CK threat-intel findings from both SOCs every ~30 minutes, the bench panel renders the same live numbers, and the `/api/rocm-info` + `/api/llm-info` endpoints confirm the remote AMD GPU and the served model.
