# Experiment evidence

This directory contains selected historical evidence retained before the AMD
cloud rerun. Machine-specific project roots were replaced with
`<PROJECT_ROOT>`. No API keys, model weights, repository workspaces, gold
patches, or hidden tests are stored here.

- `swebench-pilot-v6/`: latest five-task official-evaluator pilot.
- `api-retry-clean/`: API stability and harness retry check.
- `qwen-code-calibration/`: independent harness compatibility evidence.
- `harness-polyglot/`: summary and report from an earlier functional benchmark;
  noisy raw dependency logs are intentionally omitted.
- `api-capabilities/`: remote endpoint capability probe.
- `official-evaluator-calibration.json`: evaluator plumbing calibration only.

These small pilots are not presented as statistically significant leaderboard
results. The final comparison will be rerun with local inference on AMD Radeon.
