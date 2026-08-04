# KinetAios — Track 2 Submission

**Track 2: Development & Local Deployment of Private AI Agents**

**Team / Developer:** phinn  
**Application Name:** KinetAios — Local-First Multi-Engine AI Agent Dashboard  
**GitHub:** https://github.com/phinn/KinetAios  
**License:** GPL v3  

---

## Submission Materials

| # | Document | File |
|---|----------|------|
| 1 | Project Specification Document | [`PROJECT_SPECIFICATION.md`](./PROJECT_SPECIFICATION.md) |
| 2 | Project Source Code | https://github.com/phinn/KinetAios |
| 3 | README (environment config, startup guide, dependencies) | [`README.md`](./README.md) (see main repo) |
| 4 | Demo Video | *(to be recorded — see demo script below)* |
| 5 | Supplementary: PPT | *(to be created)* |

---

## Quick Start

```bash
git clone https://github.com/phinn/KinetAios.git
cd KinetAios
npm install
npm run build
npm start
```

**First launch**: Click ⚙ → fill in API Key (+ Base URL / model) → send a task.

**For local AMD Radeon GPU inference**:
1. Install [Ollama](https://ollama.ai) on the Radeon system
2. `ollama pull qwen2.5:32b`
3. In KinetAios settings: Base URL = `http://localhost:11434/v1`, API Key = (empty), Model = `qwen2.5:32b`

---

## Demo Video Script (3–5 minutes)

1. **(0:00–0:30)** Launch KinetAios, show the dashboard with three engine tabs
2. **(0:30–1:00)** Configure Ollama local endpoint (AMD Radeon GPU via ROCm), show `rocm-smi` with GPU active
3. **(1:00–2:00)** Send a code audit task to DirectV2 engine — show Plan → Execute → Verify → Judge phases, tool steps expanding
4. **(2:00–2:30)** Switch to Direct engine, demonstrate `dispatch_agent` sub-agent
5. **(2:30–3:00)** Show long-term memory extraction (new facts appear in memory panel)
6. **(3:00–3:30)** Demonstrate file write + snapshot rollback
7. **(3:30–4:00)** Show MCP Server feature — remote agent invocation
8. **(4:00–4:30)** Brief comparison: same task on cloud API vs. local Ollama (AMD Radeon)
9. **(4:30–5:00)** Summary: local-first, multi-engine, no account, zero infrastructure
