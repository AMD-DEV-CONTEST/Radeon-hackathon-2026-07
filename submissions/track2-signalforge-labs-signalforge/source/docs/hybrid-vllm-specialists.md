# Hybrid vLLM Specialist Runtime

This optional runtime path preserves SignalForge's local Radeon control plane while routing
the bounded context-specialist wave through the organizer-provided Radeon Cloud vLLM Model API.

## Runtime Split

| Component | Runtime | Authority |
|---|---|---|
| Request parsing and deterministic planner | Go and local rules | Intent, authorized roles, DAG, fan-out |
| Context specialists | Provided Radeon Cloud vLLM Model API | Qualitative interpretation of authorized evidence |
| Financial calculations | Deterministic Go engines | Values, formulas, units, periods, relations, receipts |
| Evidence and risk review | Local Radeon model | Claim authorization, conflicts, missing evidence |
| Final synthesis | Local Radeon model plus Go renderer | Qualitative synthesis; Go owns numbers and final envelope |

The planner permits no more than four context specialists per wave. All specialists share one API
endpoint and model; role prompts, evidence packets, capabilities, and output schemas remain
different. The remote path cannot add roles, tools, evidence IDs, numerical values, or calculation
receipts.

## Environment Contract

| Variable | Required when enabled | Meaning |
|---|---:|---|
| `SIGNALFORGE_SPECIALIST_API_ENABLED` | Yes | Explicit opt-in; defaults to disabled |
| `SIGNALFORGE_SPECIALIST_API_PROVIDER` | Yes | Must be `radeon-vllm` |
| `SIGNALFORGE_SPECIALIST_API_BASE_URL` | Yes | OpenAI-compatible `/v1` base URL; external URLs require HTTPS |
| `SIGNALFORGE_SPECIALIST_TEXT_MODEL` | Yes | Runtime-provided text model ID |
| `SIGNALFORGE_SPECIALIST_VISION_MODEL` | No | Reserved for image-bearing evidence |
| `SIGNALFORGE_SPECIALIST_API_TIMEOUT` | No | Positive Go duration; defaults to `90s` |
| `SIGNALFORGE_SPECIALIST_API_KEY_FILE` | Preferred | Read-only secret file populated at runtime |
| `SIGNALFORGE_SPECIALIST_API_KEY` | Compatibility only | Direct evaluator-injected secret |

Setting both key variables fails closed. The key is never written to reports, traces, errors,
command-line arguments, or configuration files.

## OpenBao

The application does not authenticate to OpenBao. An OpenBao Agent, CSI provider, or deployment
wrapper authenticates independently and renders
`configs/runtime/openbao-specialist-key.tmpl` to:

```text
/run/secrets/signalforge/radeon_model_api_key
```

Mount the file read-only with mode `0400` or `0440`, then set
`SIGNALFORGE_SPECIALIST_API_KEY_FILE` to that path. This keeps secret retrieval outside the model,
application logs, image layers, and Go process configuration.

For a judging harness that supports environment variables but not mounted secrets, inject
`SIGNALFORGE_SPECIALIST_API_KEY` at container startup and leave the file variable unset.

## Model Policy

- `DeepSeek-V4-Flash` is the initial text-specialist candidate.
- `Qwen3.6-35B-A3B` is reserved for evidence that genuinely requires vision.
- Model IDs remain runtime variables because the organizer may change the available set.
- The public endpoints do not advertise JSON Schema response mode. SignalForge serializes the
  exact response contract into the remote system message and omits only the unsupported
  transport-level `response_format` parameter. Every returned packet still passes the same
  deterministic decoder, schema, evidence, Numerical Silence, and review gates.
- Fine-tuning and LoRA are deferred until a frozen holdout proves a systematic failure that
  prompting, GraphRAG, deterministic tools, and output contracts cannot repair.

## Retrieval Policy

All roles use one shared evidence fabric with role-scoped retrieval profiles.

- GraphRAG may select authoritative narrative paths and preserve provenance.
- HyDE may expand narrative searches for business mechanisms, strategy, economics, or risk.
- HyDE output is never evidence and is discarded after retrieval.
- HyDE is forbidden for exact SEC facts, dates, prices, accounting values, calculations, or causal
  proof.
- Deterministic and lexical retrieval remain available when vector or graph services are degraded.

## Failure Behavior

The remote path receives a 55-second primary packet attempt inside a 180-second specialist budget.
If transport, truncation, JSON decoding, schema, evidence, Numerical Silence, or semantic
validation rejects that packet, the complete specialist role is replayed against the local model.
The remote packet never participates partially. This preserves time for local recovery while the
complete journey remains bounded by its independent deadline.

## Evidence

Every model call records the provider ID, model ID, role ID, start time, latency, TTFT, usage,
finish reason, and failure state. The API key and raw private prompts or responses are excluded.
The bonus is considered demonstrated only when at least one successful `radeon-vllm` specialist
call participates in a complete accepted product journey.
