# AetherStyle — Submission Checklist (Track 1)

This checklist maps every item in **Submission Requirements** to the material we prepared,
so nothing is missing at PR time.

## Submission Requirements → deliverables

| Requirement | Where it lives | Status |
| --- | --- | --- |
| **Project Profile Document (PDF)** with: | `submission/Project_Profile.pdf` (+ `Project_Profile.md` source) | ✅ |
| &nbsp;&nbsp;• Project background | §1 | ✅ |
| &nbsp;&nbsp;• Target users & application scenarios | §2 | ✅ |
| &nbsp;&nbsp;• System architecture | §3 | ✅ |
| &nbsp;&nbsp;• Model & algorithm introduction | §4 | ✅ |
| &nbsp;&nbsp;• Adaptation for AMD Radeon GPU / ROCm | §5 | ✅ |
| **Project Source Code** | the `aether_style/` repo (engine.py, app.py, run_light.sh, test_flow.py, requirements.txt) | ✅ |
| &nbsp;&nbsp;• Complete source code repository | fork of the luma repo + our code | ⚠️ you fork & push |
| &nbsp;&nbsp;• README (env config, startup, deps) | `submission/README.md` (also keep at repo root) | ✅ |
| **Demo Video** (3–5 min, real AMD ROCm run) | `submission/AetherStyle_Demo.mp4` (record on test machine; script in `Demo_Video_Storyboard.md`) | ⚠️ record on ROCm box |
| **Supplementary (Choose One)** | `submission/AetherStyle_Slides.pptx` | ✅ (PPT chosen) |

## Before you open the PR

- [ ] **Fork** the luma repo and branch your work.
- [ ] Copy `README.md`, `Project_Profile.pdf`, `AetherStyle_Slides.pptx` into the repo (or `submission/`).
- [ ] Record `AetherStyle_Demo.mp4` on the AMD ROCm machine using `Demo_Video_Storyboard.md`.
- [ ] All text (PDF, PPT, README, PR description, video captions) is in **English**.
- [ ] PR title exactly: **`Track 1, <Your Team Name>, AetherStyle`** (fill in your team name).
- [ ] Repo includes the full `aether_style/` source (engine.py, app.py, run_light.sh, test_flow.py, requirements.txt).

## Quick verification commands (run on the ROCm box)

```bash
source /opt/venv/bin/activate
python3 test_flow.py --mode env          # HIP backend live
bash run_light.sh                          # Web UI on :7860
python -m py_compile engine.py app.py test_flow.py   # syntax OK
```

## Note on placeholders

- **<Your Team Name>** — replace with your actual team name in the PR title and the end card of the demo video.
- Application name is **AetherStyle** (the project directory `aether_style`).
- A **Poster** was not produced because the rules allow *PPT or Poster* (one is enough); the PPT above satisfies the supplementary requirement. If a poster is preferred, say so and it can be generated.
