# RadeonStay Project Specification

## 1. Application scenario

RadeonStay is a local hotel guest-journey agent for guests and hotel staff who
need policy-grounded answers and safe operational actions without sending
private conversations or reservation data to a third-party model provider.

The primary journey combines late arrival, a child, an allergy, a quiet-room
request, airport transfer, room inventory, quoting, a reservation hold, and a
follow-up checkout change. This intentionally crosses knowledge, planning,
tools, memory, and permissions in a single inspectable flow.

## 2. Product principles

1. **Local by construction:** core inference and data remain in the controlled
   Radeon/ROCm environment.
2. **Evidence before language:** policy statements require citations and hotel
   facts require tool receipts.
3. **The model proposes; the server disposes:** the LLM does not own prices,
   permissions, state transitions, or database access.
4. **Fail closed:** invalid plans, missing evidence, expired confirmation, and
   unauthorized reads/writes produce a refusal rather than a best guess.
5. **Minimal retention:** session context is local; long-term preferences need
   explicit consent; audits avoid raw private values.

## 3. Agent capabilities

### 3.1 Local retrieval

Hotel policy Markdown files are indexed locally. Search results preserve the
document, heading, source path, excerpt, and score. The local model may select
only supplied citation IDs; final policy text is rendered by the server from
the matching excerpts. Unconstrained model prose is never treated as a fact.
For official evaluation, `data/policies/` must be a real directory inside the
project. Its path components, nested directories, and policy files cannot be
symbolic links, and every resolved corpus path must remain inside the project.

### 3.2 Typed tool calling

Tools publish a JSON-compatible schema and an effect classification. Read tools
may execute after authorization. Write tools return a preview and an opaque,
single-use, expiring confirmation token stored only as a hash in SQLite. The
confirmed server call atomically rechecks the user, session, tool, original
arguments, authoritative preview terms, expiry, operation key, and permission.
If inventory, price, or booking state changes, the old token fails closed and the
user must review a fresh preview.
Each chat call carries a client-generated request ID. Same-session retries replay
the cached response, while a stable actor/session/request/write-ordinal key keeps
confirmed domain writes idempotent across a lost response.

### 3.3 Multi-step planning

The local LLM returns an `AgentPlan` containing no more than eight steps with
unique IDs and backward-only dependencies. Pydantic validates the plan. Unknown
tools, future dependencies, malformed arguments, or excessive repair attempts
are rejected. Chat and confirmation execution is serialized per session so two
browser requests cannot reorder memory or confirm one action twice.

### 3.4 Local memory

Conversation state and reservation references are session-scoped. Long-term
preferences are stored only after an explicit opt-in action and can be listed or
deleted. Sensitive values are never copied into the audit message. Session
audit events form an HMAC-linked chain; the operational SQLite log remains a
separate, staff-only privacy-minimized trail.

### 3.5 Permissions and privacy

Guest, staff, and admin roles have different read/write permissions. Guests can
only access their own reservation and session. Consequential actions require
confirmation, are idempotent, and produce a receipt. Attempts to cross the
ownership boundary are refused without returning private data.

## 4. Model and local deployment

The model server is `llama.cpp` compiled with the HIP backend for the target AMD
Radeon GPU. It exposes a loopback OpenAI-compatible API consumed by a minimal
`httpx` client with environment proxy inheritance disabled. The competition
path rejects public model hosts.
Health checks also require the endpoint to advertise the configured model alias;
a reachable but incorrect local model fails the release gate.

Target configuration before measurement:

- Qwen3.6-35B-A3B Q6_K GGUF;
- all model layers offloaded to Radeon;
- 16K context;
- flash attention when supported;
- tuned batch and micro-batch sizes;
- one baseline slot, then controlled 2/4 concurrency experiments.

The exact model hash, llama.cpp commit and flags will be frozen only after the
quality and performance gates pass.

## 5. Radeon optimization methodology

The benchmark changes one variable at a time under the same model, prompt set,
generation limit, temperature, machine, and service build. It records TTFT,
when exposed by the pinned llama.cpp build, plus server timing fields,
HTTP-effective output throughput, end-to-end percentiles, VRAM, utilization and
task quality. A valid bundle must show native llama.cpp ROCm/HIP initialization,
non-zero model-layer offload, the exact endpoint and alias used by both evaluators,
and same-device non-zero GPU utilization plus VRAM use inside both the quality and
benchmark windows. The two windows need distinct active samples and a shared
physical GPU unique ID; baseline and optimized runs must retain identical common
active GPU indices and physical IDs. Missing TTFT is reported as unavailable
rather than inferred.

Planned comparisons:

1. conservative baseline versus flash-attention/tuned batch settings;
2. one versus two/four parallel slots while keeping the same fixed request set;
3. batch and micro-batch candidates changed one variable at a time.

Local RAG Top-K/schema ablations and a possible ROCm embedding path are exploratory
quality studies, not inputs to the official baseline/optimized comparator, because
that comparator requires the same commit, project tree, source hash, policy corpus,
model, binary, context, workload, hardware, and active physical GPU identity.

Different quantizations may be explored separately, but they are not accepted
as the evidence-controlled baseline/optimized comparison because the model-file
hash must match.

Optimization is accepted only if at least one material performance metric
improves while tool validity, citations, permission denials, and task success
remain above their release gates. Failed optimization attempts remain in the
evidence bundle.

## 6. Output and limitations

RadeonStay outputs an answer, citations, plan, tool receipts, pending-action
previews, confirmation results, and audit IDs. The included database is a
synthetic hotel sandbox. There is no payment, identity verification, emergency
dispatch, or real property-management integration. Production deployment would
require independent security, privacy, legal and operational review.
