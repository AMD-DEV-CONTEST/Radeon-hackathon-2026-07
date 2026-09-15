# UR-Agent Demo Video Storyboard and Voice-Over Script

## 1. Video goal

- Keep the video between 3 and 5 minutes.
- Show that UR-Agent is a Track 2 private AI Agent deployed locally with AMD Radeon GPU + ROCm.
- Demonstrate at least 3 of the following capabilities: RAG, tool calling, multi-step planning, multi-turn memory, and permission isolation. The recommended target is to show all 5.
- Keep command-line output or runtime logs visible enough to prove that core inference uses the local llama.cpp ROCm service.

## 2. Pre-recording checklist

- [ ] Hide or mask all API keys, SSH private keys, database passwords, and real private data.
- [ ] Increase terminal font size so it is readable in the recording.
- [ ] Prepare `rocm-smi`, the llama.cpp server, the FastAPI backend, and the Vue or Gradio UI.
- [ ] Prepare two demo spaces, such as a personal space and a Seller space.
- [ ] Prepare a short project description that can be inserted into the knowledge base.
- [ ] Prepare performance data: GPU model, model name, quantization level, VRAM usage, and tokens/s.

## 3. Storyboard

| Time | Screen | Action | Voice-over point |
| :--- | :--- | :--- | :--- |
| 00:00-00:20 | Title page or project README | Show application name, track, and applicant | UR-Agent is a local private resource management Agent |
| 00:20-00:50 | Terminal | Run `rocm-smi` and show AMD Radeon GPU status | Core inference runs on AMD Radeon GPU + ROCm |
| 00:50-01:20 | Terminal | Show llama.cpp ROCm server logs | The local model exposes an OpenAI-compatible API |
| 01:20-01:45 | Backend and frontend | Start FastAPI and the Vue/Gradio interface | Agent service, tool layer, and UI all run locally |
| 01:45-02:20 | Chat UI | Insert project knowledge and ask a related question | Demonstrate local RAG |
| 02:20-03:00 | Chat UI | Enter a compound task, such as "find resources, identify risks, and create an action plan" | Demonstrate tool calling and multi-step planning |
| 03:00-03:30 | Chat UI | Follow up with "keep only the three most urgent items" | Demonstrate multi-turn memory |
| 03:30-04:10 | Space switch | Switch to another organization space and query similar data | Demonstrate `puid` + `ouid` permission isolation |
| 04:10-04:40 | Terminal or PPT page | Show performance metrics and GPU usage | Explain quantization, GPU offload, and context trimming |
| 04:40-05:00 | Summary page | Show source link, demo website, and MIT license | Emphasize private local deployment, customization, and reproducibility |

## 4. Recommended demo prompts

RAG demo:

```text
Store this project description in the current space knowledge base, then summarize the core value of UR-Agent in three sentences.
```

Tool calling demo:

```text
Check the resources, finance records, and knowledge entries in the current space. Identify the three highest-priority risks and produce an action checklist.
```

Multi-turn memory demo:

```text
Compress the action checklist above into three tasks that can be completed this afternoon.
```

Space isolation demo:

```text
After switching to the Seller space, check inventory and orders, and explain why it cannot see the personal-space materials from the previous step.
```

## 5. Full voice-over script

非常有幸能够参加 AMD 举办的黑客松大赛，衷心感谢主办方为我们提供的宝贵算力资源。在备赛过程中，我深入学习了本地 AI 部署的诸多技术，收获颇丰。通过 llama.cpp 成功实现大模型的本地化运行，并以此为基础构建了 UR‑Agent 这一完全本地化的 AI 应用项目——这对我而言是一次系统性的学习与实战锻炼。

Hello, I am Qian Chenyu, AMD Developer Program member. This project is UR‑Agent, short for Uni‑Resource Agent. It is submitted to the 2026 AMD AI DevMaster Hackathon Track 2: Development and Local Deployment of Private AI Agents.

Let me start with the performance tuning we did to make local deployment efficient and cost‑effective.

Our server is equipped with a dual‑socket AMD EPYC 9334 32‑Core processor, giving us 128 threads in total, along with 503 GB of system memory. The GPU is an AMD Radeon with 48 GB of VRAM, running ROCm version 7.2.1. The entire environment runs inside a Kubernetes Pod with persistent storage mounted at /workspace.

For the core language model, we chose Qwen3‑7B, one of the best open‑source bilingual models. We quantized it to GGUF Q4_K_M format and served it through the llama.cpp ROCm backend, exposing a local OpenAI‑compatible API. This gives us a good balance between quality and resource usage.

Then we performed several key optimizations. Originally, the model used a 524K context window, which consumed 34.9 GB of VRAM. We reduced it to 16K tokens — sufficient for most agent tasks — and increased concurrent processing slots from 2 to 4. We also set CPU threads to 128 for batch processing. As a result, VRAM usage dropped to 19.5 GB, a 44% reduction. Single‑LLM inference improved from about 1.0 second to 0.75–0.88 seconds, roughly 20% faster. The full end‑to‑end agent latency now ranges between 1.8 and 2.0 seconds.

These optimizations also include context trimming, FAISS vector indexes for fast retrieval, and controlled tool result fields to minimize VRAM spikes. All these make UR‑Agent not only private but also responsive on real‑world hardware.

Beyond the agent itself, I want to highlight our development methodology. During this project, we adopted an AI‑powered collaborative workflow. Instead of working alone, I set up a small team of AI assistants — each playing a different role: one acts as a solution architect, one as a backend developer, and one as a QA engineer. They discuss implementation plans, review code, and even suggest improvements through multi‑turn conversations. This is not just a gimmick — it significantly accelerated iteration cycles and helped catch design flaws early.

For quality assurance, we implemented AI‑driven testing using Playwright. We first asked the AI to generate test scripts based on user stories and API specifications. These scripts cover critical paths — such as knowledge insertion, RAG query, and tool calling sequences — and run automatically in a headless browser. When the UI changes, we use the AI to update the test selectors and assertions, reducing maintenance overhead. Additionally, we applied AI to generate unit test stubs for backend modules, ensuring each tool function behaves as expected. This combination of AI‑assisted development and automated testing makes UR‑Agent not only functionally complete but also robust and maintainable.

Now let me introduce the project itself.

The core idea of UR‑Agent is “Everything is a Resource”. It represents assets, knowledge, people, financial transactions, products, and tasks from personal, family, small organization, and business scenarios as unified resources. The Agent can retrieve, analyze, and operate on those resources entirely in a local environment.

I will demonstrate four key capabilities.

First, the local knowledge base. I insert a piece of project information into the current workspace and ask the Agent about its core value. The Agent embeds my query using a local BGE embedding model, retrieves relevant chunks via FAISS from the current organization space, and then uses the local Qwen3 model to generate a grounded answer. This is fully private RAG.

Second, tool calling and multi‑step planning. I give a compound task: “Inspect all resources, finance records, and knowledge entries, identify risks, and create an action checklist.” Under the hood, we use LangGraph, a stateful graph‑based agent framework, to orchestrate the steps. The LLM selects tools like query_finance and search_knowledge, reads structured data, combines retrieval results, and produces actionable recommendations. LangGraph manages conditional routing and error retries automatically.

Third, multi‑turn memory. I follow up with: “Now compress the previous checklist into three tasks that can be completed this afternoon.” Because LangGraph persists the full session state — including tool outputs and intermediate variables — the Agent understands the context and summarizes intelligently, rather than treating each question in isolation.

Fourth, space‑aware isolation. I switch to another workspace, such as the Seller space. UR‑Agent uses puid (Person ID) and ouid (Organization ID) embedded in JWT tokens to bind every request. These IDs are passed into LangGraph’s configurable field, so every tool call, database query, and vector search is strictly filtered by the current space. Data never leaks across personal, family, business, or Seller contexts — a critical privacy boundary for a private Agent.

The production demo website is temporary. The source code is licensed under MIT and will be submitted at https://github.com/qiancy/ur-agent. Thank you.
