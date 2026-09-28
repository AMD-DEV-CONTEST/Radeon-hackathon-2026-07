# BrandPilot Local demo script

Target runtime: 4 minutes 40 seconds. Record the local product in production
mode and use only pre-recorded, sanitized Radeon evidence.

## 0:00-0:20 - Opening

**On screen:** Title, homepage hero. Label: `Local UI demonstration`.

**Narration:** BrandPilot Local is an AMD Radeon-powered creative studio
prototype that turns one product image and campaign brief into reviewable,
platform-ready marketing concepts. It is designed for small teams that need a
coherent workflow and a clear human decision before publishing.

## 0:20-0:50 - Problem and workflow

**On screen:** Homepage workflow cards, then Creative Studio.

**Narration:** Campaign work is usually fragmented across prompt tools, design
files, copy documents, and approval threads. BrandPilot joins rights-cleared
asset intake, audience and benefits, brand tone and colors, visual direction,
output formats, copy, and review in one responsive local workspace.

## 0:50-1:50 - Local product demonstration

**On screen:** Upload `examples/browser-test-product.png`; complete the brief;
select Luxury plus formats; generate. Label: `Mock campaign concept`.

**Narration:** Mock mode is the default, so this demonstration needs no GPU,
model weights, or external service. The input is validated and attached to a
persistent project. I can set the campaign objective, audience, benefits,
guardrails, style, and formats. Generation produces four clearly labelled mock
directions. These are product-flow demonstrations, not Radeon outputs.

**On screen:** Open a result; edit copy; choose Approved; refresh.

**Narration:** Every concept stays disclosed and reviewable. Copy can be
edited, a result can be approved, rejected, or sent back for changes, and the
decision survives refresh. Human review is part of the data model, not a note
added after generation.

## 1:50-2:30 - Architecture

**On screen:** Architecture page. Label: `Local UI demonstration`.

**Narration:** The Next.js interface calls FastAPI for validation, persistence,
results, and review. Experimental Radeon mode is a deliberate authenticated
opt-in. It binds the worker to loopback, accepts one GPU job at a time, lazily
loads the exact pinned model, reuses the pipeline, protects output fetches, and
has no CPU or mock fallback.

## 2:30-3:30 - Recorded Radeon evidence

**On screen:** Sanitized environment evidence, generated image, measurements.
Labels: `Recorded Radeon evidence` and `Verified Radeon output`.

**Narration:** The real image shown here was generated on AMD Radeon with ROCm
during our verified cloud session. PyTorch detected one gfx1100 Radeon device
with 48 GiB reported memory and HIP 7.2. We used SDXL base 1.0 at its exact
pinned revision, 768 by 768, 15 steps, strength point three five, guidance six
point five, and seed 20260725. Cold model load measured 132.295 seconds,
generation 222.111 seconds, with 13.41 GiB peak allocated and 14.31 GiB peak
reserved VRAM. The output hash is recorded in the repository.

**On screen:** Authenticated loopback summary.

**Narration:** A later application-integrated job completed through the
authenticated FastAPI loopback path in 252.243 seconds and persisted an
Approved review state.

## 3:30-4:00 - Honest browser-edge limitation

**On screen:** Sanitized DNS evidence and no-active-instance proof. Label:
`Public browser edge blocked by official tunnel DNS`.

**Narration:** We also installed and activated the official rc-tunnel. One
session verified browser TLS, authentication, CORS, project creation, and
upload. The final completion retry stopped because the platform-assigned
hostname did not resolve in public DNS. We did not fabricate success, bypass
TLS, or use an unofficial tunnel. Every instance was destroyed.

## 4:00-4:30 - Practical value

**On screen:** Results and review screenshots, mobile views.

**Narration:** BrandPilot's value is the system around generation: brand
context, multiple directions, platform framing, transparent provenance,
responsive access, and human accountability. Local-first processing can reduce
unnecessary asset exposure while keeping rights and product-claim review
explicit.

## 4:30-4:40 - Team and close

**On screen:** Title slide with team names and repository.

**Narration:** BrandPilot Local was created by Talal Khawaja and Aqeela Urooj
for Track 1. The repository contains the complete source, reproducible local
setup, verified Radeon evidence, exact claim boundaries, and the next measured
roadmap. Thank you.
