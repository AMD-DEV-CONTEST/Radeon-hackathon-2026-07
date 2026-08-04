# Radeon Cloud session 2b results

## Outcome

Session 2b verified the previously missing official browser transport, but it
did not complete a real browser-rendered generation. The official `rc-tunnel`
installer and identity prerequisites were present in a fresh Notebook pod,
`rc-tunnel 0.3.0` exposed only the loopback FastAPI port, and the local Chrome
frontend authenticated successfully with valid TLS and explicit CORS.

The first browser job failed before model loading because the fresh pod did not
have Diffusers installed. The previously validated inference package versions
were restored without replacing PyTorch. The second job then exposed a worker
recovery defect: a pipeline object whose model load had failed remained cached,
so the retry skipped `load_model()`. The worker now assigns the reusable
pipeline only after model loading succeeds, with a regression test.

No third GPU job was started because the session had reached its shutdown
checkpoint. The official tunnel and backend were stopped, the single instance
was destroyed, and Radeon Cloud displayed **No active instance**.

## Session record

| Field | Observed result |
|---|---|
| Date | 2026-07-25 |
| Fresh template | `BrandPilot-Track1-Tunnel` |
| Container | AMD OneClick Base ROCm 7.2.1, Python 3.12 |
| Deploy type | Notebook / JupyterLab |
| Storage | Persistent PVC |
| Visibility | Profile only |
| SSH | Disabled |
| Starting balance | 5 credits |
| Final displayed balance | 5 credits |
| Launch time | 2026-07-25 12:58:04 PKT |
| Ready time | 2026-07-25 12:58:44 PKT |
| Destroy confirmation | 2026-07-25 13:32:31 PKT |
| No-active confirmation | Approximately 2026-07-25 13:32:36 PKT |
| Ready-to-destroy duration | Approximately 33 minutes 47 seconds |
| Official installer | Present and executable |
| Identity directory | Present |
| Broker setting | Present; value was not printed |
| `rc-tunnel` | 0.3.0 |
| Tunnel | Active successfully, then stopped |
| Support escalation | Not required |

## Verification matrix

| Item | Result | Verification boundary |
|---|---|---|
| Fresh template and PVC | Passed | Radeon Cloud UI |
| Official tunnel prerequisites | Passed | Sanitised cloud check |
| Source archive hash | Passed | Local and cloud SHA-256 match |
| FastAPI loopback binding | Passed | Radeon Cloud |
| Unauthenticated status | 401 | Windows through official tunnel |
| Authenticated status | Passed | Windows through official tunnel |
| TLS certificate validation | Passed | Windows default verified TLS |
| Local-origin preflight | Passed | Windows through official tunnel |
| Unknown origin rejection | Passed | Windows through official tunnel |
| AMD Radeon and ROCm status | Passed | API and Chrome connection panel |
| Exact model and revision | Passed | API and Chrome connection panel |
| Lazy model state | Passed | `model_loaded=false` before jobs |
| Browser connection diagnostics | Passed | Chrome |
| Project creation | Passed | Chrome to FastAPI |
| Product upload | Passed | Chrome to FastAPI |
| First job | Failed before model load | Missing ephemeral Diffusers package |
| Inference packages | Restored | Validated versions; PyTorch unchanged |
| Second job | Failed before model load | Failed-load pipeline was incorrectly cached |
| Failed-load recovery fix | Implemented | Local source and cloud runtime |
| Duplicate-submit rejection | Not reached | No job remained active long enough |
| Diffusion step polling | Not reached | No diffusion run completed |
| Protected output retrieval | Not reached | No completed output |
| Browser output rendering | Not reached | No completed output |
| Measured generation metadata | Not available | No completed output |
| Human review | Not reached | No completed output |
| Refresh result/review persistence | Not reached | No completed output |
| Runtime connection restoration | Passed | Current Chrome session |
| Direct evidence downloader | Not run | No completed job to retrieve |
| Tunnel/backend shutdown | Passed | Cloud terminal |
| Instance destruction | Passed | Radeon Cloud UI |
| No active instance | Passed | Radeon Cloud UI |

## Measured generation values

No completed generation occurred in session 2b, so model-load duration,
generation duration, total job duration, peak allocated VRAM, peak reserved
VRAM, and output SHA-256 are **not available**. The validated model boundary
remained:

- model `stabilityai/stable-diffusion-xl-base-1.0`
- revision `462165984030d82259a11f4367a4eed129e94a7b`
- `StableDiffusionXLImg2ImgPipeline`
- 768 × 768, 15 steps, strength 0.35, guidance 6.5
- seed `20260725`

These settings were not reported as a new successful generation.

## Issues and fixes

1. Direct Git transport failed without a TLS bypass. The exact pushed commit
   was archived locally, hashed, uploaded through JupyterLab, hashed again, and
   extracted only after the SHA-256 values matched.
2. The fresh pod lacked `aiofiles`; the pinned backend dependency was installed.
3. The fresh pod lacked Diffusers. The previously measured inference package
   versions were installed without replacing PyTorch.
4. A failed model load left an unusable pipeline cached. The worker now caches
   a candidate only after `load_model()` succeeds. A regression test covers a
   failed first load followed by a successful retry.
5. The Next.js development console reported hydration mismatches. App-owned
   trailing class-name differences were removed; the remaining browser
   extension attribute is outside the application.
6. Browser-control handles reset near the shutdown checkpoint. No additional
   generation was started; shutdown and instance destruction took priority.

## Evidence and sanitisation

The retained screenshots show the fresh template title, profile-only
visibility, persistent PVC setting, and final no-active-instance state. They
exclude the account email, access token, tunnel URL, internal hostname, and
instance identifier.

No generated image, job metadata, result metadata, review state, or evidence
bundle is claimed for session 2b because no job completed. The temporary source
archive and transient URL/token transfer files were removed.

## Current limits

- Browser-to-official-tunnel authentication and CORS are verified.
- Full browser-to-FastAPI-to-Radeon generation remains incomplete.
- Browser result rendering, review persistence, and result refresh persistence
  remain unverified on real hardware.
- Mock remains the default and experimental Radeon mode remains disabled by
  default.
- IP-Adapter, masking/compositing, ControlNet, LoRA, training, video, batch
  generation, and permanent hosting remain outside this phase.
- Product identity, logo, and packaging-text preservation are not validated.
- Production or commercial clearance is not claimed.
