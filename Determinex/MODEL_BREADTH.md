# Model breadth, measured on the Radeon

One task, one oracle, one code path. Only the served model changed.

| Model | Family | p (per attempt) | first verified at | K | outcome |
|---|---|---:|---:|---:|:--|
| `Falcon3-1B-Instruct` | Falcon3 | **0.000** | — | 16 | not solved |
| `SmolLM2-135M-Instruct` | SmolLM2 | **0.000** | — | 16 | not solved |
| `Qwen2.5-Coder-0.5B-Instruct` | Qwen2.5-Coder | **0.000** | — | 16 | not solved |
| `Qwen2.5-1.5B-Instruct` | Qwen2.5 | **0.000** | — | 16 | not solved |
| `Qwen2.5-Coder-3B-Instruct` | Qwen2.5-Coder | **0.062** | 8 | 16 | **solved** |
| `Qwen2.5-0.5B-Instruct` | Qwen2.5 | **0.062** | 4 | 16 | **solved** |
| `Qwen2.5-Coder-1.5B-Instruct` | Qwen2.5-Coder | **0.062** | 14 | 16 | **solved** |
| `SmolLM2-1.7B-Instruct` | SmolLM2 | **0.062** | 16 | 16 | **solved** |
| `Yi-Coder-1.5B-Chat` | Yi-Coder | **0.062** | 13 | 16 | **solved** |
| `Qwen3-1.7B` | Qwen3 | **0.125** | 13 | 16 | **solved** |
| `deepseek-coder-1.3b-instruct` | DeepSeek-Coder | **0.625** | 1 | 16 | **solved** |
| `Qwen2.5-Coder-7B-Instruct` | Qwen2.5-Coder | **1.000** | 1 | 16 | **solved** |

**8 of 12 models reached a verified answer** across 7 model families, on one AMD Radeon Pro W7900 (ROCm 7.2.1, vLLM). Same task, same oracle, same code path — only the served model changed.

The row that matters is the weakest one: `Qwen2.5-Coder-3B-Instruct` succeeds **6.2%** of the time and still arrived, first verifying at sample 8. The weaker the model, the more the result belongs to the system rather than the model — which is the whole claim, and it is why this table is ordered worst-first.

Models that did **not** reach a verified answer are listed above rather than dropped: `Falcon3-1B-Instruct`, `SmolLM2-135M-Instruct`, `Qwen2.5-Coder-0.5B-Instruct`, `Qwen2.5-1.5B-Instruct`. `1 − (1 − 0)^K` is still 0, and a breadth claim that hides its failures is not a breadth claim.

Reproduce with `radeon_breadth.py` against any vLLM endpoint. The oracle executes
each candidate against six worked examples; no model is consulted about whether a
candidate is correct.
