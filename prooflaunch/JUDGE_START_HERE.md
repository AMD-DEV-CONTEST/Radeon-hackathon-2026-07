# ProofLaunch — Track 1 Judge Start Here

**Team:** Banyan  
**Application:** ProofLaunch  
**Proposed PR title:** `Track 1, Banyan, ProofLaunch: Multimodal GTM Studio`

ProofLaunch is a governed multimodal GTM employee. It converts a rights-bound
product brief into an evidence-linked strategy, channel plan, copy, SEO/GEO
pack, calendar, 4K image, mastered audio and 4K campaign film. A code-enforced
Harness keeps publishing and spend outside model authority.

## Fastest evaluation path

1. Open the finished product website at `web/index.html`, then start at
   `/control/frontier-gtm`.
2. Run the deterministic governed replay:

   ```bash
   .venv/bin/python demos/run_track1_demo.py
   ```

3. Inspect `artifacts/judge-track1-replay-v1/demo-receipt.json` and
   `artifacts/judge-track1-replay-v1/gtm-cockpit.json`.
4. View the actual 4K campaign pack under
   `evidence/v10/local-campaign-pack-v1/delivery-v6/`.
5. Read the compact submission kit in `submission/track1-prooflaunch/`.

The replay writes to a disposable evaluator directory so it cannot mutate the
sealed canonical submission receipt. It starts the real single-port API on
loopback, executes the
Graph/Loop/Harness workflow, crosses a synthetic control-plane release gate,
registers ten exact deliverables, and verifies their hashes. It makes no new
model call and is deliberately **not** labeled as Radeon evidence.

## Current verified result

| Evidence | Observed result |
|---|---:|
| Product-critical Python regression | 827/827 passed |
| UI tests | 17/17 passed |
| Route validation | 10/10 passed |
| Web build | 46 routes, 60 same-origin API contracts |
| Final integrity locks | 4/4 passed |
| Desktop + mobile horizontal overflow | none observed |
| Run-bound deliverables | 10/10 registered |
| Last-mile production lanes | 14/14 mechanically ready |
| Monotonic production-quality state | `mechanically_ready`; G1 editor, G2 named blind PK and G3 production effect blocked |
| Named-product challenger dossiers | 13/13 mechanically admitted |
| 4K campaign media | PNG + 48 kHz stereo WAV + 4K MP4 |
| Agentic production-readiness audit | 9 pass, 3 explicit gaps |
| Automatic publish/send/spend | 0 |
| Named human PK wins | 0 observed |
| Historical Gemma-4 inference on Radeon/HIP | observed in archived executed Notebook |
| Historical Gemma-4 LoRA training | 250 steps; adapter save observed |
| Fresh end-to-end ProofLaunch Radeon run | not observed |

## Why the architecture is an agent, not a prompt chain

- **Graph:** evidence → strategy → creation → audit/repair → human release →
  delivery → observation → approved learning.
- **Loop:** bounded candidate generation, contract validation, critique and one
  repair pass within a node.
- **Harness:** typed inputs, tenant isolation, content-addressed artifacts,
  rights checks, budget and tool limits, immutable approvals, audit events and
  fail-closed external-action gates.
- **Adaptive capability graph:** one supervisor selects bounded specialists for
  business model, lifecycle, budget, risk, market and platform context; hardware
  and model providers are replaceable execution resources rather than product
  identity.

## Mandatory open gate

The archived executed Notebook at
`notebooks/gemma4_emotion_lora_modelscope_single_gpu_original.ipynb` records
one `AMD Radeon Graphics` device, HIP `7.2.53211`, Gemma-4 inference and a
250-step LoRA run. Validate its immutable saved outputs with:

```bash
python3 scripts/validate_radeon_historical_evidence.py
```

The 190.9-second product-operation Demo Video is included at
`docs/ProofLaunch_Demo_Video_191s.mp4`. It shows the working product, campaign
outputs, responsive operation and human release boundary. It does **not** show
the historical Notebook run or a fresh AMD Radeon/ROCm GTM campaign run. The
remaining hardware gate is a fresh end-to-end run from CLI or GUI to final
campaign output with latency, peak VRAM and output hashes. Use
`submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md`; do not substitute a
Mac replay, cloud-provider asset or synthetic receipt.

## Primary files

- `docs/COMPETITION_PACKAGE.md` — canonical Track 1 deliverable map
- `docs/INSTALLATION.md` — local, web and Radeon reproduction
- `docs/MODEL_CARD.md` — model roles, limitations and safety
- `docs/EVALUATION.md` — evidence hierarchy and claims boundary
- `evidence/RADEON_EVIDENCE_INDEX.md` — tiered Radeon/ROCm evidence map
- `evidence/RADEON_GEMMA4_EXECUTION_RECEIPT_2026-08-06.json` — hash-bound historical execution receipt
- `notebooks/gemma4_emotion_lora_modelscope_single_gpu_original.ipynb` — archived executed Radeon Notebook
- `submission/track1-prooflaunch/README.md` — evaluator README
- `submission/track1-prooflaunch/PR_BODY.md` — English PR body
- `submission/track1-prooflaunch/SUBMISSION_MANIFEST.json` — claim/evidence map
- `docs/ProofLaunch_Project_Profile.pdf` — required profile PDF
- `docs/ProofLaunch_Submission_Deck.pptx` — supplementary English deck
- `docs/ProofLaunch_Demo_Video_191s.mp4` — 190.9-second product-operation Demo Video
- `docs/DEMO_VIDEO_SHOTLIST.md` — 3:40 recording script
- `SUBMISSION_GATE.json` — fail-closed competition gate
