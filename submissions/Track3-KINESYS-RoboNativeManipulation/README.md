# RoboNativeManipulation — KINESYS · AMD AI DevMaster Hackathon · Track 3 (Physical AI)

> **English: this file `README.md`** · 简体中文：`README_cn.md`

Teaching robots to operate home appliances in photorealistic household scenes. This project builds an end-to-end pipeline — **real-scene 3DGS reconstruction → data replay collection → dual-framework VLA post-training → AMD single-GPU inference → closed-loop evaluation** — with every key stage running on a **single AMD Radeon PRO W7900D (gfx1100, 48 GB) + ROCm 7.2.1**.

**One-line result**: Under the same GPU, the same seed, and the same 3DGS shell — DM0.5 (PyTorch+ROCm) reaches a **50%** success rate on the native clean scene and **40%** on the harder visual domain with the 3DGS shell; Pi0.5 (JAX+ROCm) provides a **10%** baseline on the shell scene; the 3DGS shell reconstruction achieves **PSNR 27.9 / SSIM 0.937** on held-out views.

> For the full technical narrative, system architecture, detailed stage-by-stage walkthrough, comparison against BiGym paper baselines, and upstream open-source contributions, see the **technical report [`TechnologyReport_cn.md`](./TechnologyReport_cn.md)**.
Demo Video: ./Radeon-hackathon-2026-07/submissions/Track3-KINESYS-RoboNativeManipulation/demo_video.mp4


---

## What this submission contains (deliverables index)

| Deliverable | File | Description |
| --- | --- | --- |
| Technical report (CN) | [`TechnologyReport_cn.md`](./TechnologyReport_cn.md) | Main report (in-depth narrative + evidence) |
| Technical report (EN) | [`TechnologyReport.md`](./TechnologyReport.md) | English version |
| Reproducible README (EN) | `README.md` (this file) | English version of `README_cn.md` |
| Source code · Core repo | [`rocm_bigym_3dgs/`](./rocm_bigym_3dgs/README.md) | 3DGS shell generation + data replay collection + closed-loop evaluation orchestration (PyTorch + gsplat + MuJoCo/HIP) · [eust-w/amd-bigym-3dgs-rocm](https://github.com/eust-w/amd-bigym-3dgs-rocm) |
| Source code · Pi0.5 | [`rocm_pi05/`](./rocm_pi05/README.md) | Pi0.5 LoRA fine-tuning + HTTP inference (**JAX + ROCm**) · [WuChao-2024/openpi_lerobot_plus](https://github.com/WuChao-2024/openpi_lerobot_plus) |
| Source code · DM0.5 | [`rocm_dm05/`](./rocm_dm05/README.md) | DM0.5 fine-tuning + merge + inference + evaluation (**PyTorch + ROCm**) · [Kyrie-w8/amd-bigym-3dgs-opendm](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm) |
| Pipeline overview diagram | [`assets/Flat_combined.jpg`](./assets/Flat_combined.jpg) | One-shot pipeline overview |
| Demo video | _(pending)_ | Rules require 3–5 minutes, showing the command-line / run flow and results |

---

## How to reproduce

**Reproducibility** of the whole pipeline rests on three repositories working together, **each with a self-contained, authoritative README**. The table below is for navigation only — it tells you which step to perform, what you will get, and which document to follow; **the specific commands, parameters, and ROCm pitfalls live in that document and are not repeated here**.

| # | Stage | What you will get | Follow this document (authoritative source) |
| --- | --- | --- | --- |
| 1 | 3DGS shell reconstruction | Photorealistic kitchen shell: 352 1080p images → ~1.45M Gaussians after cleanup, held-out views **PSNR 27.9 / SSIM 0.937** | [`rocm_bigym_3dgs/docs/05-3d-reconstruction.md`](./rocm_bigym_3dgs/docs/05-3d-reconstruction.md) (see also [`reconstruction/README.md`](./rocm_bigym_3dgs/reconstruction/README.md) and the "AMD/ROCm quick start" section of that repo's README) |
| 2 | Shell import into BiGym | Three-camera (head / dual-arm) visual shell synthesis, strict rendering with no fallback, no new physics/collision added | [`rocm_bigym_3dgs/docs/06-shell-import.md`](./rocm_bigym_3dgs/docs/06-shell-import.md) |
| 3 | Data replay and collection | 32 LeRobot v3 `DishwasherUnloadCutleryLong` trajectories (fail-closed; only genuinely successful data is released) | [`rocm_bigym_3dgs/docs/03-collection.md`](./rocm_bigym_3dgs/docs/03-collection.md) (`make collect` / `make validate`) |
| 4a | Pi0.5 training (JAX+ROCm) | Pi0.5 LoRA policy weights (horizon 20) | [`rocm_pi05/docs/amd_rocm_jax.md`](./rocm_pi05/docs/amd_rocm_jax.md) |
| 4b | DM0.5 training (PyTorch+ROCm) | Merged full DM0.5 policy | [`rocm_dm05/README.md`](./rocm_dm05/README.md) §3 "Train and merge" (see also [`docs/training_optimization.md`](./rocm_dm05/docs/training_optimization.md)) |
| 5 | Inference service | provider-neutral HTTP service: `/health` + `/process_frame` (protocol v2) | Pi0.5: [`rocm_pi05/docs/amd_rocm_bigym_eval.md`](./rocm_pi05/docs/amd_rocm_bigym_eval.md); DM0.5: [`rocm_dm05/README.md`](./rocm_dm05/README.md) §5 "Optional HTTP provider" |
| 6 | Closed-loop evaluation | Success rates: DM0.5 native **50%** / 3DGS **40%**; Pi0.5 3DGS **10%** | DM0.5 ships deterministic evaluation [`rocm_dm05/README.md`](./rocm_dm05/README.md) §4 "Evaluate" (`run_amd_eval.sh`); Pi0.5 + side-by-side dual-model comparison [`rocm_bigym_3dgs/docs/07-evaluation.md`](./rocm_bigym_3dgs/docs/07-evaluation.md) (+ [`evaluation/bigym-3dgs/README.md`](./rocm_bigym_3dgs/evaluation/bigym-3dgs/README.md)) |

> - **Two-process evaluation is a hard constraint**: The JAX policy and the PyTorch/gsplat simulation each bring their own ROCm runtime; putting them in the same process triggers MIOpen/rocBLAS symbol conflicts. The policy runs as a service, the simulation runs as an independent process, and the two time-share a single GPU — this is the fundamental reason the evaluator is not bound to either framework. For the HTTP contract, see [`evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md`](./rocm_bigym_3dgs/evaluation/bigym-3dgs/INFERENCE_PROTOCOL.md).
> - **Environment and dependencies**: The environment section of each repo's README + each dependency manifest (e.g. [`rocm_pi05/requirements_rocm.txt`](./rocm_pi05/requirements_rocm.txt)) + [`rocm_bigym_3dgs/docs/08-repository-revisions.md`](./rocm_bigym_3dgs/docs/08-repository-revisions.md) (the locked repo / branch / commit ledger).
> - **Evaluation protocol**: Task `DishwasherUnloadCutleryLong`, seeds `200000–200049`, 20 Hz, chunk 16, max 800 steps, single 3DGS shell, single GPU.
> - **Dataset evidence boundary (honest disclosure)**: The 32 LeRobot replay trajectories released here are a **cross-platform reference baseline** (`runtime: reference-baseline`, `status: technical_pass_visual_approval_pending`; the runtime environment is a historical comparison baseline, not ROCm). They are for traceability / comparison only and **must not be used as evidence that "AMD ROCm main-line training/collection has been accepted as complete"**. The AMD ROCm main line is defined by the single gfx1100 GPU — the standard-room reconstruction has been reproduced on real hardware (receipt `amd_rocm_reproduction_passed`); independent acceptance of the 32 replays on AMD (strict three-camera replay + manual visual review) is still an open stage. See "Stage 2" of the technical report.

---

## Hardware and software

- **GPU**: AMD Radeon PRO W7900D, `gfx1100`, 48 GB (the entire pipeline on a single GPU)
- **ROCm**: 7.2.1
- **Frameworks**: Pi0.5 uses **JAX 0.6.0 (rocm7.0.2)**; DM0.5 / gsplat use **PyTorch 2.8 (ROCm)**
- **Simulation / data**: MuJoCo 3.10, BiGym 4.1, LeRobot 0.6.0, gsplat 1.4.0, OpenSplat (HIP)
- **Robot**: Unitree H1 humanoid + two Robotiq 2F-85 grippers (BiGym)

---

## Release artifacts

| Artifact | Location |
| --- | --- |
| DM0.5 full checkpoint (native 50% / 3DGS 40%) | [`wangbin08/DM05-BiGym-CutleryLong-50pct`](https://huggingface.co/wangbin08/DM05-BiGym-CutleryLong-50pct) |
| Pi0.5 LoRA weights (horizon 20) | [`WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora`](https://huggingface.co/WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora) |
| 3DGS kitchen shell (CC BY-NC) | [`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804) (rev `amd-rocm-w7900d-20260804`) |
| Robot dataset | [`openSource_AMD_AI_DevMaster_Hackathon_202608`](https://huggingface.co/datasets/WuChao-Cauchy/openSource_AMD_AI_DevMaster_Hackathon_202608), [`bigym_plus_datasets`](https://huggingface.co/datasets/WuChao-Cauchy/bigym_plus_datasets) |

---

## Upstream open-source contributions

During the competition we broke general-purpose improvements into small upstream PRs, giving back to multiple upstream projects, with a focus on improving AMD/ROCm platform support (this corresponds to the "upstream open-source community contribution" scoring dimension). The status in the table below was verified on 2026-08-06; details are also in the core repo's [`docs/upstream-contributions.md`](./rocm_bigym_3dgs/docs/upstream-contributions.md).

| Upstream project | PR | What it does / what it solves |
| --- | --- | --- |
| [`nerfstudio-project/gsplat`](https://github.com/nerfstudio-project/gsplat) | [#1046](https://github.com/nerfstudio-project/gsplat/pull/1046) | Makes the ROCm JIT compilation flags more compatible: separates CUDA and ROCm compile flags (fast-math, lineinfo, nvcc-only warnings/params), fixes the source of hipcc errors, and provides a usable set of compile flags for the AMD path; adds a CPU-only build-flag test. |
| same | [#1045](https://github.com/nerfstudio-project/gsplat/pull/1045) | Fixes ROCm toolchain detection for the lazy backend: correctly identifies hipcc, prefers the `ROCM_HOME` provided by `torch.version.hip` with a PATH fallback, and avoids declaring gsplat unavailable just because detection failed; leaves the CUDA nvcc branch behavior unchanged. |
| [`NeuracoreAI/bigym`](https://github.com/NeuracoreAI/bigym) | [#65](https://github.com/NeuracoreAI/bigym/pull/65) | Supports configurable camera FOV and large-resolution observations: adds a fovy config, extends the MuJoCo framebuffer according to the config, supports large-image observations, and prevents large-resolution cameras from failing to initialize. |
| same | [#64](https://github.com/NeuracoreAI/bigym/pull/64) | Loads the fallback conversion by the requested number of demos (instead of all): reduces memory and I/O, and avoids deserializing every file even when only 1–2 demos are needed; includes a regression test. |
| same | [#63](https://github.com/NeuracoreAI/bigym/pull/63) | Adds a headless EGL pixel-rendering benchmark: docs + script + acceptance criteria, used as a reproducible performance/correctness smoke test for GPU pixel observations. |
| same | [#62](https://github.com/NeuracoreAI/bigym/pull/62) | Fixes the demo recorder state machine: stops recording and resets state after a successful save, and stays retryable on failure. |
| same | [#61](https://github.com/NeuracoreAI/bigym/pull/61) | Makes demonstration saving atomic: switches to a temp write + `os.replace`, reducing the risk of corrupted files; adds regression coverage for exception paths. |
| [`Kyrie-w8/amd-bigym-3dgs-opendm`](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm) | [#1](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm/pull/1) | Extracts a shared DM0.5 policy loader and provides `/health` and `/process_frame` protocol v2 services — **merged into upstream `main` on 2026-08-06** (merge commit `8f018b25…`), the only upstream PR in this work that has been merged. |

> - Other than OpenDM #1 which is merged, the gsplat / bigym PRs above are currently open (awaiting review).
> - We also adapted [`pierotofy/OpenSplat`](https://github.com/pierotofy/OpenSplat) for AMD ROCm/HIP builds (`opensplat-rocm-home.patch`, `opensplat-force-rocm-include.patch`; see the core repo's `reconstruction/patches/`), letting it compile and run on gfx1100 with the native HIP backend — these are local working-branch patches, not yet submitted as upstream PRs. The gsplat gfx1100 runtime patch `gsplat-1.4.0-rocm-gfx1100.patch` is likewise a local-branch patch and is a different change from the two gsplat upstream PRs in the table above.

---

## License

The repository code is Apache-2.0 (unless a file states otherwise). Derivative assets from upstream retain their respective terms: 3DGS shell assets are CC BY-NC 4.0 (+ DL3DV terms); model weights are under Gemma Terms of Use; BiGym demonstrations retain their upstream terms. **No model weights or large scene assets are distributed inside the Git tree.** For the full license table (repos / weights / datasets / libraries), see the technical report.

> Note: The two released datasets (`openSource_AMD_AI_DevMaster_Hackathon_202608` and `bigym_plus_datasets`) are licensed under CC BY-NC 4.0 — their visual observations contain reconstructed backgrounds sourced from DL3DV (CC-BY-NC), while the robot trajectories come from BiGym (Apache-2.0) demonstrations, so the datasets as a whole adopt the CC-BY-NC 4.0 terms. Downstream users must comply with the non-commercial restriction and retain source attribution.
