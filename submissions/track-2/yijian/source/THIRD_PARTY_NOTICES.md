# Third-Party Notices

This file describes the boundary between YIJIAN source code and third-party components. Model weights and inference runtimes are not committed to this repository.

## Qwen models

- Author: Qwen Team, Alibaba Cloud
- Sources:
  - <https://huggingface.co/Qwen/Qwen3-4B-GGUF>
  - <https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF>
  - <https://huggingface.co/Qwen/Qwen3.6-27B>
  - <https://huggingface.co/ggml-org/Qwen3.6-27B-GGUF>
- License: Apache License 2.0
- Use: local offline baseline and Radeon-hosted enhanced Go coach.

The current main runtime uses the `ggml-org/Qwen3.6-27B-GGUF` Q4_K_M quantization under the alias `Yijian-Qwen3.6-27B-GoCoach`. The 27B weights were not fine-tuned with a Go LoRA in this submission.

A historical Qwen3-4B classical-Go experiment used public-domain classical texts plus original modern paraphrases and evidence-binding examples. It did not use user game records, the feedback database, modern copyrighted Go books or unverified web Q&A. This historical experiment is not the current main inference path and its weights are not redistributed here.

## llama.cpp

- Author: Georgi Gerganov and contributors
- Source: <https://github.com/ggml-org/llama.cpp>
- License: MIT License
- Use: local and AMD ROCm/HIP inference runtime.

## KataGo

- Author: David Wu and contributors
- Source: <https://github.com/lightvector/KataGo>
- Release used by the demo: v1.16.5
- Use: candidate ranking, win-rate/score evaluation and principal variations.

Model licenses do not automatically cover game records, training corpora or other data. YIJIAN reviews data provenance and redistribution rights separately.
