# Third-Party Notices and Model License Boundaries

Copyright 2026 LiuYan.

This file is an attribution and provenance index for third-party material used
or downloaded by FastAgentFactory Hackson. It is not a replacement for any
upstream license, model card, NOTICE file, or service agreement, and it does
not grant rights beyond those instruments. Where a conflict exists, the
applicable upstream terms take precedence.

## Project-owned source

Source authored for FastAgentFactory is licensed under the Apache License,
Version 2.0, in the repository root [`LICENSE`](LICENSE). That license does
not relicense vendored source, model weights, uploaded content, or online
services.

## Vendored native source

| Component | Provenance and modification status | License | Local notice or license |
| --- | --- | --- | --- |
| llama.cpp Official | Pinned upstream baseline at revision `f955e394bf94e01e5e36186d13c985727e5ef5b5` | MIT | `vendor/llama.cpp-official/LICENSE` |
| llama.cpp AMD | Project-modified derivative of the same pinned baseline; upstream code and notices remain identifiable | MIT terms for upstream code; project changes do not relicense it | `vendor/llama.cpp-amd/LICENSE` |
| stable-diffusion.cpp | Pinned upstream source at revision `833369da848e8e2f960fe1896a825e3a08ef9733` | MIT | `vendor/stable-diffusion.cpp/LICENSE` |
| libwebm | Third-party component included by stable-diffusion.cpp | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebm/LICENSE.TXT` |
| libwebp | Third-party component included by stable-diffusion.cpp | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebp/COPYING` |
| darts-clone | Third-party component included by the stable-diffusion.cpp tree | See the bundled notice | `vendor/stable-diffusion.cpp/thirdparty/LICENSE.darts_clone.txt` |

Redistribution of a source or binary bundle must preserve the applicable
copyright, patent, trademark, attribution, license, and NOTICE files. The AMD
implementation is a derivative implementation, not a replacement license for
the upstream llama.cpp project.

## Runtime-downloaded model weights

Model weights are downloaded at deployment time and are not project-owned
source. A model mirror, quantization format, or hosting page is not an
independent license grant.

| Purpose | Model and source | Declared or applicable boundary |
| --- | --- | --- |
| Chat | [SC117/Qwen3.6-35B-A3B APEX GGUF](https://huggingface.co/SC117/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved-APEX-GGUF) | The current model card states Apache-2.0. This is a third-party derived and quantized distribution; verify the base-model lineage, derivative authorization, model-card revision, and notices before redistribution. |
| Embedding | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | The current model card states MIT; preserve provenance and citation information. |
| Image generation | [black-forest-labs/FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) | Subject to the FLUX.1-dev Non-Commercial License; commercial use, redistribution, and derivative-output scenarios require separate review. |
| FLUX GGUF | [city96/FLUX.1-dev-gguf](https://modelscope.cn/models/city96/FLUX.1-dev-gguf) | Quantization and the ModelScope mirror do not replace or broaden the upstream FLUX.1-dev terms. |

Before publishing a bundle or using a model for a new purpose, record the
source URL, revision, SHA-256, base model, derivative or quantization process,
and current license text or model-card reference. The project does not make a
legal determination for a model provider or downstream use case.

## Python, web, and service dependencies

Python and web dependencies are resolved from the repository lock files. A
release containing those dependencies should generate a Software Bill of
Materials and a corresponding license archive from the lock files. Tavily,
SearXNG, market-data providers, and other online services retain their own
terms, rate limits, and authorization requirements.

User-provided files, knowledge bases, prompts, and model credentials are not
third-party project assets. The user remains responsible for confirming the
right to process, transmit, or redistribute them.
