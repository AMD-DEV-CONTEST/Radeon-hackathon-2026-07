# Final Track 2 submission materials

Team: **Aperture Intelligence**

Project: **AI Photographer Agent**

Track: **Track 2 — Development & Local Deployment of Private AI Agents**

| Required deliverable | File |
|---|---|
| Project specification (PDF) | `AI-Photographer-Agent-Track2-Specification.pdf` |
| Complete public source code | Repository root |
| Demo video (4:50, English narration and subtitles) | `AI-Photographer-Agent-Track2-Demo.mp4` |
| Supplementary presentation | `AI-Photographer-Agent-Track2-Presentation.pptx` |
| Fresh Radeon result evidence | `evidence/*.json` and `evidence/*.png` |

The submitted path uses the official local
`Qwen/Qwen2.5-VL-3B-Instruct` checkpoint and torchvision's official local
`maskrcnn_resnet50_fpn_v2` weights. No model weights, virtual environment,
credentials, private user photographs, or external AI API keys are included.

The video reports 76/76 tests from the full development workspace. The public
non-generative product path in this repository excludes five tests and modules
from retired generation experiments and passes 71/71 tests on Radeon Cloud.

Performance labels distinguish warm visual inference from complete end-to-end
Agent latency. Fresh end-to-end paths measured 82.376 s, 57.867 s, and 59.569 s;
peak allocated GPU memory was 10.403 GiB.
