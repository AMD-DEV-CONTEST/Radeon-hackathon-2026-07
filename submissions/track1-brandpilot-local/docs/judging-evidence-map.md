# Track 1 judging evidence map

Every submission claim maps to a precise repository artifact and a stated
verification boundary.

## Functional completeness, application value, and innovation - 80 points

| Judging area | What judges can inspect | Evidence path | Boundary |
|---|---|---|---|
| Problem and use case | One product asset becomes a coherent campaign workflow for small brand/creative teams | `README.md`, `submission/project-profile.md` | Product narrative, not market-size research |
| Complete workflow | Asset intake, campaign brief, styles, formats, generation, result editing, and review | `frontend/app/studio/page.tsx`, `frontend/app/results/[id]/page.tsx`, final screenshots | Results shown in the local demo are mock-labelled |
| Multimodal input | PNG/JPEG/WebP validation, decoding, safe naming, and project association | `backend/app/services/uploads.py`, `backend/tests/test_api.py` | Uses the rights-safe example asset |
| Campaign configuration | Objective, audience, benefits, tone, colors, creative style, format, and guardrails | `frontend/app/studio/page.tsx` | Verified locally |
| Multi-format concepts | Instagram, story, and campaign format choices with multiple creative directions | `frontend/components/ui.tsx`, mock result screenshots | Demonstrated in mock mode |
| Human review | Approve, reject, needs-changes, copy edit, regeneration, and persisted review state | `backend/app/api/routes.py`, `frontend/app/results/[id]/page.tsx`, `evidence/final-submission/screenshots/review-approved.png` | Local browser mock flow; real Approved state verified through loopback API |
| Responsive design | Desktop and mobile home/studio views, accessible controls, no horizontal overflow | `evidence/final-submission/screenshots/`, `frontend/tests/experimental.test.ts` | Local production build |
| Responsible disclosure | Mock/Radeon labels, review gate, rights-cleared input, narrow claims | `docs/responsible-ai.md`, `docs/final-claim-audit.md` | No production or preservation claim |
| Local-first architecture | Mock default, opt-in experimental path, validated storage, protected results | `docs/architecture.md`, `backend/app/core/config.py`, `frontend/lib/experimental.ts` | Experimental public edge is temporary, not hosted |
| Innovation | Campaign system combines brand brief, visuals, copy, output framing, disclosure, and review in one workspace | `README.md`, presentation, product screenshots | Prototype differentiation, not a comparative market claim |

## Operational performance on AMD Radeon GPU - 20 points

| Evidence | Verified value | Repository path |
|---|---|---|
| GPU | AMD Radeon Graphics, `gfx1100`, one device, 48 GiB reported memory | `evidence/radeon-session-1/pytorch-gpu-summary.json` |
| ROCm/HIP | `7.2.53211-e1a6bc5663` | `evidence/radeon-session-1/pytorch-gpu-summary.json` |
| PyTorch | `2.9.1+gitff65f5b` ROCm build | `evidence/radeon-session-1/pytorch-gpu-summary.json` |
| Model | `stabilityai/stable-diffusion-xl-base-1.0` | `evidence/radeon-session-1/generation-metadata.json` |
| Exact revision | `462165984030d82259a11f4367a4eed129e94a7b` | `evidence/radeon-session-1/model-revision.txt` |
| Parameters | 768 x 768, 15 steps, strength 0.35, guidance 6.5, seed 20260725 | `evidence/radeon-session-1/generation-metadata.json` |
| Real output | Successful SDXL img2img result | `evidence/radeon-session-1/generated-output.png` |
| Cold model load | 132.295 seconds | `evidence/radeon-session-1/generation-metadata.json` |
| Generation / total | 222.111 / 357.706 seconds | `evidence/radeon-session-1/generation-metadata.json` |
| Peak memory | 13.41 GiB allocated / 14.31 GiB reserved | `evidence/radeon-session-1/generation-metadata.json` |
| Output integrity | SHA-256 `bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452` | `evidence/radeon-session-1/generation-metadata.json` |
| FastAPI integration | One authenticated loopback job completed in 252.243 seconds and persisted an Approved review | `docs/radeon-session-2-results.md`, `evidence/radeon-session-2/session-summary.json` |
| Official browser transport | Session 2b verified TLS, 401/200 auth, CORS, project creation, and upload | `docs/radeon-session-2b-results.md` |
| Official tunnel | `rc-tunnel 0.3.0` installed and activated | `docs/radeon-session-2c-results.md`, `docs/radeon-session-3-results.md` |
| DNS blocker | Official assigned hostname did not resolve in the final bounded retry | `evidence/radeon-session-3/dns-python-final.json`, `evidence/radeon-session-3/dns-powershell-final.json` |
| Shutdown | Final instance destroyed; no active instance shown | `evidence/radeon-session-3/screenshots/02-destroyed-no-active-instance.png` |

## Fast review path

1. Open `README.md` for the product and validation matrix.
2. Open `evidence/final-submission/screenshots/` for the product workflow.
3. Open `evidence/radeon-session-1/generated-output.png` and
   `generation-metadata.json` for real Radeon output and measurements.
4. Open `evidence/radeon-session-2/session-summary.json` for the authenticated
   application-integrated loopback result.
5. Open `docs/radeon-session-3-results.md` for the honest public-edge boundary.
