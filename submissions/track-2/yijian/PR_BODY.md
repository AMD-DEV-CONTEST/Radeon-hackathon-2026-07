## YIJIAN - Evidence-Grounded Go Review Agent

**Track 2 | Ali Moqi**

YIJIAN is a private Go review Agent whose core inference and KataGo analysis run on an AMD Radeon PRO W7900 with ROCm. It combines a bounded tool planner, deterministic Go rules, KataGo, source-labelled local RAG, explicit opt-in memory, model-based teaching synthesis, output validators, and deterministic fallback.

### Reproduce first

```powershell
cd submissions/track-2/yijian/source
powershell -ExecutionPolicy Bypass -File scripts/reproduce_public.ps1
```

This creates a clean temporary Python 3.13 environment, installs the pinned lock, validates every public SHA-256, compiles the source, runs all 189 public backend and training tests, and checks application health. The public W7900 path starts fixed-revision Qwen3-14B BF16 through vLLM without requiring the restricted adapter.

### Agent capabilities

- task decomposition and strict tool whitelist;
- goboard legal replay and KataGo evidence;
- local source-labelled RAG;
- explicit opt-in/view/delete memory;
- multi-turn questions bound to the current game, move, and evidence;
- deterministic fallback when model services time out or stop.

### Verified AMD results

- Qwen3-14B BF16 smoke, 30-step micro, and exact 2-epoch / 90-step LoRA training completed on the W7900;
- 220/220 Agent plan cases, 24/24 failure/privacy cases, and 39/40 unseen evidence-faithful cases passed;
- 0.72 / 0.75 / 0.78 coexistence profiles each completed 30/30 with zero OOM;
- selected 0.72 profile combined P95: 10.3355 seconds.

### Fail-closed release decision

The trained LoRA did not pass the final anonymous human gate: stable 27B scored 4.6133, base 14B 2.8500, and LoRA 2.5400, with five severe contradictions assigned to LoRA. The sealed-once set remains unopened and the competition alias therefore stays on the stable 27B service. The failed candidate is documented, not presented as the released model.

### Materials

- project specification Markdown and PDF;
- architecture SVG;
- complete public-safe source and pinned reproduction instructions;
- performance, model card, evidence index, and machine-readable status;
- Track 2 presentation;
- demo video: final recording and English subtitle upload in progress; link will be added before the deadline.
