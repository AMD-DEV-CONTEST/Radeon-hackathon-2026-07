# Radeon Cloud Evidence - 2026-08-02

These files were copied from the competition Radeon instance before teardown.
They preserve the raw, non-reproducible timing and inference evidence behind the
summaries in `PolicySeal_Specification_EN.md` and
`radeon-benchmark-results.json`.

## Files

| File | Purpose |
| --- | --- |
| `semantic-evaluation.json` | Final live Qwen3-8B evaluation over 60 frozen semantic snippets |
| `experiment-a-batching.json` | Raw Experiment A strategies and ten warm runs |
| `experiment-b-cascade.json` | Raw Experiment B strategies and ten warm runs |
| `runtime-validation-post-run.json` | Post-run Radeon, ROCm, vLLM, model, and model-file validation |
| `benchmark-output.txt` | Official benchmark command output, including the active three-service runtime validation |
| `benchmark.exit` | Benchmark process exit status (`0`) |
| `source-commit` | Source commit used by the benchmark |
| `vllm-startup-ms` | Measured vLLM cold-start duration in milliseconds |
| `SHA256SUMS` | Integrity hashes for the copied evidence files |

The final combined report remains at `docs/submission/radeon-benchmark-results.json`.
The two standalone experiment JSON files are retained even though their content
is embedded unchanged in that report, so the original cloud outputs remain
available independently.

The complete cloud `artifacts/`, `var/radeon/`, and project source snapshot is
also retained locally under `artifacts/cloud-backup-2026-08-02/`. That larger
backup contains generated QA images and service logs and is intentionally not
part of the public submission package. Model weights and dependency caches are
not backed up; the tracked model manifest and `ops/radeon/download-model.sh`
make them reproducibly downloadable.
