# Agency Source Bundle V2

TODO 0471 is implemented as exactly 2,000 unique, rights-bound source records.
The collector uses official upstream metadata rather than duplicating sample
IDs or vendoring unreviewed binaries:

- 800 CC0/public-domain visual objects from the Art Institute of Chicago;
- 800 CC0 visual objects from the Cleveland Museum of Art;
- 200 family-license-pinned OFL font files;
- 88 commit-pinned ROCm hardware documents;
- 88 commit-pinned Transformers software/doc records;
- 24 prior asset-granular seed records spanning all eight intake families.

No provider exceeds 40% of the bundle. All 2,000 source IDs and all 2,000
provider/asset identities are unique. 1,994 records are training-admitted; six
brand or trademark-bearing references are isolated from training. Raw remote
asset bytes are not vendored.

This closes only the source-bundle requirement. It does not prove the 15M CPT
tokens, 15,000 SFT episodes, preference/trajectory/gold targets, five-person
review, model training, or Agency Corpus V2 freeze.

Re-collect from official APIs and pinned repositories with:

```bash
PYTHONPATH=src python scripts/collect_v10_source_bundle.py --refresh
PYTHONPATH=src python -m unittest -v tests.test_v10_open_materials
```
