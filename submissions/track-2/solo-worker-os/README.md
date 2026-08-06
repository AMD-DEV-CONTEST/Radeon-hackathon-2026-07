# Solo Worker OS

> AI-native freelance operating system. An AI agent manages your entire business workflow — client intake, project tracking, contract generation, payment follow-ups — through natural conversation.

Powered by a **provider-agnostic agent layer** (self-hosted local / Qwen / Claude / OpenAI / MTClaw) with a self-learning FunctionRouter, full execution tracing, and persistent memory via Supabase or local JSONL files.

---

## What It Does

Solo Worker OS turns freelance business management into a conversation. Instead of juggling spreadsheets, docs, and invoicing tools, you just talk to the AI agent:

- **"New client — Marcus Rivera, e-commerce platform, budget $15,000, deadline August 15"** → Agent creates the project, generates a contract, and sets up deadline tracking
- **"Which projects are overdue?"** → Agent queries the database and prioritizes your follow-ups
- **"Write a follow-up email for the unpaid invoice from Sarah"** → Agent drafts a professional reminder in your chosen tone (polite / firm / final notice)

The agent runs a full agentic loop: it routes your request through a FunctionRouter to the right vertical Subagent, reasons over the request, selects the right tools, chains multi-step workflows, and executes autonomously — while every step is recorded in an execution trace.

### Key Capabilities

| Feature | How It Works |
|---------|-------------|
| **Multi-Tool Agent** | A reasoning loop with 14 business tools covering project operations, contracts, invoices, payments, reports, private knowledge, analysis, deliverable archiving, and browser automation |
| **FunctionRouter** | Two-layer routing engine — fast keyword matching (~0ms) with an LLM intent-classification fallback — dispatches each message to the right vertical Subagent |
| **Router Self-Learning** | User corrections feed back into per-keyword weight multipliers so routing accuracy improves over time |
| **Trace Observability** | A built-in `/trace` page visualizes every routing decision, LLM call, and tool invocation across a user turn |
| **Multi-Provider** | Switch between a self-hosted local model, Qwen, Claude, OpenAI, and MTClaw via a single `AGENT_PROVIDER` env var — no code changes |
| **Persistent Memory** | Store conversations in Supabase PostgreSQL or private local JSONL files through the same `MemoryStore` interface |
| **Streaming Responses** | Real-time SSE streaming — see the agent's reasoning as it happens |
| **Bilingual UI** | One-click toggle between English and Chinese (中文) |
| **Knowledge Base** | RAG-powered document storage (TF-IDF) for contracts, templates, and notes |
| **Demo Mode** | Run the full app against an in-memory mock backend — no Supabase or API keys required |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Agent** | Provider-agnostic agent layer — self-hosted vLLM/SGLang on AMD Radeon GPU, Qwen Cloud, Anthropic Claude, OpenAI, or MTClaw. Streaming + function calling. |
| **Framework** | Next.js 14 (App Router) + TypeScript |
| **Database** | Supabase (PostgreSQL) with Row Level Security |
| **Auth** | Supabase Auth (OTP / magic link) |
| **Styling** | Tailwind CSS + industrial dark design system (Dark + Amber) |
| **Deployment** | Vercel |
| **Email** | Resend (deadline reminders + weekly reports) |

### Multi-Agent Architecture

The agent layer is fully provider-agnostic. The active provider is selected by the `AGENT_PROVIDER` environment variable (`local` | `qwen` | `claude` | `openai` | `mtclaw`), defaulting to `qwen`. Each request is routed by the FunctionRouter to one of 5 vertical Subagents, which in turn pick from a shared declarative tool registry:

```
User Message
    ↓
FunctionRouter (lib/agent/router.ts)
    ├── Layer 1: Keyword matching (~0ms)        → confidence ≥ threshold
    └── Layer 2: LLM intent classification       → fallback for ambiguous queries
    ↓
Subagent (5 verticals: general / knowledge_rag / data_analysis / writing_assistant / quick_chat)
    ↓
Agent Factory (lib/agent/index.ts) → Provider (local | qwen | claude | openai | mtclaw)
    ↓
Tool Loop (MAX_ITERATIONS)
    ├── create_project            ├── get_exchange_rates
    ├── update_project_status     ├── get_pricing_benchmark
    ├── generate_contract         ├── get_upcoming_deadlines
    ├── generate_invoice          ├── analyze_business_data
    ├── record_payment            ├── search_knowledge_base
    ├── export_monthly_report     ├── generate_followup_message
    ↓
Streaming Response (SSE)  +  TraceCollector records the full turn
```

When `COMPETITION_MODE=casper`, two additional read-only Casper blockchain tools (`casper_query_account`, `casper_get_deploy`) are appended to the tool set.

---

## Quick Start

### Prerequisites

- Node.js 18+
- A Supabase project (free tier works) — **or** run in Demo Mode (no Supabase needed)
- A supported commercial-provider key — **or** a self-hosted vLLM/SGLang endpoint

### Setup

1. **Clone and install:**

```bash
git clone <repo-url>
cd solo-worker-os
npm install
```

2. **Configure environment:**

```bash
cp .env.example .env.local
```

Edit `.env.local` with your keys (see [Environment Variables](#environment-variables) for the full list):

```env
# Agent provider: qwen | claude | openai | mtclaw  (default: qwen)
AGENT_PROVIDER=qwen

# Qwen Cloud (DashScope) — default provider
DASHSCOPE_API_KEY=your_dashscope_api_key
QWEN_MODEL=qwen-plus

# AMD Radeon private inference — no commercial LLM API key required
# AGENT_PROVIDER=local
# LOCAL_LLM_BASE_URL=http://localhost:8000/v1/chat/completions
# LOCAL_LLM_API_KEY=EMPTY
# LOCAL_LLM_MODEL=Qwen/Qwen3-4B

# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# Optional: Email notifications
RESEND_API_KEY=your_resend_key
NOTIFICATION_EMAIL=you@example.com
```

3. **Set up the database:**

Run the SQL in `supabase/schema.sql` in your Supabase SQL Editor. (Skip this step if you are using Demo Mode.)

4. **Run the dev server:**

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Demo Mode

The app can run in **Demo Mode** — a fully self-contained experience backed by an in-memory mock Supabase client pre-seeded with sample data. No login, no Supabase project, and no API keys are required, which lets testers explore every feature immediately.

Enable it by setting:

```env
NEXT_PUBLIC_DEMO_MODE=true
```

When `NEXT_PUBLIC_DEMO_MODE=true`, both the browser and server Supabase clients use the in-memory mock. Middleware authentication is bypassed in demo mode. All demo data is in-memory and resets on server restart.

---

## AMD Radeon GPU / Private Local Provider

The Track 2 competition configuration runs Qwen3-4B through vLLM on an AMD
Radeon GPU with ROCm. The application talks to the server through the standard
OpenAI-compatible chat endpoint, so routing, tool calling, memory, streaming,
and trace logic remain provider-neutral.

### Start vLLM on the Radeon host

```bash
nohup vllm serve Qwen/Qwen3-4B \
  --host 0.0.0.0 \
  --port 8000 \
  --trust-remote-code \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.5 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  > /workspace/vllm.log 2>&1 &
echo $! > /workspace/vllm.pid
```

Wait for `Application startup complete`, then verify the model:

```bash
curl -sS http://127.0.0.1:8000/v1/models
```

### Configure Solo Worker OS

```env
AGENT_PROVIDER=local
LOCAL_LLM_BASE_URL=http://localhost:8000/v1/chat/completions
LOCAL_LLM_API_KEY=EMPTY
LOCAL_LLM_MODEL=Qwen/Qwen3-4B
DEMO_MODE=true
NEXT_PUBLIC_DEMO_MODE=true
SOLO_LOCAL_MODE=true
```

Start the application and open the health endpoint:

```bash
npm run dev
```

```text
http://localhost:3000/api/local-llm/status
```

A valid competition setup reports `provider: local`, `isLocal: true`,
`reachable: true`, and `Qwen/Qwen3-4B` in the served-model list.

The verified Radeon session used ROCm 7.2.1 and recorded the running vLLM
process, GPU memory allocation, served-model response, successful HTTP 200 chat
completions, and end-to-end tool calls. See
[`docs/evidence/README.md`](docs/evidence/README.md) and
[`submission/PROJECT_SPECIFICATION.md`](submission/PROJECT_SPECIFICATION.md).

---

## Project Structure

```
solo/
├── app/
│   ├── api/
│   │   ├── chat/route.ts              # Agent streaming endpoint (SSE + tool loop)
│   │   ├── projects/                  # Project CRUD + status update
│   │   ├── project/[id]/              # Project detail + status
│   │   ├── knowledge/route.ts         # Knowledge base RAG
│   │   ├── cron/route.ts              # Automated reminders + reports
│   │   ├── export/csv/route.ts        # CSV export
│   │   ├── export/contract/[id]/      # Contract markdown export
│   │   ├── notifications/route.ts     # Deadline reminders + weekly reports
│   │   ├── workflow/[id]/route.ts     # Workflow step tracking
│   │   ├── trace/route.ts             # Execution trace API
│   │   ├── router-feedback/route.ts   # Router self-learning feedback
│   │   └── mtclaw-tools/route.ts      # MTClaw fast-path tool API
│   ├── casper/page.tsx                # Casper blockchain demo
│   ├── chat/page.tsx                  # AI agent conversation interface
│   ├── dashboard/page.tsx             # KPI overview + recent projects
│   ├── demo/page.tsx                  # Interactive demo scenarios
│   ├── knowledge/page.tsx             # Knowledge base manager
│   ├── login/page.tsx                 # Auth entry point
│   ├── project/[id]/page.tsx          # Project detail + agent timeline
│   ├── projects/page.tsx              # Project pipeline table
│   ├── settings/page.tsx              # Preferences
│   ├── trace/page.tsx                 # Execution trace observability
│   ├── layout.tsx
│   └── page.tsx                       # Redirects to /dashboard
├── components/
│   ├── ChatClient.tsx                 # Streaming chat with SSE
│   ├── ChatMessage.tsx                # Message bubbles + tool chips
│   ├── LanguageToggle.tsx             # EN / 中文 toggle
│   ├── FollowUpGenerator.tsx          # Tone-selectable follow-up drafts
│   ├── WorkflowTracker.tsx            # Workflow stage tracker
│   ├── RouteFeedback.tsx              # Router correction feedback UI
│   ├── NotificationBell.tsx           # Deadline / report notifications
│   └── ...
├── lib/
│   ├── agent/
│   │   ├── index.ts                   # Agent factory (provider selection)
│   │   ├── qwen.ts                    # Qwen Cloud provider (default)
│   │   ├── claude.ts                  # Anthropic Claude provider
│   │   ├── openai.ts                  # OpenAI provider
│   │   ├── mtclaw.ts                  # MTClaw (OpenAI-compatible) provider
│   │   ├── openai-compat.ts           # Shared OpenAI-compatible base
│   │   ├── router.ts                  # FunctionRouter (2-layer routing)
│   │   ├── router-learning.ts         # Router self-learning (weight tuning)
│   │   ├── trace.ts                   # TraceCollector (execution traces)
│   │   ├── prompt.ts                  # System prompt builder
│   │   ├── subagents/                 # 5 vertical Subagent configs
│   │   ├── casper/                    # Casper blockchain tools + client
│   │   └── types.ts                   # Provider-neutral agent types
│   ├── tools/
│   │   ├── index.ts                   # Declarative tool registration
│   │   ├── registry.ts                # Tool registry + dispatch
│   │   ├── types.ts                   # Tool config types
│   │   └── handlers/                  # One file per tool implementation
│   ├── rag/                           # TF-IDF retrieval
│   ├── rag.ts                         # Knowledge base search
│   ├── supabase-server.ts             # SSR Supabase client
│   ├── supabase-service.ts            # Service-role client (bypasses RLS)
│   ├── mock-supabase.ts               # In-memory mock for Demo Mode
│   ├── market-data.ts                 # Exchange rates + pricing
│   ├── workflow.ts                    # Workflow step logic
│   ├── i18n.ts / i18n-server.ts       # EN/ZH translations
│   └── types.ts / utils.ts
├── supabase/
│   ├── schema.sql                     # Database schema + RLS policies (source of truth)
│   ├── migrate-columns.sql            # Column migrations for older schemas
│   ├── auth-migration.sql
│   ├── poc_schema.sql
│   └── seed.sql                       # Demo / seed data
├── scripts/                           # Benchmarks + verification scripts
├── docs/                              # Architecture, product concept, demo scripts
└── demo-video/                        # Walkthrough recordings + scripts
```

---

## Agent Tools

The agent has access to 14 business tools registered in a declarative registry (`lib/tools/handlers/`). Each Subagent only sees the subset of tools configured for its vertical, enforcing tool isolation per domain.

| Tool | Subagent | Purpose | Example Trigger |
|------|----------|---------|----------------|
| `create_project` | general | Create a new project with client details | "New client Sarah, logo design, $800, 3 weeks" |
| `update_project_status` | general | Change project status (active → delivered → invoiced → paid) | "Mark the Acme project as delivered" |
| `get_exchange_rates` | general | Fetch live exchange rates for multi-currency budgets | "What's the USD to CNY rate?" |
| `get_pricing_benchmark` | general | Look up market pricing benchmarks for a service type | "What's the going rate for a logo design?" |
| `get_upcoming_deadlines` | general | List upcoming project deadlines / schedule | "What deadlines do I have this week?" |
| `search_knowledge_base` | knowledge_rag | Search the knowledge base (TF-IDF RAG) | "Do we have a template for NDA agreements?" |
| `analyze_business_data` | data_analysis | Business analytics, revenue stats, project insights | "Give me a business overview" |
| `generate_contract` | writing_assistant | Generate a full contract from project data | "Generate a contract for Marcus's project" |
| `generate_invoice` | writing_assistant | Generate an invoice from project data | "Create an invoice for Marcus's project" |
| `record_payment` | general | Record a project payment and update status | "Record the final payment from Marcus" |
| `generate_followup_message` | writing_assistant | Draft payment reminder in selectable tone | "Write a firm follow-up for the unpaid Sarah invoice" |
| `export_monthly_report` | data_analysis | Export a monthly operating report | "Export this month's business report" |
| `archive_deliverable` | general | Archive a project deliverable | "Archive the final files for Marcus" |
| `browser_automate` | general | Run a scoped browser research or automation task | "Research three competitor pricing pages" |

**Casper mode** (`COMPETITION_MODE=casper`) adds two read-only blockchain tools: `casper_query_account` and `casper_get_deploy`.

**MTClaw fast-path** — when `AGENT_PROVIDER=mtclaw`, the MTClaw router can bypass the LLM for simple data queries via the `/api/mtclaw-tools` endpoint (actions: `overview`, `list_projects`, `search_knowledge`, `create_project`, `generate_contract`).

---

## Router Self-Learning

The FunctionRouter closes the loop between execution traces and routing accuracy. When a user corrects a routing decision (via the `RouteFeedback` UI and `/api/router-feedback` endpoint), the correction is fed back into per-keyword weight multipliers so the same message pattern routes better next time.

- **FeedbackStore** — in-memory ring buffer of user corrections (max 1000 records).
- **KeywordWeightAdjuster** — recomputes a per-`(subagent, keyword)` weight multiplier (clamped to `[0.1, 2.0]`) from the feedback history. Correct subagent keywords are boosted (`+0.1`); wrong subagent keywords are penalized (`-0.05`).
- **Adaptive threshold** — when the system has accumulated corrections, the keyword confidence floor is lowered proportionally, because the learned weights are trusted to disambiguate ambiguous queries.

The learned weights are queryable from the trace UI and persisted to the `router_weights` table for cross-session continuity. See `lib/agent/router-learning.ts` for the full implementation.

---

## Trace Observability

Every user turn is recorded as an execution trace by the `TraceCollector` (`lib/agent/trace.ts`), giving full visibility into the agent's decision-making:

- **Route events** — which Subagent was selected, the confidence score, and which routing layer decided.
- **LLM call events** — total LLM call duration per turn.
- **Tool call / tool result events** — the tool name, its input, the returned result, and how long it took.
- **Error events** — any failure that occurred during the turn.

Traces are kept in memory (max 100, newest-first) and visualized on the `/trace` page. In Demo Mode, two seed traces (based on real benchmark runs) are pre-loaded so the page is never empty on first visit; real traces push them out naturally. All trace recording is defensive — a failure to record an event never breaks the chat flow.

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `projects` | Client projects with budget, currency, deadline, status, Casper address |
| `messages` | Chat history between user and agent |
| `agent_actions` | Audit log of all tool calls made by the agent |
| `knowledge_docs` | Knowledge base documents for RAG (full-text search indexed) |
| `notifications` | Deadline reminders and weekly reports (read/unread state) |
| `workflow_steps` | Per-project workflow stage tracking (pending → in_progress → completed) |
| `router_weights` | Router self-learning keyword weight adjustments (persisted feedback) |

All tables enable Row Level Security with user-scoped policies (`user_id IS NULL` allows demo-mode rows); the service role bypasses RLS entirely for cron jobs and admin tasks. See `supabase/schema.sql` for the full schema, indexes, triggers, and policies.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_PROVIDER` | No | Provider switch: `local` \| `qwen` \| `claude` \| `openai` \| `mtclaw` (default: `qwen`) |
| `LOCAL_LLM_BASE_URL` | Local | OpenAI-compatible local chat endpoint (default: `http://localhost:8000/v1/chat/completions`) |
| `LOCAL_LLM_API_KEY` | No | Bearer token for the local endpoint (default: `EMPTY`) |
| `LOCAL_LLM_MODEL` | No | Self-hosted model name (default: `Qwen/Qwen3-4B`) |
| `SOLO_LOCAL_MODE` | No | `true` selects persistent local JSONL conversation memory instead of Supabase |
| `DASHSCOPE_API_KEY` | Qwen | Qwen Cloud / DashScope API key |
| `QWEN_MODEL` | No | Qwen model name (default: `qwen-plus`) |
| `ANTHROPIC_API_KEY` | Claude | Anthropic API key (when `AGENT_PROVIDER=claude`) |
| `OPENAI_API_KEY` | OpenAI | OpenAI API key (when `AGENT_PROVIDER=openai`) |
| `MTCLAW_BASE_URL` | MTClaw | MTClaw router endpoint (when `AGENT_PROVIDER=mtclaw`) |
| `MTCLAW_API_KEY` | MTClaw | MTClaw API key (falls back to `LLM_API_KEY` / `DASHSCOPE_API_KEY`) |
| `MTCLAW_MODEL` | No | Upstream model name for MTClaw (default: `qwen3.7-plus`) |
| `COMPETITION_MODE` | No | `qwen` \| `casper` — auto-selects provider and tool set |
| `NEXT_PUBLIC_SUPABASE_URL` | Prod | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Prod | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Prod | Supabase service role key (server-only, bypasses RLS) |
| `NEXT_PUBLIC_DEMO_MODE` | No | `true` → browser Supabase client uses in-memory mock |
| `DEMO_MODE` | No | `true` → server service-role client uses in-memory mock + seeds demo traces |
| `NEXT_PUBLIC_APP_URL` | No | App base URL (default: `http://localhost:3000`) |
| `NEXT_PUBLIC_AGENT_PROVIDER` | No | Public mirror of provider for client-side display |
| `NEXT_PUBLIC_CASPER_RPC_URL` | Casper | Casper Network RPC endpoint (casper mode only) |
| `RESEND_API_KEY` | No | Resend API key for email notifications |
| `NOTIFICATION_EMAIL` | No | Recipient for deadline reminders + weekly reports |

---

## Demo

### Try These Conversations

1. **Create a project:** "新客户张总，要做个 logo，预算 3000 元，两周后交付"
2. **Check deadlines:** "哪些项目快到期了？"
3. **Generate a contract:** "为最近的项目生成一份合同"
4. **Follow-up email:** "给 Sarah 的未付款项目写一封催款邮件，语气正式一点"
5. **Business overview:** "给我一个业务概况"
6. **Knowledge search:** "我的标准付款条款是什么？"

---

## License

MIT

---

## Links

- **Live Demo:** Runs in Demo Mode by default — explore all features with zero setup via the `/demo` page.
- **Documentation:** See `docs/` directory for architecture, product concept, and demo scripts (`docs/ARCHITECTURE.md` is the canonical architecture reference).
- **Qwen Cloud:** [https://dashscope.aliyun.com](https://dashscope.aliyun.com)
- **Supabase:** [https://supabase.com](https://supabase.com)
