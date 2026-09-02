# Controlled Report Artifact Bundle

## Background

The end-to-end project run currently writes only a source-linked Markdown
report. Phase C already produces a risk list and a next-week plan, but those
results are not yet available as controlled run artifacts.

## User-visible behavior

- A completed report run produces three download-ready, read-only artifacts:
  a Markdown project report, a CSV risk list, and a Markdown next-week plan.
- Every artifact is stored below the configured output root for the same
  project and run. The API exposes relative paths only.
- Risk and plan content derives from the same evaluated tasks as the report;
  no original task file is changed.

## Non-goals

- This change does not edit, overwrite, or synchronize the user's task CSV or
  XLSX file.
- This change does not add a UI or arbitrary output paths.
