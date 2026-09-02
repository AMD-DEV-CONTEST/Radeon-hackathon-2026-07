# RadeonX Cloud Results (2026-08-04)

This report records the first reproducible RadeonX Cloud run of Radeon Code Agent.
It is deliberately hardware-specific: **AMD Radeon Graphics (gfx1100), 51.52 GB
VRAM, RadeonX Cloud**. It is not an MI300X result.

## Frozen runtime

- Model: `Qwen3-14B BF16` (`Qwen/Qwen3-14B`, local checkpoint)
- ROCm: 7.2.2; PyTorch: 2.11.0+rocm7.2.2; vLLM: 0.25.1
- Endpoint: `http://127.0.0.1:8000/v1` (loopback only)
- Context: 32,768; single sequence; GPU memory utilization 0.90
- KV cache: `int8_per_token_head`
- Tool parser: `hermes` (the `qwen3_coder` parser emitted XML content rather than
  native tool calls on this checkpoint)
- Structured actions: vLLM xgrammar (`J3`)
- Prefix caching: enabled for the final runtime after the A/B test

## Service acceptance

The final service passed 10/10 automatic tool calls, 20/20 structured-action
schema checks and 30/30 stability requests, with no OOM or server crash. The
10-request inference probe measured TTFT p50 103.97 ms, TTFT p95 137.38 ms,
decode p50 25.66 tokens/s, and VRAM usage about 46.7 GB of 51.52 GB.

Prefix caching materially reduced prefill latency. In the fixed single-request
probe, TTFT p50 changed from 3,976 ms to 219 ms at 4K input and from 43,568 ms
to 562 ms at 16K input (off to on, respectively). Decode throughput was
unchanged at about 24--21 tokens/s, so prefix caching is enabled for the Agent
run.

## Five-task pilot

The pilot used the fixed five public SWE-bench Lite tasks. Each variant used the
same model, task order, local workspace policy and 12-turn/30-tool/15-minute
budget. Numbers below are Agent-level diagnostics; official scores are computed
only from frozen patches by the local Docker evaluator.

| Variant | Change | Non-empty patches | JSON valid | Mean tokens | Mean wall ms |
|---|---|---:|---:|---:|---:|
| B0 | mini-SWE C0/J0/A0/V0 | 0/5 | n/a | 12,311 | 20,825 |
| B1 | Aider Repo Map | 0/5 | n/a | 42,881 | 33,431 |
| B2 | static RepoGraph | 1/5 | n/a | 33,998 | 27,805 |
| B3 | budget controller A1 | 0/5 | n/a | 7,454 | 10,933 |
| B4 | verifier + one repair | 0/5 | n/a | 9,664 | 11,685 |
| B5 | xgrammar JSON Action | 1/5 | 50/50 | 37,635 | 88,988 |

The RepoGraph and J3 pilot each had one non-empty patch. The local official
SWE-bench evaluator resolved 1/5 for each of those two frozen patch sets; the
other tasks had empty patches. This is a five-task pilot, not a statistically
significant benchmark.

## Fixed ten-task confirmation

The confirmation manifest is frozen with seed `20260804` and is stored without
gold fields on the Agent host. B0 completed all ten tasks with 0/10 non-empty
patches. The selected combination B6 is `static RepoGraph + J3 xgrammar +
V1R1` and completed all ten tasks with 2/10 non-empty patches. Every B6 response
was schema-valid (115/115); no API or integrity failures occurred. It used
578,593 total tokens (mean 57,859) and mean wall time 85.9 s per task.

The first five tasks were rerun with seed 1. B0 again produced 0/5 patches;
B6 produced 1/5 patches. The seed-1 patch applied but failed all three
FAIL_TO_PASS tests, so the fixed-task stability result is `pass@2 = 0/5` and
`pass^2 = 0/5` for Full Resolve. (The seed-0 run also had no resolved task in
this first-five subset.)

For the full ten-task B6 set, the local evaluator resolved
`scikit-learn__scikit-learn-12471`. The other non-empty patch,
`scikit-learn__scikit-learn-25638`, hit an evaluator infrastructure error:
the legacy test image's pip does not accept `--no-use-pep517`. Thus the
intent-to-run result is 1/10 Full Resolve, with one evaluator error and eight
empty patches; among the one non-error non-empty patch, the result is 1/1.
The infrastructure error is retained and is not presented as model failure.

## Harness calibration

Qwen Code 0.21.0 was calibrated on two tasks but excluded from the ranking. Its
Linux sandbox requires Docker or Podman; the RadeonX instance has neither, so it
produced no model/tool events. This is an infrastructure incompatibility, not a
model-quality score. No OpenHands result is substituted for it.

## Reproducibility and integrity

The Agent host received only public task fields and repository contents. Gold
patches, test patches and official test IDs were retained on the local evaluator
side and never synchronized to RadeonX. Cloud execution is command-level
isolation for this no-Docker instance; it is not described as a container
sandbox. All artifacts under `runs/amd-cloud-*` include the run configuration,
public manifest, trajectories, patches, token usage, latency and integrity
events.
