# SignalForge - AMD AI DevMaster Hackathon Track 2 Submission

| Field | Current release |
|---|---|
| Track | Track 2 - Development and Local Deployment of Private AI Agents |
| Team | SignalForge Labs |
| Application | SignalForge |
| Team member | Rafael Bernucci - product architecture, financial domain design, evaluation strategy, and release ownership |
| Canonical repository | [github.com/rvbernucci/signalforge](https://github.com/rvbernucci/signalforge) |
| Judge documentation source | [`756432d8fda288564c25988e826c47fdff781a48`](https://github.com/rvbernucci/signalforge/commit/756432d8fda288564c25988e826c47fdff781a48) |
| Application image source | [`ac8685307a420e23f73632f0e59fc647e6fdd870`](https://github.com/rvbernucci/signalforge/commit/ac8685307a420e23f73632f0e59fc647e6fdd870) |
| Championship release | [`v1.2.1`](https://github.com/rvbernucci/signalforge/releases/tag/v1.2.1) |
| Immutable application image | `ghcr.io/rvbernucci/signalforge@sha256:4b68c713e824d3cea9ad6a83cef4c93304961f9f3c3782a984af312bec47bf43` |
| Platform manifest | `linux/amd64` - `sha256:622013807d01c47e05f1f0a1032a534a237d5c77483b746f3c64ea9c29ce4524` |

This documentation update changes no application code or Docker image. The immutable image above
remains the exact executable release.

## Required Materials

- [4 min 26 s AMD Radeon demo](https://github.com/rvbernucci/signalforge/releases/download/v1.2.1/SignalForge-Radeon-Demo.mp4)
- [Project specification PDF](https://github.com/rvbernucci/signalforge/releases/download/v1.2.1/SignalForge-Project-Specification.pdf)
- [Six-slide judge deck](https://github.com/rvbernucci/signalforge/releases/download/v1.2.1/SignalForge-Judge-Deck.pptx)
- [Judge guide](https://github.com/rvbernucci/signalforge/blob/main/JUDGES.md)
- [Architecture](https://github.com/rvbernucci/signalforge/blob/main/docs/architecture.svg)
- [Track 2 compliance matrix](https://github.com/rvbernucci/signalforge/blob/main/docs/track2-compliance.md)
- [Final release authority and media hashes](https://github.com/rvbernucci/signalforge/blob/main/evidence/final-release-authority.json)
- [Complete clean source and verification suite](https://github.com/rvbernucci/signalforge)

The `source/` directory in this PR is the immutable source snapshot included with the original
submission. The canonical repository and exact commits above are authoritative for the current
judge documentation and executable image.

## Product

SignalForge is a private, local-first financial research workspace for independent investors. It
turns public company evidence into an inspectable process with typed multi-agent planning,
source-authorized retrieval, deterministic financial tools, independent review, optional local
memory, explicit permissions, and fail-closed answer contracts.

The governed universe covers 20 US-listed technology companies and five metric-level peer lanes:
Cisco/Arista, Microsoft/Alphabet, NVIDIA/AMD, Oracle/Microsoft, and
Salesforce/ServiceNow. Unsupported periods, units, definitions, accounting perimeters, and
overbroad comparisons remain unavailable or fail closed.

SignalForge is research software. It does not predict prices, execute trades, or provide
personalized investment recommendations.

## Agent Architecture

1. A typed interpreter closes intent, entities, horizon, and constraints.
2. A Go planner creates the bounded execution plan and specialist wave.
3. Point-in-time retrieval resolves authorized evidence and lineage.
4. Eighty role-authorized deterministic operations own values, periods, units, formulas, and
   receipts.
5. Eleven logical roles provide specialist context, independent evidence review, risk challenge,
   and final synthesis.
6. The Answer Contract Engine validates and deterministically constructs the released projection.
7. The React workspace keeps the investor view concise while exposing an expandable plan and
   privacy-safe Mission Control when requested.

SignalForge implements all five Track 2 capability families: local retrieval, tool invocation,
multi-step planning, local multi-turn memory, and permission/privacy controls.

## AMD Radeon And ROCm

- AMD Radeon Cloud `gfx1100`, 47.98 GiB VRAM, ROCm 7.2.1.
- Gemma 4 26B A4B Instruct QAT Q4_0 through AMD-validated ROCm `llama.cpp`.
- 32,768-token context and four continuous-batching specialist slots.
- Gemma passed 40/40 deterministic model-profile contract checks at 86.4601 median decode
  tokens/s.
- Qwen3 8B BF16 passed 40/40 at 26.3855 median decode tokens/s; Granite 4.1 8B BF16 passed
  35/40 at 24.9882.
- Gemma measured 3.28x Qwen's median decode throughput in this bounded workload. The profiles
  differ in model, runtime, and precision, so this is not a universal model ranking.
- The selected four-slot profile was 29.17% faster end-to-end than the passing three-worker
  control.
- A 5 hour 28 minute soak completed 180/180 journey contracts with no measured allocated-VRAM
  growth.
- The optional Radeon API path is selective; loss of that API recovered locally, while loss of
  indispensable local authority failed closed.

These are bounded application-profile measurements, not a universal model ranking or independent
accuracy certification.

## Verification

The application image passed a clean public pull, SBOM and provenance checks, zero unresolved
HIGH/CRITICAL vulnerability gates, exact-image fixture execution, and bounded readback on the
Radeon host. The current repository passed frontend, Go race/vet/tests, Python, financial-reference,
observability, privacy, hardening, and public-integrity gates in
[GitHub Actions run 30752888662](https://github.com/rvbernucci/signalforge/actions/runs/30752888662).

Pull the exact executable:

```bash
docker pull \
  ghcr.io/rvbernucci/signalforge@sha256:4b68c713e824d3cea9ad6a83cef4c93304961f9f3c3782a984af312bec47bf43
```

Run the credential-free source fixture:

```bash
git clone https://github.com/rvbernucci/signalforge.git
cd signalforge
npm --prefix web ci
npm --prefix web run build
go run ./cmd/signalforge-workspace --mode fixture --static-dir web/dist
```

Open `http://127.0.0.1:8080/?audience=judge`.

SignalForge can make mistakes. Important information must be verified before financial decisions.
The project-owner release decision is not an independent audit opinion, legal opinion, investment
recommendation, fiduciary service, or professional assurance engagement. Final eligibility and
scoring remain solely with the hackathon organizers and judges.
