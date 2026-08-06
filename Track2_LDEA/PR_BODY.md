# Track 2 Submission — Local Dev Evidence Agent (LDEA)

**Track:** Track 2 — Private AI Agents (local deployment on AMD Radeon / ROCm)  
**Team / author:** reflect (`starsstreaming`)  
**Application name:** Local Dev Evidence Agent (LDEA)

## One-liner

Refuse **unverified completion narratives**. A local CLI agent plans with Qwen on ROCm/vLLM; a deterministic L0→L1 evidence ledger decides what may be called “done.” Only `status=verified` counts. The LLM cannot self-certify.

## What’s in this PR

```text
Track2_LDEA/
  README.md                         English startup + architecture
  docs/Project_Specification.md     Contest project specification (EN)
  docs/LDEA-pitch-editorial.pdf     Supplementary PPT (PDF)
  docs/pitch/                       HTML 8-page deck + index
  demo/demo_video.mp4               ~2:38 real run (Radeon/ROCm path)
  source/airecap-plus/              Evidence core (L0→L1 state machine)
  source/local-dev-evidence-agent/  Agent CLI, tools, report, demos
```

## Highlights

| Area | Detail |
|------|--------|
| Gate matrix | `demo --suite` → abandoned / evidenced / evidenced / **verified** (offline, no GPU) |
| Live agent | `demo --live` on local Qwen tool-calls → verified report |
| AMD stack | gfx1100 · ROCm 7.2.1 · vLLM 0.16 · Qwen2.5-7B · ~24 tok/s · live E2E ~12s |
| Privacy | Inference on `127.0.0.1` + SSH tunnel; privacy scan column on report |

## Judge quick path

```bash
cd Track2_LDEA/source/airecap-plus && npm install && npm run build
cd ../local-dev-evidence-agent && npm install && npm run build && npm test
node dist/cli.js demo --suite
# with ROCm vLLM tunnel:
# node dist/cli.js doctor && node dist/cli.js demo --live
```

## Deliverables checklist

- [x] Project specification document  
- [x] Complete source + README (env, startup, deps)  
- [x] Demo video (real operation on AMD Radeon path)  
- [x] Supplementary PPT (PDF + HTML)

Full detail: `Track2_LDEA/docs/Project_Specification.md`
