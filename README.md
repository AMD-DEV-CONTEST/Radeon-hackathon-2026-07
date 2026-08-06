# Local Incident Commander

Local Incident Commander is a private, evidence-first SRE investigation agent for
AMD AI DevMaster Hackathon Track 2. It turns a production incident into a bounded,
auditable workflow: inspect deployments, inspect metrics, search sanitized logs,
synthesize a cited root cause, and place every proposed response behind an operator
decision.

The competition path runs core inference locally with Qwen3-8B-AWQ, vLLM, AMD
Radeon, and ROCm. A deterministic fallback keeps the investigation useful when the
model or a tool is unavailable. It never executes a remediation command.

## What is implemented

- A server-owned four-step plan with a maximum of three read-only tool calls and one synthesis step
- Native OpenAI-compatible tool calls through the Hermes parser used by the Radeon vLLM launch configuration
- An append-only evidence ledger with server-generated evidence IDs and cited hypotheses
- A visible tool trace containing sanitized arguments, duration, status, errors, and evidence references
- Persistent JSON investigation sessions, optimistic version checks, idempotent request IDs, and an append-only audit log
- Session-scoped follow-up memory whose answers cite only evidence already collected in the investigation
- Simulation-only approval and rejection records for proposed actions; no command executor exists
- Deterministic model/tool fallback, partial-evidence retention, restart recovery, and a visible degraded state
- Runtime attestation that reports `local-radeon` only for a loopback model endpoint with fresh, matching ROCm evidence
- A responsive three-column operator workspace for evidence, agent execution, findings, approval, follow-up, and audit
- A compatibility `/api/analyze` endpoint for the original single-shot analyzer

## Quick start: offline-safe mode

The application and deterministic fallback use only the Python standard library.
Python 3.10 or later is required.

```bash
git clone https://github.com/8dgeRunner/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
python3 -m incident_commander.server --port 8765
```

Open <http://127.0.0.1:8765>, load the included checkout incident, create an
investigation, and run each of the four plan steps. Without a configured local
model, the same workflow uses deterministic fallback and clearly marks the session
as degraded.

## Radeon Cloud deployment

Clone the repository under the persistent volume on the competition image, then run:

```bash
cd /workspace/persistence/amd-ai-devmaster-hackathon-2026
./scripts/start-radeon-demo.sh
```

The script:

1. starts `Qwen/Qwen3-8B-AWQ` with vLLM on the local Radeon GPU;
2. enables native tool calling with the Hermes parser;
3. uses an 8,192-token context and `--enforce-eager`;
4. waits for the loopback model endpoint;
5. writes a sanitized ROCm runtime-evidence file; and
6. starts the operator console on port `8765`.

Model caches, logs, session snapshots, and runtime evidence remain under
`/workspace/persistence`. The local vLLM endpoint does not require an API key.

### Configuration

| Variable | Purpose | Competition default |
| --- | --- | --- |
| `LIC_ENABLE_LLM` | Enable the OpenAI-compatible model adapter | `1` in the Radeon launcher |
| `LIC_LLM_BASE_URL` | Model API root | `http://127.0.0.1:8000/v1` |
| `LIC_LLM_MODEL` | Served model name | `qwen3-8b` |
| `LIC_DATA_DIR` | Writable directory for session snapshots and audit data | Persistent Radeon storage |
| `LIC_RUNTIME_EVIDENCE` | Sanitized runtime attestation generated after model startup | Persistent Radeon storage |
| `LIC_MODEL_PORT` | vLLM port used by the launcher | `8000` |
| `LIC_APP_PORT` | Operator-console port used by the launcher | `8765` |

See [`.env.example`](.env.example) for local configuration. Never commit `.env`.

## Demo workflow

1. Confirm that the header says `Private Radeon` and the health endpoint reports `local-radeon`.
2. Load the synthetic checkout incident and create an investigation.
3. Run `get_deployments`, `query_metrics`, and `search_logs` one step at a time.
4. Inspect the growing evidence ledger and changing cited hypotheses.
5. Run synthesis to produce the commander brief and approval queue.
6. Approve the rollback dry-run and reject the unsafe connection-pool increase.
7. Ask why the pool should not be expanded and inspect the cited session-memory answer.
8. Demonstrate deterministic fallback without losing collected evidence.

The recording checklist and exact narration are in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
The submission-ready recording is [demo/Local-Incident-Commander-demo.mp4](demo/Local-Incident-Commander-demo.mp4), with the editable subtitle source in [docs/DEMO_SUBTITLES.srt](docs/DEMO_SUBTITLES.srt).

## Architecture

![Local Incident Commander architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

The agent is deliberately bounded instead of being a general-purpose autonomous
runtime. The server owns the plan, tool allowlist, evidence IDs, action safety text,
step budget, and approval semantics. The model may choose arguments for the current
allowlisted step and write a concise synthesis, but it cannot register tools, create
trusted citations, or execute a command.

The implementation is split into:

- `incident_commander/agent.py`: bounded orchestration and state transitions
- `incident_commander/tools.py`: validated, read-only local demo adapters
- `incident_commander/store.py`: atomic snapshots, quarantine, and audit persistence
- `incident_commander/llm.py`: dependency-free OpenAI-compatible completion and tool-call client
- `incident_commander/analyzer.py`: deterministic evidence ranking, hypotheses, and safe baseline
- `incident_commander/server.py`: static console, health checks, compatibility API, and investigation API
- `web/`: operator workspace

See [docs/SPECIFICATION.md](docs/SPECIFICATION.md) for the complete product and
interface specification and [docs/SECURITY.md](docs/SECURITY.md) for trust
boundaries and deployment precautions.

## Investigation API

Every mutation uses a printable ASCII `request_id` and the current
`expected_version`. Replaying the same request is idempotent; stale or conflicting
mutations return HTTP `409`.

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/investigations` | Create a persisted four-step investigation |
| `GET` | `/api/investigations/{id}` | Read the current complete snapshot |
| `POST` | `/api/investigations/{id}/next` | Execute exactly one bounded step |
| `POST` | `/api/investigations/{id}/messages` | Ask a session-scoped, cited follow-up |
| `POST` | `/api/investigations/{id}/actions/{action_id}/decision` | Record an immutable approve/reject decision |
| `GET` | `/api/health` | Report model mode and verified Radeon runtime evidence |
| `POST` | `/api/analyze` | Run the legacy single-shot compatibility analyzer |

Successful investigation responses use
`{"schema_version": 1, "investigation": {...}}`. Structured API errors use
`{"error": "...", "code": "..."}`.

## Verification

Run the automated unit and HTTP API suite:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q incident_commander
```

Run the deterministic analyzer microbenchmark:

```bash
python3 -m incident_commander.benchmark \
  --iterations 100 \
  --output benchmarks/local-baseline.json
```

Run the complete four-step workflow gate with two warmups and ten measured runs:

```bash
python3 -m incident_commander.workflow_benchmark \
  --warmups 2 \
  --iterations 10 \
  --p95-limit-ms 30000 \
  --output benchmarks/workflow-current-runtime.json
```

The workflow gate checks completion, all three tools, unknown citations, remote
core requests, and total p95 latency. Its output describes whichever runtime is
configured when the command runs; an offline-safe result is not Radeon evidence.
The checked-in offline gate result is
[benchmarks/workflow-offline.json](benchmarks/workflow-offline.json); it is a
workflow-integrity result, not a GPU-performance claim.

Run the model-level Radeon benchmark against a local OpenAI-compatible endpoint:

```bash
export LIC_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LIC_LLM_MODEL=qwen3-8b
python3 -m incident_commander.gpu_benchmark \
  --iterations 5 \
  --output benchmarks/radeon-vllm.json
```

The GPU benchmark writes only a public-safe hardware manifest plus TTFT,
end-to-end latency, output rate, token usage, and a sample response. It does not
write raw device inventory or hardware serial numbers.

## Recorded Radeon optimization evidence

The repository contains a model-level microbenchmark recorded on 2026-07-30 on
the competition Global Radeon Cloud with ROCm 7.2.1, vLLM 0.16.1.dev, and a 48 GB
Radeon PRO W7900 (`gfx1100`, 96 compute units). Both configurations served
Qwen3-8B-AWQ with an 8,192-token context and generated 160 tokens for the same
459-token incident prompt over five iterations.

| vLLM configuration | TTFT p50 | End-to-end p50 | Mean output rate |
| --- | ---: | ---: | ---: |
| Default compiled | 76.54 ms | 10.31 s | 15.64 tokens/s |
| `--enforce-eager` | 56.50 ms | 4.13 s | 39.35 tokens/s |

For this workload, eager execution produced about 2.5 times the output throughput
and avoided the long first-start graph compilation. Machine-readable evidence is
stored in
[the default run](benchmarks/radeon-qwen3-8b-awq-8k.json) and
[the eager run](benchmarks/radeon-qwen3-8b-awq-8k-eager.json).

These files are model microbenchmarks, not an end-to-end benchmark of the current
four-step agent. A final full-workflow run on the competition Radeon instance has
not yet been recorded in this repository.

## AgenticOpsEval compatibility boundary

The checkout incident included here is synthetic and independently authored. The
repository does not redistribute AgenticOpsEval/RCA100 data or its answer key, and
it does not claim an RCA100 result. The `Localization`, `Identification`, and
`Reason` taxonomy informs a lightweight, explicitly unofficial evaluator:

```bash
python3 -m incident_commander.evaluator \
  --predictions /private/path/predictions.json \
  --ground-truth /private/path/ground-truth.json \
  --output /private/path/evaluation.json
```

The evaluator reports `official_score: false`; it does not reproduce the official
benchmark judge. See
[docs/agenticopseval.md](docs/agenticopseval.md) for dataset and license notes.

## Documentation

- [Project specification](docs/SPECIFICATION.md)
- [Security model](docs/SECURITY.md)
- [Shared Radeon API notes (non-core path)](docs/radeon-cloud.md)
- [AgenticOpsEval compatibility](docs/agenticopseval.md)
- [Architecture source](docs/architecture.excalidraw)
- [Demo script](docs/DEMO_SCRIPT.md)
- [Submission checklist](docs/SUBMISSION_CHECKLIST.md)

## Safety boundary

Local Incident Commander is decision support, not an autonomous remediation
system. Hypotheses remain provisional until an operator verifies them. Approval
records a simulation-only decision and returns a command preview; it never changes
infrastructure. Do not expose the unauthenticated development server directly to
the public internet.

## License

See [LICENSE](LICENSE).
