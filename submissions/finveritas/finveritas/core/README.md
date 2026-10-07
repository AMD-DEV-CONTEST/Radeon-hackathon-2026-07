# FinVeritas — Explainable Financial Analysis Platform

> **Financial truth, quantified.**  
> A Bloomberg Terminal-inspired dashboard that ingests financial statements, verifies their credibility, computes metrics deterministically, and uses a local LLM exclusively to narrate — never to calculate.

---

## Overview

FinVeritas is a multi-agent financial analysis system built as a Streamlit app. It accepts data from three sources — Bloomberg PDFs, listed company tickers (Yahoo Finance), and private company CSV/Excel files — and routes them through a pipeline of five specialized agents that compute ratios, detect risk flags, and generate plain-English explanations. A built-in credibility engine scores the trustworthiness of every data load before analysis begins.

**Core principle:** All financial math is done in Python (pandas / numpy). The LLM never touches raw numbers — it only receives a pre-computed metric dictionary and turns it into a readable narrative.

---

## Pipeline

```
Data Source (Bloomberg PDF / Ticker / CSV)
        │
        ▼
  OCR & Ingestion Layer
  ├── pdfplumber (Bloomberg PDFs)
  ├── yfinance   (Listed tickers)
  └── pandas     (Private CSV / Excel)
        │
        ▼
  Data Credibility Engine          ← scores source authenticity + completeness
        │
        ▼
  ┌─────────────────────────────────────────────────┐
  │              Agent Pipeline                      │
  │                                                  │
  │  Revenue Agent        → YoY growth, CAGR, vol   │
  │  Balance Sheet Agent  → Leverage, risk level     │
  │  Liquidity Agent      → Current ratio, WC trend  │
  │  Sentiment Agent      → News sentiment (NewsAPI) │
  │  Cross-Reference Agent→ Integrated LLM narrative │
  └─────────────────────────────────────────────────┘
        │
        ▼
  Explainable Output (Dashboard + JSON)
```

---

## Key Features

| Feature | Details |
|---------|---------|
| **3 data sources** | Bloomberg PDF, Yahoo Finance ticker, Private Company CSV/Excel |
| **Data credibility scoring** | 0-100 score with PASS/WARN/FAIL checks per field |
| **Smart readiness alert** | Detects missing fields; lets you proceed or supplement before running |
| **Auto-fill missing data** | FMP and Alpha Vantage APIs fill gaps when ticker data is incomplete |
| **5 specialized agents** | Revenue, Balance Sheet, Liquidity, Sentiment, Cross-Reference |
| **LLM-agnostic** | Any OpenAI-compatible endpoint — LM Studio, Ollama, GPT-4, Claude via OpenRouter |
| **Dark / Light mode** | Full theme toggle with amber accent palette |
| **Font scaling** | 0.8× → 1.4× slider scales all UI text uniformly |
| **Basel III context** | Pillar 2 / 3 alignment page for regulatory narrative |
| **CLI mode** | Run the OCR pipeline headlessly without the UI |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Dashboard | Streamlit ≥ 1.34 |
| PDF Extraction | pdfplumber |
| Ticker Data | yfinance |
| Supplemental APIs | Financial Modeling Prep (FMP), Alpha Vantage |
| Data Processing | pandas, numpy |
| LLM Integration | LangChain (`langchain-openai`) |
| Pipeline Graph | streamlit-agraph, graphviz |
| News Sentiment | NewsAPI (free tier) |
| Font | JetBrains Mono, Material Symbols Outlined |

---

## Setup

### 1. Clone the repo and navigate to the app

```sh
git clone https://github.com/rocko131205/PBL-2.git
cd PBL-2/mayankPbl/ocr
```

### 2. Create a virtual environment

```sh
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```sh
pip install -r requirements.txt
```

### 4. Run the dashboard

```sh
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## Data Sources

### Bloomberg PDF
Upload one or both of:
- **Income Statement PDF** — enables the Revenue Agent
- **Balance Sheet PDF** — enables the Balance Sheet and Liquidity Agents

Both together unlock all five agents including the Cross-Reference Agent.

### Listed Ticker (Yahoo Finance)
Enter any Yahoo Finance ticker (e.g. `INFY.NS`, `TCS.NS`, `AAPL`). Financial statements are fetched automatically. If fields are missing, supplemental APIs (FMP / Alpha Vantage) can fill the gaps.

### Private Company CSV / Excel
Upload a file with columns:

| Column | Description |
|--------|-------------|
| `period` | Reporting period, e.g. `2023-FY` or `2022-Q3` |
| `revenue` | Total revenue |
| `total_assets` | Total assets |
| `total_liabilities` | Total liabilities |
| `current_assets` | Current assets |
| `current_liabilities` | Current liabilities |
| `equity` | Shareholders' equity |

A downloadable template is available inside the app.

---

## Sidebar Configuration

All settings are configurable at runtime from the sidebar — no `.env` file needed.

| Setting | Default | Notes |
|---------|---------|-------|
| **LLM Base URL** | `http://127.0.0.1:1234/v1` | LM Studio local endpoint |
| **Model** | `qwen2.5-coder-1.5b-instruct-mlx` | Any OpenAI-compatible model name |
| **API Key** | `local` | Set to real key for cloud LLMs |
| **NewsAPI Key** | *(empty)* | Free key at newsapi.org |
| **FMP Key** | *(empty)* | Free 250 req/day at financialmodelingprep.com |
| **Alpha Vantage Key** | *(empty)* | Free 25 req/day at alphavantage.co |

> Sentiment Agent is gracefully skipped if no NewsAPI key is provided. FMP/AV keys are optional and only used for supplemental gap-filling.

---

## Data Credibility Engine

Every data load is automatically scored 0–100 before analysis runs. The score is a weighted average of individual checks:

| Check | Source Types | What It Tests |
|-------|-------------|---------------|
| Source authenticity | All | Bloomberg PDF > ticker > CSV in trust weighting |
| Account identity | Bloomberg PDF | Company name extracted and verified from the document |
| Period coverage | All | Minimum 4 aligned fiscal periods required |
| Required field presence | All | All core fields (revenue, assets, liabilities, equity) must exist |
| Data consistency | All | No negative assets; periods in chronological order |
| Cross-source agreement | Ticker | FMP and AV values cross-checked against yfinance |

The result is shown as a **HIGH / MEDIUM / LOW** confidence card with an expandable per-check breakdown before you run any agents.

---

## Agent Details

### Revenue Agent
Computes: YoY growth rates, 3-year CAGR, revenue volatility (standard deviation of growth), trend direction.  
LLM receives: metric dictionary only, at `temperature=0`.

### Balance Sheet Agent
Computes: debt-to-equity ratio, leverage ratio, asset growth rate, equity growth rate, risk classification (LOW / MEDIUM / HIGH).  
Validation: no negative balance-sheet values; minimum 4 periods.

### Liquidity Agent
Computes: current ratio, working capital, working capital trend, liquidity risk flag.  
Compliance retry: if the LLM uses forbidden terms (e.g. "cash flow", "margin"), it retries once with a correction prompt.

### Sentiment Agent *(optional)*
Fetches headlines from NewsAPI for the company entity.  
Scoring: keyword-based matching against ~50 positive and ~50 negative financial terms — no ML model involved.  
Gracefully skipped if no API key is provided.

### Cross-Reference Agent
Receives all pre-computed metric dicts from the four agents above.  
Generates a single integrated narrative summary cross-referencing revenue, balance sheet, liquidity, and sentiment signals.

---

## Dashboard Pages

| Page | What's on it |
|------|-------------|
| **Upload Statement** | Data source tabs, credibility score card, smart readiness alert, Run Analysis button |
| **Agent Workflow** | Interactive pipeline diagram; hover nodes to see live agent outputs |
| **Financial Analysis** | Full metrics + LLM narrative per agent, raw JSON audit trail |
| **Basel III Alignment** | Pillar 2/3 regulatory context; maps system outputs to supervisory expectations |

---

## Smart Readiness Alert

Before running analysis, the system checks which fields are populated and which agents can execute. It shows one of two paths:

- **Proceed Anyway** — skips agents with missing required fields, runs the rest
- **Fix Missing Data** — opens a supplement form with auto-fetch (FMP/AV) and manual entry options

Manual supplement is only prompted when automated extraction is incomplete — it never appears when all data is available.

---

## Output JSON Schema

Each processed company produces a structured JSON file in `output/`:

```json
{
  "entity": {
    "entity_id": "Infosys Ltd",
    "source": "bloomberg_pdf",
    "currency": "INR",
    "source_files": ["infosys_is.pdf", "infosys_bs.pdf"]
  },
  "time_series": {
    "revenue":             [{"period": "2022-FY", "value": 121641}, ...],
    "total_assets":        [{"period": "2022-FY", "value": 89400},  ...],
    "total_liabilities":   [...],
    "current_assets":      [...],
    "current_liabilities": [...],
    "equity":              [...]
  }
}
```

Period format is always `YYYY-FY` (annual) or `YYYY-QN` (quarterly). The parser normalises all Bloomberg header variants automatically.

---

## Project Structure

```
ocr/
├── app.py                           # Main Streamlit app (4 pages, ~1050 lines)
├── requirements.txt
├── AGENTS.md                        # Developer reference for the pipeline
│
├── agents/                          # Thin wrappers (Streamlit-facing entry points)
│   ├── revenue_agent.py
│   ├── balance_sheet_agent.py
│   ├── liquidity_agent.py
│   ├── sentiment_agent.py
│   └── cross_reference_agent.py
│
├── src/                             # Core logic
│   ├── extractor.py                 # pdfplumber → PDFContent
│   ├── parser.py                    # PDFContent → ParsedStatement
│   ├── mapper.py                    # Bloomberg label → canonical key
│   ├── builder.py                   # ParsedStatement[] → company JSON
│   ├── main.py                      # CLI entry point
│   ├── revenue_agent.py             # Full agent implementation
│   ├── balance_sheet_agent.py
│   ├── liquidity_agent.py
│   ├── sentiment_agent.py
│   ├── data_verifier.py             # Credibility scoring engine
│   ├── supplemental_fetchers.py     # FMP + Alpha Vantage auto-fill
│   ├── yfinance_ingestion.py        # Ticker-based data fetch
│   └── private_company_ingestion.py # CSV/Excel ingestion
│
├── ocr/
│   └── pdf_parser.py                # Streamlit-facing OCR wrapper
│
├── ui/
│   ├── dashboard_components.py      # render_* functions, theme injection
│   └── styles.css                   # Full CSS design system (dark/light)
│
├── input_pdfs/                      # Drop PDFs here for CLI mode
└── output/                          # Agent JSON outputs written here
```

---

## CLI Mode (No UI)

Run the OCR extraction pipeline without starting the Streamlit server:

```sh
# Default: reads from input_pdfs/, writes to output/
python3 -m src.main

# Custom paths
python3 -m src.main --input path/to/pdfs --output path/to/output

# Verbose logging
python3 -m src.main --verbose
```

---

## Basel III Note

FinVeritas is **not** a regulatory reporting tool. It does not compute capital adequacy ratios, Tier 1/2 capital buffers, LCR, NSFR, or any binding Basel III compliance measures. It is designed for:

- Structured financial statement review and audit trails
- Preliminary credit background checks from public filings
- Risk trend monitoring across reporting periods
- Generation of explainable, auditable financial summaries

---

## Branch Info

| Branch | Purpose |
|--------|---------|
| `main` | Stable production branch |
| `ASSHUL` | Base feature integration |
| `avi` | UI revamp — FinVeritas rebranding, theme system, credibility engine |

---

## License

This project was developed as part of a Problem-Based Learning (PBL) academic project. All financial data shown is sourced from public filings or Yahoo Finance and is used for educational purposes only.
