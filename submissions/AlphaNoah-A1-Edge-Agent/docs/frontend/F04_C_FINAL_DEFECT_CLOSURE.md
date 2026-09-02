# F04-C Final Defect Closure

## Result

F04-C closes the three defects selected for the final demo: Human Review
double-submission, localized terminal review status, and Chinese-by-default AI
business prose. It does not change the Runtime architecture or state machine,
SQLite schema, Skill Runtime, Provider architecture, Projection architecture,
or frontend composition.

## Existing Human Review idempotency

### Available before F04-C

- Event state validation rejected a second sequential review after the first
  review had moved the Event out of `PENDING_HUMAN_REVIEW`.
- The Task web command returned an existing Task on a sequential retry.
- SQLite already had a generic `idempotency_keys` table, used by Evidence.

### Missing before F04-C

- Human Review did not look up an existing review by Decision.
- The status check and Review insert were not atomic. Two simultaneous requests
  could both pass validation and persist different Review records.
- The UI disabled actions only after React had committed its submitting state,
  leaving a same-frame double click able to start a second command.

### Reproduction evidence

A 12-run concurrent approval probe against the F04-B baseline produced two
Review records in 8 runs. The observed maximum was two Reviews for one
Decision. This established a real race rather than a presentation-only defect.

## Idempotency strategy

Human Review now treats the Decision ID as the command identity:

- SQLite uses `BEGIN IMMEDIATE` and the existing `idempotency_keys` table to
  atomically register the first Review for a Decision. No table or column was
  added.
- A repeat with the same outcome returns the original persisted Review.
- A repeat with a different terminal outcome returns a controlled HTTP `409`
  conflict and does not create another Review or Task.
- An in-process Runtime lock keeps the status transition, Audit write, and
  response path single-writer. SQLite remains the restart-safe source of
  identity.
- The existing Task read-before-create behavior is serialized at the web
  command boundary, so a double approval still produces one Task.
- Restart recovery returns the same persisted Review and Task IDs.

The post-fix 12-run concurrent probe produced exactly one Review and one Task
in every run. Concurrent HTTP calls both returned `200` with the same object
IDs; the opposite outcome returned `409`, never `500`.

Existing historical duplicate rows are not destructively migrated. F04-C
prevents new duplicates and safely returns the earliest persisted Review if a
legacy Decision is encountered.

## Frontend interaction hardening

`useHumanReview()` now owns a synchronous in-flight guard in addition to the
rendered submitting state. The guard is set before the first asynchronous
operation, so a same-frame double click cannot dispatch a second Review.

While either decision is running:

- both Approve and Reject are disabled;
- both show the submitting label;
- no local final state is synthesized;
- the confirmed result is read back through the HTTP data source and Runtime
  projections;
- a failure clears the guard and restores both actions for retry.

The production data flow remains:

```text
UI -> DataSource -> HTTP API -> Runtime -> SQLite -> safe projection -> UI
```

## Status localization boundary

The frontend adapter now maps these known machine states to i18n message keys:

- `PENDING_HUMAN_REVIEW`
- `APPROVED`
- `REJECTED`
- `TASK_CREATED`
- `CLOSED`

The Simplified Chinese UI renders them as `待人工复核`, `已批准`, `已拒绝`,
`任务已创建`, and `已关闭`. API values, Runtime enums, persisted values, and
TypeScript contract unions remain unchanged.

## Provider-neutral response language policy

The authoritative analysis language contract is defined once in
`providers/base.py` and is shared by the Ollama and OpenAI-compatible
providers. The default is `zh-CN`; `en-US` remains an explicit supported
policy value.

The contract requires Simplified Chinese for human-readable business content
while preserving machine-stable JSON schema keys, enum values, IDs, booleans,
severity values, model names, and version strings. The Fake provider uses
Chinese human-readable fixture prose so Windows and CI validation exercise the
same product expectation without Ollama.

Prompt contract versions were advanced to:

- `ollama-industrial-analysis-v4`
- `openai-compatible-industrial-analysis-v2`

There is no Provider-specific Chinese prompt copy, frontend translation of AI
content, or brittle character-count language guard. Contract tests verify the
shared prompt authority, exact output schema, Chinese prose path, and stable
machine fields.

## Safety boundary

F04-C does not expose or translate Prompt content in the UI. It does not add
Trace IDs, request IDs, raw Audit details, Provider internals, local paths, or
database paths to any projection. Human Review continues to require an
explicit human actor and never performs equipment control.

## Automated verification

- Python tests: 218/218 PASS.
- Frontend tests: 198/198 PASS across 34 files.
- TypeScript typecheck: PASS.
- Vite production build: PASS.
- Python compileall: PASS.
- Git whitespace validation: PASS.

Coverage added for concurrent and repeated approvals, repeated rejection,
opposite-outcome conflict, restart recovery, single-Task persistence, no HTTP
`500`, synchronous frontend double-click protection, error recovery, refresh
recovery, status localization, Provider prompt authority, Chinese Fake output,
and stable schema fields.

## Windows browser evidence

A real Chromium session used the HTTP data source, Fake provider, and a
temporary SQLite Runtime. It verified:

- pending review with Chinese AI business prose;
- a programmatic double approval producing one Review request;
- both buttons disabled with `正在提交…` while the request was held in flight;
- persisted approved state and Task creation;
- persisted rejected state rendered as `已拒绝` with no raw `REJECTED` text.

Temporary untracked screenshots from the verification run:

```text
tmp/f04-c-visual/pending-chinese.png
tmp/f04-c-visual/approve-submitting-disabled.png
tmp/f04-c-visual/approved.png
tmp/f04-c-visual/rejected-chinese.png
```

The temporary backend, frontend, and browser-debug listeners were stopped after
the persisted Review and Task counts were checked.

## Linux follow-up

The AMD Linux acceptance run should keep the same checks while selecting the
real Ollama provider and `qwen3.5:9b`: verify Chinese human-readable analysis,
double approval, one persisted Review, one persisted Task, localized rejection,
and refresh recovery. F04-C does not install Ollama or claim that Linux run as
part of this Windows closure.
