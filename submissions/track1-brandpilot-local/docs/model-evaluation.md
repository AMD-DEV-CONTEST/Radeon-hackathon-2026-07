# Model and framework evaluation

## Decision

Use **Hugging Face Diffusers with `stabilityai/stable-diffusion-xl-base-1.0` and `h94/IP-Adapter`** as the primary Phase 3 path. Begin with ordinary SDXL image-to-image at conservative strength, then add the SDXL ViT-H IP-Adapter only after the base pipeline succeeds. This provides the clearest Python integration with BrandPilot's existing inference interface, strong 1024px output quality, deterministic seeds, and explicit control over loading and measurements.

Use **`stable-diffusion-v1-5/stable-diffusion-v1-5` with Diffusers** as the limited-VRAM fallback. Its current Hugging Face repository is a mirror of the deprecated RunwayML repository, so provenance and license files must be captured and reviewed before any commercial deployment. It is acceptable for a time-boxed compatibility experiment, not yet approved for production.

Planning figures below remain estimates unless explicitly marked measured. The
first Radeon Cloud run measured the selected SDXL path; other candidates remain
unverified.

## First measured result

On 2026-07-25, SDXL base image-to-image succeeded on one Radeon `gfx1100` device
with 48 GiB detected memory. Exact revision
`462165984030d82259a11f4367a4eed129e94a7b` loaded directly in fp16 with no CPU
offload or attention slicing. At 768 × 768 and 15 steps, cold load took 132.295
seconds, generation took 222.111 seconds, peak allocated memory was 13.41 GiB,
and peak reserved memory was 14.31 GiB. This validates compatibility, not
product preservation or production quality.

## Comparison

| Path | Exact model/source | License and commercial status | Approximate download | Planning VRAM | Image-to-image and preservation | Quality / expected speed | ROCm and setup | Hackathon fit / main risks |
|---|---|---|---:|---:|---|---|---|---|
| **Primary: Diffusers SDXL + IP-Adapter** | [`stabilityai/stable-diffusion-xl-base-1.0`](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0); [`h94/IP-Adapter`](https://huggingface.co/h94/IP-Adapter) using `ip-adapter_sdxl_vit-h` or Plus | SDXL: CreativeML Open RAIL++-M. IP-Adapter: Apache-2.0. Commercial use is not categorically prohibited, but SDXL use restrictions, output responsibility, trademarks, and input rights apply. Legal review still required. | SDXL inference checkpoint about **6.94 GB**; Diffusers component cache can be larger. IP-Adapter weight **~698 MB** plus a CLIP image encoder. Avoid cloning the full 76.9 GB repository. | **12–16 GB** for base fp16 is the first test target; budget **14–18 GB** with image encoder/adapter. CPU offload can reduce VRAM but may be much slower. | Native `AutoPipelineForImage2Image`. IP-Adapter adds reference-image conditioning; the Plus variant uses patch embeddings and is documented as closer to the reference. Add masks or ControlNet only after baseline success. | Highest expected advertising quality of evaluated practical candidates; slower than SD 1.x. No numeric latency claim before measurement. | PyTorch on ROCm intentionally uses the `cuda` device API. Diffusers is pure Python above PyTorch and should be tested against AMD's ROCm 7.2 PyTorch build. Moderate installation complexity. | **Best fit** if the cloud GPU has adequate memory. Risks: first-load download time, attention/operator compatibility, product geometry drift, text artifacts, and license obligations. |
| **Fallback: Diffusers SD 1.5** | [`stable-diffusion-v1-5/stable-diffusion-v1-5`](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) | CreativeML OpenRAIL-M in the model card. Responsible-use restrictions apply. The current repository says it is an unaffiliated mirror of deprecated RunwayML material, so **commercial clearance is unresolved** until provenance and the exact downloaded revision are reviewed. | Inference-only single checkpoint is commonly about **4.3 GB**; a Diffusers snapshot may require additional component files. | **6–8 GB** base fp16 planning target; **8–12 GB** with ControlNet/IP-Adapter. | Native image-to-image. Compatible SD 1.5 IP-Adapter weights exist. Canny ControlNet can preserve silhouette/edges, but logos, labels, and exact packaging still need masking/compositing. | Lower 512px detail than SDXL; expected to load and generate faster and fit smaller GPUs. No numeric latency claim before measurement. | Same PyTorch/ROCm path with fewer memory demands. Low-to-moderate installation complexity. | Strong compatibility fallback. Risks: weaker typography and premium detail, 512px native resolution, mirror provenance, and product drift. |
| **ComfyUI on ROCm** | [`Comfy-Org/ComfyUI`](https://github.com/Comfy-Org/ComfyUI) with either model above | ComfyUI code: GPL-3.0. Model licenses remain separate. Running it as a tool is possible; distributing or tightly integrating modified GPL code needs review. | Framework is lightweight; model downloads are unchanged. | Model-dependent; project guidance treats 8 GB as a practical floor and 16 GB+ as preferable for larger workflows. | Visual nodes support img2img, masks, ControlNet, and IP-Adapter workflows. Strong experimentation and workflow visualization. | Same underlying model quality and broadly similar compute; node graphs add orchestration rather than model speed. | Upstream documents stable ROCm 7.2 PyTorch installation on Linux. More moving parts and a separate server/API lifecycle. | Useful secondary lab/debugging path, **not the first backend** under a 45-minute session. Risks: dependency drift, custom-node supply chain, GPL boundary, reproducibility of graphs, and integration time. |
| **SD 1.5 + Canny ControlNet** | Base above plus [`lllyasviel/control_v11p_sd15_canny`](https://huggingface.co/lllyasviel/control_v11p_sd15_canny) | Base: OpenRAIL-M with the provenance caveat above. ControlNet card: CreativeML OpenRAIL-M. Commercial review required. | Base about **4.3 GB** plus ControlNet roughly **1.4–1.6 GB** in fp32 Diffusers form. | **8–12 GB** planning range in fp16, depending on attention implementation and offload. | Strong edge/layout conditioning. Good for keeping product outline and pose; weak for exact colors, logos, fine text, and unseen surfaces. Combine later with IP-Adapter or masked compositing. | Expected below SDXL in detail and faster at 512px. No numeric latency claim before measurement. | Official Diffusers examples exist; OpenCV edge preprocessing adds little setup. | Good fallback preservation test after base SD 1.5 works. Risk: over-constrained edges, haloing, loss of label fidelity, and extra memory. |
| **SDXL + IP-Adapter + structural control** | Primary models; later add an SDXL-compatible ControlNet or a segmentation/mask stage after exact checkpoint review | Licenses are cumulative and must be reviewed checkpoint by checkpoint. Do not assume an adapter inherits Apache-2.0 or SDXL terms. | SDXL **6.94 GB** + adapter/encoder; structural model commonly adds several GB. | Plan **16–24 GB** until measured. | Best evaluated route for identity plus layout: img2img preserves pixels, IP-Adapter preserves semantic/product reference, and a mask/ControlNet constrains structure. Exact label preservation still needs compositing. | Potentially best quality and slowest/most complex evaluated path. | Multiple model loads increase ROCm/operator and memory risk. | Target architecture after the minimal first inference. Not appropriate for the first 45-minute compatibility test. |

## License findings

- SDXL's CreativeML Open RAIL++-M grants model use and distribution rights subject to use-based restrictions. Stability AI claims no general right in outputs, while placing responsibility for outputs on the user.
- IP-Adapter is Apache-2.0, but its CLIP encoder and SDXL base retain their own licenses.
- SD 1.5 and the evaluated ControlNet use CreativeML OpenRAIL-M. The current SD 1.5 repository is a mirror and explicitly says it is unaffiliated with RunwayML; freeze and archive the exact model-card/license revision before relying on it.
- ComfyUI is GPL-3.0. Treat it as an external experiment service unless a deliberate GPL-compatible distribution decision is made.
- None of these licenses clears copyrighted inputs, product photography, trademarks, packaging, publicity rights, or misleading advertising claims. Human and legal review remain required.

**License status:** suitable for hackathon compatibility research with the stated restrictions; **not yet commercially cleared**. The primary SDXL/IP-Adapter combination has the cleanest evaluated provenance, but still requires final legal review.

## Compatibility findings

- AMD publishes ROCm 7.2/7.2.1 PyTorch wheels and recommends its tested wheels or prebuilt containers. The documented Linux wheel uses Python 3.12 and PyTorch 2.9.1.
- PyTorch deliberately exposes HIP devices through `torch.cuda`; `DEVICE=cuda` is therefore correct on ROCm. `torch.version.hip`, device name, and `rocm-smi` evidence distinguish AMD from NVIDIA.
- Diffusers uses PyTorch operations and documents SDXL, image-to-image, IP-Adapter, ControlNet, fp16, and CPU offload. Radeon Cloud validation is still required because an upstream-supported API does not guarantee every attention kernel or dtype works on the selected GPU.
- ComfyUI upstream documents stable ROCm 7.2 wheels on Linux. It is technically credible, but increases setup and integration surface for the first session.
- Product identity cannot be guaranteed by any generative model. The strongest practical plan is low-strength img2img, IP-Adapter reference conditioning, an explicit product mask, and compositing the untouched product back over generated backgrounds.

## Rejected or deferred options

- **SDXL refiner:** deferred because it adds another multi-gigabyte model and load step before base compatibility is proven.
- **FLUX.1-dev:** rejected for the first sessions because its non-commercial license and much larger memory/download footprint conflict with license safety, five-hour credits, and fast setup.
- **Stable Diffusion 3/3.5 Large:** deferred because of larger memory demands, gated/community licensing obligations, and unnecessary first-session complexity.
- **SDXL Turbo / LCM as the first test:** deferred. Low-step generation may be useful later, but it changes guidance/scheduler behavior and complicates the clean baseline.
- **Fine-tuning, DreamBooth, or LoRA training:** rejected for Phase 2/first GPU session because training consumes credits, adds data/license risk, and is not required to prove inference.
- **ComfyUI as the production backend:** rejected for the first integration because Diffusers maps directly to the existing Python interface with fewer services and clearer benchmark hooks.
- **ControlNet alone:** rejected as an identity solution. It preserves conditions such as edges or depth, not exact logos, text, or product pixels.

## Final recommendation

1. In the first GPU session, verify ROCm/PyTorch and run the smallest **SDXL base image-to-image** test at 768×768 or lower if necessary, without the refiner or adapters.
2. If SDXL cannot load or exceeds available VRAM after one evidence-based offload attempt, switch immediately to **SD 1.5 image-to-image** rather than spending credits debugging.
3. In session two, add `h94/IP-Adapter` with the SDXL ViT-H weight and compare product similarity at fixed seeds and strengths.
4. Preserve exact packaging with a mask and post-generation compositing; add ControlNet only when a specific structural failure is demonstrated.
5. Use Diffusers as the application backend. Keep ComfyUI as an optional visual research tool, not a dependency of the core service.

## Primary sources

- [AMD: Install PyTorch for ROCm 7.2 on Radeon/Linux](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/install/installrad/native_linux/install-pytorch.html)
- [AMD: PyTorch compatibility for ROCm](https://rocm.docs.amd.com/en/docs-7.2.2/compatibility/ml-compatibility/pytorch-compatibility.html)
- [PyTorch: HIP (ROCm) semantics](https://docs.pytorch.org/docs/main/notes/hip.html)
- [Hugging Face Diffusers: IP-Adapter and image-to-image](https://huggingface.co/docs/diffusers/using-diffusers/ip_adapter)
- [Hugging Face Diffusers: memory optimization](https://huggingface.co/docs/diffusers/optimization/memory)
- [Stability AI: SDXL base model card](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Stability AI: SDXL Open RAIL++-M license](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md)
- [IP-Adapter model card and Apache-2.0 license](https://huggingface.co/h94/IP-Adapter)
- [Stable Diffusion v1.5 mirror model card](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5)
- [ControlNet v1.1 Canny model card](https://huggingface.co/lllyasviel/control_v11p_sd15_canny)
- [ComfyUI upstream repository, ROCm instructions, and GPL-3.0 license](https://github.com/Comfy-Org/ComfyUI)
