# Final Evidence Card

## Complete-product W7900 checkpoint

| Field | Frozen fact |
|---|---|
| Exact implementation | `c9ec07489d17a2abb74bac66a23ade2c775c1b06` (merged through PR #52) |
| User-visible result | M1-M4 generation, evidence inspection, correction-driven invalidation/regeneration, M5 route/privacy review and private HTML/Markdown/JSON delivery |
| Public scenario | `web/e2e/m4.spec.ts::live M4 insight and boundary map journey` |
| Fixture SHA-256 | `2991389c5a3f0c79d38626377ab2980d11d6e7d8ceeb1ddbaeed1f51bf3fe889` |
| Model | `Qwen/Qwen3.5-9B` revision `460979c3d11864dd16408d860ac930a360a2fac2` |
| Serving | BF16, no quantization, vLLM 0.26.0, 20K max context, thinking disabled for bounded structured output |
| Device | Radeon PRO W7900, `gfx1100`, 96 CUs, 48 GiB VRAM; ROCm/HIP 7.2 |
| Network boundary | Application and vLLM bound to pod localhost; temporary local SSH tunnel for browser acceptance only |
| Functional result | `PASS` |
| Evidence packet | `evidence/milestones/e8-a0-w7900/20260806T122806Z/` |

## Stage 2 bounded decision

| Profile | Result | Observed wall time | Boundary |
|---|---:|---:|---|
| S0 | PASS | approximately 120 s | accepted rollback |
| P1 prefix cache | PASS | 109.21 s | selected final launch profile |

This was one public synthetic case per profile, with no repetitions or
statistical estimate. The P1 log reported 0.0% prefix-cache hit rate, so the
timing difference is not attributed to caching. Peak Stage 2 VRAM was not
measured; the 40,741 MiB value is a post-run reading only.

Evidence packet:
`evidence/performance/stage2-minimal/20260806T124938Z/`.

## Submission material locations

| Material | Location or status |
|---|---|
| Source repository | https://github.com/kinnyuww/amd-devmaster-track2-agent - currently private; public access is required before submission |
| Reproducible repository snapshot | `c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd` before the documentation PR merges |
| Project Specification | `docs/submission/e9/deliverables/Experience_Asset_Project_Specification.pdf` |
| Presentation | `docs/submission/e9/deliverables/Experience_Asset_Track2_Deck.pptx` |
| Demo | https://drive.google.com/drive/folders/1_cOmcYBIJuPfkoJ4VuA7ZuBYV8nYB8yr?usp=drive_link - signed-out access must be enabled |
| Official organizer PR | Pending owner-authorized publication |

Do not combine this complete-product evidence with service-only Stage 1
metrics as if they measured the same unit. Do not expose secrets, private
prompts, internal hostnames or raw private evidence.
