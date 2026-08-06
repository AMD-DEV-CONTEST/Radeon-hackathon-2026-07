# Open Materials V1

This intake seed closes the source-capture gap for TODO 0463–0470 without
claiming that Agency Corpus V2 is complete. It records three immutable,
license-evidenced locators for each of eight material kinds: hardware,
software, brand, product visual, scene visual, video, font, and audio.

The gate separates copyright permission from other rights. Public visibility
is never treated as a license. Wikimedia media must carry asset-granular
license metadata and an upstream content SHA-1. GitHub sources are pinned to an
exact commit and path. Fonts are pinned to a family-specific OFL text.

Brand assets and product photographs containing third-party marks are retained
only as reference/audit material. They do not enter training even when the
underlying file is CC0. The Linux Foundation trademark policy does not become
a copyright training license merely because its artwork repository is public.

The intake seed remains a 24-record eight-kind gate. Agency Source Bundle V2
now expands it to exactly 2,000 rights-bound records with two museum sources
and three pinned GitHub sources. No remote asset bytes are vendored, no model
was trained from these records, and the Agency Corpus V2 freeze remains false.
The scaled training and gold-review requirements remain open.

Reproduce the deterministic ledger with:

```bash
PYTHONPATH=src python scripts/build_v10_open_materials.py
PYTHONPATH=src python -m unittest -v tests.test_v10_open_materials
```
