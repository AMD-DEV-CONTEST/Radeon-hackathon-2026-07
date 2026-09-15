# UR-Agent (Uni-Resource Agent) — AMD AI DevMaster Hackathon 2026 Submission

> **Track 2 — Development & Local Deployment of Private AI Agents**
> **Applicant:** qiancy (AMD Developer Program No. 00000657)
> **GitHub:** https://github.com/qiancy/ur-agent
> **Production demo:** https://rc-e2369faa1fa45132.radeon.firstdg.ai
> **Local demo service:** http://127.0.0.1:5173
> **Application name:** UR-Agent (Uni-Resource Agent)
> **Tagline:** *One AI. All Your Worlds.* / *Everything is a Resource.*
> **License:** MIT

---

## 1. Submission Contents

| # | Item | Location in this folder | Source / Notes |
| :--- | :--- | :--- | :--- |
| 1 | **Project Specification Document** | [`ProjectSpecificationDocument/project-specification.md`](./ProjectSpecificationDocument/project-specification.md) | English final draft; Chinese draft at `project-specification_cn.md` |
| 2 | **Project Source Code** | [`ProjectSourceCode/README.md`](./ProjectSourceCode/README.md) | Final source repo target: https://github.com/qiancy/ur-agent |
| 3 | **Demo Video** | [`DemoVideo/video-link.md`](./DemoVideo/video-link.md), [`DemoVideo/storyboard.md`](./DemoVideo/storyboard.md) | Demo link placeholder + Tencent Meeting storyboard |
| 4 | **Supplementary Materials** | [`SupplementaryMaterials/PPT/outline.md`](./SupplementaryMaterials/PPT/outline.md) | PPT outline; final export should be PDF or PPTX |

> Chinese working drafts use the `*_cn.md` suffix. English files without `_cn` are intended for final submission.

---

## 2. Five Required Capabilities Coverage

Track 2 requires at least 2 of 5 capabilities (more = bonus). UR-Agent covers **all 5**:

| # | Capability | Evidence in code |
| :--- | :--- | :--- |
| 1 | **Local Knowledge Retrieval (RAG)** | `src/tools/knowledge_tools.py` → `rag_search` / `store_knowledge`; ChromaDB collection per `ouid` (`org_{ouid}`); BAAI/bge-large-zh-v1.5 embedding |
| 2 | **Tool Calling** | 9 `@tool`-decorated functions in `src/tools/{resource,finance,human,knowledge,seller}_tools.py`; LangChain `create_openai_tools_agent` |
| 3 | **Multi-Step Task Planning** | `AgentExecutor` with `max_iterations=20`, `handle_parsing_errors=True`; auto-decomposes natural language → tool sequence |
| 4 | **Local Multi-Turn Memory** | `POST /chat` keeps session context; LangChain `AgentExecutor.invoke({"input": ...})` chained per turn; `chat_history` field in schema |
| 5 | **Permission Control & Privacy** | JWT (`puid` + `ouid` only); strict context isolation per request; `_enforce_ecommerce_jwt`; zero cloud API in production path (Qwen 30B/80B local via llama.cpp ROCm) |

---

## 3. Quick Navigation

- **Want to run it?** → https://github.com/qiancy/ur-agent README → `scripts/setup_env.sh` → `scripts/unires_agent.sh`
- **Want to try the live demo?** → https://rc-e2369faa1fa45132.radeon.firstdg.ai
- **Want to see the spec?** → [`ProjectSpecificationDocument/project-specification.md`](./ProjectSpecificationDocument/project-specification.md)
- **Want to follow the demo?** → [`DemoVideo/storyboard.md`](./DemoVideo/storyboard.md)
- **Want to flip the slides?** → [`SupplementaryMaterials/PPT/outline.md`](./SupplementaryMaterials/PPT/outline.md)

---

## 4. Why UR-Agent Wins on Track 2

- **Creative scenario** (20 pts): "Everything is a Resource" + Multi-Context Space isolation — one person, many roles, zero data leakage.
- **Core capabilities** (20 pts): All 5 required capabilities shipped, not just 2.
- **Multi-turn UX** (20 pts): Vue 3 SPA workbench (Seller) + chat panel; one-click space switch with re-issued JWT.
- **AMD Radeon GPU inference** (20 pts): Qwen3-Coder-30B-A3B Q4_K_M (18.6 GB, 20–30 tok/s) and Qwen3-Coder-Next 80B Q5_K_M fallback on llama.cpp ROCm.
- **Speed optimization** (20 pts): Quantization tiering, role-bound tool context (no extra DB queries), strict JWT identity cache, batched transactions.

---

## 5. Environment Used for Submission

- AMD Radeon GPU (ROCm) — local inference
- llama.cpp ROCm backend serving OpenAI-compatible `http://127.0.0.1:8080/v1`
- PostgreSQL 16 + pgvector (ChromaDB optional)
- Vue 3 + Vite + TypeScript (product surface) / Gradio (internal debug)
- Python 3.11 / FastAPI / LangChain 0.1

See [`ProjectSpecificationDocument/project-specification.md`](./ProjectSpecificationDocument/project-specification.md) § 5 for the full deployment plan and § 6 for inference optimization details.
