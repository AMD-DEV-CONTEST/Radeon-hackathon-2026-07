# AgenticOpsEval compatibility

Local Incident Commander adopts the evaluation structure introduced by
[AgenticOpsEval](https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval):

- **Localization**: identify the root-cause service or infrastructure entity.
- **Identification**: identify the failure type.
- **Reason**: support a causal explanation with observable evidence checkpoints.

The repository does not redistribute the 15.3 GB benchmark or its answer key.
The included checkout scenario is synthetic and independently authored. An
optional evaluator can consume user-prepared prediction and ground-truth JSON
derived from separately downloaded data, without placing an answer key in the
model prompt or repository.

## Lightweight evaluator CLI

The evaluator is deliberately offline and does not download, discover, or
redistribute any dataset files. Supply prediction and ground-truth JSON files
explicitly:

```bash
python3 -m incident_commander.evaluator \
  --predictions /path/to/predictions.json \
  --ground-truth /path/to/ground-truth.json \
  --output /tmp/lic-evaluation.json
```

Both files accept a JSON list or a `{"cases": [...]}` envelope. Each case uses
this minimal schema:

```json
{
  "case_id": "t001",
  "localization": ["checkout-api"],
  "identification": ["database connection pool contention"],
  "reason": [
    "rc3 enabled the pricing lookup",
    "pool waiters increased to 137"
  ]
}
```

For separately obtained answer formats, the evaluator also recognizes
`root_cause_entity`/`root_cause_service`, `fault_type`/`failure_type`, and
`causal_chain`/`evidence_checkpoints`. It never writes these inputs into the
repository. Localization and identification use normalized exact-set F1;
reason measures ground-truth checkpoint coverage at 70% token overlap.

The output always contains `"official_score": false`. This compatibility score
is a transparent local regression metric, not an official AgenticOpsEval or
RCA100 leaderboard result.

## Ten-run workflow gate

Run two warmups followed by ten measured, complete four-step investigations:

```bash
python3 -m incident_commander.workflow_benchmark \
  --warmups 2 \
  --iterations 10 \
  --p95-limit-ms 30000 \
  --output /tmp/lic-workflow-benchmark.json
```

The command exits non-zero unless every measured workflow completes, invokes
all three distinct read-only tools, produces zero unknown citations, performs
zero remote core requests, and keeps workflow p95 at or below 30 seconds. With
`LIC_ENABLE_LLM=1`, it uses the configured local OpenAI-compatible endpoint;
otherwise it verifies the deterministic degraded path without network access.

## Dataset notice

- AgenticOpsEval paper: *A Multi-Dataset Benchmark for Evaluating LLM Agents in
  Microservice Failure Diagnosis*, arXiv:2606.29193.
- AIOps2025 data: CC BY-NC 4.0.
- RCA100 data: CC BY-NC-SA 4.0.
- Dataset repository: <https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval>

Users must download the dataset separately and comply with its license and
answer-key distribution restrictions. No AgenticOpsEval data is required to run
the application or reproduce the Radeon demo.
