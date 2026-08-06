# Radeon Cloud: operational notes (from the official User Guide, fetched 2026-08-05)

> Source: `Radeon-Cloud-User Guide/README.md` in AMD-DEV-CONTEST/Radeon-hackathon-2026-07.
> This is THE hackathon platform: the R&C requires "AMD Radeon GPU of Radeon cloud".
> (AMD Developer Cloud on amd.com is a different service, Instinct-class, not this event.)

## Access flow

1. Login at https://radeon-global.anruicloud.com/ (Login with Email). ⚠️ Credits are granted only AFTER first login, and the email must match the AMD Developer Program registration email (Discord announcement, 2026-07-16).
2. Profile → SSH Public Key box → paste the `.pub` → Save Key.
3. Profile → My Templates → Add Template: Title + Container Image (required) · Storage = **Persistent (PVC)** to survive instance destroys · toggle **SSH Access (advanced)** ON.
4. Launch → when "Your workspace is ready (100%)": Open Notebook (JupyterLab) or copy the **SSH Command / Host : Port** shown in the dialog and in Profile → Active Instance.
5. `ssh <user>@<host> -p <port>`. If sshd is missing in the image: `sudo apt install -y openssh-server && mkdir -p /run/sshd && /usr/sbin/sshd`.
6. ⚠️ **Destroy Instance** (Profile → Active Instance, red button) when done: a running instance keeps consuming credits.

## Model APIs

- **Free shared endpoints (Token Factory, zero credits)**: https://developer.amd.com.cn/radeon/modelapis → Public Free Model APIs → Qwen or DeepSeek. One API key works for all shared models. Base URL: `https://developer.amd.com.cn/radeon/api/v1` (OpenAI-compatible `chat/completions`), models e.g. `Qwen3.6-35B-A3B`, `DeepSeek-V4-Flash`.
- **Dedicated endpoint (your credits)**: Add Template with **Deploy Type = vLLM Model API** ("Radeon only supports vLLM"), Serve Command format `vllm serve <model> --host 0.0.0.0 --port 8000` (keep host/port: the platform routes port 8000). Ready dialog gives Base URL `.../spaces/<id>/8000/v1` + API key.

## rc-tunnel (expose a dashboard publicly)

From a Notebook terminal: `/var/run/secrets/frp-self-service/install` installs `rc-tunnel`; `rc-tunnel expose --port <1024-65535>` returns a public `https://rc-<random>.radeon.firstdg.ai` URL. HTTP/WS on 127.0.0.1 only, one port per Notebook, no auth added by the platform (add our own). Useful for showing the live leaderboard/dashboard in the demo video. `rc-tunnel stop` when done.

## Container images available (dropdown observed 2026-08-05)

- **ROCm vLLM-dev (Navi)** `vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0` ← our template: vLLM 0.16.0 prebuilt for Navi/RDNA, ROCm 7.2.1, PyTorch 2.9, py3.10
- AMD OneClick Base `amd-oneclick-base:rocm7.2.1-py3.12` (bare ROCm)
- Huggingface `huaggingface_for_amd_radeon:20260707` (+ a "workaround streaming" variant)
- comfy-ui (Track 1 image) · GH-proxy-stable · rocm-certification (x2) · Openclaw
- **Unsloth + Llama.cpp** `unsloth_llama.cpp:latest`: llama.cpp is prebuilt somewhere on this platform; useful reference for the llama.cpp-HIP backend lever

## Credits context

Discord (2026-07-20): GPU resources were "fully open and freely available" only until July 23; after that, expect limited credits. Batch benchmarks, destroy instances between sessions.
