# Upstream mechanism and license registry

No upstream source code is vendored in this package. “Remix” means a
license-aware adaptation of mechanisms behind typed interfaces, not copying a
repository or claiming authorship. Every runtime dependency and optional
backend remains replaceable.

| Project | Upstream | Declared license | Status in ProofLaunch |
|---|---|---|---|
| Pillow | https://github.com/python-pillow/Pillow | HPND | Required: deterministic product-layer compositing, audit pixels, and PNG export |
| Gemma 4 E4B-it | https://huggingface.co/google/gemma-4-E4B-it | Gemma Terms of Use | Required multimodal Audience Pulse; safe LoRA targets language-model modules only and adds a visual-retention gate |
| Hugging Face Diffusers | https://github.com/huggingface/diffusers | Apache-2.0 | Implemented local background provider; V6 Gate uses SDXL Base for key Radeon image inference |
| SigLIP2 Base | https://huggingface.co/google/siglip2-base-patch16-224 | Apache-2.0 | Required fifth local visual-semantic release gate; relative zero-shot score with disclosed limits |
| PyTorch | https://github.com/pytorch/pytorch | BSD-3-Clause | Supplied by the Radeon environment; HIP runtime, local inference, VRAM telemetry |
| ModelScope | https://github.com/modelscope/modelscope | Apache-2.0 | Supplied Gemma/LoRA Notebook integration path |
| ComfyUI | https://github.com/comfyanonymous/ComfyUI | GPL-3.0 | Evaluated local graph/backend option; not linked, imported, or redistributed in this package |
| LTX-Video code / 2B weights | https://github.com/Lightricks/LTX-Video | Apache-2.0 code / LTXV Open Weights License 0.X for the selected weight revision | V7 required 24 GB image-to-video tier; custom use restrictions and revenue-threshold commercial terms apply; actual Radeon output remains gated |
| LTX-2.3 | https://github.com/Lightricks/LTX-2 | LTX-2 Community License Agreement | 46 GB+ synchronized audio-video quality candidate; not promoted without ROCm evidence |
| Qwen3-VL | https://github.com/QwenLM/Qwen3-VL | Apache-2.0 | V6 required local image/video evidence analyzer with source locators |
| Whisper | https://github.com/openai/whisper | MIT | Optional local timestamped ASR for audio/video input |
| Grounding DINO | https://github.com/IDEA-Research/GroundingDINO | Apache-2.0 | V6 competition-2X open-set localization specialist; Radeon execution still gated |
| SAM 2.1 Hiera Small | https://github.com/facebookresearch/sam2 | Apache-2.0 | V6 temporal product-mask specialist using the official Transformers video-session API |
| LAION CLAP HTSAT fused | https://huggingface.co/laion/clap-htsat-fused | Apache-2.0 | V6 local decoded-audio semantic gate; paired with a deterministic timestamp-alignment gate |
| Qwen-Agent | https://github.com/QwenLM/Qwen-Agent | Apache-2.0 | Tool/MCP reference only; not adopted because a free agent loop would weaken the bounded L2 release path |
| OpenWorker | https://github.com/andrewyng/openworker | MIT | Local-first outcome, deliverable, resume, and consequential-action approval reference; no source copied |
| UI-TARS / Agent TARS | https://github.com/bytedance/UI-TARS-desktop | Apache-2.0 | Candidate GUI and hybrid-browser adapter |
| Browser Use | https://github.com/browser-use/browser-use | MIT | Candidate stateful browser adapter |
| MCP | https://github.com/modelcontextprotocol/modelcontextprotocol | Apache-2.0 | Typed connector boundary |
| LangGraph | https://github.com/langchain-ai/langgraph | MIT | Optional killed-process resume runtime; not required for the five-day package |
| Agent-S | https://github.com/simular-ai/Agent-S | Apache-2.0 | Evaluation and desktop-agent failure-taxonomy reference |
| OpenHands | https://github.com/OpenHands/OpenHands | MIT | Workspace isolation reference |

## V7.4 immutable external-model lock

`config/model_supply_chain.json` is the reviewer-readable source of the same
seven-role lock embedded in the runtime. The adapter passes each commit to both
processor and weight/pipeline loaders, records `repo@commit` in model evidence,
and fails closed when repository, revision, or license metadata drifts.

| Role | Repository | Immutable revision | Release license metadata |
|---|---|---|---|
| Qwen3-VL understanding | `Qwen/Qwen3-VL-2B-Instruct` | `89644892e4d85e24eaac8bacfd4f463576704203` | Apache-2.0 |
| Grounding DINO | `IDEA-Research/grounding-dino-tiny` | `a2bb814dd30d776dcf7e30523b00659f4f141c71` | Apache-2.0 |
| SDXL Base | `stabilityai/stable-diffusion-xl-base-1.0` | `462165984030d82259a11f4367a4eed129e94a7b` | CreativeML Open RAIL++-M |
| SigLIP2 | `google/siglip2-base-patch16-224` | `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2` | Apache-2.0 |
| LTX-Video | `Lightricks/LTX-Video` | `8984fa25007f376c1a299016d0957a37a2f797bb` | LTXV Open Weights License 0.X (`other` in Hub metadata) |
| SAM 2.1 | `facebook/sam2.1-hiera-small` | `ee5bba1d82bb8749febdf90f45e84b687142ba03` | Apache-2.0 |
| CLAP | `laion/clap-htsat-fused` | `365dea6ef167def6676140ed93bbc43f84dabb28` | Apache-2.0 |

Licenses, security posture, transitive dependencies, current revisions, and
ROCm compatibility must be rechecked before a future release changes this
lock. Model weights can have separate terms from their libraries. In
particular, “open weights” is not treated as synonymous with OSI-approved open
source. Popularity and star count are not adoption criteria.
