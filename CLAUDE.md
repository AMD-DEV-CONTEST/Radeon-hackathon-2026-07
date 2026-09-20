# Track 2: Agentic AI — Crypto Trading Agent

## Competition Context

- **Track**: Track 2 — Agentic AI
- **Goal**: Build an AI agent that reasons, plans, uses tools, and executes tasks
- **Key Requirement**: Local inference on AMD Radeon GPU via ROCm
- **Judging**: Functional completeness (60pts) + AMD ROCm optimization (40pts)
- **Timeline**: Submit by August 6, 2026

## Project: Crypto Trading Agent

Fine-tune Qwen2.5-7B on AMD ROCm GPU to act as an experienced crypto trader.
NL → DSL → Backtest → Paper Trade — full-chain autonomous trading agent.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Base model | Qwen2.5-7B-Instruct | Chinese-capable, ROCm-friendly, code generation |
| Fine-tuning | QLoRA 4-bit | Fits in 51GB VRAM, fast training |
| Inference | vLLM (ROCm, merged LoRA) | V1 engine, ~56 t/s, avoids V0 LoRA fallback |
| Agent framework | Dify | Workflow + LLM nodes + custom tools + chat UI |
| Backtest engine | Freqtrade | Crypto-native, CCXT integration, FreqAI/ROCm |
| Strategy DSL | YAML + JSON Schema | LLM-friendly, human-readable, validatable |
| Market | Crypto (Binance) | 24/7, open API, Testnet for paper trading |

## Development Constraints

1. **Same AMD GPU instance as Track 3** — no new instances, share VRAM
2. **All inference on ROCm** — vLLM or fallback to transformers
3. **Dify runs in Docker** — co-located with vLLM on same machine
4. **Freqtrade runs in venv** — shares `/opt/venv/` with Track 3
5. **All submission materials in English**

## Key File Locations

- DSL: `src/dsl/` — schema, validator, transpiler
- Backtest: `src/backtest/` — FastAPI server, Freqtrade runner
- LLM: `src/llm/` — vLLM client, system prompts
- Training: `training/` — data prep, QLoRA scripts, configs
- Dify: `dify/` — workflow definitions, tool specs
- Docker: `docker/` — compose for full stack

## Common Tasks

1. **DSL iteration** — Update schema, validator, transpiler together
2. **Fine-tuning** — Run on ROCm, merge LoRA, serve via vLLM
3. **Dify workflow** — Update node prompts, tool connections
4. **Testing** — DSL validation, transpilation, e2e pipeline
