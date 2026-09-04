# Models, Versions, and Licenses

Reviewed: 2026-08-03
This is an engineering compliance inventory, not legal advice. The distributor
must evaluate license obligations against the actual distribution, changes, and
applicable law.

| Model | Local identity/version | Official source | License | Project use | Commercial-use assessment |
|---|---|---|---|---|---|
| Qwen/Qwen3-VL-8B-Instruct | Radeon-tested fingerprint `cec420e03b2df4db1f120faed9a7a2c302c2d5ecb65ccab2085c2c5e561be6dc` | https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct | Apache License 2.0 | Multimodal evidence understanding, structured facts, Agent inference | Permitted, including commercial use, subject to Apache-2.0 notice, modification, trademark, and patent terms |
| BAAI/bge-m3 | Local weight SHA256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38` | https://huggingface.co/BAAI/bge-m3 | MIT | Local legal-corpus embeddings | Permitted, including commercial use, with copyright and license notice retained |
| BAAI/bge-reranker-v2-m3 | Local weight SHA256 `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` | https://huggingface.co/BAAI/bge-reranker-v2-m3 | Apache License 2.0 | Local legal retrieval reranking | Permitted, including commercial use, subject to Apache-2.0 terms |

## Runtime and Fallback Paths

- vLLM is an inference engine, not a model. The project uses its local
  OpenAI-compatible endpoint in a ROCm environment. A redistributable package
  must retain vLLM and third-party license/NOTICE material.
- Qwen2.5-VL-7B-Instruct was a compatibility fallback only. Qwen3-VL passed the
  compatibility gate, so Qwen2.5-VL is not reported as an inference model used
  by this submission.
- `mock` deterministic adapters are test and Demo code, not trained models and
  are never represented as real model output.

## Reproducibility

The Radeon-tested Qwen3-VL fingerprint identifies the local model used in the
benchmark. Upstream commit revisions were not captured during the early BGE
download, so local weight SHA256 values and
`config/mac-bge-validated-versions.txt` provide the current identity record.
Future downloads should capture both upstream revision and file hashes.

## Project Source License

The project owner selected the **Apache License, Version 2.0**. The full license
text is stored in the repository root as `LICENSE`. Project source distribution
must retain the license and applicable notices and must identify modified files
as required by Apache-2.0.
