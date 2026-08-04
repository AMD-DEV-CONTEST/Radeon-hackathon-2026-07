# Third-Party Notices

RadeonStay source code is licensed under the repository's [MIT License](LICENSE).
The entries below identify external software and the model artifact used by the
local competition path. They remain subject to their own licenses. Links identify
upstream projects; no external source code, model weight, or `llama-server`
binary is vendored in this directory.

## Validated Python environment

`requirements.lock` is the complete resolved package-version snapshot captured
on 2026-08-04 with `python -m pip freeze --all` from the clean Python 3.12.3
target validation virtual environment. It excludes the pip bootstrap and editable
RadeonStay entry. It does not include artifact hashes and is not a software bill
of materials. The table below calls out the project's direct runtime and
development dependencies; license names are the upstream projects' declarations.

| Direct component | Resolved version | Upstream | Declared license |
| --- | ---: | --- | --- |
| FastAPI | 0.141.1 | <https://github.com/fastapi/fastapi> | MIT |
| Gradio | 5.50.0 | <https://github.com/gradio-app/gradio> | Apache-2.0 |
| HTTPX | 0.28.1 | <https://github.com/encode/httpx> | BSD-3-Clause |
| Pydantic | 2.12.3 | <https://github.com/pydantic/pydantic> | MIT |
| Uvicorn | 0.52.1 | <https://github.com/encode/uvicorn> | BSD-3-Clause |
| pytest | 8.4.2 | <https://github.com/pytest-dev/pytest> | MIT |
| pytest-cov | 6.3.0 | <https://github.com/pytest-dev/pytest-cov> | MIT |
| Ruff | 0.16.1 | <https://github.com/astral-sh/ruff> | MIT |

Hatchling is a PEP 517 build backend declared by `pyproject.toml`; it is not
present in the captured target virtual-environment freeze and is therefore not
claimed as locked here. The evidence release must preserve the license notices
for every resolved package in `requirements.lock`; the direct table above does
not replace that complete notice inventory.

## Local inference stack

| Component | Upstream / provenance | License | Verified identity |
| --- | --- | --- | --- |
| llama.cpp | <https://github.com/ggml-org/llama.cpp/commit/0b14b87d7c20cb753b94b96854dd7b45306fc696> | MIT | Commit `0b14b87d7c20cb753b94b96854dd7b45306fc696`; `llama-server` SHA256 `926e2297d7144a59182ba9d37de877ec972a0cf8d1b697baa82277b3066c45c6` |
| ROCm / HIP components | <https://github.com/ROCm/ROCm> and installed target packages | Component-specific upstream licenses | ROCm `7.2.1`; HIP `7.2.53211-e1a6bc5663`; detected `AMD Radeon Graphics` / `gfx1100` / `0x744b` / 96 CUs / `51522830336` VRAM bytes |
| Local GGUF model | <https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/tree/a483e9e6cbd595906af30beda3187c2663a1118c> | Apache-2.0 | `Qwen3.6-35B-A3B-UD-Q6_K.gguf`; revision `a483e9e6cbd595906af30beda3187c2663a1118c`; SHA256 `4fe53b148b46f9b88830e2a3055c5b15c3a4d1e3ddc9a1384a108d8b9d59f043` |

The model license above comes from the pinned repository revision, not from a
family name or local alias. Model weights are not committed to this repository;
the judge retrieves the exact revision and filename and verifies the recorded
SHA256 before use.

## Project data

Hotel records, guest identities, evaluation reservations, and policy scenarios in
this repository are synthetic competition data. They contain no real guest,
payment, identity, or health records.
