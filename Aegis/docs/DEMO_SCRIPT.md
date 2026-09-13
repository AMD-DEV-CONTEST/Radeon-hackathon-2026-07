# Aegis — Demo Script (~6 minutes)

## Setup (before judges arrive)

1. `make up` — starts Postgres+pgvector, Redis, vLLM/ROCm, backend, frontend.
2. `make migrate` (if not run automatically).
3. Seed one runbook so the Runbook Retriever has precedent to find:
   ```
   POST /api/v1/knowledge/runbooks
   { "title": "Checkout service connection pool exhaustion",
     "content": "During high-traffic periods, checkout-service has previously
     exhausted its DB connection pool, causing 5xx spikes. Resolution: restart
     the service to clear stale connections, then investigate pool size config." }
   ```
4. Have a browser tab open on `http://localhost:3000` and `http://localhost:8000/docs`.
5. Run `python benchmarks/benchmark_inference.py` once beforehand so `/benchmarks` has data.

## 1. The problem (30s)

"When production breaks, an on-call engineer manually correlates logs, metrics,
deploys, and tribal knowledge — under pressure, alone, often at 3am. Existing
tools alert. None of them investigate."

## 2. Why local GPU inference is the whole point (30s)

"Incident data is some of the most sensitive data an enterprise has — logs,
secrets, internal architecture. Sending that to a cloud LLM is often a
compliance non-starter for finance, defense, and healthcare. Aegis runs
entirely on-prem on an AMD Radeon GPU via ROCm — nothing here calls out."

Show `/api/v1/health` — point at `inference_engine: ok`, hitting the local vLLM server.

## 3. Trigger an incident (30s)

```
POST /api/v1/incidents
{ "title": "Checkout service 500 errors",
  "description": "Spike in 5xx responses on checkout-service starting 14:02 UTC",
  "severity": "sev2", "service_hint": "checkout-service" }
```

Switch to the frontend — the incident appears in the stream immediately (status: triggered).

## 4. Watch the multi-agent investigation live (90s)

Open the incident detail page. Narrate as the agent trace timeline fills in:

- "The Planner just decided which specialists this incident needs — it's not
  running deploy correlation because nothing here suggests a deploy issue."
- "Log Analyst and Metrics Analyst are running concurrently right now — that's
  real parallel agent execution, not a demo animation."
- "The Runbook Retriever just searched our vector memory and found the
  precedent we seeded — this is the system getting smarter over time."
- Point at tokens/sec next to each step: "That number is real, streamed from
  the ROCm GPU right now."

## 5. Root cause + explainability (45s)

Point at the root-cause card: "Every claim here traces to a specific evidence
row from a specific agent — click through and you see the actual log/metric
data, not just LLM prose asserting a conclusion."

## 6. Human-in-the-loop remediation (45s)

"Aegis proposes a fix — restart checkout-service — but it does NOT execute it.
An SRE has to click Approve." Click approve. "That action is now in the audit
log with a timestamp, before it even executed — auditable by design."

## 7. GPU benchmark dashboard (45s)

Switch to `/benchmarks`. "This isn't a claimed number — it's a real benchmark
run against this exact vLLM/ROCm server, tokens/sec and GPU utilization across
concurrency levels."

## 8. Close (15s)

"Multi-agent planning, tool orchestration, long-term memory, human-gated
remediation, full explainability — running entirely on an AMD Radeon GPU.
That's Aegis."
