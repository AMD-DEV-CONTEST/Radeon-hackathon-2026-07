# aiQuant — Private AI Agent for Quantitative Research

> Built for AMD Radeon Hackathon 2026 · Track 2: Agentic AI

## Overview

aiQuant is a private AI Agent that automates quantitative factor mining using natural language instructions. It runs entirely on AMD Radeon GPU with ROCm acceleration, ensuring data privacy and local inference.

The system leverages an LLM-driven R&D loop to automatically generate factor hypotheses, implement them as code, backtest performance, and review results — all without sending data to external APIs.

## Key Features

- **Natural Language → Factor**: Users describe what they want in plain language, the Agent generates and tests quantitative factors automatically
- **Automated R&D Loop**: Hypothesis → Code → Backtest → Review → Iterate
- **SSE Streaming Progress**: Real-time progress display of each research stage
- **Multi-Agent Collaboration**: Multiple analyst agents cross-review factors
- **Paper Upload + Factor Extraction (RAG)**: Upload research papers (PDF) to extract and test factors
- **100% Local Inference**: LLM runs on AMD Radeon GPU via vLLM, no data leaves the device
- **Long-term Memory**: Factor knowledge base accumulates across sessions

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (SPA)                     │
│  HTML/CSS/JS · Dark Theme · SSE Streaming · Multi-chat│
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────▼──────────────────────────────┐
│               API Gateway (FastAPI)                   │
│  Port 8008 · CORS · nest_asyncio                      │
└──┬──────────┬──────────┬──────────┬─────────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────────────┐
│Data  │ │Engine│ │Re-   │ │RD-Agent UI   │
│Svc   │ │      │ │search│ │(Streamlit)   │
└──────┘ └──────┘ └──────┘ └──────────────┘
                 │
                 ▼
         ┌──────────────┐
         │  Local LLM   │
         │  (vLLM on    │
         │  Radeon GPU) │
         └──────────────┘
```

## Requirements

- AMD Radeon GPU (ROCm 5.7+)
- Python 3.10+
- 16GB+ GPU memory (for 7B model)

## Quick Start

### 1. Setup ROCm Environment

```bash
bash scripts/setup_rocm.sh
```

This script will:
- Verify ROCm installation
- Install Python dependencies
- Install and start vLLM with Qwen2.5-7B-Instruct on Radeon GPU
- Configure environment variables

### 2. Start the Application

```bash
bash scripts/start.sh
```

### 3. Open Browser

Visit `http://localhost:8008`

### 4. Try a Demo Command

Type in the chat interface:
```
Mine momentum factors for CSI 500, 1 iteration
```

## Alternative: AMD Free Model API

If local LLM deployment is not available, you can use AMD's free shared model API:

1. Get API Key from https://developer.amd.com.cn/radeon/modelapis
2. Copy `.env.example` to `.env` and configure:
   ```
   LLM_API_BASE=https://developer.amd.com.cn/radeon/api/v1
   LLM_API_KEY=your_api_key
   LLM_MODEL=DeepSeek-V4-Flash
   ```

## AMD Radeon GPU Optimization

- **vLLM PagedAttention**: Optimized memory management for higher throughput
- **FP16 Inference**: Half-precision for reduced memory and faster inference
- **Local Inference**: No network latency, all computation on-device
- **GPU Utilization**: Monitor with `rocm-smi`

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend API | FastAPI + uvicorn |
| AI Engine | RD-Agent + Qlib |
| LLM Inference | vLLM on AMD Radeon GPU (ROCm) |
| Frontend | HTML/CSS/JS SPA |
| Data | A-share market data (Qlib format) |
| Streaming | SSE (Server-Sent Events) |

## Project Structure

```
aiquant-agent/
├── README.md              # This file
├── .gitignore
├── docs/                  # Documentation
│   ├── project_spec.pdf   # Project specification (to be added)
│   └── architecture.png   # Architecture diagram (to be added)
├── scripts/
│   ├── setup_rocm.sh      # ROCm environment setup
│   ├── start.sh           # Application start script
│   └── demo.sh            # Demo script
├── src/                   # Source code
│   ├── backend/           # FastAPI backend
│   ├── frontend/          # Web UI
│   ├── requirements.txt   # Python dependencies
│   ├── start.sh           # Original start script
│   ├── patch_rd_ui_cn.py  # RD-Agent UI localization
│   └── .env.example       # Environment variable template
├── video/                 # Demo video (to be added)
│   └── demo.mp4
└── assets/                # Screenshots and images
```

## Team

- Team Name: [Your Team Name]
- Member: CHANGCHENGGAO

## License

This project uses open-source components. See individual component licenses for details.
