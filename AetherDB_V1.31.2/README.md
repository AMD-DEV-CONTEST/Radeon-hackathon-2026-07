[English](README.md) | [中文](README_CN.md)

# AetherDB V1.31.2 - AMD Radeon Hackathon 2026-07

**Track 1: Development of Multimodal Content Creation Tools**

AetherDB is a local-first desktop system for worldbuilding and long-form writing. It combines structured lore management, semantic and full-text retrieval, multimodal assets, chapter narration, and reviewable AI workflows for professional novelists, serialized fiction teams, game narrative designers, and IP development teams.

## Developer and Credits

- **Solo developer:** 陈sir
- **Demo video production assistance:** 奶糖 (contracted and compensated; not a project developer or team member)

## Submission Materials

| Material | File |
| --- | --- |
| Project Profile Document | [AetherDB_V1.31.2_Project_Profile_Bilingual.pdf](AetherDB_V1.31.2_Project_Profile_Bilingual.pdf) |
| Demo Video | [AetherDB_V1.31.2_Demo_1080p.mp4](AetherDB_V1.31.2_Demo_1080p.mp4) |
| Supplementary Poster | [AetherDB_V1.31.2_Poster_Bilingual.pdf](AetherDB_V1.31.2_Poster_Bilingual.pdf) |
| Complete Source Code | [source/](source/) |
| Environment and Startup Guide | [source/README.md](source/README.md) |
| AMD ROCm Reproduction | [source/deploy/COMPETITION_REPRODUCTION.md](source/deploy/COMPETITION_REPRODUCTION.md) |
| Model Compatibility | [source/deploy/ROCM_MODEL_COMPATIBILITY.md](source/deploy/ROCM_MODEL_COMPATIBILITY.md) |

The demo video is 4 minutes 20.854 seconds, 1920x1080, and approximately 88.86 MiB.

## Technical Summary

- Vue 3 + Tauri 2 desktop authoring application.
- FastAPI backend with approximately 279 `/api/*` method/path entries.
- SQLite + Alembic + FTS5 + sqlite-vec local data and retrieval layer.
- BGE-M3 multilingual embeddings and hybrid RAG retrieval.
- BGE-VL image/text retrieval and managed multimodal assets.
- Kokoro 82M multilingual chapter narration and voice preview.
- Optional Kandinsky 2.2 image generation path.
- Verified model packages, isolated workers, resource scheduling, and explicit ROCm/CUDA/CPU backends.
- Header-only API key authentication, capability gates, and private generated runtime credentials.

## AMD Radeon / ROCm

Competition mode requires real ROCm platform and model execution evidence. It validates the device nodes, PyTorch HIP runtime, a real GPU operation, package integrity, compatible model backends, and current worker evidence. Silent CPU fallback and unverified models are blocked when ROCm is required.

## Source Boundary

The source tree intentionally excludes model weights, API keys, local configuration, user databases, logs, caches, generated binaries, internal agent records, and private test evidence. Model manifests, dependency declarations, verification code, Docker files, Tauri source, and tests are included.

## Pull Request

Use [PR_DESCRIPTION.md](PR_DESCRIPTION.md) as the English Pull Request body and complete [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md). The required title is `Track 1, 陈sir, AetherDB`.

## License

AetherDB is licensed under GNU Affero General Public License version 3 only (`AGPL-3.0-only`). See [source/LICENSE](source/LICENSE) and [source/NOTICE](source/NOTICE).
