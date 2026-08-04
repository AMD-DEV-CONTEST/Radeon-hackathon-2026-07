# aiQuant — Private AI Agent for Quantitative Factor Mining

> **AMD Radeon Hackathon 2026 · Track 2: Private AI Agent Development & Local Deployment**

> 📺 **Demo Video**: [https://www.bilibili.com/video/BV1oFuP6wEmt/](https://www.bilibili.com/video/BV1oFuP6wEmt/)

## Overview

aiQuant is a **fully private, local-first AI Agent** that automates quantitative factor mining through natural language. Users describe their research intent (e.g., "Mine momentum factors for CSI 300, 1 iteration"), and the Agent autonomously generates factor hypotheses, writes implementation code, runs Qlib backtests, and reviews results — all powered by an LLM running locally on AMD Radeon GPU via ROCm.

**Zero data leaves the device.** All LLM inference, factor computation, and backtesting happen on the local machine, making it suitable for privacy-sensitive financial research.

## Key Features

- **Natural Language → Factor Mining**: Users describe what they want in plain language; the Agent parses intent, selects stock universe, and runs the full R&D loop
- **Automated R&D Loop**: Hypothesis Generation → Code Implementation → Qlib Backtest → Performance Review → Iteration
- **SSE Streaming Progress**: Real-time progress display of each research stage via Server-Sent Events
- **Multi-Stock-Pool Support**: CSI 300, CSI 500, SSE 50, or all A-shares
- **Local LLM Inference**: Qwen3-8B runs on AMD Radeon GPU via Lemonade SDK / llama-server with ROCm acceleration (~90 tokens/s)
- **Qlib Integration**: Industry-grade backtesting framework with IC, ICIR, annualized return, and max drawdown metrics
- **RD-Agent Framework**: Microsoft's automated R&D agent for factor hypothesis generation and code synthesis
- **Hash Embedding Fallback**: Runs without external embedding APIs by using deterministic local hash vectors
- **Visual Dashboard**: Streamlit-based UI for backtest charts, IC time series, and layered returns

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Frontend (React SPA)                    │
│  Dark Theme · SSE Streaming · Multi-session · Markdown    │
└────────────────────────┬───────────────────────────────────┘
                         │ HTTP / SSE (Port 8010)
┌────────────────────────▼───────────────────────────────────┐
│               API Gateway (FastAPI + uvicorn)              │
│  Intent Parsing · SSE Streaming · nest_asyncio · CORS    │
└──┬──────────┬───────────┬──────────┬───────────────────────┘
   │          │           │          │
   ▼          ▼           ▼          ▼
┌──────┐ ┌─────────┐ ┌─────────┐ ┌──────────────────┐
│Data  │ │RD-Agent │ │ AI      │ │Streamlit UI      │
│Svc   │ │Engine   │ │ Agent   │ │(Port 19899)      │
│      │ │         │ │(Intent) │ │Backtest Charts   │
└──────┘ └────┬────┘ └─────────┘ └──────────────────┘
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
┌────────┐┌───────┐┌──────────┐
│ Qlib   ││CoSTEER││ LLM Call │
│Backtest││Coder  ││(LiteLLM) │
└────────┘└───────┘└────┬─────┘
                      │
               ┌──────▼──────┐
               │  Local LLM  │
               │  Qwen3-8B   │
               │  (ROCm GPU) │
               │  ~90 tok/s  │
               └─────────────┘
```

## Hardware & Software Requirements

### Hardware
- AMD Radeon GPU (ROCm 5.7+)
- 16GB+ GPU memory (for 8B model with Q4_K_M quantization)
- 32GB+ System RAM
- 50GB+ disk space (for model + market data)

### Software
- Ubuntu 22.04 (Radeon Cloud) or macOS (local dev)
- Python 3.10+
- ROCm 5.7+ with PyTorch ROCm build
- Lemonade SDK (for LLM serving on AMD GPU)
- Docker (optional, for sandboxed backtesting)

## Quick Start

### Option A: Radeon Cloud (Recommended for Competition)

1. **Get Radeon Cloud Instance**
   - Sign up at [AMD Developer Portal](https://developer.amd.com.cn/radeon/)
   - Follow the [Feishu guide](https://my.feishu.cn/wiki/WZjewQhHBi5qvwk0U1Sca8Qenfg) for cloud setup

2. **Clone the Repository**
   ```bash
   git clone https://github.com/CHANGCHENGGAO/Radeon-hackathon-2026-07.git
   cd Radeon-hackathon-2026-07/submissions/track2/aiquant-agent
   ```

3. **Start Local LLM (Qwen3-8B on AMD GPU)**
   ```bash
   # Install Lemonade SDK
   pip install lemonade-sdk

   # Start LLM server on GPU
   lemonade serve \
     /root/.cache/lemonade/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
     --host 0.0.0.0 --port 13305
   ```

4. **Configure Environment**
   ```bash
   cd src
   cp .env.example .env
   # Edit .env:
   #   LLM_API_BASE=http://localhost:13305/v1
   #   LLM_API_KEY=lemonade
   #   LLM_MODEL=/root/.cache/lemonade/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf
   #   OPENAI_API_BASE=http://localhost:13305/v1
   #   OPENAI_API_KEY=lemonade
   #   CHAT_MODEL=/root/.cache/lemonade/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf
   #   CHAT_TOKEN_LIMIT=32768
   #   RUN_MODE=local
   ```

5. **Install Dependencies & Start**
   ```bash
   pip install -r requirements.txt

   # Start API server
   CONDA_DEFAULT_ENV=base uvicorn backend.api.main:app \
     --host 0.0.0.0 --port 8010 --loop asyncio
   ```

6. **Open Browser**
   Visit `http://localhost:8010`

### Option B: AMD Free Model API (Quick Demo)

If local GPU is unavailable, use AMD's free shared API:

1. Get API Key from [AMD Model API Portal](https://developer.amd.com.cn/radeon/modelapis)
2. Configure `.env`:
   ```env
   LLM_API_BASE=https://developer.amd.com.cn/radeon/api/v1
   LLM_API_KEY=your_api_key_here
   LLM_MODEL=DeepSeek-V4-Flash
   OPENAI_API_BASE=https://developer.amd.com.cn/radeon/api/v1
   OPENAI_API_KEY=your_api_key_here
   CHAT_MODEL=DeepSeek-V4-Flash
   CHAT_TOKEN_LIMIT=32768
   RUN_MODE=local
   ```

## Usage

### Natural Language Factor Mining

Type in the chat interface:
```
Mine momentum factors for CSI 300, 1 iteration
```

Or in Chinese:
```
在沪深300挖掘动量因子，迭代1轮
```

The Agent will:
1. Parse your intent (universe=CSI 300, loop_n=1, factor style=momentum)
2. Generate factor hypotheses via LLM
3. Write Python factor code using CoSTEER
4. Run Qlib backtest with historical data
5. Report IC, ICIR, annualized return, max drawdown
6. Stream real-time progress via SSE

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/robot/chat` | POST | Chat interface (non-streaming) |
| `/api/research/factor-evolve/stream` | POST | Factor mining with SSE streaming |
| `/api/research/factor-report` | GET | Get factor backtest report |
| `/docs` | GET | FastAPI auto docs |

### Factor Mining API Example

```bash
curl -X POST http://localhost:8010/api/research/factor-evolve/stream \
  -H "Content-Type: application/json" \
  -d '{
    "loop_n": 1,
    "universe": "沪深300",
    "all_duration": "30m"
  }'
```

## AMD Radeon GPU Optimization

- **ROCm Acceleration**: LLM inference runs on AMD Radeon GPU via ROCm compute platform
- **Q4_K_M Quantization**: 4-bit quantization reduces 8B model from 16GB to 4.7GB VRAM
- **Lemonade SDK**: AMD's native inference server optimized for Radeon GPUs
- **~90 tokens/s**: Measured inference speed on Radeon Cloud GPU
- **Local Inference**: Zero network latency, all computation on-device
- **GPU Monitoring**: Use `rocm-smi` to monitor GPU utilization

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM Inference | Qwen3-8B via Lemonade SDK / llama-server on AMD Radeon GPU (ROCm) |
| AI R&D Framework | Microsoft RD-Agent (Hypothesis → Code → Backtest → Feedback) |
| Backtesting | Qlib (Microsoft AI quantitative platform) |
| Backend API | FastAPI + uvicorn (Python async) |
| Frontend | React SPA with SSE streaming |
| LLM Routing | LiteLLM (OpenAI-compatible API) |
| Task Queue | Celery + Redis (optional, for background tasks) |
| Visualization | Streamlit (RD-Agent UI, backtest charts) |
| Data | A-share market data (Qlib format, 通达信 CSV import) |

## Project Structure

```
aiquant-agent/
├── README.md                  # This file
├── .gitignore                 # Excludes .env, data, caches
├── docs/
│   ├── architecture.html      # Architecture diagram (interactive)
│   └── project_spec.pdf       # Project specification
├── scripts/
│   ├── setup_rocm.sh          # ROCm environment setup
│   ├── start.sh               # Application start script
│   └── demo.sh                # Demo script
├── src/
│   ├── backend/
│   │   ├── api/main.py        # FastAPI gateway (endpoints, SSE, LLM config)
│   │   ├── engine/
│   │   │   ├── rd_agent_adapter.py   # RD-Agent Python API adapter
│   │   │   ├── backtest_engine.py    # Backtest execution
│   │   │   ├── factor_generator.py   # Factor code generation
│   │   │   └── llm_client.py         # LLM API client
│   │   ├── services/ai_agent.py      # Intent parsing (NL → structured)
│   │   ├── data_svc/                 # Data pipeline (通达信 → Qlib)
│   │   ├── worker/                   # Celery worker (background tasks)
│   │   └── shared/config.py          # Configuration management
│   ├── frontend/
│   │   └── chat-app/                 # React frontend (Vite + Tailwind)
│   ├── data/instruments/             # Stock pool definitions (CSI300/500/50)
│   ├── requirements.txt
│   ├── .env.example
│   └── start.sh                      # Full startup script
└── video/
    └── demo_script.md               # Demo video recording guide
```

## Competition Compliance

### Track 2: Private AI Agent Development & Local Deployment

| Requirement | Status |
|-------------|--------|
| Local personal assistant | ✅ Natural language quantitative research assistant |
| Local knowledge base Q&A | ✅ Factor knowledge base with long-term memory |
| Tool Calling | ✅ Qlib backtesting, data pipeline, factor code execution |
| Multi-step task planning | ✅ R&D loop: hypothesis → code → backtest → review |
| Privacy protection | ✅ 100% local LLM inference, zero data egress |
| AMD Radeon GPU utilization | ✅ Qwen3-8B on ROCm, ~90 tokens/s |

## Team

- **Team Member**: CHANGCHENGGAO
- **Track**: Track 2 — Private AI Agent Development & Local Deployment
- **Repository**: [GitHub](https://github.com/CHANGCHENGGAO/Radeon-hackathon-2026-07)

## License

This project uses open-source components:
- [RD-Agent](https://github.com/microsoft/rdagent) (MIT License)
- [Qlib](https://github.com/microsoft/qlib) (MIT License)
- [LiteLLM](https://github.com/BerriAI/litellm) (MIT License)
- [Lemonade SDK](https://github.com/AMD-AIGEK/Lemonade) (MIT License)
