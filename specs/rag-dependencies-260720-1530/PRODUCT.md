# Phase A Reproducible Parser Dependencies

## Goal

Make the already-implemented Phase A document importer reproducible from a
clean project installation for all declared formats: PDF, DOCX, and XLSX in
addition to the stdlib Markdown and TXT parsers.

## Acceptance criteria

- A normal package install includes `pypdf`, `python-docx`, and `openpyxl`.
- A development install includes `reportlab`, which is required only by the
  Phase A verification-data generator.
- The full Phase A verification script completes in a fresh isolated virtual
  environment without manually installing packages.
- A regression test prevents these dependency declarations from being removed.
