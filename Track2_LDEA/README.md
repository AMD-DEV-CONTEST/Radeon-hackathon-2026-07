# Local Dev Evidence Agent (LDEA)

**Track 2 — Private AI Agents · AMD Radeon Hackathon 2026-07**

> Refuse unverified completion narratives. Answer *what was actually finished* — not chat praise.

LDEA is a **local CLI agent + deterministic evidence ledger**. Planning may use a local Qwen model on AMD ROCm/vLLM; **truth does not**. Only outcomes with `status=verified` may be reported as done. The LLM cannot self-certify.

| Story | Input | Ledger result |
|-------|--------|----------------|
| A | “Everything is done today” (no git / tests) | `abandoned` — achievements empty |
| B | Code diff only | `evidenced` — not “done” |
| C | Claimed fixed + tests still red | `evidenced` — not verified |
| D | Diff + test fail→pass | **`verified`** — may say “fixed” |
| — | Model says “fixed” in chat | **Does not count** |

One offline command for the full matrix (no GPU):  
`node dist/cli.js demo --suite`

---

## Layout in this PR

```text
Track2_LDEA/
  README.md                          ← this file (English)
  docs/
    Project_Specification.md         ← contest Project Spec (English)
    LDEA-pitch-editorial.pdf         ← supplementary PPT (PDF)
    pitch/                           ← HTML slide deck (optional viewer)
  demo/
    demo_video.mp4                   ← ~2:38 real run on Radeon/ROCm
  source/
    local-dev-evidence-agent/        ← agent CLI + tools + report
    airecap-plus/                    ← L0→L1 evidence core (sibling dep)
```

---

## Quick start (judges)

**Requirements:** Node.js ≥ 20, git. GPU optional for offline demos.

```bash
# 1) Evidence core
cd source/airecap-plus
npm install && npm run build

# 2) Agent
cd ../local-dev-evidence-agent
npm install && npm run build && npm test

# 3) Offline demos (no GPU)
node dist/cli.js demo              # abandoned vs verified
node dist/cli.js demo --suite      # four-story gate matrix (recommended)
```

### Local ROCm vLLM (live agent)

On the AMD Radeon machine (validated: **gfx1100**, ROCm **7.2.1**, vLLM **0.16**):

```bash
vllm serve /models/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --served-model-name qwen2.5-7b-instruct \
  --attention-backend TRITON_ATTN \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
```

On the developer machine:

```bash
ssh -L 8000:127.0.0.1:8000 <gpu-host>
export LDEA_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LDEA_LLM_MODEL=qwen2.5-7b-instruct
node dist/cli.js doctor
node dist/cli.js demo --live
```

---

## CLI

| Command | GPU? | Purpose |
|---------|------|---------|
| `demo` / `demo --suite` | No | Rule-based gate stories |
| `close --claim "…"` | No | End-of-day evidence close |
| `run "<goal>"` / `demo --live` | Yes | Agent plans tools under ambiguous goals |
| `doctor` | Yes | Probe local OpenAI-compatible endpoint |
| `ls` / `show` | No | Multi-session ledger navigation |

---

## Architecture (one glance)

```text
User goal / claim
        │
        ▼
 LDEA agent loop  OR  rule pipeline (close/demo)
   tools: claim · git_diff · tests · privacy · show · end · report
        │
        ▼
 airecap-plus  L0 events.jsonl → L1 store.json (rule state machine)
        │
        ▼
 Deterministic report.md / report.json
 (LLM must NOT write verified)
```

Hard rules:

1. Facts come from tool-written L1 outcomes.  
2. Only `verified` may be phrased as completed/fixed.  
3. The LLM must never promote an outcome to `verified`.  
4. Bare claims at session end → `abandoned`.

---

## AMD Radeon / ROCm (measured)

| Item | Value |
|------|--------|
| GPU | AMD Radeon · **gfx1100** (cloud single card) |
| Stack | ROCm **7.2.1** · vLLM **0.16** · Qwen2.5-7B-Instruct |
| Endpoint | `127.0.0.1:8000` only (SSH tunnel from dev machine) |
| Throughput | **~24 tok/s** via tunnel |
| Live E2E | `demo --live` → **verified=1**, 8 tools, **~12s** |

Details: `docs/Project_Specification.md` §6.

---

## Deliverables map

| Contest item | Path |
|--------------|------|
| Project specification | `docs/Project_Specification.md` |
| Source + README | `source/*` + this README |
| Demo video (3–5 min recommended; film ~2:38) | `demo/demo_video.mp4` |
| Supplementary PPT | `docs/LDEA-pitch-editorial.pdf` (+ HTML under `docs/pitch/`) |

---

## License / privacy

Do not commit real `.env`, cloud SSH keys, or production secrets.  
`fixtures/` may contain obvious demo-only fake keys (`sk-demoonly…`).

Team / author: **reflect** (`starsstreaming`) · Application name: **Local Dev Evidence Agent (LDEA)**
