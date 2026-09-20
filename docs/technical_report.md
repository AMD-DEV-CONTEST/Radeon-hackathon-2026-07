# AMD ROCm Local Quant Agent — Technical Report

**AMD AI DevMaster Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents**

## 1. Application

This project is a locally deployed investment and quantitative assistant for the domestic securities market. It accepts ordinary questions in natural language and can escalate quantitative requests into an auditable workflow:

```text
Natural language → RAG → multi-agent reasoning → strategy DSL
                 → validation → deterministic backtest → risk report
```

The assistant has a general-conversation fallback, so questions outside the quantitative workflow receive a useful explanation instead of being forced into a malformed strategy object.

## 2. Architecture

```text
User
 │
 ├─ General question ───────────────► Assistant response
 │
 └─ Quantitative request
       │
       ▼
  Intent Router
       │
       ├─ Retrieval Agent: keyword/BM25/RAG + confidence gate
       ├─ Reasoning Agent: local Qwen model + grounded context
       └─ Risk Agent: hard constraints and independent veto
                              │
                              ▼
       DSL canonicalizer → schema/semantic validator
                              │
                              ▼
                 backtest → metrics → risk report
```

The Dify workflow exposes the same capabilities as a visible six-node chain:

```text
User Input → RAG Retrieval → Local LLM → Code Validation
           → Backtest HTTP API → Risk Report
```

## 3. Agent capabilities

| Capability | Implementation | Evidence |
|---|---|---|
| Reasoning | ReAct Thought → Action → Observe loop | `src/agent/core.py` |
| Planning | Model selects the next tool from structured tool descriptions | `src/agent/prompts.py` |
| Tool use | Registered market, knowledge, indicator, validation, backtest, and report tools | `src/agent/tools.py` |
| Memory | Working, episodic, semantic memory and preference extraction | `src/agent/memory.py` |
| Task execution | DSL validation, deterministic backtest, risk report, and paper-report mode | `src/backtest/`, `src/api.py` |
| Safety | Code-level constraints and independent Risk Agent veto | `src/agent/risk_agent.py` |

## 4. AMD Radeon / ROCm implementation

All model training and inference in the submitted evidence chain ran locally on an AMD GPU:

| Component | Configuration |
|---|---|
| GPU | AMD Radeon Graphics, gfx1100 |
| ROCm | 7.2.1 |
| Base model | Qwen2.5-7B |
| Fine-tuning | FP16 LoRA through PEFT/TRL; no CUDA dependency |
| Serving | vLLM, FP16, OpenAI-compatible local endpoint |
| Model endpoint | `http://127.0.0.1:8000/v1` |
| API endpoint | `http://127.0.0.1:8080` |

The final LoRA run used 400 domestic-market samples, 39 steps, and 615 seconds of training. It reached loss 0.2848 and token accuracy 98.1%, with peak GPU memory of 16.21 GB. The merged model is served by vLLM on the same AMD host.

## 5. Grounding and safety

- RAG results carry confidence and source context; low-confidence retrieval does not silently become a trading fact.
- External or public data adapters are separated from deterministic demo data.
- The demo uses deterministic synthetic historical data so evaluators can reproduce the same output.
- The validator enforces domestic-market constraints such as T+1, lot size, no naked short selling, price limits, fees, and risk limits.
- The risk layer can reject model output; the model cannot override hard risk rules.
- No real orders are placed and the system is not investment advice.

## 6. Evaluation

| Evaluation | Result |
|---|---:|
| CN-market cases after canonicalization | 24/24 |
| JSON validity | 100% |
| Instrument and timeframe matching | 100% |
| Constraint compliance | 100% |
| Dify demo workflow | 6 nodes, 3 cases |
| Test suite | 285 passed; 2 documented async integration failures when `pytest-asyncio` is unavailable |

The initial 24-case constraint pass rate was 45.83%. The final result reached 100% through explicit prompt constraints, typed canonicalization, repair logs, and validation—not by hiding failed cases.

## 7. Reproduction

```bash
bash scripts/setup.sh
bash scripts/verify_submission.sh
```

For Dify, follow [`dify/workflows/SETUP_GUIDE.md`](../dify/workflows/SETUP_GUIDE.md). Large model weights are stored outside GitHub; checksums, training configuration, evaluation artifacts, and serving instructions are included in the repository.

## 8. Deliverables

- Source code and tests in this repository.
- AMD ROCm training and inference configuration.
- DSL specification and safe parser/transpiler.
- Dify workflow and OpenAPI tool definition.
- Evaluation artifacts and demo scripts.
- Reproducibility instructions and safety limitations.
