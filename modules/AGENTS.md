# Live Science core agent workflow

This directory implements the three-phase Live Science workflow. Use `Phase 1`, `Phase 2`, and `Phase 3` consistently in new filenames, documentation, logs, and user-facing messages. Do not introduce alternate phase terminology.

## Authoritative specifications

- Phase 1: `phase1/PHASE1_PROMPT.md`
- Phase 2: `phase2/PHASE2_PROMPT.md`
- Phase 3: `phase3/PHASE3_PROMPT.md`
- Full pipeline: `PIPELINE_PROMPT.md`
- Shared GPU generation policy: `GPU_GENERATION_POLICY.md`

Read the applicable prompt completely before taking phase-specific actions. Before any GPU image or video generation, also read `GPU_GENERATION_POLICY.md`. The nested `phase1/AGENTS.md` also applies to work inside `phase1/`.

## Choose the phase

Use Phase 1 when the input is a concept, teaching outline, textbook process, or a request to build or repair the programmatic teaching video.

Use Phase 2 when the user supplies an existing Phase 1 run and asks for realistic keyframes, world reference generation, anchor selection, or image-generation preparation.

Use Phase 3 when the user supplies Phase 1 process definitions and Phase 2 realistic anchors and asks for interpolated video, segment assembly, or final overlay and subtitle composition.

If the user asks for the full pipeline, complete and validate each phase in order. Start Phase 2 only when the Phase 1 route permits it, and start Phase 3 only after its selected anchors are usable.

For a natural-language end-to-end run, use `run_pipeline.py`. Treat `runs/<run-id>/pipeline.json` as the orchestration state, never overwrite an existing run without explicit `--resume`, and never select assets from undeclared historical runs.

## Phase 1 workflow

1. Read `phase1/PHASE1_PROMPT.md` and the current request.
2. Create a new directory under `phase1/runs/<run-id>/`.
3. Build the teaching narrative, deterministic app, subtitles, video, poster, and Bridge metadata.
4. Expose `renderFrame(t, options)`, `LIVE_SCIENCE_META`, and `LIVE_SCIENCE_BRIDGE`.
5. Render and visually inspect presentation, clean, and overlay modes when required.
6. Export `bridge/manifest.json` with `phase1/tools/export_bridge.mjs`; never hand-write it.
7. Run the Phase 1 output and Bridge validators and repair failures.

Prefer `phase1/run_phase1.sh` for a complete new Phase 1 run.

Write generated artifacts only inside the current Phase 1 run. Do not modify previous runs unless the user explicitly requests it.

## Phase 2 workflow

1. Read `phase2/PHASE2_PROMPT.md` completely.
2. Treat the supplied Phase 1 run as read-only.
3. Read `brief.md`, `bridge/manifest.json`, and `bridge/clean/`.
4. Check `manifest.route`:
   - `programmatic`: normally stop and explain that realistic conversion is not recommended;
   - `realizable`: select from all eligible key moments;
   - `hybrid`: select only moments with `realizable: true`.
5. Select 4–5 necessary generation anchors from existing moments.
6. Generate or reuse one stable `world_reference.png`.
7. Generate each anchor from the current clean frame plus world reference, preferring full-frame generation.
8. Retry a failed anchor at most once. Use local editing only when an existing workflow can be reused with minimal work.
9. Produce the simple Phase 2 output package and record known issues honestly.

Write outputs only inside a new `phase2/runs/<run-id>/`. Do not write generated files into the source Phase 1 run.

## Phase 3 workflow

1. Read `phase3/PHASE3_PROMPT.md` and `GPU_GENERATION_POLICY.md` completely.
2. Treat the supplied Phase 1 and Phase 2 runs as read-only.
3. Build `timeline.json` from Phase 1 event semantics and Phase 2 anchor order.
4. Generate adjacent anchor transitions as separate segments, using a derived intermediate anchor when a topology change is too large.
5. Validate one representative smoke segment before running the remaining compatible segments serially.
6. Remove duplicate boundary frames, assemble `base_video.mp4`, then remap Phase 1 overlays and subtitles into `final_video.mp4`.
7. Preserve prompts, workflows, generation metadata, failed attempts, and an honest report.

Write outputs only inside a new `phase3/runs/<run-id>/`. Do not modify the source Phase 1 or Phase 2 runs.

## Bridge handoff contract

Phase 1 owns the teaching sequence, moment IDs, times, object identity, event relations, and structural state.

Phase 2 may select fewer moments, but it must not invent a new teaching order or silently change the meaning of an event. For every selected anchor:

- `manifest.json` provides the moment identity and semantics;
- `clean/<moment-id>.png` is the current-state structural source;
- `world_reference.png` provides appearance only;
- `realistic.png` remains traceable to the original Phase 1 moment ID.

Use presentation, overlay, video, or `renderFrame(t)` only when the clean frame or manifest is ambiguous.

## Safety and scope

- Preserve historical runs by default.
- Reuse the existing rendering and FLUX.2/ComfyUI environments; do not install parallel frameworks without explicit need.
- Follow `GPU_GENERATION_POLICY.md` for all GPU image and video tasks.
- Do not fake generated images, Bridge metadata, model runs, or validation results.
- Keep Phase 2 Fast Mode small: 4–5 anchors, one world reference, and no more than one retry per anchor.
- Prefer a complete, honestly documented run over an open-ended attempt to perfect one difficult frame.
