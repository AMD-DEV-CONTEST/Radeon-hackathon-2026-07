# ETF-Smart Advisor: Intelligent Investment Advisory System Based on AMD ROCm

## Project Background
In today's financial markets, ETFs (Exchange-Traded Funds) have become increasingly popular among investors due to their low costs and high liquidity. However, individual investors face significant challenges:
- Information overload: Inability to effectively process large volumes of financial data
- Analysis barriers: Lack of professional technical analysis skills
- Decision difficulty: Difficulty in making optimal choices among numerous ETF products

## Target Users and Application Scenarios
**Target Users:**
- Individual investors seeking automated investment advice
- Financial advisors needing auxiliary analysis tools
- FinTech companies requiring integrable analysis engines

**Application Scenarios:**
- ETF market screening and recommendation
- Technical analysis and price prediction
- Intelligent Q&A and investment consultation
- Portfolio construction assistance

## System Architecture
┌─────────────────────────────────────────────────────────────┐
│ ETF-Smart Advisor │
├─────────────────────────────────────────────────────────────┤
│ Web Layer (FastAPI + Gradio) │
│ ├── REST API (Port 7860) │
│ ├── Web UI / API Docs │
│ └── Static Files │
├─────────────────────────────────────────────────────────────┤
│ Agent Layer (ETFAdvisorAgent) │
│ ├── Intent Recognition │
│ ├── Multi-turn Memory (MemoryManager) │
│ ├── Task Planning (TaskPlanner) │
│ └── Tool Dispatching │
├─────────────────────────────────────────────────────────────┤
│ Skills Layer │
│ ├── ETFDataSkill - Data Acquisition │
│ ├── ETFAnalyzeSkill - Quick Analysis (Stage 1) │
│ ├── ETFRankingSkill - Fine Ranking (Stage 2) │
│ └── ETFDeepAnalyzeSkill - Deep Analysis (Stage 3) │
├─────────────────────────────────────────────────────────────┤
│ Core Services │
│ ├── LLM Client (vLLM / Transformers) │
│ ├── Milvus Client (Vector Search + Cache) │
│ ├── ETFDataFetcher (Data Acquisition) │
│ ├── InvestmentAdvisor (Recommendation Engine) │
│ └── ETFPricePredictor (Price Prediction) │
├─────────────────────────────────────────────────────────────┤
│ Infrastructure Layer │
│ ├── AMD ROCm 7.2.1 GPU │
│ ├── PyTorch 2.9.1 + ROCm │
│ ├── Milvus Lite (Vector Database) │
│ └── Qwen 1.5B-9B Model │
└─────────────────────────────────────────────────────────────┘

## Models and Algorithms
**1. Large Language Model (LLM)**
- Qwen series models (1.5B-9B)
- vLLM for high-performance inference
- Fallback to Transformers for reliability

**2. Technical Indicators**
- Moving Average System (MA5, MA20, MA60)
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Bollinger Bands

**3. Three-Stage Screening Algorithm**
- Stage 1: Quick Analysis (Score screening → Top 700)
- Stage 2: Fine Ranking (Sort → Top 100)
- Stage 3: Deep Analysis (Final → Top 3)

**4. Vector Search (RAG)**
- Milvus for knowledge vector storage
- Sentence Transformer for Embedding generation
- Knowledge retrieval and augmented generation

## AMD Radeon GPU / ROCm Adaptation
- **Hardware**: AMD Radeon GPU (RX 7900 XTX, etc.)
- **Software Stack**: ROCm 7.2.1
- **Framework**: PyTorch 2.9.1 + ROCm
- **Inference Engine**: vLLM with ROCm support
- **Optimizations**:
  - `PYTORCH_ROCM_ALLOC_CONF: max_split_size_mb:128`
  - `TORCH_ROCM_GRAPH: 1`
  - 4-bit quantization

## Project Structure
ETF-Smart-Advisor/
├── app/
│   ├── __init__.py
│   ├── agent.py              # Main Agent
│   ├── advisor.py            # Investment Advisor Engine
│   ├── advisor_v2.py         # Skill-based Version
│   ├── config.py             # Configuration
│   ├── data_fetcher.py       # Data Acquisition
│   ├── feedback_learning.py  # Feedback Learning
│   ├── llm_client.py         # LLM Client
│   ├── main.py               # FastAPI Entry
│   ├── milvus_client.py      # Milvus Client
│   ├── predictor.py          # Price Prediction
│   ├── utils.py              # Utilities
│   ├── privacy/              # Privacy Protection
│   │   ├── __init__.py
│   │   └── privacy_manager.py
│   └── skills/               # Skill Modules
│       ├── __init__.py
│       ├── base_skill.py
│       ├── base_batch_skill.py
│       └── etf_skills.py
├── data/                     # Data Directory
│   └── history/1D/           # Historical Data (Parquet)
├── models/                   # Model Files
│   └── mapfinben-qwen35-9b/
├── scripts/
│   ├── demo_all_features.py  # Feature Demo
│   ├── start.sh              # Startup Script
│   └── start_milvus.sh       # Milvus Startup
├── requirements.txt          # Dependencies
├── setup_env.sh              # One-click Setup Script
├── README.md                 # Project Documentation
└── .gitignore

## Quick Start
1. Donwload dataset from  https://www.kaggle.com/datasets/samsamsamzz/ahistory and unzip the file to data/ folder which is the same level of app (ensure the dir structuss is: app/data/history/1D/xxxxxxxx.parquet)
2. Run bash ./setup_env.sh
3. Run bash scripts/demo_all_features.py to go through all features and check the result from reports/"demo_report_{timestamp}.html". About 4 hours to finish.
4. Or bash scripts/start.sh to serve on-demand service requests

## Access Service
Web UI: http://localhost:7860
API Docs: http://localhost:7860/docs

## API Usage Examples

- Single ETF Analysis
curl -X POST http://localhost:7860/api/recommend \
  -H "Authorization: Bearer abc-123" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SH510050", "period": "1y"}'
- Get Top Recommendations
curl -X GET http://localhost:7860/api/top-recommendations/v2 \
  -H "Authorization: Bearer abc-123"
- Smart Chat
curl -X POST http://localhost:7860/api/chat \
  -H "Authorization: Bearer abc-123" \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyze 510050 trend", "symbol": "SH510050"}'
- RAG knowledge retrieval
curl -X POST http://localhost:7860/api/rag/search \
  -H "Authorization: Bearer abc-123" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is ETF", "top_k": 3}'