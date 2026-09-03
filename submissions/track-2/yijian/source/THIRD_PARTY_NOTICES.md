# Third-party notices

YIJIAN source code and third-party components are kept separate. Model weights and runtime binaries are not committed to this repository.

## Qwen models

- Authors: Qwen Team, Alibaba Cloud
- Qwen3-14B source: <https://huggingface.co/Qwen/Qwen3-14B>
- Qwen3-4B GGUF source: <https://huggingface.co/Qwen/Qwen3-4B-GGUF>
- Qwen3.6-27B source: <https://huggingface.co/Qwen/Qwen3.6-27B>
- 27B GGUF conversion: <https://huggingface.co/ggml-org/Qwen3.6-27B-GGUF>
- License: Apache License 2.0

The competition-safe runtime uses the published Q4_K_M 27B quantization under the alias `Yijian-Qwen3.6-27B-GoCoach`; that 27B model was not Go-LoRA fine-tuned. Qwen3-14B revision `40c069824f4251a91eefaf281ebe4c544efd3e18` is the fixed base for the experimental YIJIAN LoRA v3 training and public base-model reproduction path.

## KataGo

- Source: <https://github.com/lightvector/KataGo>
- Version used for evidence: 1.16.5
- License: MIT License for the engine; network files retain their upstream terms

KataGo provides position analysis. YIJIAN's rules engine independently verifies legal moves, captures, liberties, turn order, and position hashes.

## llama.cpp and vLLM

- llama.cpp: <https://github.com/ggml-org/llama.cpp> (MIT)
- vLLM: <https://github.com/vllm-project/vllm> (Apache-2.0)

llama.cpp serves the stable quantized runtime; the pinned ROCm vLLM environment serves Qwen3-14B and optional LoRA adapters on the Radeon PRO W7900.

## Data boundary

The public repository contains synthetic fixtures, schemas, code, aggregate manifests, and hashes. It excludes creator-authorized training text, raw media, private games, reviewer comments, authorization screenshots, sealed cases, weights, and adapters. Model licenses do not automatically grant rights to game records or training corpora; those sources are reviewed independently.
