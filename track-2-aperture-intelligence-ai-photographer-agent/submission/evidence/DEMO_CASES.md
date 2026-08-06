# Canonical demo cases

These three cases are the fixed public demonstration set. Every input is covered
by the Pexels License and has a source page and SHA-256 record in
`SAMPLE_SOURCES.md`. All inference, segmentation, planning, and rendering were
executed on AMD Radeon Cloud.

| Case | Role in the demo | Capability proved | Canonical output |
|---|---|---|---|
| `01_single_with_phone` | Live recording case | Local Qwen-VL analysis, visible-prop grounding, single-person mask, deterministic card | `results/01_single_with_phone/final.png` |
| `02_single_no_prop` | Contrast case | No object invention; clothing is not misrepresented as a handheld prop; concrete hand guidance remains available | `results/02_single_no_prop/final.png` |
| `03_group_three_people` | Multi-person case | Three-person grounding and segmentation, group-specific planning, gaze and arm coordination | `results/03_group_three_people/final.png` |

## Case 01 — Single portrait with a phone

- Source: Abubakar Isa, Pexels photo 19518383.
- Input: `samples/01_single_with_phone.jpg`
- What to point out: the phone is preserved as a real interaction element; the
  card uses the real person contour and does not generate a replacement image.
- Verified warm-path timing: approximately 52 seconds end to end.
- Peak allocated VRAM in retained evidence: 9.567 GiB.

## Case 02 — Single portrait without a handheld prop

- Source: Connor Scott McManus, Pexels photo 12182660.
- Input: `samples/02_single_no_prop.jpg`
- What to point out: clothing and accessories are excluded from the handheld
  prop explanation; the card labels the action area as `Both hands` instead of
  inventing an object.
- Verified three-run average: 116.459 seconds.
- Peak allocated VRAM: 10.684 GiB.

## Case 03 — Three-person group portrait

- Source: Bobography, Pexels photo 35054544.
- Input: `samples/03_group_three_people.jpg`
- What to point out: three foreground people are detected, matched, segmented,
  and represented in the contour; the instructions change from an individual
  pose to shared gaze, spacing, and hand coordination.
- Verified three-run average: 226.018 seconds.
- Peak allocated VRAM: 10.677 GiB.
- Demo treatment: show the retained result and audit JSON with an explicit
  pre-generated disclosure; do not present this long path as instant inference.

## Evidence contract

For each case, `final.json` contains the analysis, final plan, Critic result,
tool calls, permission audit, GPU metrics, pose JSON, and deterministic-render
metadata. `final.png` is the canonical user-facing card. The `run_*.json` files
preserve repeated real-cloud evidence. No model weights or private photographs
belong in the public submission.
