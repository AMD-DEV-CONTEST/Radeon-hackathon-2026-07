# Analysis Provider

Status: Ollama provider implemented, unit-tested with a controlled local fake
HTTP server, and directly exercised once in the Task 03B AMD Linux record.

## Boundary

```text
NEW Event
→ optional deterministic SkillResolver
→ optional explicit SkillContext
→ optional structured KnowledgeQuery
→ replaceable KnowledgeRetriever
→ bounded ContextBuilder
→ KnowledgeContext (zero or more versioned documents)
→ ReliableAnalysisProvider (total deadline + finite retry)
→ AnalysisProvider explicit Event / SkillContext / KnowledgeContext input
→ AnalysisResultGuard
→ existing AnalysisResult
→ AlphaNoahRuntime
→ existing Decision
→ existing DecisionHook
→ PENDING_HUMAN_REVIEW / existing policy route
→ AuditRecord + SQLite
```

`AnalysisProvider` is a backend-neutral `Protocol`. It does not own persistence,
state transitions, Decisions, Tasks, HTML, QR handling, notification, approval
or equipment control.

`OllamaAnalysisProvider` uses only Python's standard library. Each raw adapter
call sends one non-streaming request to `POST /api/generate`. The explicit CLI
wraps that adapter in `ReliableAnalysisProvider`, which applies a total deadline,
strict canonical-result validation and at most the configured finite retry.
There is no tool call, embedding, Agent loop or multi-turn reasoning.

When `--demo-skills` is supplied, Runtime composition resolves one of the two
synthetic Task 04.5C demo definitions before model analysis. Resolution uses
only Event type and `metadata.asset_type`; Ollama never imports or selects a
Skill. Zero matches, deprecated-only matches and equal-specificity conflicts
fail explicitly before any model call or Decision.

When `--knowledge-file` is supplied, `ContextBuilder` creates a bounded
`KnowledgeQuery` from stable Event fields and consumes the `KnowledgeRetriever`
protocol. The current JSON repository delegates to
`DeterministicKnowledgeRetriever`; a future implementation can replace it
without changing the Provider contract. `ReliableAnalysisProvider` builds one
`KnowledgeContext` before the model attempt sequence and requires the backend to
implement `analyze_with_context`. The current Ollama adapter supports that
explicit method. With no knowledge file, the existing `analyze(Event)` path is
unchanged. When Skill guidance is also enabled, the backend must implement the
separate explicit `analyze_with_contexts(Event, SkillContext,
KnowledgeContext)` boundary; the current Ollama adapter and test fakes do so.

## Explicit configuration

Required:

- loopback HTTP base URL (default CLI value:
  `http://127.0.0.1:11434`);
- actual model tag, supplied with `--model` or
  `ALPHANOAH_OLLAMA_MODEL`.

Optional:

- reviewed local JSON knowledge repository through `--knowledge-file` or
  `ALPHANOAH_KNOWLEDGE_FILE`.

Bounded defaults:

- connect timeout: 5 seconds;
- total reliability deadline, including retries: 60 seconds;
- maximum retry count: 1 (two total attempts);
- maximum prompt: 64 KiB;
- maximum encoded request body: 128 KiB;
- maximum response body: 1 MiB;
- `keep_alive`: `5m`;
- `temperature`: `0`;
- `num_predict`: `1024`;
- non-streaming;
- thinking output disabled.

`num_ctx` has no guessed default. Supply `--num-ctx` only after confirming the
actual model and host setting. A full SHA-256 model digest may be passed through
`--model-digest` or `ALPHANOAH_OLLAMA_MODEL_DIGEST`; an unconfirmed or abbreviated
digest is rejected.

The provider accepts only unauthenticated `http` loopback hosts
`127.0.0.1`, `localhost` or `::1`. Cloud and LAN endpoints are not supported by
this adapter.

## Minimal data projection

The prompt includes:

- `event_id`;
- `event_type`;
- `source`;
- `location`;
- `asset_id`;
- `description`;
- safe opaque attachment reference tokens.

Reporter and `normalized_input` are omitted under the minimum-data
principle. Metadata is omitted. The provider never opens a path, downloads a
URL or reads attachment content. Path-like, URL-like and otherwise non-opaque
attachment references are omitted from the model projection.

When an explicit `SkillContext` exists, its bounded identity, version,
instructions, escalation rules and knowledge-query hints enter their own prompt
section. Hints are also passed into the structured query without changing the
retriever contract. Skill identity, version and resolution reason are persisted
in existing audit metadata; no SQLite schema was changed.

When a non-empty `KnowledgeContext` exists, the prompt also receives a bounded
array containing document identity, title, content, document type, source,
version, status and effective date. Arbitrary document metadata is not sent to
the model. Prompt version `ollama-industrial-analysis-v3` separates fixed
system rules, Event, Skill Context, Knowledge Context and output schema.
Neither Skill guidance nor knowledge may override mandatory human review,
strict output validation or equipment-control prohibitions.

Selection is deterministic: exact Event metadata fields and bounded lexical
signals are matched against reviewed document metadata, title and content.
No match produces an empty context and does not block analysis. This is not a
vector retriever, semantic ranker or Agent search loop.

## Output contract

The model must return exactly these fields:

```json
{
  "issue_summary": "string, 1..500 characters",
  "possible_causes": ["1..5 strings, each 1..500 characters"],
  "recommended_actions": ["1..5 strings, each 1..500 characters"],
  "severity": "low|medium|high|critical",
  "confidence": 0.0,
  "evidence_used": ["1..8 strings, each 1..500 characters"],
  "limitations": ["1..8 strings, each 1..500 characters"],
  "requires_human_review": true
}
```

The same JSON Schema is passed through Ollama's `format` field and embedded in
the prompt. Standard-library validation is still applied after parsing. Missing,
extra or mistyped fields, non-finite/out-of-range confidence, invalid severity,
overlong arrays/strings and `requires_human_review: false` are rejected.

The mapping to the existing `AnalysisResult` is:

| Ollama field | Existing field |
|---|---|
| `issue_summary` | `detected_issue` |
| possible causes, suggested actions, limitations | clearly qualified `reasoning_summary` and labelled `evidence` |
| `evidence_used` | labelled `evidence` strings |
| model tag/digest | `model_or_rule` and `evidence` |
| `confidence` | `confidence` |
| `severity` | uppercase `severity` |
| required `true` | `requires_human_review` |

Possible causes remain possible causes. The result is an AI-assisted preliminary
analysis, not a confirmed diagnosis or repair conclusion.

## Reliability guard

`AnalysisResultGuard` validates the existing canonical `AnalysisResult`; it does
not introduce a second analysis model. Exact mappings may be converted only when
their fields match the existing dataclass exactly. The guard does not infer,
repair or silently add fields.

Validation statuses are:

- `VALID`;
- `INVALID_SCHEMA`;
- `MISSING_FIELD`;
- `UNSAFE_OUTPUT`;
- `NOT_VALIDATED` when no model result reached validation.

`requires_human_review` must remain exactly `true`. An attempted bypass is
`UNSAFE_OUTPUT`, produces no Decision and is not retried.

The standardized model failure codes are:

- `MODEL_TIMEOUT`;
- `MODEL_UNAVAILABLE`;
- `MODEL_OUTPUT_INVALID`;
- `MODEL_CONNECTION_ERROR`;
- `MODEL_INTERNAL_ERROR`.

Input projection failures remain the existing typed provider-input errors
because they occur before model execution.

## Failure and recovery

Input preflight failures include an oversized prompt or encoded request and
occur before any network call. Transport failures include connection/timeout,
non-2xx HTTP and an oversized response. Output failures include invalid
outer/model JSON, an incomplete response and schema/policy violations.

Runtime handles either expected provider failure by:

1. creating no Decision;
2. transitioning the Event `NEW → FAILED`;
3. writing `provider_analysis_failed` with failure type and safe error code;
4. re-raising the typed failure to the CLI.

The reliability wrapper retries only transient timeout, connection and provider
availability failures. `max_retry=1` means one initial attempt plus at most one
retry, all inside one total deadline. Schema, unsafe-output, input and internal
failures are never retried. A wrapper-level hard timeout is also not retried,
because Python cannot safely cancel an arbitrary provider thread and overlapping
calls are prohibited.

If the bounded sequence still fails, recovery is explicit: an operator calls
existing `retry_failed_event()` to return `FAILED → NEW`, then runs analysis
again. A normal second analysis of an already-routed Event is rejected before a
second provider call or Decision.

The existing Decision audit or terminal provider-failure audit records bounded
model metadata: model/provider identity, analysis timestamp, prompt/skill version
when available, validation status, attempt count, retry policy, model digest when
configured, and safe source error codes. Raw output, prompts, traceback and
exception internals are not persisted.

When Knowledge Context is configured, the same audit metadata also records
`knowledge_sources` as source/version identities, `knowledge_statuses`,
`knowledge_version` as the context contract version and `context_count`.
Knowledge content is not copied into the audit record.

## Deterministic retrieval semantics

`KnowledgeQuery` contains only stable current inputs: Event type, asset ID,
optional asset type, location, bounded keywords and Top-K. A document that
explicitly declares a conflicting value for one of those structured fields is
excluded. Missing optional query fields and documents without a corresponding
constraint remain valid.

Remaining active documents use fixed, explainable scores:

- exact asset ID: 120;
- exact Event type: 100;
- exact asset type: 80;
- exact location: 60;
- keyword in reviewed metadata: 30;
- keyword in title: 10;
- keyword in content: 2.

Ordering is score descending and document ID ascending, followed by Top-K.
`KnowledgeMatch` records the score, matched fields and matched keywords;
`ContextBuilder` projects only its document into `KnowledgeContext`.

Normal retrieval excludes `deprecated` documents. `knowledge_key` identifies a
logical knowledge family. Loading or adding more than one `active` document for
the same key fails explicitly; arbitrary version labels are not parsed or
silently ranked.

## CLI

```bash
export ALPHANOAH_OLLAMA_BASE_URL="http://127.0.0.1:11434"
export ALPHANOAH_OLLAMA_MODEL="<actual model tag from ollama list>"

PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 \
  analyze event <event_id> \
  --provider ollama \
  --knowledge-file examples/knowledge_documents.json \
  --max-retry 1 \
  --total-timeout 60
```

For the synthetic Task 04.5C path, first create a
`device_not_shutdown` Event whose `metadata.asset_type` is
`air_conditioner` or `industrial_machine`, then add:

```text
--demo-skills --knowledge-file examples/skill_demo_knowledge.json
```

An unrelated Event fails resolution explicitly before the model call. Omitting
`--demo-skills` preserves the prior non-Skill analysis path.

The command prints `event_id`, `trace_id`, `decision_id`, Event/Decision status,
hook action, model identity and the enforced human-review flag. It does not
approve, create a Task, notify anyone or run from QR POST.

Read persisted results:

```bash
PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 show event <event_id>

PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 show decision <decision_id>

PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/alphanoah_qr_demo.sqlite3 show trace <trace_id>
```

Official API references:

- [Ollama `/api/generate`](https://docs.ollama.com/api/generate)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama errors](https://docs.ollama.com/api/errors)
- [Ollama installed model list/digest](https://docs.ollama.com/api/tags)

## Current non-capabilities

- one AMD Linux `qwen3.5:9b` run is recorded, but it is not a benchmark or
  general model-performance guarantee;
- GPU evidence is limited to pre/post snapshots, not continuous attribution;
- no automatic queue or scheduling; retry is local, finite and transient-only;
- no embedding, Vector DB, semantic ranking, remote knowledge service or
  complete RAG pipeline;
- no dynamic Skill generation, LLM Skill selection, Skill marketplace,
  low-code editor, remote Skill registry or tool execution;
- no cryptographic document trust or automatic defense against misleading
  knowledge content; repository content must be reviewed before use;
- no Equipment Skill or confirmed equipment diagnosis;
- no automatic approval, Task creation, notification or control;
- no production authentication, remote endpoint or cloud fallback.
