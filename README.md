# PrivateLocalAgent

**Track 2: Development & Local Deployment of Private AI Agents**  
**Team:** 说干就干  
**GitHub:** Wyf66669

PrivateLocalAgent is a privacy-first local AI agent for office productivity. It combines:

- Local / private **RAG knowledge base**
- **Tool calling** (KB search, files, notes, facts)
- **Multi-step task planning**
- **Local session memory**
- Dual LLM backends:
  - OpenAI-compatible API (Radeon Cloud Model APIs)
  - Local Transformers inference on **AMD Radeon GPU + ROCm**

---

## 1. Quick Start

```bash
# 1) create venv
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / Radeon Cloud
source .venv/bin/activate

# 2) install deps
pip install -r requirements.txt

# 3) configure API key (for openai_compatible mode)
copy .env.example .env   # Windows
# cp .env.example .env   # Linux
# edit .env and set RADEON_API_KEY

# 4) ingest sample docs
python scripts/ingest_sample.py

# 5a) recommended on Radeon Cloud: Jupyter visual demo (NO tunnel)
#    open notebooks/private_agent_demo.ipynb → Restart → Run the single cell

# 5b) CLI demo (RAG + memory + workflow + multi-agent)
python scripts/demo_cli.py

# 5c) ROCm verify + latency bench (fill AMD_ROCM_OPTIMIZATION.md)
python scripts/verify_rocm.py
python scripts/bench_rocm.py

# 5d) optional Gradio / HTTP (may need tunnel; not required)
python app.py
```

**Primary contest demo:** `notebooks/visual_no_tunnel.ipynb` (one cell → real agent UI + official `rc-tunnel`).  
Bonus map: `docs/SCORING_BONUS.md`  
Skills (generate real projects): `docs/SKILLS.md` · `python scripts/run_skill.py --list`  
Six apps map: `docs/SIX_APPS.md` · `python scripts/demo_six_apps.py`  
**Fallback CLI:** `python scripts/demo_judge.py`.  
Details: `START_HERE.md` · `docs/JUDGE_DEMO.md` · Checklist: `docs/SUBMISSION_CHECKLIST.md` · PR text: `docs/PR_BODY.md`

**Cloud backup (before 2026-07-31 18:00):** `python scripts/backup_to_persistence.py` then `git push`.

**Judge one-shot:** `bash scripts/start_for_judge.sh`（与 Demo 视频 / 网页推荐问题一致）

Get a free Model API key from:
https://developer.amd.com.cn/radeon/modelapis

---

## 2. Project Layout

```text
track2-private-local-agent/
├── app.py
├── configs/default.yaml
├── data/sample_docs/
├── notebooks/
│   └── private_agent_demo.ipynb   # tunnel-free visual chat (primary demo)
├── docs/
│   ├── PROJECT_SPECIFICATION.md
│   ├── ARCHITECTURE.md
│   ├── AMD_ROCM_OPTIMIZATION.md
│   ├── RADEON_CLOUD_RUN.md
│   ├── PR_BODY.md
│   └── DEMO_VIDEO_SCRIPT.md
├── scripts/
│   ├── verify_rocm.py
│   ├── demo_cli.py
│   ├── generate_kb_faqs.py        # optional ~10k related FAQs
│   └── rebuild_kb.py
└── src/
    ├── agent/          # planner + tool-using agent loop
    ├── app/            # Gradio + notebook visual helpers
    ├── llm/            # OpenAI-compatible + local transformers backends
    ├── memory/         # local persistent memory
    └── rag/            # ingest + Chroma vector store
```
---

## 3. Switch to Local ROCm Inference

On Radeon Cloud / Linux with ROCm PyTorch installed:

1. Edit `configs/default.yaml`:

```yaml
llm:
  backend: "local_transformers"
  local_model_id: "Qwen/Qwen2.5-7B-Instruct"
  device: "cuda"
  dtype: "float16"
```

2. Verify GPU:

```bash
python scripts/verify_rocm.py
```

3. Launch:

```bash
python app.py
```

---

## 4. Core Demo Scenarios

1. **Private KB QA**: “请假需要提前几天申请？”
2. **Tool calling**: agent calls `kb_search` then returns grounded answer
3. **Memory**: “记住我喜欢简洁中文回答”
4. **Files**: upload a PDF/MD and ask questions over it
5. **Planning**: multi-step office request with visible plan + trace

---

## 5. Submission Materials

| Requirement | Path |
|-------------|------|
| Project specification | `docs/PROJECT_SPECIFICATION.md` |
| Architecture | `docs/ARCHITECTURE.md` |
| AMD/ROCm optimization notes | `docs/AMD_ROCM_OPTIMIZATION.md` |
| Source code | `src/`, `app.py` |
| Run guide | this README |
| Poster outline | `docs/POSTER_OUTLINE.md` |

Demo video (3–5 min): follow `docs/DEMO_VIDEO_SCRIPT.md`  
(show ROCm check + notebook visual chat + `kb_search` tool trace; Gradio/tunnel optional).

---

## 6. Environment Notes

- Python 3.10+ recommended
- Embedding model downloads on first run (`sentence-transformers/all-MiniLM-L6-v2`)
- Vector DB / uploads / memory resolve under `data/` locally, or under  
  `/workspace/persistence/PrivateLocalAgent/data/` on Radeon Cloud (auto-detected).  
- Seed docs stay in the repo: `data/sample_docs/`  
- See `docs/RADEON_CLOUD_RUN.md` for `PLA_DATA_ROOT` / `HF_HOME`

---

## 7. License / Contest

Built for **2026 AMD AI DevMaster Global Hackathon · Track 2**.  
PR title suggestion:

`Track 2, 说干就干, PrivateLocalAgent`
