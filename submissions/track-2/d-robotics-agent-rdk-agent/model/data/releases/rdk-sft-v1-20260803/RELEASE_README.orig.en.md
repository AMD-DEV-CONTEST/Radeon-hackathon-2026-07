> Chinese version: [RELEASE_README.orig.md](RELEASE_README.orig.md)

# rdk-sft-v1-20260803 — Unified-format SFT release directory

This directory is the **unified training-data entry point** produced after organizing `data/`: every conversation sample uses the same `rdk_sft_sample.v1` format (see `schema/rdk_sft_sample.v1.schema.json`). All 1755 unique samples pass strict per-sample validation covering top-level fields, message structure, one-to-one correspondence between tool_call and tool messages, and object-valued `arguments`; there are zero duplicate task_id values globally. See `manifest.json` for the machine-readable inventory, including each file's line count, SHA-256, source, and transformation method.

> **2026-08-03 promotion event**: All 848 samples in the original needs-review quarantine were **promoted in full** by owner decision and merged into `agentic/` and `combined/`. The metadata of every promoted sample carries `promoted_from_needs_review: true` together with the original `failed_checks` and `quality_score` markers. **Rollback method**: filtering out rows where `metadata.promoted_from_needs_review == true` restores the curated 327-sample set. Of the promoted samples, 428 have evidence-related failures on record (unsupported inference / unsourced numbers / ssh contract); training configurations may apply additional filtering by `failed_checks`.

## Directory structure

```text
rdk-sft-v1-20260803/
├── manifest.json                  # Machine-readable inventory (line count / sha256 / source / transformation)
├── schema/rdk_sft_sample.v1.schema.json
├── agentic/                       # Real-board Agentic, 1175 samples (946/116/113)
│                                  #   = curated 327 + promoted 848 (with promoted markers)
├── qa/                            # Tool-free QA, 300 samples (240/30/30)
├── combined/                      # Combined training entry = agentic + qa, 1475 samples (1186/146/143)
├── repair-synthetic/              # synthetic repair, 280 samples, stored separately
│   ├── stage2_train.jsonl (96)   ├── stage2_validation.jsonl (24)
│   ├── stage3_train.jsonl (128)  └── stage3_validation.jsonl (32)
└── needs-review/                  # Audit copy: 848 samples promoted; originals and quality details retained here
    ├── needs_review.jsonl                      # ⚠️ Already merged into agentic/; do not double-count
    └── quality_scores.needs_review.jsonl       # Per-sample quality score and failed_checks
```

## Usage

- **Train directly**: use `combined/train.jsonl` + `combined/validation.jsonl`; alternatively, use `agentic/` and `qa/` separately as needed.
- **Use only the curated set**: filter out rows where `metadata.promoted_from_needs_review == true` (this restores the pre-promotion real-data entry point of 627 samples).
- **Add synthetic repair**: explicitly append `repair-synthetic/*_train.jsonl` in the training configuration. These samples have `metadata.is_synthetic=true` and can be filtered at any time.
- **Do not use**: `needs-review/` (an audit copy whose contents are already present in `agentic/`), or `rejected.jsonl` and `raw_trajectories.jsonl` from the source dataset (audit artifacts).

## Data sources and transformations

| Output | Source (relative to data/) | Transformation |
| --- | --- | --- |
| `agentic/*` | v2 dataset `{train,validation,test}.jsonl` + `needs_review.jsonl` | Curated portion retained byte-for-byte; promoted portion receives 6 additional metadata marker keys |
| `qa/*` | `sft/magicbox-no-tool-qa-300-20260731-v1/{train,validation,test}.jsonl` | Retained byte-for-byte |
| `combined/*` | agentic + qa concatenated by split | Concatenation only |
| `repair-synthetic/stage2_*` | stage2-repair-v5 `repair_*.jsonl` | `schema_version` normalization |
| `repair-synthetic/stage3_*` | stage3-repair-v7 `repair_*.jsonl` | `schema_version` normalization |
| `needs-review/*` | v2 dataset `needs_review.jsonl` / `quality_scores.jsonl` (filtered) | Audit copy retained unchanged |

The following keys were added to the metadata of promoted samples: `promoted_from_needs_review`, `original_quality_status`, `quality_score`, `failed_checks`, `promoted_at`, and `promotion_basis`. Messages, tools, and outcome fields were left unchanged field by field, as verified by sampled assertions. Repair normalization is unchanged from before: only `schema_version` plus 3 provenance markers.

## Boundary statement

- `repair-synthetic/` is synthetic native Pi replay, **not** a real-board trajectory. It is excluded from `combined/`; whether it is used for training is an explicit training-configuration decision.
- The 848 promoted samples were not manually reviewed one by one; their quality-control `failed_checks` remain recorded. If training or evaluation behaves abnormally, first roll back using the markers or filter by `failed_checks` strata.
- validation/test contain 84/80 promoted samples respectively. For a "curated-only" evaluation set, filter by the markers.
- stage3 repair includes v7; the same-set v6 has been superseded. All source-dataset directories remain in their original locations, and the absolute-path provenance in sample metadata remains resolvable.
