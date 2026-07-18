# Perciqa Cortex — Pitch Deck Outline

**Format:** 10 slides, ~20 s each, 2-minute total runtime.

### Slide 1 — Title
- Title: "Perciqa Cortex"
- Subtitle: "Decentralized agent memory with cryptographic provenance"
- AMD AI DevMaster Hackathon 2026 — Track 2

### Slide 2 — Problem
- Today every SOC is an island
- Cross-org sharing = CSV drops, no provenance, no trust
- Sovereignty vs collaboration is unsolved

### Slide 3 — Solution
- Federated memory articles, signed + hashed at source
- Two sovereign SOCs, one broker, cross-org query
- Trust formula baked in: 0.6·base + 0.4·source − penalty

### Slide 4 — Live Demo (screenshots / 30 s clip)
- ATT&CK matrix lighting up
- Provenance graph edges forming
- Bench sidecar panel

### Slide 5 — Architecture diagram
- Tenant nodes ↔ Broker ↔ Console ← Bench
- Embedder (bge-small) + Reasoner (Llama-3 8B/vLLM)

### Slide 6 — AMD angle (load-bearing)
- Why Radeon matters: sovereign inference can't be vendor-lock
- Throughput numbers from bench sidecar
- Production target: MI300X

### Slide 7 — Generality (montage proof)
- Hospital + Research Lab framework reuses the same fabric
- Patient data never leaves the hospital

### Slide 8 — Roadmap
- Spec → OSS → ISAC offering → healthcare/finance registries

### Slide 9 — Team
- orbinix (lead), excelle (co-author)

### Slide 10 — Q&A / call to action
- "Imagine a 2028 where agents have verifiable memory across
  organizations. This is the first step."
