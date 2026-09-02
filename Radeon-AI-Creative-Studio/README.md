# Radeon AI Creative Studio

Local multimodal image creation workstation for AMD Radeon GPUs and ROCm.

Radeon AI Creative Studio helps creators turn an idea or reference image into a small set of usable visual concepts. It is designed for social media creators, small businesses, product teams, and visual designers who need fast local ideation without sending the core generation request to a closed online image API.

## Features

- Text-to-image generation with Stable Diffusion 1.5
- Reference-image restyling with image-to-image diffusion
- Batch generation of two to four candidates with deterministic seeds
- Image enhancement, contrast/color/sharpness adjustment, and 1x/2x/4x enlargement
- Prompt templates for creative type, style, aspect ratio, and quality
- Generation history, reproducible seeds, downloadable PNG output, and timing/GPU information
- Gradio web UI that runs inside the designated Radeon Cloud container

## AMD Radeon and ROCm adaptation

The core generation pipeline uses PyTorch through its ROCm-compatible `torch.cuda` interface. Stable Diffusion inference is moved to the AMD Radeon GPU with FP16 weights and executed inside `torch.inference_mode()`. The application displays the detected GPU name, VRAM capacity, seed, resolution, steps, and elapsed generation time for each diffusion request.

The image enhancement tab currently uses Pillow for deterministic post-processing. It is intentionally described as a CPU post-processing stage; the key image generation and image-to-image inference stages run locally on the AMD Radeon GPU.

## Tested environment

The application was verified by the project team in the designated Radeon Cloud container on July 31, 2026. Before a final submission, record the exact container tag, GPU name, ROCm version, PyTorch version, and timings in `docs/benchmark.md` so that evaluators can reproduce the result.

Run this verification before launching the UI:

```bash
python -c "import torch; print('torch:', torch.__version__); print('cuda available:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

The expected result is `cuda available: True` with an AMD Radeon GPU name.

## Installation in Radeon Cloud

The Radeon Cloud image should provide the ROCm-compatible PyTorch and torchvision wheels. Do not replace those wheels with generic CPU/CUDA wheels from PyPI. Install the application dependencies with:

```bash
python -m pip install -r requirements.txt
```

If the container does not already contain PyTorch, install the ROCm-specific PyTorch build recommended by the container documentation first, then rerun the verification command above.

The first application run downloads `stable-diffusion-v1-5/stable-diffusion-v1-5` through Hugging Face unless the model is already cached. For an offline or reproducible run, pre-cache the model in the container and set the normal Hugging Face cache variables before starting the app.

## Start the application

```bash
python app.py
```

The server listens on `0.0.0.0:7860`. Open the forwarded Radeon Cloud port for port 7860 in a browser.

## Suggested demo workflow

1. Open the Text-to-Image tab.
2. Select a creative type and style, enter a short idea, and preview the generated prompt.
3. Generate one image and record the displayed GPU and timing information.
4. Upload that image or another reference image in the Image-to-Image tab and create a variation.
5. Use Batch Creation to generate two to four alternatives with adjacent seeds.
6. Open Image Enhancement, apply a 2x enlargement and detail enhancement, and download the result.

## Example prompt

```text
A compact cyberpunk night market in Shenzhen, rain reflections, warm shop lights, cinematic composition, editorial concept art
```

## Reproducibility

Generation results are saved under `outputs/` with the operation mode, timestamp, and seed in the filename. To reproduce a diffusion result, use the same prompt, negative prompt, resolution, number of steps, guidance scale, and seed on the same model revision.

The application currently targets 512x512 generation for a practical memory/performance balance. Batch generation is limited to two to four images to keep the Cloud session responsive.

## Project structure

```text
app.py                    Gradio interface and event handlers
configs/config.py         Model, device, and output configuration
configs/prompt_templates.py  Prompt presets and prompt builder
pipeline/image_generator.py  Text-to-image, image-to-image, and batch diffusion
pipeline/image_enhancer.py   Deterministic Pillow post-processing
utils/timer.py            Inference timing helper
assets/                   Curated demo images and visual evidence
docs/                     Project report, benchmark notes, and demo script
```

## Model and license note

The core model is `stable-diffusion-v1-5/stable-diffusion-v1-5`. Review and comply with the model card and license terms before redistribution. This repository does not bundle model weights; the weights are downloaded or loaded from the runtime cache.

## Known limitations

- The core pipeline requires a ROCm-compatible PyTorch build and an available AMD Radeon GPU.
- The first model load may take several minutes and requires model files to be available in the cache or through the network.
- Image enhancement is CPU-based Pillow post-processing, not a second neural inference stage.
- Large resolutions and large batches may exceed the available VRAM or reduce interactive responsiveness.

## Competition deliverables

- Project Profile Document: `docs/project-profile.pdf`
- Supplementary presentation: `docs/project-poster.pptx`
- Demo script and shot list: `docs/demo-script.md`
- Radeon Cloud measurement template: `docs/benchmark.md`

