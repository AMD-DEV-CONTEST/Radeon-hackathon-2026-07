# AetherStyle

*A Multimodal Content Creation Toolkit for AMD Radeon GPUs / ROCm*

Track 1: Development of Multimodal Content Creation Tools  

Submission materials — Project Profile Document  


---


## 1. Project Background


The explosive growth of short-video, social, and e-commerce content has created huge demand for fast, affordable, and private AI-generated images and video. Most open-source AIGC tooling, however, is built and tested for NVIDIA CUDA, leaving AMD Radeon owners — who often have very capable, cost-effective GPUs — underserved.


AetherStyle was created to close that gap. It is a local-first, one-stop multimodal creation toolkit that runs natively on AMD ROCm and turns natural-language prompts into images and short videos. Rather than hard-wiring a single heavy model, AetherStyle observes the machine's disk and VRAM budget and automatically selects the best model that actually fits, while gracefully falling back to lighter models when a download or load fails. The result is a tool that is stable across a wide range of AMD hardware and never crashes on a misconfigured box.


A second design goal is accessibility for Chinese-speaking creators. The video path is built around Wan2.2-TI2V-5B, whose umt5-xxl text encoder understands Chinese natively, so users can write prompts in Chinese without any translation step.


## 2. Target Users & Application Scenarios


### Target users


### Application scenarios


## 3. System Architecture


AetherStyle is organized in clear layers so that model choice, hardware adaptation, and the user interface are decoupled:


Data flow: prompt (and optional image) -> engine selects a model that fits the budget -> generation -> frame/image normalization -> export to MP4 / PNG (and optional GIF). Robustness comes from three mechanisms: (a) disk gating that refuses to download weights that will not fit; (b) weight-integrity checks that detect incomplete downloads; and (c) an automatic tier fallback that routes to the next model when any stage fails — so the service stays up instead of crashing.


## 4. Model & Algorithm Introduction


### Image generation


Image models are latent-diffusion / DiT architectures. The primary model is Stable Diffusion 3.5-Medium (MMDiT with a T5-XXL + CLIP text encoder and flow-matching sampling), chosen for its strong prompt adherence and quality. It falls back to SDXL (UNet + refiner) and then SD v1.5 for constrained environments.


### Video generation


The primary video model is Wan2.2-TI2V-5B: a ~5B-parameter DiT with the umt5-xxl multilingual text encoder, capable of 720P @ 24fps clips under the Apache-2.0 license. Its multilingual encoder means Chinese prompts work natively. Two fallbacks keep the tool usable everywhere: LTX-Video (a 2B DiT with T5-XXL, very fast) and the legacy damo-vilab text-to-video-ms-1.7b pipeline.


### Inference configuration


The key algorithmic contribution at the system level is the best-model selection heuristic: it compares each candidate model's size against free disk and VRAM, downloads only what fits, and degrades safely — turning 'will it run on my AMD card?' into an automatic decision.


## 5. Adaptation for AMD Radeon GPU / ROCm


In summary, AetherStyle makes multimodal image+video generation a first-class, stable experience on AMD Radeon / ROCm hardware, with automatic model selection, native Chinese prompts, and crash-proof operation.
