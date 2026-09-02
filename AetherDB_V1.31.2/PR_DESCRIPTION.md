# Track 1, 陈sir, AetherDB

## Project

**AetherDB V1.31.2 - Local-first Multimodal Worldbuilding and Long-form Writing System**

AetherDB is a desktop application for professional novelists, serialized fiction teams, game narrative designers, and IP development teams. It combines a Vue 3 + Tauri 2 writing workspace with a FastAPI control plane, structured SQLite lore storage, hybrid semantic retrieval, multimodal asset workflows, and reviewable AI assistance.

## Track

Track 1 - Development of Multimodal Content Creation Tools

## Developer and Contributions

- **Development:** 陈sir (solo developer)
- **Demo video production assistance:** 奶糖 (contracted and compensated)

The video assistant is acknowledged for production support and is not a project developer or team member.

## Key Capabilities

- Structured management of characters, locations, factions, events, relations, timelines, rules, and tags.
- Long-form writing workflow with AI analysis, entity extraction, consistency checks, and author approval boundaries.
- BGE-M3 multilingual embeddings with FTS5 and sqlite-vec hybrid retrieval.
- BGE-VL image/text retrieval for character art, maps, and reference assets.
- Kokoro 82M chapter narration and voice preview.
- Managed model packages with manifests, license acceptance, SHA-256 verification, isolated workers, and explicit resource scheduling.
- Local-first data, header-only API key authentication, capability gates, and private runtime credentials.

## AMD Radeon GPU / ROCm

The competition profile is fail-closed: it verifies Linux ROCm devices, PyTorch HIP, a real GPU matrix operation, package integrity, compatible AMD backends, and current model-worker evidence. It blocks silent CPU fallback and unverified models when ROCm is required.

## Submission Materials

- Project Profile Document: bilingual Chinese/English PDF
- Demo Video: 4 minutes 20.854 seconds, 1920x1080
- Supplementary Material: bilingual one-page poster
- Source Code: complete sanitized V1.31.2 source tree with dependency declarations and reproduction documentation

## Reproduction

See `source/README.md` for environment setup, startup instructions, dependencies, tests, and project structure. See `source/deploy/COMPETITION_REPRODUCTION.md` for the immutable ROCm container profile and model-level verification process.

## Notes for Reviewers

- Model weights, user databases, logs, local API keys, and private provider credentials are intentionally excluded.
- Model package manifests and verification logic are included.
- The ordinary desktop application supports ROCm, CUDA, and CPU paths. Competition mode independently requires verified ROCm execution and disallows silent fallback.
- The source code is licensed under GNU Affero General Public License v3.0 only (`AGPL-3.0-only`).
