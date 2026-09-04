# Synthetic Demo Data

The frozen P0 corpus contains 15 synthetic source files: three polished hero
documents and four edge files for each supported format. The edge corpus covers
safe, approval, Block, and processing-failure behavior.

Regenerate and verify the byte-stable corpus with:

```bash
make demo-data
.venv/bin/python -m pytest tests/demo_data -v
```

`source_manifest.json` records every SHA-256 and size. Never add real company
information, personal data, credentials, or customer files. Values that look
sensitive are explicitly fictional leakage-test markers under reserved example
domains and documentation address ranges.
