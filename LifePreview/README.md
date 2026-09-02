# LifePreview

LifePreview is a Track 1 multimodal content creation tool adapted for an AMD Radeon `gfx1100` GPU and ROCm 7.2.1. A user finds a biography or book, reviews source-backed material, generates a short AI script, prepares one FLUX character reference image, and submits a three-second MiniMax H3 video job from the English web interface.

> Submission status: this repository is assembled as a reproducible competition snapshot. The frozen acceptance profile for the deadline is **GPU Runtime Proof**: the live request must reach H3 exactly once and the AMD GPU must begin executing it. The competition cloud server was stopped before this snapshot was finalized, so no additional final live request was issued. Waiting for the final MP4 is not part of the deadline gate. Previously generated videos are presented separately and are never represented as the result of the current job.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## Deployment and validation status

The project has already been deployed in an NVIDIA environment. Because the competition cloud server has limited memory and compute capacity, some demonstration data and media assets have been generated locally in advance. On AMD Radeon/ROCm, the project has completed the minimum end-to-end loop and targeted smoke tests that confirm core service startup, the main request path, and GPU execution. Pre-generated inputs and showcase outputs are identified separately from live AMD execution evidence. This validation scope does not mean that every dataset, media asset, or production feature was regenerated or fully validated on the competition server.

## Submission materials

- [English project profile](docs/LifePreview_Project_Profile_EN.pdf) - a 29-page project profile covering the product background, target users, prototype and demo flow, end-to-end generation pipeline, AMD Radeon/ROCm validation, and current results. The editable source is available as [DOCX](docs/LifePreview_Project_Profile_EN.docx).
- [English project presentation deck](deck/LifePreview_Project_Deck_EN.pdf) - a 10-page PDF deck for Track 1 covering the user problem, product model, current results, core innovation, reusable AI generation pipeline, AMD Radeon/ROCm compute foundation, productization roadmap, and project vision. The PDF export preserves the presentation layout for direct review on GitHub.
- [Current demo video](demo/LifePreview-demo-under-100MB.mp4) - a 4 minute 47 second compressed MP4 (92.1 MB). It is showcase material and is kept separate from evidence of a live AMD run.
- [AMD Radeon / ROCm evidence index](evidence/AMD_ROCm_Evidence.md) - records the reported minimal-loop and smoke-test evidence, its scope, and the final live-run evidence still required for submission.
- [Artifact checksums](evidence/SHA256SUMS.txt) - SHA-256 values for the demo video, profile, and deck files included in this directory.

## License and third-party notices

LifePreview-originated software is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Third-party software, model weights, and media assets remain subject to their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The included source snapshot preserves its allowlist and model-manifest records.

## Competition workflow

1. The English LifePreview UI sends one `POST /api/video-jobs` after the user clicks **Start generation**.
2. Search/Reader resolves the selected book and returns source material.
3. The research worker produces a non-empty AI script and records its digest.
4. The job binds one prepared FLUX character-reference image, including its request ID, prompt, seed, workflow digest, and image digest.
5. The H3 compiler creates a request for 3.0 seconds, 73 frames at 24 fps, native audio, and no subtitles.
6. The submitter sends the H3 request exactly once and records the prompt/queue ID, job ID, attempt, submission nonce, workflow digest, and timestamp.
7. ComfyUI starts the same prompt and `rocm-smi` confirms AMD GPU activity.

## Reproducible source profile

The included source package is assembled from an explicit allowlist instead of copying the development worktree wholesale. See [submission-source-whitelist.txt](submission-source-whitelist.txt) and the [source snapshot record](source/SNAPSHOT.md). The snapshot records its source revision and states that eligible uncommitted source files were included as a working-tree snapshot.

Included runtime units:

- `consumer_web`: English React/Vite user interface.
- `shidu_api`: public API, job projection, prompt-reference stage, H3 submitter, and competition worker.
- `shidu_provider_mcp`: keyless Search/Reader provider boundary.
- `creative_hub`: PostgreSQL records, research/script orchestration, artifact lineage, and H3 compiler.
- `shared_contracts`: immutable cross-component contracts.
- `drama_factory`: FLUX reference generation and MiniMax H3/ComfyUI runtime adapters.
- `atomic_runtime`: capability registration used by the orchestration layer.
- `deploy/amd` and `ops/amd`: AMD Radeon cloud configuration, preflight, startup, status, and GPU gates.

Explicitly excluded:

- model weights, ComfyUI installations, caches, generated images/videos, runtime databases, logs, and local outputs;
- API keys, cookies, SSH keys, real `.env` files, PostgreSQL passwords, signing secrets, and credential material;
- source files and tests outside the explicit allowlist, including private development-worktree metadata;
- internal agent handoff files and all runtime-generated artifacts.

## Target environment

- Linux AMD Radeon cloud instance, `gfx1100` class GPU with approximately 48 GiB VRAM.
- ROCm 7.2.1 and a ROCm-compatible PyTorch/ComfyUI environment.
- Python 3.12 for application services.
- Node.js 22 and npm for the web application.
- PostgreSQL for Creative Hub and job state.
- ComfyUI listening on `127.0.0.1:18188` when the GPU stage is enabled.

The repository does not contain model weights. Pinned filenames, sizes, and SHA-256 values are documented in `source/deploy/amd/model-manifests/`. Obtain every model from its licensed distribution channel and verify it before use.

## Installation

The allowlisted source is included in `LifePreview/source`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e source/atomic_runtime
python -m pip install -e source/shared_contracts
python -m pip install -e source/drama_factory
python -m pip install -e source/creative_hub
python -m pip install -e source/shidu_provider_mcp
python -m pip install -e source/shidu_api

cd source/consumer_web
npm ci
npm run build
```

Copy the public template and provide secrets as restricted files outside the repository:

```bash
cp source/deploy/amd/.env.example /persistent/douyin-amd/config/amd.env
chmod 600 /persistent/douyin-amd/config/amd.env
```

Do not put secret values in Git. The template uses file-based secret references under `/persistent/douyin-amd/secrets`.

## Database and CPU services

Create the two PostgreSQL databases and credentials referenced by `amd.env`, then run:

```bash
cd source/creative_hub
creative-hub-migrate
creative-orchestration-migrate

cd ../..
bash source/ops/amd/start-radeon-cloud.sh /persistent/douyin-amd/config/amd.env
```

The startup script performs preflight checks, starts Search/Reader, the API, research worker, vertical-slice worker, and web application, and intentionally leaves ComfyUI/GPU stopped until the user action.

Useful checks:

```bash
bash source/ops/amd/status-radeon-cloud.sh /persistent/douyin-amd/config/amd.env
curl -fsS http://127.0.0.1:18082/health/ready
curl -fsS http://127.0.0.1:14289/
```

## GPU Runtime Proof

Before the final user click:

1. Generate one character reference through the production FLUX backend.
2. Persist its request ID, prompt, seed, workflow SHA-256, and image SHA-256.
3. Stop FLUX/ComfyUI and confirm the memory and disk preflight gates.
4. Do not submit H3 in advance.

The user then clicks **Start generation** once. Preserve evidence for the single browser POST, Search/Reader result, script digest, prepared-image digest, H3 DTO, prompt/queue ID, ComfyUI running entry, and `rocm-smi` activity.

```bash
bash source/ops/amd/gpu-go-no-go.sh /persistent/douyin-amd/config/amd.env
rocm-smi
```

## Focused verification

Only the direct competition tests are in the initial startup set:

```bash
python -m pytest \
  source/shared_contracts/tests/test_h3_contracts.py \
  source/drama_factory/tests/test_h3_compilation.py \
  source/creative_hub/tests/test_h3_workflow_compiler.py \
  source/shidu_api/tests/test_competition_prompt_reference.py \
  source/shidu_api/tests/test_competition_runtime_wiring.py \
  source/shidu_api/tests/test_competition_vertical_slice_worker.py -q

cd source/consumer_web
npm test -- --run
npm run test:amd-gateway
```

## Previously generated showcase

The deployed demo may expose a separate **Previously generated on AMD** gallery with two Steve Jobs videos, one Su Dongpo video, and one Frida Kahlo video. These large MP4 files are deployment assets and are not committed to Git. Their checksums belong in the evidence manifest.

## Submission

The official repository is [AMD-DEV-CONTEST/Radeon-hackathon-2026-07](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07). Submit this `LifePreview` directory from a personal fork and open a pull request against the official `main` branch.

PR title:

```text
Track 1, <registered team name or legal name>, LifePreview
```

All official submission materials and the pull request description must be in English.
