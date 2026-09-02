[English](README.md) | [中文](README_CN.md)

# AetherDB V1.31.2

AetherDB is a local-first worldbuilding and long-form writing system for professional novelists, serialized fiction teams, game narrative designers, and IP development teams. It combines a Vue 3 + Tauri 2 desktop workspace, a FastAPI control plane, structured SQLite storage, hybrid retrieval, multimodal asset workflows, and reviewable AI assistance.

This repository is the source submission for Track 1, Development of Multimodal Content Creation Tools, in the AMD Radeon Hackathon 2026-07.

## Core Capabilities

- Writing workspace with autosave, document navigation, entity extraction, conflict checks, and AI-assisted analysis.
- Structured management of characters, locations, factions, events, items, concepts, rules, timelines, relations, and tags.
- Multi-database and multi-book organization with migration-managed SQLite storage.
- Hybrid retrieval through FTS5 keyword search, sqlite-vec, and BGE-M3 multilingual embeddings.
- Multimodal image/text retrieval with BGE-VL, optional image generation, and managed media assets.
- Chapter narration and voice preview through the Kokoro 82M multilingual TTS baseline.
- Model package manifests, SHA-256 verification, isolated workers, resource leases, and explicit backend selection.
- Header-only `X-API-Key` authentication, capability gates, local owner tokens, and private runtime data.

## Architecture

```text
Vue 3 / Tauri 2 desktop UI
            |
            | dynamic loopback HTTP + X-API-Key
            v
FastAPI control plane (approximately 279 /api/* method/path entries)
       |                 |                    |
       v                 v                    v
SQLite + Alembic   Runtime scheduler    Model package registry
FTS5 + sqlite-vec  Resource leases      Manifest + SHA-256 checks
       |                 |                    |
       +-----------------+--------------------+
                         v
                  Isolated model workers
              BGE-M3 / BGE-VL / Kokoro TTS
                   Kandinsky optional
```

The frontend owns authoring interactions and status display. The backend owns authentication, persistence, consistency, model admission, scheduling, and security boundaries. Frontend state never replaces backend authorization.

## Models and Algorithms

| Package | Primary use | Supported backends |
| --- | --- | --- |
| AetherDB BGE-M3 | Multilingual embeddings, semantic search, RAG context | ROCm/MIGraphX, CUDA, CPU |
| AetherDB BGE-VL Base | Image/text retrieval for character art, maps, and references | ROCm PyTorch, CUDA, CPU |
| AetherDB Kokoro 82M | Chapter narration, voice preview, pronunciation checks | ROCm PyTorch, CUDA, CPU |
| AetherDB Kandinsky 2.2 | Optional local image generation | ROCm PyTorch, CUDA |

Model weights are not stored in the source repository. A model enters scheduling only after its package manifest, declared size, license acceptance, required files, and SHA-256 hashes are verified.

## AMD Radeon GPU and ROCm

Competition mode is fail-closed. It requires a visible Linux ROCm device, a functioning PyTorch HIP runtime, a real GPU matrix operation, a compatible model backend, and current worker verification evidence. It sets:

```text
REQUIRE_ROCM=true
ALLOW_SILENT_FALLBACK=false
ALLOW_UNVERIFIED_MODEL=false
```

If the AMD backend or required model evidence is unavailable, the task is blocked instead of being presented as a successful GPU execution. See [Competition Reproduction](deploy/COMPETITION_REPRODUCTION.md) and [ROCm Model Compatibility](deploy/ROCM_MODEL_COMPATIBILITY.md).

## Requirements

### Core backend

- Python 3.10-3.12 (Python 3.10.11 is the primary verified environment)
- Dependencies pinned in `requirements.txt`
- SQLite with FTS5 support

### Desktop development

- Node.js 20.19 or newer
- pnpm 10 or newer
- Stable Rust toolchain
- Tauri 2 platform prerequisites for the target operating system

### AMD competition profile

- Linux `amd64`
- Compatible AMD Radeon GPU and kernel driver
- `/dev/kfd` and `/dev/dri/renderD*`
- Docker Engine with Compose
- ROCm/PyTorch environment pinned by `deploy/docker/Dockerfile.rocm`

## Quick Start

### Backend and browser interface

```bash
python -m venv venv

# Windows
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe scripts\init_runtime.py
venv\Scripts\python.exe main.py

# Linux/macOS
venv/bin/python -m pip install -r requirements.txt
venv/bin/python scripts/init_runtime.py
venv/bin/python main.py
```

Open the dynamic loopback URL printed at startup. Do not assume port 8000.

On Windows, after the virtual environment has been prepared, `start.bat` performs runtime initialization and starts the backend through the supported source startup flow.

### Frontend development

```bash
cd frontend
pnpm install
pnpm run dev
```

For browser development, set `AETHERDB_DEV_API_URL` to the explicit dynamic loopback URL printed by the backend. The Vite configuration rejects non-local API targets.

### Tauri desktop development and build

```bash
cd frontend
pnpm install
pnpm tauri dev

# Build the host-native desktop package and managed backend sidecar
pnpm run tauri:build:host
```

Native packages must be accepted on each target operating system. A successful Windows build is not evidence for macOS or Linux packaging.

## Docker

Docker Core is a local browser/server profile without model weights or private runtime data:

```bash
cp deploy/docker/.env.example deploy/docker/.env
docker compose --env-file deploy/docker/.env \
  -f deploy/docker/docker-compose.yaml up --build -d
```

The AMD competition profile is documented separately and uses an immutable image digest, explicit ROCm device mapping, real GPU verification, and per-model worker evidence.

## Tests

```bash
python -m compileall main.py api app services routes tests
python check_routes_auth.py
python -m pytest

cd frontend
pnpm run test:api
pnpm run build
```

ROCm competition checks require an actual compatible Linux AMD host and cannot be proven by a Windows or CPU-only development machine.

## Runtime and Privacy Boundary

The first runtime initialization creates local-only files and directories such as `config.local.yaml`, `.api_keys.json`, `app_data/`, and `logs/`. These files must never be committed. The repository and release packaging rules also exclude user databases, prompts and content, caches, model weights, private provider credentials, and generated sidecar binaries.

## Repository Layout

```text
api/                 FastAPI route modules
app/                 Configuration, deployment, identity, and data models
services/            Persistence, retrieval, model runtime, media, and AI services
frontend/            Vue 3 + Tauri 2 desktop application
resources/           Model package and installer manifests (no model weights)
deploy/              Core, native service, and ROCm competition deployment files
scripts/             Initialization, verification, packaging, and maintenance tools
tests/               Backend, security, model, multimodal, and release tests
```

## Hackathon Materials

The official submission bundle contains:

- bilingual Project Profile PDF;
- 3-5 minute 1080p demonstration video;
- bilingual one-page poster;
- complete sanitized source tree and dependency declarations;
- English Pull Request description and a final submission checklist.

## License

AetherDB is open-source software licensed under the [GNU Affero General Public License version 3 only](LICENSE) (`AGPL-3.0-only`). Individuals and organizations may use, modify, and redistribute the project under the license terms. Modified versions used to provide network services must comply with the AGPL source-availability requirements.

Copyright (C) 2026 陈sir. Third-party libraries and model packages retain their own upstream licenses, notices, attribution requirements, and acceptance conditions. See [NOTICE](NOTICE).
