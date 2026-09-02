# Attribution

This repository is original work by Hao Miao (Copyright (c) 2026) with one
documented adaptation:

- `mini_swe_runner.py` was adapted from the MIT-licensed
  [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
  mini-SWE runner. The standalone runtime and Track 2 experiment modules in
  this repository remove the dependency on the rest of Hermes Agent; the
  controller loop, budgets, action protocol, context wiring, verifier, and
  product CLI are original additions.

Original modules include (not exhaustive): `radeon_fix.py`, `track2_demo.py`,
`track2_context_extract.py`, `track2_harness_benchmark.py`,
`track2_swebench_harness.py`, `track2_qwen_code.py`, `swe_experiments/`,
`scripts/`, `docs/`, `examples/`, and the test suite.

The project integrates or evaluates the following separately licensed open
source projects without vendoring their repositories:

- mini-SWE-agent
- Aider Repo Map
- RepoGraph
- SWE-bench
- Qwen Code

Their exact revisions are recorded in `scripts/bootstrap_benchmarks.sh`.
