> Chinese version: [README.md](README.md)

# MagicBox Data Pipeline Example Bundle (Small, Complete, and Offline-Reproducible)

This is a public example bundle for the `data-gen` collection/export loop. It drives **the exact same export and validation code used in the production pipeline** with **small frozen inputs** and produces **byte-for-byte reproducible** SFT samples. It requires no network access, development-board connection, or teacher-model call.

```bash
npm run check
```

This single command performs the following steps in order:

1. Regenerates the three QA splits and the Agentic sample from `fixtures/` into `out/`;
2. Independently revalidates the JSON Schema, tool-call/result causal chain, unique task IDs, and semantic-group split isolation;
3. Compares the results byte for byte with `expected/` to prove determinism;
4. Runs unit and negative tests (a tampered snapshot, missing board evidence, an orphaned tool result, or an injected secret must all fail closed);
5. Scans the entire tree for secrets and local paths.

Dependencies: Node >= 22.19, Python 3, and `pip install -r requirements.txt` (`jsonschema` only).

## Directory Layout

```text
schemas/     rdk_collection_task.v1 / rdk_collection_record.v1 / rdk_sft_sample.v1 (byte-identical to production)
scripts/     export_qa_dataset.mjs, validate_dataset.py, validate_native_pi_dataset.py (production originals)
             + export_agentic_fixture.mjs, check.mjs, scan_tree.py, python.sh (added for this example)
src/         native_pi_export.mjs (production original: native Pi trajectory -> rdk_sft_sample.v1)
fixtures/    3 real QA tasks + a tiny frozen knowledge snapshot + 1 synthetic native Pi trajectory
expected/    canonical outputs for those inputs (train/validation/test, manifest, and audit reports)
gallery/     4 sanitized artifact examples: 1 each for eligible / needs-review / rejected / synthetic repair
test/        production unit-test originals + negative tests added for this example
source-manifest.json  source, SHA-256, selection rule, and sanitization transform for every file
```

## Data Flow

```text
3 QA tasks + tiny knowledge snapshot ──> QA exporter ──────┐
                                                          ├──> rdk_sft_sample.v1
1 synthetic native Pi trace ──> Agentic exporter ─────────┘
        └──> Schema / causality / secret validation ──> train/validation/test + manifest + audit
```

## Exact Boundary of “Complete Reproduction”

`npm run check` proves the **offline fixture/replay -> export -> validation -> report** loop and its fail-closed behavior on invalid inputs. It does **not** mean that the teacher model was called again, a real development board was connected, or a physical effect was verified. For real collection trajectories and the full dataset, follow the source directory referenced by the repository root README and see `data/releases/`.

- `expected/qa/test.jsonl` is only a format example; it is not presented as a hidden evaluation set.
- `fixtures/native_pi_trace.fixture.json` is synthetic. Its structure matches a real `before_provider_request` capture, but its host and evidence paths are placeholders.
- Rows marked `sanitized` in `gallery/` replace the local absolute project root with `/srv/rdk-data-gen`. The SHA-256 of each original row is recorded in `source-manifest.json` for source verification.
