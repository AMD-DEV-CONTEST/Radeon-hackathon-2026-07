# External artifacts

Training data and checkpoints are intentionally excluded from Git. Their logical target
locations, sizes and hashes are recorded in `manifest.json`.

Before model evaluation, download and extract them to:

```text
artifacts/datasets/fruit_pick_dr_600ep/
artifacts/models/smolvla_fruit_pick_dr_600ep/
artifacts/models/plum_residual_sac_lift/last.pt
```

The `download_url` fields are currently `null`; publishing stable URLs is a release blocker.
Do not claim standalone reproducibility until those URLs are filled and verified on a clean machine.
