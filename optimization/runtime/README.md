# SmolVLA ROCm runtime backends

This directory contains only the runtime code used by the submitted primary results:

- `backends.py`: eager, HIP Graph and targeted-compile integration;
- `benchmark_full_inference.py`: real full `sample_actions()` benchmark;
- `validate_full_inference.py`: fixed and changed-input correctness checks;
- `summarize_results.py`: JSON to CSV/Markdown summary;
- `summarize_closed_loop_ab.py`: paired closed-loop result summary.

Training data and checkpoints are external artifacts. After downloading them according to
`artifacts/manifest.json`:

Recommended launchers from the repository root:

```bash
bash scripts/benchmark_rocm_backends.sh
bash scripts/validate_rocm_backends.sh
bash scripts/evaluate_rocm_closed_loop.sh
```

Set `DRY_RUN=1` to print commands without loading the model. Set
`CANDIDATE=targeted-compile` for the compile closed-loop A/B run. Outputs are written
under `reproductions/` and do not overwrite the frozen submission results.

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export POLICY=artifacts/models/smolvla_fruit_pick_dr_600ep
export DATASET=artifacts/datasets/fruit_pick_dr_600ep

python -m optimization.runtime.benchmark_full_inference \
  --backend hip-graph --policy-path "$POLICY" --dataset-root "$DATASET"

python -m optimization.runtime.validate_full_inference \
  --backend hip-graph --policy-path "$POLICY" --dataset-root "$DATASET"
```

Targeted compile is faster in the saved benchmark but fails the strict numerical check.
HIP Graph is the primary deployment candidate. See `docs/REPRODUCIBILITY.md` for the full
commands and expected values.
