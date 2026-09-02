# Radeon AI Creative Studio

## Project Profile Document

### 1. Project background

Creative teams often need many visual directions before choosing one final design. Cloud-only image tools can add latency, usage cost, privacy concerns, and limited control over the execution environment. Radeon AI Creative Studio is a lightweight local visual ideation workstation that turns text ideas and reference images into a small set of editable creative candidates.

The project targets Track 1: Development of Multimodal Content Creation Tools. It demonstrates text-to-image generation, reference-image restyling, batch ideation, and image enhancement in a single web interface.

### 2. Target users and application scenarios

- Social media creators preparing campaign concepts and post artwork.
- Small businesses exploring product, poster, and promotional visual directions.
- Visual designers generating reference variations before manual refinement.
- Content teams producing multiple aspect-ratio-ready concepts from one idea.

The practical value is fast local exploration: a user can compare several seeded alternatives, refine a reference image, and prepare a higher-resolution output without sending the core prompt and image data to a closed image-generation API.

### 3. Core workflow

```text
Text idea or reference image
            |
            v
       Gradio Web UI
            |
            v
 Prompt template builder
            |
            v
 PyTorch + Diffusers pipeline
            |
            v
 AMD Radeon GPU through ROCm
            |
            v
 Generated image candidates
            |
            v
 History, download, enhancement
```

The workflow is complete from input to output. Text-to-image creates a new visual from a prompt. Image-to-image uses a reference image and a strength value to control how much of the source composition is retained. Batch generation produces two to four deterministic candidates using adjacent seeds. Enhancement applies deterministic Pillow operations for contrast, color, sharpness, detail, and enlargement.

### 4. Model and algorithm

The core model is the open model `stable-diffusion-v1-5/stable-diffusion-v1-5`, loaded through Hugging Face Diffusers. The text-to-image pipeline uses `StableDiffusionPipeline`; the reference workflow uses `StableDiffusionImg2ImgPipeline`.

The implementation uses FP16 model weights, GPU-resident PyTorch tensors, `torch.inference_mode()`, and explicit seeded generators. These choices reduce memory pressure, avoid unnecessary autograd work, and make output comparisons repeatable.

The enhancement module is intentionally deterministic and lightweight. It uses Pillow auto-contrast, brightness, contrast, color, sharpness, Unsharp Mask detail enhancement, and Lanczos resizing. This stage is CPU post-processing and is not presented as GPU inference.

### 5. AMD Radeon GPU and ROCm adaptation

The application is designed for the designated AMD Radeon Cloud environment. The ROCm-enabled PyTorch build exposes the available Radeon device through the CUDA-compatible PyTorch API used by Diffusers. At startup, the application checks `torch.cuda.is_available()`, detects the GPU name, reads total VRAM, and moves both diffusion pipelines to `cuda`.

The key inference stages therefore run locally on the AMD Radeon GPU:

- Text encoding and diffusion denoising for text-to-image.
- Text encoding, denoising, and reference-image conditioning for image-to-image.
- Repeated or batched diffusion requests for batch creation.

The UI reports GPU name, VRAM, seed, image size, steps, and elapsed time after each core generation request. The final submission should include the exact Radeon Cloud container tag and measured timings captured from the verified run.

### 6. Functional completeness and output quality

The project provides a single input-processing-output workflow with four user-facing creation modes. Seed controls support reproducibility, prompt presets reduce the barrier for new users, and batch output supports rapid comparison. Generated outputs are saved as PNG files with operation mode and seed in the filename, which helps a designer return to a promising candidate.

### 7. Deployment and reproducibility

The repository includes a Gradio web application, Python modules, dependency list, startup command, model identifier, and reproducibility instructions. The Radeon Cloud container should provide ROCm-compatible PyTorch and torchvision wheels; the application requirements intentionally do not overwrite those container-specific wheels with generic PyPI packages.

The model is not bundled in the repository. It is loaded from the Hugging Face cache or downloaded on first use. For an offline evaluator run, the model should be pre-cached in the container before launching the application.

### 8. Limitations and future work

The current project focuses on a dependable lightweight image workflow. The next technical steps could include a GPU-native super-resolution model, LoRA style packs, ControlNet guidance, and video clip stylization. These are intentionally outside the final competition scope so that the submitted workflow remains stable and reproducible.

### 9. Deliverables

- Source code and README.
- Project Profile Document in PDF format.
- Three-to-five-minute Radeon Cloud demonstration video.
- Supplementary presentation/poster.
- Curated output examples and benchmark evidence.
