# Dify Workflow Setup — Domestic-market Quant Agent

This guide connects Dify to the local AMD ROCm services. Dify performs orchestration; model inference and quantitative tools remain on the AMD host.

## Services

| Service | Host endpoint | Purpose |
|---|---|---|
| vLLM | `http://127.0.0.1:8000/v1` | Local Qwen2.5-7B model |
| Trading API | `http://127.0.0.1:8080` | RAG, validation, backtest, risk report |
| Gradio | `http://127.0.0.1:7860` | Optional standalone demo UI |

When Dify runs in Docker, use `host.docker.internal` instead of `127.0.0.1`. On Linux, add this mapping to the Dify compose service if required:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## 1. Start the local services

From the repository root:

```bash
python -m uvicorn src.api:app --host 0.0.0.0 --port 8080
python src/chat_app.py
```

Start vLLM with the merged local model and verify it:

```bash
curl http://127.0.0.1:8000/v1/models
```

The expected model id is `models/qwen-trader-merged`.

## 2. Configure the Dify model provider

In Dify, add an OpenAI-compatible provider:

```text
API Base URL: http://host.docker.internal:8000/v1
Model name:   models/qwen-trader-merged
Context:      4096
```

The API key is a local placeholder required by some Dify versions. It is not sent to a cloud model. If credential validation is enabled, use any non-empty local value and confirm that the Dify container can reach port 8000.

## 3. Import the custom tools

Import [`dify/tools/trading_api_openapi.yml`](../tools/trading_api_openapi.yml) as a custom OpenAPI tool. The main operations are:

- knowledge retrieval;
- domestic-market strategy validation;
- deterministic backtest and risk report;
- indicator calculation;
- paper-report generation.

The workflow does not require live credentials and does not place real orders.

## 4. Create the six-node workflow

Create a Chatflow with this sequence:

```text
User Input
    ↓
RAG Knowledge Retrieval
    ↓
Local LLM — strategy JSON/DSL generation
    ↓
Code — canonicalize and validate
    ↓
HTTP Request — /api/cn/backtest/report
    ↓
Answer — metrics, warnings, and PASS/REVIEW decision
```

### LLM system instruction

```text
You are a domestic-market quantitative research assistant running locally on an AMD ROCm GPU.
Answer ordinary questions naturally. For quantitative strategy requests, produce only the
validated domestic-market strategy JSON required by the next code node. Use instruments such
as 510300.SH, 510500.SH, and 159915.SZ when an example is needed. Never invent live prices.
Respect T+1, lot size 100, no naked short selling, price limits, fees, and risk limits.
If the request is outside the workflow, explain the limitation and answer generally instead
of forcing it into a strategy object.
```

### Code node contract

The code node must:

1. parse the model output;
2. canonicalize numeric types and domestic-market defaults;
3. validate the schema and semantic constraints;
4. return `valid`, `strategy`, `repair_log`, and `errors`.

Only continue to the backtest HTTP node when `valid=true`.

### Backtest HTTP node

```text
POST http://host.docker.internal:8080/api/cn/backtest/report
Content-Type: application/json
```

Pass the validated `strategy` object. The response contains return, drawdown, trade count, warnings, and the final risk decision.

## 5. Test prompts

Use a domestic-market prompt such as:

```text
生成沪深300 ETF（510300.SH）日线 EMA20/EMA50 趋势策略，遵守 T+1、100 股整手和禁止做空，输出回测与风险报告。
```

Also test a general question:

```text
什么是最大回撤？
```

The first prompt should traverse the full tool chain. The second should receive a normal assistant answer and should not be rejected as malformed strategy DSL.

## Reproducibility

```bash
bash scripts/verify_e2e.sh
python -m pytest tests/ -v
```

The submitted evaluation uses deterministic synthetic historical data. This makes the demo reproducible and clearly separates a software demonstration from live financial activity.
