# Evaluation Artifacts

This directory stores compact, structured evidence files:

~~~text
environment.remote.json
dataset_manifest.json
dataset_validation.json
training.json
evaluation.json
evaluation.csv
evaluation_20k_banana_success.json
evaluation_20k_banana_success.csv
evaluation_20k_banana_success.summary.md
probe_20k_lemon_success.json
world_success_examples.json
interrupt_evaluation.json
interrupt_evaluation.csv
interrupt_evaluation.summary.md
summary.md
SHA256SUMS
~~~

The canonical release files are populated in this repository:

- `dataset_manifest.json` / `dataset_validation.json`: Physical-2K coverage and strict-physics validation;
- `training.json`: final Physical-2K continuation and public checkpoint identity;
- `evaluation.json` / `evaluation.csv` / `summary.md`: all 100 disjoint-seed episodes, including failures;
- `evaluation_20k_banana_success.*`: standard fixed-seed 20K banana replay evidence with release verification;
- `probe_20k_lemon_success.json`: 20K lemon replay evidence with scene and episode seeds recorded separately;
- `world_success_examples.json`: certificate, source interval, episode, seed, and checksum mapping for all 20 task examples;
- `environment.remote.json`: exact Radeon/ROCm evaluation environment;
- `SHA256SUMS`: hashes for the compact evidence, report, cards, and published website video.

Large dataset shards and checkpoints remain on Hugging Face and can be retrieved with
`python -m radeonvla.download_artifacts`; no private repository is required. The 200-second
English release video is tracked below `website/public/videos/` so GitHub Pages can serve it directly.

The final `evaluation.json` validates against `evaluation.schema.json`. `evaluate.py`
automatically writes JSON, flattened CSV, and a Markdown summary while hashing the actual
checkpoint tree. Technical-report tables use these immutable results. The public model repository
also carries the same evidence at revision `1ea32da3d59ce0905d0f1331bc3c6643e42beb7e`.
