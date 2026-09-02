# Ollama Event Analysis — AMD Linux Integration Evidence

Status: **PASSED — AMD Linux direct integration completed 2026-07-23.**

A direct local Ollama analysis run was recorded on an AMD Ryzen AI Max+ 395
host with Radeon 8060S (`gfx1151`) and ROCm 7.2.

Evidence boundary: this is an operator-produced single-run integration record,
not an independent Windows reproduction, continuous GPU trace or performance
benchmark. The final validated model JSON and selected measurements are retained;
raw system logs and sensitive host data are intentionally not stored.

## Preconditions

Do not pull into a repository with local changes. If the repository already
exists:

```bash
git status
git fetch origin
git checkout main
git pull --ff-only origin main
```

For a new checkout:

```bash
git clone <repository-url>
cd AlphaNoah-A1-Edge-Agent
```

Verify software and tests:

```bash
python3 --version
PYTHONPATH=src python3 -m unittest discover -s tests -v
ollama --version
ollama list
```

Choose the actual model tag from `ollama list`; do not guess:

```bash
export ALPHANOAH_OLLAMA_BASE_URL="http://127.0.0.1:11434"
export ALPHANOAH_OLLAMA_MODEL="<actual model tag from ollama list>"
ollama show "$ALPHANOAH_OLLAMA_MODEL"
curl "$ALPHANOAH_OLLAMA_BASE_URL/api/version"
curl "$ALPHANOAH_OLLAMA_BASE_URL/api/tags"
```

Record the full installed digest returned by `/api/tags`. If confirmed, it may
be configured:

```bash
export ALPHANOAH_OLLAMA_MODEL_DIGEST="<full 64-hex digest>"
```

Do not use an abbreviated registry digest. Use `--num-ctx` only if the actual
host/model context setting has been confirmed.

## Fixed synthetic Event

The repository fixture is labelled:

```text
Synthetic demo data
Not a real production incident
```

Fixture SHA-256: `5dac9c92ceca350dd87e19429629a86a217ceff3c349202aa4dbca912fe39d95`

Create one `NEW` Event in the integration database:

```bash
mkdir -p tmp
EVENT_ID="$(
PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path

from alphanoah_a1.runtime import AlphaNoahRuntime

fixture = json.loads(
    Path("examples/synthetic_factory_incident.json").read_text(encoding="utf-8")
)
runtime = AlphaNoahRuntime("tmp/ollama_integration.sqlite3")
event = runtime.create_event(
    source=fixture["source"],
    actor="human:amd-linux-integration-operator",
    raw_input_ref=fixture["raw_input_ref"],
    event_type=fixture["event_type"],
    location=fixture["location"],
    asset_id=fixture["asset_id"],
    reporter=fixture["reporter"],
    description=fixture["description"],
    timestamp=fixture["timestamp"],
    attachments=fixture["attachments"],
    metadata=fixture["metadata"],
)
print(event.event_id)
PY
)"
printf '%s\n' "$EVENT_ID"
```

## Analyze explicitly

Tag-only command:

```bash
PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/ollama_integration.sqlite3 \
  analyze event "$EVENT_ID" \
  --provider ollama \
  --base-url "$ALPHANOAH_OLLAMA_BASE_URL" \
  --model "$ALPHANOAH_OLLAMA_MODEL"
```

After the full digest is confirmed, add:

```text
--model-digest "$ALPHANOAH_OLLAMA_MODEL_DIGEST"
```

Save the printed `decision_id` and `trace_id`, then inspect:

```bash
PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/ollama_integration.sqlite3 show event "$EVENT_ID"

PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/ollama_integration.sqlite3 show decision "<decision_id>"

PYTHONPATH=src python3 -m alphanoah_a1.demo \
  --db tmp/ollama_integration.sqlite3 show trace "<trace_id>"
```

Verify exactly one Decision and no Task:

```bash
EVENT_ID="$EVENT_ID" PYTHONPATH=src python3 - <<'PY'
import os

from alphanoah_a1.runtime import AlphaNoahRuntime

runtime = AlphaNoahRuntime("tmp/ollama_integration.sqlite3")
snapshot = runtime.snapshot(os.environ["EVENT_ID"])
assert snapshot["event"]["status"] == "PENDING_HUMAN_REVIEW"
assert len(snapshot["decisions"]) == 1
assert snapshot["decisions"][0]["requires_human_review"] is True
assert snapshot["tasks"] == []
assert snapshot["human_reviews"] == []
print("Runtime acceptance checks passed.")
PY
```

If the model safely returns `critical` severity or confidence below the existing
DecisionHook threshold, the existing policy may route to `ESCALATED` or
`NEEDS_MORE_EVIDENCE`; record that actual result and treat the specified
`PENDING_HUMAN_REVIEW` acceptance as not yet passed. Do not alter the model
output or routing policy to force a pass.

## Failure recovery

Transport or output failure creates no Decision and moves the Event to `FAILED`
with a `provider_analysis_failed` AuditRecord. After correcting the cause, an
operator may explicitly reset the failed Event:

```bash
EVENT_ID="$EVENT_ID" PYTHONPATH=src python3 - <<'PY'
import os

from alphanoah_a1.runtime import AlphaNoahRuntime

runtime = AlphaNoahRuntime("tmp/ollama_integration.sqlite3")
runtime.retry_failed_event(
    os.environ["EVENT_ID"],
    actor="human:amd-linux-integration-operator",
)
print("Event returned to NEW.")
PY
```

Then rerun the single analysis command. There is no automatic retry.

## Evidence record to complete on AMD Linux

Do not enter values until directly observed:

| Evidence | Direct result |
|---|---|
| Run timestamp | 2026-07-23T20:46:25+08:00 — 2026-07-23T20:46:44+08:00 |
| Non-sensitive machine identifier | AMD-A1-LINUX-01 |
| Ollama version | 0.20.3 |
| Model tag | qwen3.5:9b |
| Full model digest | 6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7 |
| Confirmed capabilities/context | completion, vision, tools, thinking; 262144 context |
| Request start/end | 2026-07-23T20:46:25+08:00 / 2026-07-23T20:46:44+08:00 |
| End-to-end elapsed time | ~19 seconds |
| Validated structured output | issue_summary, possible_causes(5), recommended_actions(5), severity=medium, confidence=0.75, evidence_used(8), limitations(8), requires_human_review=true |
| Event ID / trace ID / Decision ID | event_345396b7119e40b6a5c8ea4e8a081c79 / trace_500b476781b143af84bcfa7162bd0c62 / decision_08e8d32457d848d9b7a3742136b8f740 |
| Event final route | PENDING_HUMAN_REVIEW (via REQUEST_HUMAN_REVIEW hook) |
| Exactly one Decision | 1 |
| No automatic approval | Confirmed — requires_human_review=true, status=PENDING_HUMAN_REVIEW |
| No Task created | 0 tasks |
| Notification boundary | Notification is not implemented; no notification path exists in this runnable flow |
| Schema validation | Passed — all 8 required fields present, confidence=0.75 in [0,1], severity in {low,medium,high,critical} |
| Python version | 3.12.3 |
| ROCm | 7.2; GPU: gfx1151; reported ~96 GiB GPU/UMA aperture is not an application-allocatable capacity claim |
| Platform compatibility observation | CPython 3.12 did not fail at the earlier 1200-level parser threshold; reconciliation replaces depth escalation with deterministic exception injection |

Do not save API keys, private IPs, usernames/home paths, raw system logs,
unnecessary model reasoning, customer data or sensitive host details.

## Acceptance

Stage B passes only if direct evidence shows:

- one real local Ollama response satisfying the strict output contract;
- exactly one Decision;
- Event status `PENDING_HUMAN_REVIEW`;
- no HumanReview was synthesized;
- no Task was created; notification is not implemented in this flow;
- Event, Decision and trace are readable from the same SQLite database;
- failures, if exercised, have a typed CLI error and AuditRecord.

**Result: PASSED — All acceptance criteria met on AMD Linux.**

## Verified Structured Output (final model JSON)

```json
{
  "issue_summary": "Machine 001 on production line A reports abnormal noise during operation, indicating a potential equipment fault requiring investigation.",
  "severity": "medium",
  "confidence": 0.75,
  "possible_causes": [
    "Loose mechanical components causing vibration or rattling.",
    "Worn bearings or gears generating friction noise.",
    "Misaligned belts or chains resulting in slapping sounds.",
    "Foreign object debris caught within moving parts.",
    "Lubrication failure leading to increased friction and noise."
  ],
  "recommended_actions": [
    "Immediately halt the machine and apply lockout/tagout procedures before inspection.",
    "Conduct a visual and auditory inspection to identify the source of the noise.",
    "Measure vibration levels if available to correlate with specific components.",
    "Review maintenance logs for recent changes or missed lubrication schedules.",
    "Document findings and submit a formal incident report for engineering review."
  ],
  "limitations": [
    "No direct observation of the fault.",
    "No access to real-time sensor data.",
    "No prior maintenance records reviewed.",
    "No audio recording of the incident.",
    "No vibration analysis performed.",
    "No thermal imaging conducted.",
    "No operator interview completed.",
    "No historical failure data for this specific machine."
  ],
  "evidence_used": [
    "Manual report indicating abnormal sound.",
    "Asset ID machine_001.",
    "Location production_line_A.",
    "Event type equipment_fault.",
    "No physical inspection data available yet.",
    "No measurement data recorded.",
    "No repair history provided.",
    "No video or audio logs attached."
  ],
  "requires_human_review": true
}
```

## GPU Evidence (rocm-smi snapshots)

| Metric | Pre-analysis (idle) | Post-analysis (after inference) |
|--------|---------------------|--------------------------------|
| GPU Temp | 42°C | 47°C |
| GPU Power | 15 W | 20 W |
| VRAM Usage | 0% | 20% |
| GPU Activity | 1% | 4% |

GPU activity consistent with local GPU inference was observed through VRAM
allocation, temperature rise and power increase during the Ollama run. These
pre/post snapshots do not provide continuous attribution or benchmark evidence.

## Linux Compatibility Fix

The Linux run observed that a 1,200-level JSON payload did not trigger the
expected `RecursionError` on CPython 3.12.3. Increasing depth to 10,000 made the
test pass, but tied it to interpreter recursion details and required an unrelated
response-size override.

The Windows reconciliation replaced depth escalation with a local deterministic
`json.loads` `RecursionError` injection inside a fake Provider. The test still
proves typed `ProviderOutputError`, `FAILED` Event state, no Decision and the
expected output AuditRecord without changing production limits or Provider code.
