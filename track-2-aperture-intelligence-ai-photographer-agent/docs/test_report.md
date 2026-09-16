# Radeon Cloud release-candidate test report

## Environment

| Item | Verified value |
|---|---|
| GPU | AMD Radeon Graphics |
| VRAM | 47.98 GiB |
| PyTorch | 2.13.0+rocm7.2 |
| HIP | 7.2.53211 |
| `torch.cuda.is_available()` | `True` |
| VLM | Qwen2.5-VL-3B-Instruct, official local checkpoint |
| Person segmentation | torchvision Mask R-CNN, local checkpoint |

No CUDA PyTorch package was installed. Core inference, segmentation, planning,
criticism, and card rendering ran on AMD Radeon Cloud. No external AI API or
image-generation model was used.

## Automated tests

Command:

```bash
/workspace/venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
```

Result for the final public non-generative product path on Radeon Cloud:
**71/71 passed**.

The final demo also shows **76/76** for the complete development workspace.
That workspace still contained five tests for retired generation experiments.
Those tests and modules are intentionally omitted from this public release,
whose product flow does not generate replacement images.

The suite covers the fixed Planner schema, Critic contract, image orientation,
physical camera-geometry calibration, malformed Qwen JSON repair, permission
policy, HTTP privacy behavior, person-mask matching, deterministic rendering,
and single/group/no-prop guidance.

## Real-GPU regression matrix

Each scenario ran three times through the local HTTP product path.

| Scenario | Runs | Critic pass | People detected / matched | Mean agent time | Peak VRAM |
|---|---:|---:|---|---:|---:|
| Single portrait with phone | 3 | 3/3 | 1 / 1 | 113.401 s including first-run warm-up; warm runs ≈52 s | 9.567 GiB |
| Single portrait, no handheld prop | 3 | 3/3 | 1 / 1 | 116.459 s | 10.684 GiB |
| Three-person group | 3 | 3/3 | 3 / 3 | 226.018 s | 10.677 GiB |

The three-person case intentionally reports the slower path: malformed-comment
repair, local grounding, and a second visual-field completion pass. Results were
not replaced with synthetic estimates.

## Release fixes proven by the matrix

- A no-prop image now renders `Both hands` with a concrete action instead of an empty
  or invented object label.
- Clothing, ties, belts, shoes, and watches remain visible evidence but are not
  presented as interactive photography props.
- Qwen responses containing trailing commas, one missing property comma, or
  `//` line comments are handled by narrow deterministic repairs.
- Model-output parse failures are not misreported as corrupt user images.
- Full-body low-angle instructions require compatible geometric evidence.
  A half-body `waist + level` label no longer forces an incorrect low camera.
- All final cards use the real local person mask and deterministic PIL drawing.

## Evidence files

- `submission/evidence/SAMPLE_SOURCES.md` — licenses and source URLs
- `submission/evidence/RELEASE_CANDIDATE_REPORT.md` — historical nine-run summary
- `submission/final/evidence/*.json` — fresh final English results
- `submission/final/evidence/*.png` — fresh final English cards

The final English files are complete Agent results produced after the final copy
and calibration fixes.

## Fresh final English UI cases

These three complete Agent paths were rerun after the final English UI and
camera-geometry calibration changes:

| Scenario | End-to-end Agent time | Peak allocated VRAM | Notes |
|---|---:|---:|---|
| Single portrait with phone | 82.376 s | 7.558 GiB | One bounded JSON repair |
| Single portrait without a prop | 57.867 s | 10.403 GiB | No invented handheld object |
| Three-person graduation group | 59.569 s | 10.385 GiB | Three foreground people |

The corresponding JSON and cards are under `submission/final/evidence/`.
