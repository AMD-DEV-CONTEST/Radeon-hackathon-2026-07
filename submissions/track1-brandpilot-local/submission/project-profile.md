# BrandPilot Local - Project Profile

## Project overview

BrandPilot Local is an AMD Radeon-powered creative studio prototype that turns
a rights-cleared product image and campaign brief into reviewable,
platform-ready marketing concepts. It combines campaign configuration, visual
directions, copy, output formats, and human review in one responsive workspace.

**Track:** Track 1 - Multimodal AI / Development of Multimodal Content Creation Tools

**Team:** Talal Khawaja and Aqeela Urooj

## Problem

Small brands and creative teams assemble campaigns across disconnected prompt
tools, design files, copy documents, and approval threads. That slows iteration,
weakens traceability, and can expose sensitive product assets to unnecessary
external services.

## Target users and scenarios

- Independent brands launching a new product
- In-house marketing teams adapting a campaign across social formats
- Creative studios exploring multiple directions before production
- Privacy-conscious teams that want a local-first workflow and explicit review

Primary scenarios include product launches, seasonal campaigns, promotional
sales, social content, and cross-format concept exploration.

## Solution and workflow

1. Upload a validated PNG, JPEG, or WebP product image.
2. Define product, objective, audience, benefits, tone, brand colors, and
   negative guardrails.
3. Choose creative styles and output formats.
4. Generate four clearly labelled mock campaign concepts locally, or connect
   explicitly to a temporary authenticated Radeon worker.
5. Inspect visual, copy, format, and disclosure metadata.
6. Approve, reject, request changes, edit copy, or regenerate.
7. Reopen persisted project and review state.

## System architecture

The Next.js frontend calls a FastAPI backend for validation, project storage,
results, and human review. Mock mode is always the default and needs no ML
runtime. The experimental path is disabled unless configured and connects to a
single-job worker that lazily loads a pinned SDXL img2img pipeline on AMD Radeon
through PyTorch/HIP. Experimental output is protected by bearer authentication
and retrieved through authenticated fetches.

The worker binds to loopback, permits one GPU job at a time, reuses the loaded
pipeline, records genuine stages/steps and measured metadata, and refuses CPU
or mock fallback.

## Multimodal AI implementation

The application combines image input with a structured text campaign brief.
The verified image-to-image pipeline transforms the product image according to
the selected campaign direction. The surrounding application stores the
product/campaign context, result metadata, copy, formats, and human decision.

## AMD Radeon and ROCm adaptation

- AMD Radeon Graphics (`gfx1100`), one device, 48 GiB reported memory
- PyTorch `2.9.1+gitff65f5b`
- HIP/ROCm `7.2.53211-e1a6bc5663`
- `StableDiffusionXLImg2ImgPipeline` in `torch.float16`
- Radeon exposed through PyTorch's `torch.cuda` API
- Exact model revision pinned for reproducibility
- No CPU offload, attention slicing, CPU fallback, or mock fallback
- Lazy load, pipeline reuse, and single-job serialization in the API worker

## Verified model and performance

| Item | Verified value |
|---|---|
| Model | `stabilityai/stable-diffusion-xl-base-1.0` |
| Revision | `462165984030d82259a11f4367a4eed129e94a7b` |
| Output | 768 x 768 |
| Steps / strength / guidance | 15 / 0.35 / 6.5 |
| Seed | 20260725 |
| Cold model load | 132.295 seconds |
| Generation | 222.111 seconds |
| Total smoke test | 357.706 seconds |
| Peak allocated / reserved | 13.41 / 14.31 GiB |
| Output SHA-256 | `bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452` |

One later authenticated FastAPI loopback job completed in 252.243 seconds from
start to completion and persisted an Approved review state. The Session 1
memory/hash measurements above are not presented as measurements from that
later job.

## Product experience and human review

The premium responsive UI makes the workflow demonstrable without a live GPU.
Mock concepts stay visibly labelled. Review is a first-class stored state,
covering approval, rejection, and requested changes. Generated output is a
draft that must not be published without human, rights, and product-claim
review.

## Innovation and practical value

BrandPilot Local treats multimodal generation as one stage in a campaign
system, not a standalone prompt box. It joins asset intake, brand strategy,
visual exploration, copy, format selection, transparent provenance, and human
decision-making. The mock-first/experimental split keeps the product useful and
testable without hiding infrastructure constraints.

## Validation boundary

Verified on Radeon Cloud: device/HIP detection, real SDXL img2img, measured
timing/memory, authenticated FastAPI loopback generation, official rc-tunnel
installation/activation, and safe instance destruction.

Verified through Chrome in Session 2b: valid TLS, authentication, explicit
CORS, project creation, and product upload through the official tunnel.

Not completed: a protected generated result rendered in Chrome through the
official public edge. The final retry stopped because the platform-assigned
rc-tunnel hostname did not resolve in public DNS. No unofficial tunnel or TLS
bypass was used.

## Limitations and roadmap

This prototype is not production-ready or permanently hosted. It does not
claim product identity, logo, or packaging-text preservation; IP-Adapter,
ControlNet, masking/compositing, LoRA, fine-tuning, video, and comparative
benchmarks remain future work. Commercial model/source clearance is incomplete.

The next technical phase, only after submission, is a measured comparison of
base SDXL against IP-Adapter plus masking/compositing for product preservation.

## Team

- Talal Khawaja - project lead, application development, Radeon integration,
  technical documentation, and demo preparation.
- Aqeela Urooj - product testing, output review, usability feedback, and
  documentation review.

## References

- Development repository: https://github.com/kmt9967/brandpilot-local
- Full evidence map: `docs/judging-evidence-map.md`
- Claim boundary: `docs/final-claim-audit.md`
- Demo package: `submission/demo-script.md`
