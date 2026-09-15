# Project Source Code

## Complete source code repository

> The final source code repository target is:
> **https://github.com/qiancy/ur-agent**

This folder is intentionally lightweight. Before final submission, the complete source code should be pushed to the GitHub repository above so reviewers can inspect, build, and run the project.

## Why a pointer, not a mirror?

- The full Uni-Resource Agent repo contains the entire FastAPI backend, Vue 3 SPA, multi-context data fixtures, and AMD ROCm deployment scripts.
- Mirroring into the contest fork would create a large diff against the upstream `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` repo, complicating review.
- The final upstream repository should be **public** and **MIT-licensed** (see `LICENSE` at the repo root).

## README file including environment configuration, startup guide and dependency list

The GitHub source repository README should include the following reproduction path:

```bash
git clone https://github.com/qiancy/ur-agent.git
cd ur-agent

# 1. Python venv + dependencies
bash scripts/setup_env.sh

# 2. Configure secrets (DB password + LLM endpoint) in .env
#    — see .env.example

# 3. Initialize PostgreSQL + demo data
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python scripts/seed_demo_spaces.py   # 4 demo spaces

# 4. Start llama.cpp ROCm server (assumes AMD Radeon GPU + ROCm installed)
#    See scripts/llama-rocm-server.sh in the repo

# 5. Start the backend
PYTHONPATH=. python -m uvicorn src.app:app --host 0.0.0.0 --port 8000

# 6. Start the Vue SPA (product surface)
cd web && npm install && npm run dev

# 7. Run TDD test suite (proves all 5 capabilities work end-to-end)
python3 -m pytest agents/tdd -q
cd web && npm test && npm run build
```

## Repository map

| Path | Purpose |
| :--- | :--- |
| `src/app.py` | FastAPI entry; mounts 11 routers |
| `src/agents/agent.py` | LangChain agent (`create_openai_tools_agent`) |
| `src/tools/*.py` | 9 tool functions: resource, finance, human, knowledge, seller |
| `src/routers/chat.py` | `POST /chat` — natural-language → tool sequence |
| `src/routers/seller.py` | Seller workbench API (ecommerce orgs only) |
| `src/routers/spaces.py` | Multi-Context Space observation API (overview/resources/persons/transactions/timeline) |
| `src/db/database.py` | PostgreSQL CRUD, context isolation |
| `src/db/chroma_client.py` | ChromaDB per-org collections for RAG |
| `web/` | Vue 3 + Vite + TS product surface |
| `data/campaigns/*.json` | Three demo spaces: Fire at Xinye / Family Learning / Deep Space Fleet |
| `scripts/seed_demo_spaces.py` | Idempotent demo data + `zhansan` user with 4 memberships |
| `agents/tdd/test_*.py` | TDD black-box test suite (HTTP API only) |
| `docs/API.md` | Full REST API reference |
| `docs/ARCHITECTURE.md` | Architecture deep-dive |

## License

MIT — see `LICENSE` at the upstream repo root.
