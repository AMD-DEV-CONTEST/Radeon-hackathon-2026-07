# E9 Deadline Handoff

The engineering proof is no longer the critical path. Complete-product W7900
acceptance and the bounded Stage 2 decision are finished. The remaining work
is repository integration, media production, public links and the official
organizer-repository PR.

## Ten-minute takeover

1. Read [`README.md`](README.md) and
   [`source/SUBMISSION_FACTS.md`](source/SUBMISSION_FACTS.md).
2. Open the R8 English final-content PDF/PPT in `deliverables/`.
3. Use [`source/DEMO_SCRIPT.md`](source/DEMO_SCRIPT.md) for the recording.
4. Use [`source/FINAL_CHECKLIST.md`](source/FINAL_CHECKLIST.md) to avoid
   confusing team PR completion with official competition submission.
5. Fill the remaining URLs in
   [`source/OFFICIAL_PR_DRAFT.md`](source/OFFICIAL_PR_DRAFT.md).

## Parallel lanes

### Lane A - final repository state and recording environment

Recommended owner: teammate with Radeon Cloud/W7900 access.

- decide and record the exact final repository commit;
- use submitted source snapshot `aab2ae6`, which includes the final English
  WebUI and stage navigation;
- start the loopback model, API and Web UI on W7900;
- load the public synthetic fixture and confirm the complete path is ready;
- send the recorder the exact commit/model/device identity card.

No new benchmark or full evidence cycle is needed unless integration changes
the tested product behavior. The final UI/source updates do not replace or
invalidate the frozen W7900 packet by themselves.

### Lane B - demo recording and upload

Recommended owner: teammate who can operate the UI smoothly.

- rehearse the four-minute script once;
- record the real Web UI, not mock screens;
- show the local Radeon/vLLM identity briefly, then spend most of the video on
  the user journey;
- include correction -> invalidation -> regeneration and the private M5 route;
- add English narration or complete English subtitles;
- upload and verify the public link while signed out;
- return the URL and timestamps to the materials editor.

### Lane C - artifacts and official PR

Recommended owner: E9 materials editor.

- inspect the R8 PDF/PPT and make only fact-preserving visual edits;
- insert the final repository, PDF, PPT and video URLs;
- update the contribution sentence if PR #54/#59 merge states change;
- check every public link while signed out;
- open the official organizer PR only after the owner authorizes publication.

## Stable story

Keep these facts consistent everywhere:

- product: private local Agent for evidence-bound first-person experience;
- workflow: M1 -> M2 -> M3 -> M4 -> M5 -> private delivery;
- authority: model proposes; deterministic Runtime permits or rejects;
- grounding: current experience first, gated historical RAG only after M4;
- tested implementation: `c9ec07489d17a2abb74bac66a23ade2c775c1b06`;
- local model: Qwen3.5-9B revision `460979c3d118...`, BF16, 20K;
- device: Radeon PRO W7900, ROCm/HIP 7.2, vLLM 0.26.0;
- evidence: complete W7900 flow PASS; P1 selected from one bounded Stage 2
  comparison, with S0 rollback;
- limitations: one Stage 2 case, 0.0% cache hit, peak Stage 2 VRAM not measured.

## Ready-to-send teammate message

> E9 R8 materials are under `docs/submission/e9/`. The complete product already
> passed on W7900 at implementation `c9ec074`, and Stage 2 selected P1 with S0
> rollback. Please do not rerun planning or describe product evidence as
> pending. PR #58 is merged. We now need: (1) the final WebUI handoff and exact
> recording commit, (2) the real 3-5 minute W7900 demo plus public URL, and
> (3) final public PDF/PPT/repository links for the organizer PR. Use
> `source/DEMO_SCRIPT.md` and `source/OFFICIAL_PR_DRAFT.md`.

## Publication boundary

This package prepares the submission. It does not authorize merging open PRs,
publishing the demo, exposing a service or opening the official contest PR.
