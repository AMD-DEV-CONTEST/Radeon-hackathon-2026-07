# Field notes: serving LLMs on Radeon Cloud (gfx1100), night of 2026-08-05

Everything below was measured on the hackathon instance (Radeon PRO W7900-class,
gfx1100, 48 GB VRAM, ROCm 7.2.1, vLLM 0.16.1.dev rocm721 image build of 2026-03-18).
Motto of the project: measured, not assumed. These are the findings the leaderboard
numbers stand on, including the paths that failed.

## Telemetry

1. **The amdsmi energy accumulator is wired but dead on this SKU.** `amdsmi_get_energy_count` returns a well-formed struct (counter_resolution 15.3 uJ) whose accumulator stays at 0 across idle and loaded windows. Consequence: energy is measured by integrating `amdsmi_get_power_info().average_socket_power` at 2 Hz over each benchmark window, reported as `method: power_integration` in every run record. Socket power reads are healthy (8-9 W idle, cap 241 W).
2. **Power capping is expected to be denied in the cloud container** (no CAP_SYS_ADMIN), as on every cloud NVIDIA pod we tested in Act I; the agent reports the denial rather than hiding the lever.

## Serving Gemma 4 on this build: two documented dead ends

3. **Native architecture absent.** This vLLM ROCm build (March 2026 snapshot) predates Gemma 4: no `gemma4` entry in the model registry (gemma → gemma3n only), and its pinned transformers 4.57 does not recognize the `gemma4` config type.
4. **Transformers-fallback path broken.** After upgrading transformers to 5.14 (config then parses), `--model-impl transformers` dies during weight load with a silent native crash (no Python traceback, EngineCore gone mid-safetensors-load). Reproduced on gemma-4-12B-it bf16.
5. **The QAT w4a16 kernel gap, precisely.** `gemma-4-31B-it-qat-w4a16-ct` (compressed-tensors, group size 32) finds no usable WNA16 kernel on gfx1100: ConchLinearKernel supports only group sizes {-1, 128}; ExllamaLinearKernel requires fp16 activations while Gemma checkpoints are bf16. Exact error preserved in the run logs. To our knowledge these RDNA3 numbers/limits are not published anywhere.

## Network (mainland-China Radeon Cloud specifics)

6. **huggingface.co is effectively unreachable** from the instance (China Mobile egress): HEAD requests answer but LFS transfers stall at ~0 B/s. `HF_ENDPOINT=https://hf-mirror.com` restores full throughput (~37 MB/s measured, 59 GB in ~25 min).
7. **Instance egress can drop entirely** (Errno 101 observed mid-load, killing a launch). All serving is therefore done with `HF_HUB_OFFLINE=1` after the download phase: model load must never touch the network.
8. **Model licenses gate the sprint.** Access is per-family: the account's token opened gemma-4 but not gemma-3/gemma-2 (403 on resolve). Check `resolve/main/config.json` per family before counting on a fallback model.

## Ops

9. The vLLM-dev Navi image ships **without an SSH server**; install openssh-server by hand on every fresh instance.
10. The persistent volume is mounted at `/persistent` (100 GB NFS); the workspace overlay dies with the instance. Results are mirrored to /persistent after every phase.
