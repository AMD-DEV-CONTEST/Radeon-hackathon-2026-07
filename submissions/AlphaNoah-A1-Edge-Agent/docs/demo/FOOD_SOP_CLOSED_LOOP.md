# Implemented Food SOP Closed-loop Demo

Status: Implemented and tested on 2026-07-23.

## Scope

This is AlphaNoah v0.1's **first validation skill**:

> A synthetic cold-holding observation exceeds a project-defined demo threshold,
> a human approves the proposed corrective action, synthetic evidence is submitted,
> and a post-task rule closes the event.

It is not a real incident, real SOP or food-safety recommendation. It validates
the domain-neutral Runtime and does not define AlphaNoah's product scope.
AlphaNoah is positioned as an industrial field Agent.

## Fixtures

- `examples/synthetic_food_sop_event.json`
- `examples/synthetic_corrective_evidence.json`

Both contain:

```text
Synthetic demo data
Not a real production incident
```

## Run

Interactive:

```bash
PYTHONPATH=src python -m alphanoah_a1.demo --reset
```

Reproducible approved path:

```bash
PYTHONPATH=src python -m alphanoah_a1.demo --reset --decision approve
```

Explicit rejection path:

```bash
PYTHONPATH=src python -m alphanoah_a1.demo --reset --decision reject
```

## Expected approved path

```text
NEW
→ ANALYZED
→ PENDING_HUMAN_REVIEW
→ APPROVED
→ TASK_CREATED
→ IN_PROGRESS
→ EVIDENCE_SUBMITTED
→ UNDER_REVIEW
→ CLOSED
```

The command prints every AuditRecord with actor, action, object, previous/new
state, timestamp and trace ID.

## Persistence

Default database: `tmp/alphanoah_demo.sqlite3`.

The path is ignored by Git. `--reset` clears only the explicitly selected demo
database tables. A restart without `--reset` preserves earlier events and timelines.

Existing data can be inspected without changing Runtime state:

```bash
PYTHONPATH=src python -m alphanoah_a1.demo --db tmp/alphanoah_demo.sqlite3 list events
PYTHONPATH=src python -m alphanoah_a1.demo --db tmp/alphanoah_demo.sqlite3 show event <event_id>
PYTHONPATH=src python -m alphanoah_a1.demo --db tmp/alphanoah_demo.sqlite3 show trace <trace_id>
```

## Verified in this repository

- normal close;
- human rejection;
- more-evidence recovery;
- illegal transition rejection;
- restart recovery;
- duplicate submission protection;
- malformed analysis-output failure and retry;
- audit-chain completeness.

AMD GPU/Ollama inference is not part of this implemented path yet.

The standard-library workflow was executed on an AMD Ryzen 7 8845H / Radeon 780M
Windows host; this proves host execution only, not GPU inference. See
[Local AMD Host Run Evidence](LOCAL_AMD_HOST_RUN.md).
