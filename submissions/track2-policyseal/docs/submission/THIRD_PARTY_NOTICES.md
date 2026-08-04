# PolicySeal Third-Party Notices

Prepared for the AMD AI DevMaster Hackathon 2026 Track 2 submission. This file
summarizes the principal third-party software and model assets used by the
competition build. It is an attribution and review aid, not a substitute for
the complete license texts distributed by each upstream project.

Exact dependency versions are locked in `uv.lock` and `pnpm-lock.yaml`. The
license files inside installed distributions remain authoritative.

## Models

| Component | Use | License | Source |
| --- | --- | --- | --- |
| Qwen/Qwen3-8B | Local semantic classification through vLLM | Apache License 2.0 | https://huggingface.co/Qwen/Qwen3-8B |
| intfloat/multilingual-e5-small | Local policy-evidence embeddings through FastEmbed | MIT | https://huggingface.co/intfloat/multilingual-e5-small |

Qwen3-8B weights are not committed to this repository. The competition runtime
downloads them separately and verifies the critical files against
`ops/radeon/qwen3-8b.sha256`.

## Python Runtime Dependencies

Versions below are the resolved versions in the final local lock environment on
2026-08-02.

| Package | Version | License |
| --- | ---: | --- |
| FastEmbed | 0.8.0 | Apache License 2.0 |
| FastAPI | 0.141.1 | MIT |
| HTTPX | 0.28.1 | BSD 3-Clause |
| Jinja2 | 3.1.6 | BSD 3-Clause |
| LangGraph | 1.2.10 | MIT |
| openpyxl | 3.1.5 | MIT |
| Pydantic | 2.13.4 | MIT |
| pydantic-settings | 2.14.2 | MIT |
| PyMuPDF | 1.28.0 | GNU Affero General Public License 3.0 or Artifex commercial license |
| python-docx | 1.2.0 | MIT |
| python-multipart | 0.0.32 | Apache License 2.0 |
| PyYAML | 6.0.3 | MIT |
| SQLAlchemy | 2.0.51 | MIT |
| Uvicorn | 0.52.0 | BSD 3-Clause |

Development and evaluation dependencies include pytest (MIT), Ruff (MIT), mypy
(MIT), and their locked transitive dependencies.

### PyMuPDF notice

PyMuPDF is dual licensed under AGPL-3.0 or a commercial Artifex license. It is
used for the text-PDF input and preview path. Anyone redistributing or deploying
PolicySeal must independently review and satisfy the applicable PyMuPDF license
terms. This competition notice does not grant a commercial Artifex license.

## Web Runtime Dependencies

| Package family | Resolved version(s) | License |
| --- | --- | --- |
| React / React DOM | 19.2.8 | MIT |
| React Router DOM | 7.18.2 | MIT |
| Radix UI React primitives | 1.x / 2.x locked versions | MIT |
| TanStack React Virtual | 3.14.9 | MIT |
| class-variance-authority | 0.7.1 | Apache License 2.0 |
| clsx | 2.1.1 | MIT |
| Lucide React | 0.468.0 | ISC |
| tailwind-merge | 3.6.0 | MIT |

Development tooling includes TypeScript, Vite, Vitest, Tailwind CSS, Testing
Library, jsdom, and Playwright under the licenses recorded in `pnpm-lock.yaml`
and their installed package license files.

## Radeon Runtime

The official competition image provides ROCm, HIP, PyTorch, Transformers, and
vLLM. They are not vendored in this repository. The measured image versions are
recorded in `PolicySeal_Specification_EN.md` and the raw runtime evidence.

Principal upstream projects:

- ROCm: https://github.com/ROCm/ROCm
- PyTorch: https://github.com/pytorch/pytorch
- vLLM: https://github.com/vllm-project/vllm
- Transformers: https://github.com/huggingface/transformers

Each project contains multiple components and may include more than one license;
the exact image contents and upstream notices govern their use.

## Synthetic Data And Project Assets

The source XLSX, DOCX, PDF, evaluation labels, policy examples, screenshots, and
benchmark inputs in this submission were generated specifically for PolicySeal.
They do not contain real company secrets or real personal data.

The presentation and video may include screen captures of PolicySeal and factual
text derived from this repository's own runtime and benchmark records. No stock
photography is required for the core demonstration.

The English demo narration was generated with StepAudio 2.5 TTS using StepFun's
official `Soft-spoken Gentleman` voice. StepFun is a production aid for the
submission video, not part of the PolicySeal application or its local inference
runtime. Only the approved synthetic English narration script was sent to the
service; no source documents, policies, audit records, credentials, or model
inputs were uploaded.

## Dependency Inventory

The complete dependency inventory can be regenerated from the final lockfiles:

```bash
pnpm licenses list --json --prod
.venv/bin/python -m pip list
```

This notice covers third-party components only and does not itself license the
PolicySeal project source.
