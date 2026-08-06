# BeaverBeaver Memory Service — Public Contest Package

BeaverBeaver is a private AI memory assistant developed by **Beaver Genius**
for Track 2 of the AMD Radeon Developer Contest. An M5Stack CoreS3 captures
voice and device events; this service validates and stores the evidence,
creates time-aligned memory windows, builds searchable memory capsules, and
serves the user-facing memory workbench.

This directory is the publishable runtime subset of Beaver Memory. It contains
the complete source needed for the demonstrated gateway and web application,
while deliberately excluding credentials, personal memory data, captured
media, downloaded model weights, local databases, evaluation corpora, and
internal development notes.

## Architecture

```text
M5Stack CoreS3
  -> reliable authenticated media upload
  -> Beaver Memory FastAPI gateway
       -> ASR service on AMD Radeon (Qwen3-ASR-1.7B)
       -> LLM endpoint through the Radeon gateway
       -> long-term memory and retrieval through EverOS
  -> web memory workbench
```

The companion device package is published separately as
`beaverbeaver-firmware-public`.

The inference endpoints are configured through environment variables. In the
contest deployment, Nginx exposes the LLM, ASR, and TTS services through one
public gateway. No API key is stored in this repository.

## Included Source

- `backend/glass_gateway/`: FastAPI gateway, media ingestion, memory pipeline,
  external model clients, and EverOS integration.
- `frontend/`: memory workbench pages and static assets.
- `contracts/`: device and external-service request contracts.
- `scripts/`: environment setup, readiness checks, launchers, and systemd
  templates.
- `tools/everos/`: pinned EverOS patches and prompt configuration used by the
  runtime.

The package omits benchmark datasets, raw predictions, historical planning
documents, private recordings, model caches, and experimental replay tools;
none of them is required to run the contest demo.

## Requirements

- Linux x86_64
- Python 3.12
- Git
- [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg` for media conversion paths
- External OpenAI-compatible LLM and multimodal endpoints
- An ASR endpoint compatible with the selected provider adapter
- EverOS v1.2.0 (installed by the provided pinned installer)

Python dependencies are declared in:

- `backend/requirements.txt`: FastAPI gateway and HTTP clients.
- `backend/requirements-presence.txt`: optional local speech-presence stack.

Object, face, and voice perception are external HTTP integrations in this
public contest package; local experimental model workers are not bundled.

## Quick Start

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` and replace every example endpoint and empty credential. At a
minimum, set a strong `DEVICE_TOKEN`, the Radeon inference gateway endpoints,
and the corresponding API keys. Never commit `.env`.

Prepare the Python runtime and EverOS:

```bash
./scripts/setup-gateway-linux.sh
./scripts/install-everos-linux.sh
```

Start EverOS in one terminal:

```bash
./scripts/start-everos.sh
```

Check configured services and start Beaver Memory:

```bash
./scripts/check-services.sh
./scripts/start-gateway.sh
```

Open `http://127.0.0.1:8788/memory`. The service health endpoint is
`http://127.0.0.1:8788/healthz`.

Optional perception services can be disabled in `.env` during a minimal demo:

```dotenv
OBJECT_PERCEPTION_ENABLED=0
IDENTITY_PERCEPTION_ENABLED=0
VOICE_PERCEPTION_ENABLED=0
```

## Device Upload

The firmware authenticates with a device token and uploads evidence to:

```http
POST /api/v1/media/upload
Authorization: Bearer <DEVICE_TOKEN>
Content-Type: application/octet-stream
```

See `contracts/device-protocol.md` for the complete reliable-upload contract.

## Public-package Verification

Run this before publishing:

```bash
./verify_public_package.sh
sha256sum -c SHA256SUMS
```

The check rejects common private keys, API tokens, private LAN addresses,
developer home paths, runtime state, captured media, and local environment
files. It is a guardrail, not a substitute for reviewing the Git diff and the
staged files before pushing.

## Source Snapshot

This package was exported from the current working tree of the private Beaver
Memory repository on 2026-08-05. Its base commit was
`f490fa1a181c8d1b27a1b4580abfbdcf648c60ff`; the export also includes the
tracked, uncommitted reliable-media changes used by the contest demo. It does
not include the private repository's Git history.

## License

See `LICENSE`.
