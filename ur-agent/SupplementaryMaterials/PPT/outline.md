# UR-Agent PPT Outline

Suggested final export: `UR-Agent-Hackathon-2026.pdf`.

## Slide 1: Title

**UR-Agent (Uni-Resource Agent)**  
One AI. All Your Worlds.

- Track 2: Development & Local Deployment of Private AI Agents
- qiancy, AMD Developer Program No. 00000657
- GitHub: https://github.com/qiancy/ur-agent
- Production demo: https://rc-e2369faa1fa45132.radeon.firstdg.ai
- License: MIT

## Slide 2: Problem and opportunity

Title: One person has many worlds, and generic assistants struggle to handle them safely

- Personal, family, small organization, and seller data are scattered across different tools.
- Cloud-based generic Agents are difficult to use with private data and strict permission boundaries.
- Traditional management software can record data, but cannot plan and act through natural language.
- AMD Radeon GPU + ROCm makes local private Agents practical.

## Slide 3: Product positioning

Title: Everything is a Resource

- Assets, knowledge, people, finance, products, orders, and tasks are represented as resources.
- User + organization space creates multi-context isolation.
- The same Agent can switch between personal, family, business, and Seller spaces.
- Goal: local, private, customizable, and operational.

## Slide 4: System architecture

Title: Local LLM + Agent orchestration + toolchain + private data

Recommended visual: redraw the Mermaid architecture from the Project Specification Document as a slide diagram.

- Vue 3 / Gradio is the interaction entry.
- FastAPI is the API service.
- LangChain AgentExecutor handles task decomposition and tool calling.
- llama.cpp ROCm runs the local model on AMD Radeon GPU.
- PostgreSQL, pgvector, and ChromaDB store structured data and knowledge.
- `puid` and `ouid` in JWT control identity and space boundaries.

## Slide 5: Core capabilities

Title: All 5 Track 2 capabilities covered

- Local Knowledge Retrieval (RAG): isolated knowledge collections by organization space.
- Tool Calling: resource, knowledge, people, finance, and Seller tools.
- Multi-Step Task Planning: natural language goals become tool sequences.
- Local Multi-Turn Memory: follow-up questions keep conversation context.
- Permission Control & Privacy: local inference, JWT-bound context, and no cross-space data leakage.

## Slide 6: AMD Radeon GPU / ROCm adaptation

Title: Core inference runs locally on AMD Radeon GPU

- Production environment: Ubuntu 24.04.4 + ROCm 7.2.1 + AMD-SMI 26.2.2.
- Server: dual AMD EPYC 9334, 64 cores / 128 threads, 503 GB RAM.
- GPU: AMD Radeon Graphics, 49136 MB VRAM.
- Model: Qwen3-Coder-30B-A3B GGUF Q4_K_M served by llama.cpp ROCm through an OpenAI-compatible API.
- Launch flags: `-ngl -1`, `-c 524288`, `-np 2`, KV cache `q4_0`, `--flash-attn on`, `--cache-prompt`, `--op-offload`.
- CPU/NUMA: `--numa distribute`, `-t 64`, `--threads-batch 64`.
- PostgreSQL + pgvector uses vector indexes to accelerate RAG.

Production configuration data:

- Launch-script hint: about 35 tok/s.
- VRAM hint: about 19 GB model VRAM + 13 GB KV cache.
- First-token latency: to be measured in the demo video.

## Slide 7: Demo workflow

Title: A usable private Agent in 3 minutes

- Show `rocm-smi` and local model server logs.
- Open the UR-Agent frontend or Gradio UI.
- Insert knowledge and run RAG Q&A.
- Execute a compound resource, finance, or Seller task.
- Ask a follow-up question to show multi-turn memory.
- Switch spaces to show permission isolation.
- Show the production demo website: https://rc-e2369faa1fa45132.radeon.firstdg.ai

## Slide 8: Value and next steps

Title: From chatbot to private resource operating system

- For individuals: manage life, learning, assets, and knowledge in one place.
- For families: coordinate family matters with clearer context boundaries.
- For small organizations: build a low-cost private business Agent.
- For sellers: query inventory, orders, and business risks through natural language.
- Next steps: more tools, audit logs, deployment templates, and multimodal input.

## Slide 9: Submission information

- Application name: UR-Agent (Uni-Resource Agent)
- Track: Track 2
- Applicant: qiancy
- AMD Developer Program No.: 00000657
- Source: https://github.com/qiancy/ur-agent
- Production demo: https://rc-e2369faa1fa45132.radeon.firstdg.ai/
- License: MIT
- Demo video: https://www.bilibili.com/video/BV1UUun6YEg5
