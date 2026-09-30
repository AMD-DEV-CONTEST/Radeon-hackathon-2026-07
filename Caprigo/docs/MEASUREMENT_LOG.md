# Caprigo — ROCm + scrap measurement log

## Matched-method delta (2026-08-04)

Prompt: "Write a short paragraph about AMD ROCm GPUs." · 128 tokens · temperature=0 · model loaded.

| Env | Model | tok/s |
|-----|-------|-------|
| Scrap RX580 Vulkan Ollama | qwen2.5-coder:7b | **13.73 wall / 14.34 eval** |
| ROCm gfx1100 vLLM | Qwen2.5-7B-Instruct | **29.21 wall** |
| **Uplift** | | **~2.1×** |

## ROCm instance (destroyed after capture)

- `u-14549-080f238e` · gfx1100 · vLLM ROCm 7.2.1
- 7B load 14.37 GiB · 0.5B smoke 215 tok/s

## Scrap Session (prior)

- Caprigo lean Session ~31287 ms · 17 tools · `artifacts/bench-agent-delta.csv`

## Scrap lived proof (separate)

- 7B Q4 @32k ~19 tok/s — rx580-vulkan-agents
