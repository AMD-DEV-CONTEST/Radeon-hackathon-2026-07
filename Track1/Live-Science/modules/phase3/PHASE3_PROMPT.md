# Live Science · Phase 3

Phase 3 treats Phase 1's process definition as the **motion truth** and Phase 2's realistic keyframes as the **visual anchors**. The goal is not to redesign the teaching process, but to make adjacent states change continuously according to the correct mechanism and to produce traceable, spliceable realistic video segments.

Before starting, also read `../GPU_GENERATION_POLICY.md` in full. That file defines the scheduling, smoke, VRAM-safety, and logging requirements shared by image and video generation; this Prompt only adds Phase 3's video-generation rules.

## 1. Input and boundaries

Read the following at the start of every run:

- Phase 1: `brief.md`, `bridge/manifest.json`, event relationships, subtitles, and overlays; read the programmatic video or the deterministic `renderFrame` when necessary.
- Phase 2: the selected realistic anchors, `world_reference.png`, the anchor list, and the report.

Phase 1 determines what happens, how it changes, and the order of events; Phase 2 determines what the start and end states look like. Do not modify Phase 1 or Phase 2, do not add new events out of thin air, and do not let later states happen early.

By default, generate in segments between adjacent anchors; do not cram four or five keyframes into one long video at once.

For the `hybrid` route, only generate adjacent changes marked `realizable: true`. The final video must preserve the necessary programmatic segments in Phase 1's original order; programmatic segments may be labeled `sourceType: "programmatic"` and generated segments `sourceType: "generated"` in `timeline.json`. Do not drop necessary teaching content just because no realistic anchor exists.

## 2. Pre-generation checks

Before submitting a GPU job, you must confirm:

1. The start and end anchors exist and their dimensions and aspect ratios are compatible;
2. Anchor order, state meaning, and event direction are consistent with Phase 1;
3. The job, queue, parameter, and VRAM pre-checks in `../GPU_GENERATION_POLICY.md` have passed;
4. The sources of inputs and historical artifacts are clear; do not reuse generated videos of unclear origin.

Continue using the validated local video workflow; the specific VRAM strategy is uniformly governed by the shared policy.

## 3. Segment difficulty classification

Classify each segment before generating it:

- `appearance_only`: lighting, weather, color, or material changes;
- `continuous_motion`: flow, growth, migration, or continuous deformation;
- `topology_change`: appearance, disappearance, connection, disconnection, splitting, merging, or collapse.

For `topology_change`, you must judge whether the span between start and end is too large. If a segment requires the model to complete multiple key actions at once, select or derive a semantically clear intermediate anchor from Phase 1, then split it into shorter segments.

Derived anchors must record:

- The Phase 1 source time and state;
- The structural source;
- The visual style source;
- The generation prompt;
- Whether it is written back to Phase 2; by default it is not.

## 4. Constraints on each segment's prompt

Each segment's prompt must clearly state:

- The video strictly starts from the first frame and ends at the last frame;
- The changes that must occur and their order;
- The objects and spatial regions allowed to change;
- The objects and regions that must remain still;
- Whether the camera is locked;
- Later events that must not occur early;
- Structures that must not be added, removed, or wrongly connected.

For local events, explicitly write "only a certain local region is allowed to change." Do not vaguely describe the entire scene as changing, or the model may mis-assign motion to the background, vegetation, or unrelated structures.

## 5. Separation of smoke and release

By default, first run a conservative single-stage smoke configuration to verify:

- Whether the start/end constraints take effect;
- Whether the event direction is correct;
- Whether the camera and non-target regions are stable;
- Whether obvious hallucinations appear;
- Whether the VRAM configuration is safe.

After smoke succeeds, then decide whether to run the two-stage high-definition pipeline. Do not describe a low-resolution smoke as the final high-quality result.

If the event semantics in smoke are unclear, first adjust the anchors, segments, and prompts. Do not assume that raising the resolution will fix wrong motion or topology.

## 6. GPU performance and VRAM strategy

All general scheduling, caching, VRAM, and retry rules follow `../GPU_GENERATION_POLICY.md`. Phase 3 additionally has the following video constraints:

- For first validation, use the lowest reasonable resolution, shortest reasonable duration, and minimum legal frame count that suffice to judge the motion semantics;
- Video dimensions must satisfy the current model's spatial-multiple requirements; LTX frame counts must satisfy `8n+1`;
- Segments sharing the same model, resolution, and sampling configuration should be generated consecutively to exploit hot loading;
- For high-risk topology changes, prefer adding intermediate anchors, which is usually faster and more stable than repeatedly retrying;
- After smoke passes, prefer the "low-resolution temporal generation → official spatial upscaling or second-stage refinement → final encoding" path for high-definition output; do not default to generating the full temporal sequence directly at the highest resolution;
- If Phase 3 generates derived image anchors, they are likewise governed by the shared policy and follow Phase 2's full-image-first and one-targeted-retry principles.

## 7. Retry rules

Each segment may have at most one retry with a clear purpose. Before retrying, classify the primary failure as one of:

- `endpoint_drift`: insufficient start/end anchor constraints;
- `camera_drift`: the camera has moved;
- `background_motion`: non-target regions have changed;
- `topology_failure`: wrong connection, disconnection, or object-existence relationships;
- `hallucinated_object`: unrelated objects appear;
- `temporal_artifact`: flickering, breathing, or sudden jumps.

One retry may target only one primary problem. You may strengthen the start/end guidance, reduce input compression, narrow the region allowed to change, strengthen negative constraints, or switch to segment splitting and intermediate anchors. Do not modify many parameters at once without basis.

The first result, first prompt, first workflow, generation metadata, and failure reason must be preserved.

## 8. Fast QA

After each segment is generated, extract only a small number of equally time-spaced frames to check:

1. Without reading the prompt, can one broadly understand what happened;
2. Did the change occur in the correct region;
3. Is the change direction correct;
4. Were the start and end states reached;
5. Are the camera, background, and object identities stable;
6. Do added objects, disappeared structures, or wrong connections appear;
7. Did later stages happen early.

A successful technical pipeline is not the same as successful teaching expression. Even if the video can play, if an observer cannot understand the key process, it should be recorded as a semantic failure.

## 9. Automatic overlay and subtitle mapping

Use `timeline.json` as the single temporal truth for Phase 3 compositing.

For each segment:

1. Slice the Phase 1 subtitles according to `phase1StartTime` and `phase1EndTime`;
2. Proportionally map the subtitle times to the Phase 3 segment duration;
3. Compress subtitles that cannot be read in full based on reading speed;
4. Preferably generate continuous overlays from Phase 1's deterministic interface;
5. Overlay the overlays and subtitles onto the realistic base video;
6. Recompute the full subtitle timing after splicing.

Time slicing, scaling, mapping, and burning should be done automatically. Semantic compression of subtitles may be done by the model, but it must not change the original meaning of the knowledge. Only when a continuous overlay cannot be obtained should you fall back to a start/end overlay fade, and note this in the report.

## 10. Splicing contract

All segments must use compatible resolution, frame rate, pixel format, and camera direction. The splicing order is determined only by `timeline.json`, not by directory-name ordering.

Except for the first segment, remove the first duplicated end frame from each segment. The final frame count must satisfy:

```text
totalFrames = firstSegmentFrames + sum(otherSegmentFrames - 1)
```

Audio tracks produced per segment are not directly spliced by default, unless an existing audio-continuity handling solution is in place.

For general execution, prefer generating serially with `tools/run_all_segments.py`, compositing the per-segment teaching overlay with `tools/compose_segment.sh`, then splicing according to the timeline with `tools/assemble_phase3.py`. Do not let a single-segment generator directly overwrite the entire `base_video.mp4`.

## 11. Traceability

Preserve at least the following for each segment:

```text
segments/<id>/
  start.png
  end.png
  prompt.txt
  workflow_api.json
  generation.json
  video.mp4
  preview/
```

When a retry occurs, you must also preserve:

```text
attempt-1.mp4
prompt-attempt-1.txt
generation-attempt-1.json
```

In the report, record the failure reason, the changes made, and the rationale for the final choice. Do not describe unexecuted generation, retries, or checks as already completed.

## 12. Output

A Phase 3 run must at least contain:

```text
timeline.json
segments/
base_video.mp4
final_video.mp4
report.md
```

`base_video.mp4` is the realistic base video after removing duplicated end frames; `final_video.mp4` is the teaching version with Phase 1 overlays and subtitles re-applied.

After completion, run `tools/validate_phase3.py` to verify segment sources, formats, and the total frame count after deduplication.

## 13. Completion criteria

When Phase 3 is complete, the following must hold:

- Every necessary stage has a corresponding segment;
- The change direction between adjacent stages is discernible;
- Key events can be broadly understood without reading the prompt;
- No later events happen early;
- Changes do not wrongly spread to the background;
- Difficult topology events have had their spans reduced via segment splitting or intermediate anchors;
- Duplicated end frames have been removed;
- Overlays and subtitles have been re-mapped according to the timeline;
- All attempts, parameters, and known issues have been truthfully recorded.

For a minimal test, generate only the `pre_event → post_event` segment for one important event in Phase 1. Prefer a conservative single-stage job spec, and explicitly record that it is not the two-stage high-definition release path.
