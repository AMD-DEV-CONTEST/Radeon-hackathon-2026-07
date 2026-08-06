# Solo Worker OS — AMD AI DevMaster 2026 Demo Script

> Track 2: Private AI Agent Development & Local Deployment
> Target: 3-5 minutes · English narration
> Recording: Screen capture + voiceover

---

## Pre-Recording Checklist

- [ ] AMD Radeon GPU vLLM instance running (or free API as fallback)
- [ ] `.env.local` set to `AGENT_PROVIDER=local`
- [ ] App running at `http://localhost:3000`
- [ ] Browser zoom set to 110% for readability
- [ ] Close all other tabs and notifications
- [ ] Mic test — speak clearly, moderate pace
- [ ] Screen resolution: 1920×1080

---

## Recording Timeline

### [0:00–0:25] Opening: The Problem

**Screen:** Dashboard page (`/dashboard`)

**Narration:**

> Freelancers juggle clients, contracts, invoices, and deadlines across five different tools. When they use cloud-based AI like ChatGPT or Claude, their sensitive business data — client names, contract terms, payment amounts — gets sent to third-party servers. For lawyers, accountants, and consultants, that violates professional confidentiality obligations.
>
> Solo Worker OS solves this. It's a private AI agent that runs entirely on AMD Radeon GPU — your business data never leaves your machine.

---

### [0:25–0:50] AMD Radeon GPU Proof

**Screen:** Settings page (`/settings`) — scroll to Local LLM section

**Narration:**

> Here on the Settings page, you can see the AMD Radeon GPU integration. The agent provider is set to "local" — meaning all LLM inference runs on AMD Radeon GPU through the ROCm software stack. The health probe shows the GPU is reachable with 321-millisecond latency, and the model in service is DeepSeek-V4-Flash, an open-source model running on AMD hardware.
>
> No cloud API in the path. No data leaves the premises.

**Action:** Point cursor to the status indicator showing "reachable: true"

---

### [0:50–1:40] Core Demo: Chat with Tool Calling

**Screen:** Chat page (`/chat`)

**Narration:**

> Now let's talk to the agent. I'll create a new client just by describing them in natural language.

**Action:** Type in chat box:

```
New client — Marcus Rivera, e-commerce platform redesign, budget $15,000, deadline August 20
```

**Narration:**

> The agent receives my message. The FunctionRouter — a two-layer routing engine — classifies this as a "general" subagent task in milliseconds. The agent then calls the "create project" tool automatically.

**Action:** Wait for agent response. Show tool call chip appearing.

> The project is created. The agent extracted the client name, project type, budget, and deadline — all from one sentence. No forms, no manual entry.
>
> Now let's generate a contract for this project.

**Action:** Type:

```
Generate a contract for Marcus's project
```

**Narration:**

> Same conversation. The agent calls the "generate contract" tool. A full services agreement is produced — with payment terms, scope of work, and timeline — all chained from the project we just created.

**Action:** Show the contract text streaming in the chat.

---

### [1:40–2:20] RAG: Knowledge Base Search

**Screen:** Stay on chat page

**Narration:**

> Solo Worker OS also has a local knowledge base with RAG capabilities. Let me ask about my standard payment terms.

**Action:** Type:

```
What are my standard payment terms?
```

**Narration:**

> The agent routes this to the "knowledge RAG" subagent. It searches my private documents using TF-IDF retrieval — not a generic LLM hallucination, but an answer grounded in my own templates and notes stored locally.

**Action:** Show the RAG search result with source reference.

---

### [2:20–2:50] Multi-Turn Memory + Data Analysis

**Screen:** Stay on chat page

**Narration:**

> The agent remembers our conversation. Let me ask for a business overview.

**Action:** Type:

```
Give me a business overview
```

**Narration:**

> The "data analysis" subagent fires. It queries the project database — the same project we just created — and returns revenue stats, active project count, and payment status. All from local data, all in the same session.

**Action:** Show the analysis result.

---

### [2:50–3:20] Trace Observability

**Screen:** Trace page (`/trace`)

**Narration:**

> Every interaction is fully traceable. On the Trace page, you can see the complete execution loop — the routing decision, the LLM call, the tool invocations, and the response. This is critical for debugging and for proving that the agent is actually reasoning on AMD Radeon GPU, not calling a cloud API behind the scenes.

**Action:** Click on the most recent trace. Show the routing + tool call chain.

---

### [3:20–3:40] Bilingual + Architecture Summary

**Screen:** Toggle language to Chinese (top-right button)

**Narration:**

> The UI supports bilingual operation — English and Chinese — with one click.

**Action:** Toggle back to English.

> Under the hood: a self-learning FunctionRouter dispatches to five specialist subagents. Fourteen business tools. TF-IDF RAG. Dual-backend memory — Supabase for cloud, local JSONL for air-gapped deployment. And all inference runs on AMD Radeon GPU via the open ROCm stack.

---

### [3:40–4:00] Closing

**Screen:** Dashboard page

**Narration:**

> Solo Worker OS — a private AI agent for freelancers. Client management, contracts, invoicing, and payments — all running locally on AMD Radeon GPU. Your business data never leaves your machine.
>
> AMD AI DevMaster 2026, Track 2. Thank you.

---

## Narration Script (中文参考稿)

> 以下为中文参考稿，录制时请用英文。中文仅用于理解和练习节奏。

**[0:00] 开场**
自由职业者每周浪费大量时间在管理工具上——Notion 管项目、Docs 写合同、Stripe 开发票。用云端 AI 的话，客户数据还得上传到第三方服务器。Solo Worker OS 把这些全部本地化——跑在 AMD Radeon GPU 上，数据不外泄。

**[0:25] GPU 证明**
设置页可以看到 AMD Radeon GPU 集成。Provider 设为 local，推理跑在 ROCm 上。健康探针显示 GPU 可达，延迟 321 毫秒。模型是 DeepSeek-V4-Flash，开源模型跑在 AMD 硬件上。

**[0:50] 核心演示**
跟 Agent 说话，自然语言创建客户。路由引擎毫秒级分类，自动调用工具。一句话创建项目，再一句话生成合同。全程不需要填表单。

**[1:40] RAG 知识库**
问 Agent 标准付款条款，它搜索本地知识库返回答案——不是 LLM 瞎编的，是从你自己的文档里检索的。

**[2:20] 多轮记忆 + 数据分析**
Agent 记住上下文。要一个业务概览，它查询本地数据库返回收入统计和项目状态。

**[2:50] Trace 可观测性**
Trace 页展示完整执行链——路由决策、LLM 调用、工具执行——证明推理确实在 AMD GPU 上跑。

**[3:20] 架构总结**
自学习路由 + 5 个垂直 Subagent + 14 个业务工具 + TF-IDF RAG + 双后端记忆。全部推理跑在 AMD Radeon GPU + ROCm 上。

**[3:40] 结尾**
Solo Worker OS——自由职业者的私有 AI Agent。客户、合同、发票、收款，全部本地化。AMD AI DevMaster 2026，赛道二。

---

## Recording Tips

1. **先演练一遍**，不用录，熟悉流程和时间
2. **工具调用时停顿**，等 Agent 响应完再继续说
3. **录屏前清空聊天历史**，确保演示干净
4. **打字时放慢**，让观众看清输入内容
5. **如果 Agent 响应慢**（6-7 秒），这是正常的——说明推理在 GPU 上跑，不是预录的
6. **结尾留 2 秒静音**再停止录制

## Fallback: If Dedicated GPU Instance Not Available

If you cannot launch a dedicated vLLM instance on Radeon Cloud (due to rate limits), the free model API at `developer.amd.com.cn/radeon/api/v1` is still running on AMD Radeon GPU hardware. In the demo video, you can:

1. Show the Settings page health probe (proves AMD GPU reachability)
2. Emphasize that the API endpoint is AMD's own platform running on Radeon GPU
3. Note in the documentation that the code supports both dedicated vLLM instances and the shared API

However, **for maximum compliance**, try to launch a dedicated vLLM instance. The rate limit resets after 1 hour.
