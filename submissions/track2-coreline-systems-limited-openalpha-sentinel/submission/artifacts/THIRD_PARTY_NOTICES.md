# OpenAlpha Sentinel - Third-Party Notices

This file records the principal components used by the submission. Exact transitive versions are pinned in `requirements.lock`. The final team must re-run the license review after any dependency or model change.

## Runtime components

| Component | Purpose | License |
|---|---|---|
| FastAPI | Local HTTP API | MIT |
| Uvicorn | Local ASGI server | BSD-3-Clause |
| Pydantic | Typed schemas and validation | MIT |
| HTTPX | Public source HTTP client | BSD-3-Clause |
| feedparser | RSS/Atom support | BSD-2-Clause |
| PyYAML | Local snapshot metadata | MIT |
| python-dotenv | Local environment configuration | BSD-3-Clause |
| SQLite / FTS5 | Local metadata and retrieval | Public domain |
| ROCm/llama.cpp | Final local Radeon model runtime | Verify the pinned source commit's license before submission |
| Ollama | Development-only local model runtime | Not required by the final Radeon deployment |

## Development and document export

| Component | Purpose | License |
|---|---|---|
| pytest | Offline automated tests | MIT |
| pytest-cov | Test coverage | MIT |
| python-docx | Project report export | MIT |
| python-pptx | Slide and poster export | MIT |

## Model artifacts

| Artifact | Intended use | License/status |
|---|---|---|
| [`Qwen/Qwen3-8B-GGUF`](https://modelscope.cn/models/Qwen/Qwen3-8B-GGUF) / `Qwen3-8B-Q4_K_M.gguf` | Final local generation on Radeon | Apache-2.0, as declared by the official ModelScope model metadata; selected file SHA-256 is `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`; weights are not redistributed in this repository |
| `mistral:latest` in local Ollama | Development smoke test only | Locally cached artifact; not part of the final submitted runtime or benchmark |

No model weights are committed to this repository.

## Collected source material

Public visibility is not treated as an open-source license. The application records each source's reported SPDX identifier or `NOASSERTION`, keeps source links and hashes, and does not vendor collected third-party repositories into the submission. The three files in `fixtures/strategies/` are authored specifically for this project and are redistributable with the submission.

## Final review gate

- Confirm every version in `requirements.lock` matches the final environment.
- Save the license text or authoritative license link for the pinned ROCm/llama.cpp commit.
- Confirm the final GGUF hash still matches the selected file and archive the official ModelScope Apache-2.0 metadata link with the submission record.
- Re-run a dependency license scan and resolve any `UNKNOWN` entry.
- Confirm screenshots, video, fixtures, fonts, and logos may be included under the submission terms.
