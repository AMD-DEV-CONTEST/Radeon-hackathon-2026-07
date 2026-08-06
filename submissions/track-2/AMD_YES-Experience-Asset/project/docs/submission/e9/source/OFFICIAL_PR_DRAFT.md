# Official Submission PR Copy

This is the ready English body for the PR against the organizer repository.
The product and document copy is complete. The registered team name is
`AMD_YES`. The Demo URL is included; the owner must verify that every link
works while signed out.

## Title

```text
Track 2, AMD_YES, Experience Asset
```

## Body

### Project

**Experience Asset** is a private local Agent that turns fragmented
first-person experience into an evidence-bound, editable and reusable asset,
then prepares audience-specific deliverables while keeping facts, privacy and
approval under user control.

### Application scenario and result

The user moves through five visible, resumable artifacts: Experience Brief,
Critical Moment Map, Decision and Evidence Ledger, Insight and Boundary Map,
and Route Readiness Matrix. One accepted canonical asset can then be previewed
and exported as HTML, Markdown or JSON.

Exact implementation `c9ec07489d17a2abb74bac66a23ade2c775c1b06` passed a
real local-model journey on a Radeon PRO W7900. The observed path covered
M1-M4 generation, canonical evidence inspection, correction-driven
invalidation/regeneration, real M5 route/privacy evaluation and private
three-format delivery.

### Track 2 capabilities

- durable multi-step planning and checkpoints with LangGraph;
- phase-gated local RAG and user-confirmed detailed retrieval;
- governed tool invocation with allowlists and argument validation;
- persistent versions, restart recovery and audit;
- deterministic privacy review and exact-bound approval;
- local core inference through vLLM, ROCm and Radeon PRO W7900.

### Local model and reproduction

- Tested application implementation:
  `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
- Current reproducible repository snapshot before the materials PR merges:
  `c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd`
- Model: `Qwen/Qwen3.5-9B`, revision
  `460979c3d11864dd16408d860ac930a360a2fac2`, BF16, no quantization
- Runtime/device: vLLM 0.26.0, ROCm/HIP 7.2, Radeon PRO W7900 48 GiB
- Selected Profile: P1-prefix-cache; S0 is the one-command rollback
- Setup and startup:
  https://github.com/kinnyuww/amd-devmaster-track2-agent/blob/main/README.md
- Product evidence:
  `evidence/milestones/e8-a0-w7900/20260806T122806Z/`
- Stage 2 evidence:
  `evidence/performance/stage2-minimal/20260806T124938Z/`

### Materials

- Submission index:
  https://github.com/kinnyuww/amd-devmaster-track2-agent/blob/main/docs/submission/e9/FINAL_SUBMISSION_INDEX.md
- Source repository: https://github.com/kinnyuww/amd-devmaster-track2-agent
- Project Specification:
  https://github.com/kinnyuww/amd-devmaster-track2-agent/blob/main/docs/submission/e9/deliverables/Experience_Asset_Project_Specification.pdf
- Presentation:
  https://github.com/kinnyuww/amd-devmaster-track2-agent/blob/main/docs/submission/e9/deliverables/Experience_Asset_Track2_Deck.pptx
- Demo video:
  https://drive.google.com/drive/folders/1_cOmcYBIJuPfkoJ4VuA7ZuBYV8nYB8yr?usp=drive_link

The Demo will use English narration or complete English subtitles and will be
viewable without repository or Radeon Cloud credentials.

### Radeon optimization evidence

The frozen W7900 Stage 1 service comparison places P1 first. Against S0, P1
recorded p95 TTFT 83.89% lower, median
E2EL 4.33% lower and output TPS 0.47% higher, with 85% warm-up reliability.
These are service-profile results, not complete-Agent acceleration.

The same complete Agent/model/case passed on both S0 and P1 in the minimal
Stage 2 check. S0 completed in about 2.0 minutes and P1 in 109.21 seconds. This
is one observation, not a statistical latency claim. The P1 run reported 0.0%
cache hit, so the difference is not attributed to prefix caching. P1 was
selected because it won the frozen service screen and passed this integrated
safety check; S0 remains the rollback.

### Honest limitations

The submitted Demo uses public synthetic data. The Stage 2 comparison contains
one paired observation, does not measure peak Stage 2 VRAM and cannot support a
causal cache-speed claim. Editable final language still requires user review.
The product controls evidence, permission and privacy risk; it does not claim
to eliminate hallucinations or make personal experience universal.

### Team contributions

- `kinnyuww`: requirements and quality architecture, W7900 serving benchmark,
  integrated device acceptance and Stage 2 evidence.
- `Eas000n`: Runtime foundation, M1/M3/M5 milestones, privacy/approval path and
  E9 submission materials.
- `1olaqua616-web`: React application shell, M2 semantic extraction, gated M4
  retrieval and E5-E8 integration.

Several final outcomes were collaborative and converged in PR #52.

## Pre-publication check

- [x] use the registered team name `AMD_YES`;
- [x] add the Demo URL;
- [ ] all submission-facing text is English;
- [ ] title follows the organizer format;
- [ ] final source, PDF/PPT and Demo locations are accessible while signed out;
- [ ] device/model/performance claims match the cited evidence;
- [ ] the final repository commit contains no secret or private data;
- [ ] the owner has authorized the official PR;
- [ ] the PR targets the organizer repository before the deadline.
