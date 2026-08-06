# ColorGraph Landscape Annotation Guideline v1

> Frozen identifier: `colorgraph.landscape-annotation/v1`  
> Frozen date: 2026-07-28  
> Scope: real-camera Landscape Gold Set shot, scene, mask and relative-depth
> truth.

Any semantic change requires a new identifier and a new Gold Set manifest
version. Typographical corrections must not change labels or frame decisions.

## 1. Common timebase and source rules

- Annotate the downloaded, SHA-256-pinned source represented by the manifest.
- Frame indices are zero-based decoded video frames.
- Preserve FFprobe `best_effort_timestamp_time`; do not derive VFR truth from
  `frame_index / average_fps`.
- A derivative, proxy or crop keeps the original `source_group_id` and may
  occur in only one of train, calibration or test.
- Do not infer missing camera, lens, transfer, primaries, matrix, range or Log
  profile. Record unknown values as missing and explain the evidence gap.
- An annotator must not review the same item. Use stable pseudonymous IDs.

## 2. Shot-boundary truth

Record each transition as one of:

- `cut`: the boundary frame is the first frame of the new shot;
- `fade_in`, `fade_out`, `dissolve`, or `wipe`: inclusive start and end frame
  of the visible transition;
- `flash`: a transient exposure event that is explicitly not a shot boundary.

Camera pans, tilts, zooms, drone motion, occlusion, exposure changes and
same-shot focus changes are not boundaries. When a transition cannot be placed
within one frame, mark `uncertain=true` and explain why; the independent
reviewer must either resolve it or reject the item.

## 3. Scene truth

Assign every shot to exactly one ordered scene. A scene change requires a
meaningful change in location, time, lighting regime or narrative visual
intent; visual similarity alone is insufficient.

Allowed landscape labels are:

`mountain`, `forest`, `water`, `snow`, `desert`, `coast`, `rural`,
`urban_landscape`, `night_landscape`, `aerial_landscape`, and `unknown`.

Use `unknown` rather than forcing an unsupported category. Record all
applicable conditions separately as tags, including `day`, `night`, `fog`,
`fast_motion`, `occlusion`, `rec709`, and `log`.

## 4. Semantic and temporal mask truth

The required classes are `sky`, `vegetation`, `water`, `mountain_rock`,
`snow_ice`, and `foreground_subject`. A class absent from a frame is an
explicit empty mask, not a missing annotation.

- Masks use source-frame dimensions and lossless binary or 16-bit grayscale
  storage.
- Boundary pixels follow the visible object at 100% zoom; do not include
  feathering, halos or guessed content behind occluders.
- For transparency, spray, mist and reflections, annotate the underlying
  semantic surface and set the relevant ambiguity flag.
- Complex sequences must include fast motion, partial or full occlusion, or
  disappearance/re-entry. Annotate every scored frame; unannotated frames must
  be listed in `excluded_frames` with a reason.
- The reviewer checks frame count, dimensions, class IDs, boundary alignment,
  occlusion decisions and at least the first, last and every tenth scored
  frame.

## 5. Relative-depth truth

Depth truth is relative unless an independently calibrated metric source is
available.

- Store float disparity/depth plus a valid-pixel mask.
- Record whether larger values mean nearer or farther.
- Preserve one scale/shift convention for the entire shot.
- Mark sky, reflections, transparent regions, motion blur and occlusion
  ambiguity; do not silently assign zero.
- The reviewer checks ordinal foreground/background relationships and
  shot-wide scale/shift consistency.

## 6. Independent review and acceptance

Each annotation package must record:

- source and annotation SHA-256;
- guideline identifier;
- annotator ID and completion timestamp;
- independent reviewer ID and review timestamp;
- accepted/rejected status;
- frame-specific rejection reasons and corrective notes.

Acceptance requires exact source/hash agreement, complete required fields,
disjoint annotator/reviewer IDs, no unresolved uncertainty, and a second
checksum after corrections. Copy the accepted provenance into the Gold Set
manifest, then run both `colorgraph gold-validate` and
`colorgraph gold-audit`. A failed audit may not be waived in prose.
