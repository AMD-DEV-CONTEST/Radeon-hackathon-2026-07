# BeaverBeaver

> **A Private, Evidence-Grounded Memory Agent**
>
> M5Stack CoreS3 × AMD Radeon
>
> **Team:** Beaver Genius · **Track:** AMD Radeon Hackathon 2026 — Track 2 (Private AI Agent Development & Local Deployment)

BeaverBeaver is a private multimodal memory agent that runs on M5Stack CoreS3
wearable hardware. The device continuously records first-person sound and
images; a private memory service (Beaver Memory) organizes the fragmentary
evidence into searchable, traceable long-term memory; and AMD Radeon inference
provides the listening, reasoning, and speaking loop.

```
M5Stack CoreS3  --reliable upload-->  Beaver Memory (LAN)  --single entry-->  AMD Radeon Inference
   capture / speak                        Gateway + EverOS           /llm/  Qwen3.6-35B-A3B (AMD Radeon API)
   SD queue / ACK                         Memory Web                  /asr/  Qwen3-ASR-1.7B (Radeon Cloud, vLLM)
                                                                       /tts/  VoxCPM-0.5 (Radeon Cloud, BF16)
```

See [project-spec.md](project-spec.md) for the full project specification
(application scenarios, agent architecture, core capabilities, model &
deployment plan, and AMD Radeon inference optimization notes).

---

## Repository Layout

```text
track-2-beaver-genius-beaverbeaver/
├── README.md                     # This file — top-level overview and quick start
├── project-spec.md               # English project specification (Track 2 deliverable #1)
├── firmware/                     # Sanitized M5Stack CoreS3 firmware package
│                                 #   pinned upstream + full patch + build scripts
│                                 #   README: env setup, build, flash, verify
├── memory-server/                # Sanitized Beaver Memory runtime package
│                                 #   FastAPI gateway, EverOS, web workbench, scripts
│                                 #   README: env setup, startup, dependencies
├── radeon-inference/             # AMD Radeon deployment configuration
│   ├── nginx-three-services.conf #   single-entry router for /llm/ /asr/ /tts/
│   └── evidence/                 #   runtime screenshots (amd-smi, ASR, TTS, device, memory)
└── presentation/                 # Supplementary material
    ├── beaverbeaver.pptx          #   10-slide English deck (PPT)
    └── beaver-memory-architecture.svg/png
```

## Source Packages

| Package | Path | Contents |
| --- | --- | --- |
| CoreS3 firmware | [`firmware/`](firmware/README.md) | Reproducible firmware patch on pinned `78/xiaozhi-esp32` `417f52d7` (MIT). Background JPEG/WAV capture, SD durable queue, sequence + SHA-256 metadata, authenticated upload with retry/backoff/ACK, CoreS3 interaction states. |
| Memory service | [`memory-server/`](memory-server/README.md) | Beaver Memory publishable runtime: FastAPI gateway, memory pipeline, external model clients, EverOS integration, memory web workbench, device/external contracts, setup/startup/systemd scripts. |

Each package README contains its own environment configuration, startup guide,
and dependency list, and ships a `verify_public_package.sh` integrity/leak
check.

## Requirements (overall)

- **Device:** M5Stack CoreS3 (ESP32-S3); Linux host with ESP-IDF 5.5.2+ to build.
- **Memory server:** Linux x86_64, Python 3.12, `uv`, `ffmpeg`, EverOS v1.2.0.
- **Inference:** an AMD Radeon GPU with ROCm (self-hosted ASR/TTS), plus an AMD
  Radeon API key for the interactive LLM.

Full step-by-step setup is in [`firmware/README.md`](firmware/README.md) and
[`memory-server/README.md`](memory-server/README.md).

## Quick Start (end-to-end)

1. **LLM — AMD Radeon API.** Confirm `Qwen3.6-35B-A3B` with a minimal request:

   ```bash
   curl https://developer.amd.com.cn/radeon/api/v1/chat/completions \
     -H "Authorization: Bearer ${AMD_API_KEY}" \
     -H "Content-Type: application/json" \
     -d '{"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":"Hello"}]}'
   ```

2. **Self-hosted speech models on Radeon Cloud (ROCm).** Start `Qwen3-ASR-1.7B`
   (vLLM) and `VoxCPM-0.5` (PyTorch, BF16), then the single-entry router:

   ```bash
   nginx -t && nginx            # uses radeon-inference/nginx-three-services.conf
   curl localhost:8080/healthz  # -> {"status":"ok", ...}
   ```

3. **Memory server.** Configure `.env`, install the runtime and EverOS, start
   the gateway and web:

   ```bash
   cp .env.example .env         # fill endpoints + credentials; never commit .env
   ./scripts/setup-gateway-linux.sh
   ./scripts/install-everos-linux.sh
   ./scripts/start-everos.sh
   ./scripts/check-services.sh
   ./scripts/start-gateway.sh
   # open http://127.0.0.1:8788/memory  · health: http://127.0.0.1:8788/healthz
   ```

4. **Firmware.** Reconstruct, build, and flash the CoreS3:

   ```bash
   ./prepare_firmware.sh /tmp/beaverbeaver-xiaozhi
   cd /tmp/beaverbeaver-xiaozhi
   source "$IDF_PATH/export.sh"
   python scripts/release.py m5stack-core-s3
   idf.py -p /dev/ttyACM0 flash monitor
   ```

5. **Use it.** Ask a question on the CoreS3 and play back the answer generated
   by the Radeon chain; open the memory web to inspect the resulting Capsule and
   long-term Episode with its source evidence.

## AMD Radeon Inference Optimization (summary)

- Native ROCm runtime: PyTorch `2.9.1+gitff65f5b` on ROCm/HIP `7.2.53211`, one
  AMD Radeon GPU with 47.98 GiB VRAM, `CUDA field: None`.
- Sparse-MoE interactive LLM: `Qwen3.6-35B-A3B` (~35B total, ~3B active/token).
- BF16 TTS, persistent vLLM ASR, ~35.63 GiB KV-cache pre-allocation, multimodal
  warm-up, single TTS worker, and decoupled async pipelines.
- Only verified runtime evidence is reported; no unbenchmarked speedup
  percentage is claimed. See [project-spec.md](project-spec.md#6-amd-radeon-gpu-inference-optimization).

## Privacy & Security

- Raw media, derived memories, and indexes are isolated per user.
- Device uploads use Bearer tokens; real credentials are never committed.
- The public packages are sanitized (`verify_public_package.sh`) and exclude
  personal data, media, model weights, private history, and LAN addresses.
- **Deployment boundary:** the current demo is a LAN-private memory service +
  AMD Radeon API + Radeon Cloud self-hosted speech models. Migration to a fully
  local ROCm workstation is documented in the spec (Section 5.3).

## Demo Video

A 3–5 minute demo video showing a continuous, uncut real operation from the
physical device through Radeon inference to an evidence-backed answer will be
linked here. The planned shot list is in [project-spec.md](project-spec.md#8-demo-video-plan).

## License

The firmware package is MIT (pinned to the MIT upstream); the memory service
package ships its own `LICENSE`. See each package directory.

---

*Team: Beaver Genius · AMD Radeon Hackathon 2026 — Track 2*
