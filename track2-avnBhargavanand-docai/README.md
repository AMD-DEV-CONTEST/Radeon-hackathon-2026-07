# Doc.AI — Agentic Medical RAG Assistant

Submission for the **AMD AI DevMaster Hackathon**, Track 2: Development and Local Deployment of Private AI Agents.

Doc.AI is a conversational medical assistant that combines a local curated knowledge base with
live, trusted-source web search, deciding per-question which source(s) to use, then reasons
across multiple turns before generating a downloadable summary report.

## Architecture

- **Backend:** FastAPI (`backend.py`)
- **Frontend:** static HTML/CSS/JS (`index.html`, `script.js`, `style.css`)
- **Local retrieval:** FAISS + `sentence-transformers/all-MiniLM-L6-v2` over 50 curated
  medical condition documents (`medical_data/`)
- **Web search tool:** Tavily API, restricted to a trusted medical-domain allowlist
  (WHO, NIH, CDC, Mayo Clinic, MedlinePlus, PubMed/NCBI)
- **LLM provider:** swappable via an environment variable — Groq (development) or a
  self-hosted vLLM endpoint on AMD Radeon Cloud (deployed submission), no code changes required
  to switch

## Environment Setup

1. Clone this repository and enter the project folder.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your values:
   ```
   PROVIDER=groq
   GROQ_API_KEY=your_groq_key
   TAVILY_API_KEY=your_tavily_key

   # Only needed when PROVIDER=radeon
   RADEON_BASE_URL=
   RADEON_API_KEY=
   ```

## Running Locally (Groq — fast iteration)

```bash
uvicorn backend:app --reload
```

Open `index.html` in a browser. The backend serves at `http://127.0.0.1:8000`.

## Running Against AMD Radeon Deployment

1. On [Radeon Cloud](https://radeon-global.anruicloud.com/), create a template with:
   - **Deploy Type:** vLLM Model API
   - **Container Image:** ROCm vLLM-dev (Navi)
   - **Serve Command:**
     ```
     vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ --host 0.0.0.0 --port 8000
     ```
   - **Port:** 8000
2. Launch the template. Once ready, copy the dedicated Base URL and API Key.
3. In `.env`, set:
   ```
   PROVIDER=radeon
   RADEON_BASE_URL=<your base url>
   RADEON_API_KEY=<your api key>
   ```
4. Restart the backend — startup logs will confirm:
   ```
   LLM provider: radeon | model: Qwen/Qwen2.5-7B-Instruct-AWQ
   ```

## Dependencies

See `requirements.txt`. Key packages: `fastapi`, `uvicorn`, `openai`, `langchain-community`,
`faiss-cpu`, `sentence-transformers`, `tavily-python`, `python-dotenv`.

## Notes

- This is an assistive tool only and does not provide professional medical diagnosis;
  the interface displays this disclaimer at all times.
- Web search is intentionally restricted to a trusted-domain allowlist rather than open
  web search, given the medical use case.

## Demo Video
Watch the complete project demo here:
https://youtu.be/vA64f2AU0GI
