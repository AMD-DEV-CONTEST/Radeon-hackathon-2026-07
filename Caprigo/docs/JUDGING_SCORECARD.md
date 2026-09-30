# Caprigo — Track 2 Judging Scorecard

**How judges should map Caprigo to the Track 2 rubric (100 points).**

| Rubric (Luma Track 2) | Pts | Caprigo evidence |
|-----------------------|-----|------------------|
| Functional completeness & application value | 60 | Real agent runtime: Overview / Session / Board, tools, MCP, missions, permissions, lean-tool filter. Source: https://github.com/doteyeso-ops/caprigo · Spec: `PROJECT_SPEC.md` · Scrap agent answer: `artifacts/agent-demo-20260728.md` · Demo MP4 |
| Scenario / UX (within functional) | — | Operator HUD for local private agents on AMD; not a chat wrapper |
| **AMD Radeon GPU + ROCm optimization** | **40** | Scrap Polaris/Vulkan → contest gfx1100 ROCm/vLLM. **Matched-prompt 7B: 13.73 → 29.21 tok/s (~2.1×)**. Lived-proof scrap 7B@32k ~19 still listed. `AMD.md` · `artifacts/delta.csv` · `MEASUREMENT_LOG.md` |
| Lean-tool inference optimization | (within 40) | `CAPRIGO_LEAN_TOOLS=1` → ~17 schemas vs ~170 (`packages/agent/src/lean-skills.ts` upstream). Scrap Session ~31s with lean: `artifacts/bench-agent-delta.csv` |

## Why this beats “bench-only” entries

Caprigo is an **agent product** that already runs on unsupported AMD scrap silicon, then shows a **measured** uplift on supported ROCm — the scrap→supported story AMD’s program is asking for.

## Gaps (trust > theater)

| Gap | Mitigation |
|-----|------------|
| Demo ~72s vs 3–5 min recommendation | Dense VO walkthrough: `DEMO_WALKTHROUGH.md` |
| Caprigo Session not re-timed on cloud | Decode tok/s is the published ROCm delta; Session scrap CSV included |
| Cloud instance destroyed | Numbers + method reproducible via `REPRODUCTION_README.md` |

## Start here (2 minutes)

1. This scorecard  
2. `AMD.md` headline table  
3. Demo MP4 + `DEMO_WALKTHROUGH.md`  
4. Upstream Caprigo README / Session UI  

— b_Radford / Vibes-Coded
