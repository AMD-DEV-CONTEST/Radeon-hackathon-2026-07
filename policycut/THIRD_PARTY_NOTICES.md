# Third-Party Notices

PolicyCut builds on the following third-party models, libraries, and tools.
Each component remains subject to its own license; copies of the license
texts are available at the linked upstream repositories. No model weights
are redistributed with this repository — they are downloaded from their
official sources at setup time.

| Component | Use in PolicyCut | License | Source |
|---|---|---|---|
| Grounding DINO (IDEA-Research/grounding-dino-tiny) | Open-vocabulary visual detection | Apache-2.0 | https://github.com/IDEA-Research/GroundingDINO |
| SAM 2 (facebook/sam2.1-hiera-small) | Video mask propagation / tracking refinement | Apache-2.0 | https://github.com/facebookresearch/sam2 |
| Qwen3 (Qwen/Qwen3-4B-Instruct-2507) | Natural-language policy parsing | Apache-2.0 | https://github.com/QwenLM/Qwen3 |
| Whisper (openai/whisper-large-v3-turbo) | Speech-to-text with word timestamps | MIT | https://github.com/openai/whisper |
| YuNet face detector (via OpenCV Zoo) | Fast face keyframe detection | MIT | https://github.com/opencv/opencv_zoo |
| Microsoft Presidio (presidio-analyzer, optional) | Extra audio PII recall | MIT | https://github.com/microsoft/presidio |
| FFmpeg | Media probe, normalize, render, mux | LGPL-2.1+ / GPL-2.0+ (build-dependent) | https://ffmpeg.org |
| FastAPI | HTTP API framework | MIT | https://github.com/fastapi/fastapi |
| OpenCV (opencv-python-headless) | Frame processing, effects, overlays | Apache-2.0 | https://github.com/opencv/opencv |

## Notes

- **FFmpeg** is invoked as an external executable and is not linked into or
  redistributed with PolicyCut. Depending on how the system FFmpeg binary was
  built, it is licensed under LGPL 2.1 or later, or GPL 2 or later when GPL
  components are enabled. See https://ffmpeg.org/legal.html.
- **Hugging Face Transformers, Accelerate, Uvicorn, Pydantic, NumPy, SciPy**
  and other Python dependencies are used under their respective open-source
  licenses (Apache-2.0, BSD, or MIT); see each package's metadata.
- Model weights downloaded at runtime (Grounding DINO, SAM 2, Qwen3, Whisper,
  YuNet) are governed by the licenses listed above as published by their
  authors.
