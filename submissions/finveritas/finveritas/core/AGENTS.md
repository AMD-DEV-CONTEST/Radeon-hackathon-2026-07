# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project overview
This repo is a small Python package that ingests Bloomberg-exported financial-statement PDFs and emits one structured JSON file per company.

Pipeline (high level):
1. `src/extractor.py` uses `pdfplumber` to extract page text and table grids.
2. `src/parser.py` turns extracted content into structured time-series data (detects statement type, currency, periods, and maps line-items to canonical keys).
3. `src/builder.py` aggregates multiple statements per company and writes a JSON payload per company.
4. `src/main.py` is the CLI entry point that wires everything together.

## Common commands
### Set up a local virtualenv
```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the ingestion pipeline (directory of PDFs → JSON files)
Default directories are `input_pdfs/` and `output/`:
```sh
python3 -m src.main
```

Custom input/output directories:
```sh
python3 -m src.main --input path/to/pdfs --output path/to/output
```

Verbose logging:
```sh
python3 -m src.main --verbose
```

### Process a single PDF
The CLI scans a directory non-recursively for `*.pdf`/`*.PDF` files (see `discover_pdfs()` in `src/main.py`). To run against a single file, put it alone in a directory:
```sh
mkdir -p /tmp/one_pdf
cp path/to/file.pdf /tmp/one_pdf/
python3 -m src.main --input /tmp/one_pdf --output output
```

### Tests / linting
No test runner or lint/format tooling is configured in this repository (no `tests/`, `pyproject.toml`, `pytest.ini`, etc. found). If you add one, update this file with the new canonical commands.

## Architecture notes (where to look)
### Key modules
- `src/main.py`: CLI + orchestration.
  - Finds PDFs in the input directory.
  - For each PDF: `extract_pdf(...)` → `parse_statement(...)`.
  - After collecting parsed statements: `aggregate_and_write(...)`.

- `src/extractor.py`: PDF → `PDFContent`.
  - `PDFContent.pages` contains `PageData` entries (page text + extracted tables).
  - Uses two sets of `pdfplumber` table settings: strict line-based first, then a text-based fallback.

- `src/parser.py`: `PDFContent` → `ParsedStatement`.
  - Header parsing: company name, currency, statement type (Income Statement vs Balance Sheet).
  - Period normalization: converts many header formats into `YYYY-QN` / `YYYY-FY` via `normalise_period()`.
  - Data extraction:
    - Preferred path: `_parse_from_tables(...)` reads `pdfplumber` tables.
    - Fallback path: `_parse_from_text(...)` splits lines on 2+ spaces.
  - Label mapping delegates to `src/mapper.py`.

- `src/mapper.py`: canonicalization.
  - `detect_statement_type(...)` identifies IS vs BS based on header patterns.
  - `resolve_field(...)` maps Bloomberg line-item labels to canonical keys used in the JSON output.

- `src/builder.py`: aggregation + output schema.
  - Groups parsed statements by normalized company name.
  - Merges all `(period, value)` observations per canonical field.
  - Ensures a small set of required fields exist in output (empty arrays if missing).

### Output schema (what gets written)
`src/builder.py` writes one `*.json` per company to the output directory with the shape:
- `entity`: metadata (`entity_id`, `source`, `currency`, `source_files`)
- `time_series`: mapping of canonical field key → list of `{ "period": ..., "value": ... }`

If a new field should appear in outputs, it must be added to `src/mapper.py` (label mapping) and will then flow through the parser/builder automatically.