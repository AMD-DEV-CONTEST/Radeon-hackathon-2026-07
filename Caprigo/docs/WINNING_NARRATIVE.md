# Caprigo — Winning Narrative (Judge Quick-Read)

**Start:** [`JUDGING_SCORECARD.md`](JUDGING_SCORECARD.md)

Track 2 = **agent product (60%)** + **AMD Radeon/ROCm optimization (40%)**. Caprigo is both: a shipping local agent runtime and a measured scrap→supported decode uplift.

## 40% — measured

| Scrap (Polaris / Vulkan) | Contest ROCm (gfx1100 / vLLM) |
|--------------------------|-------------------------------|
| 7B Q4 ~**19** tok/s | Qwen2.5-7B-Instruct **29.21** tok/s (**~1.5×**) |

Log: `MEASUREMENT_LOG.md` · CSV: `../artifacts/delta.csv`

Agent-side: `CAPRIGO_LEAN_TOOLS=1` (~170→17 schemas) so 8GB scrap can run agents; Session lean ~31s (`../artifacts/bench-agent-delta.csv`).

## 60% — product

Overview / Session / Board · tools · MCP · permissions · backend-agnostic gateway.  
Scrap agent completion: `../artifacts/agent-demo-20260728.md`.  
Demo + second-by-second guide: Caprigo MP4 · `DEMO_WALKTHROUGH.md`.

## Trust notes

- Demo ~72s (under 3–5 min recommendation) — walkthrough compensates.  
- Cloud instance destroyed after capture — method reproducible.  
- ROCm Caprigo Session wall-clock not re-run; published cloud metric is decode tok/s.

— b_Radford · `doteyeso@gmail.com`
