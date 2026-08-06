# Performance Evidence Workflow

Performance work is prospective: declare the experiment before measuring,
retain all failures, and compare frozen conditions. Do not use this directory
to invent a baseline before the first end-to-end slice exists.

## Baseline

Use `BASELINE_READINESS.md`. Run the server benchmark on Radeon Cloud, collect
Agent-task and refinement-UX records separately, copy
`manifest.template.json`, fill it from real evidence, and validate it:

```bash
python3 qa/scripts/validate_manifest.py path/to/manifest.json
```

## Candidate

Before running a candidate, copy and complete
`candidate_plan.template.json`. `declared_changes` may contain more than one
path when a component profile requires a coherent change, but every difference
must be prospective, justified, and reversible.

```bash
bash qa/gates/perf_promotion_gate.sh \
  path/to/candidate-plan.json \
  path/to/baseline-manifest.json \
  path/to/candidate-manifest.json
```

Mechanical PASS means only that the evidence is admissible and comparable.
The quality owner still checks public regressions and the private blind suite.

Store repeated observations as JSONL records following
`metric-record.schema.json`, with interactive/background/stress scenarios in
separate files. Produce descriptive statistics without private promotion
thresholds:

```bash
python3 qa/scripts/summarize_metrics.py records-interactive.jsonl \
  --output summary-interactive.json
```
