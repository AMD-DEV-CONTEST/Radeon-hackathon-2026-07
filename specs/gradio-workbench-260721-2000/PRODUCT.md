# Phase D Minimal Workbench

## Background

The controlled RAG-to-report workflow is verified by scripts and APIs. A demo
user still needs terminal commands to create a project, place files safely,
start a run, inspect evidence, and download output.

## User-visible behavior

- A single Gradio page creates or selects a project and uploads reference files
  plus one CSV/XLSX task list.
- The page starts the approved report run, shows its final step status and
  renders task status, explanation, and retrieved source evidence.
- Users download the Markdown report, risk CSV, and next-week plan from the
  controlled run artifacts.

## Non-goals

- No login, multi-user collaboration, background queue, or task-file rewrite.
- The browser never receives arbitrary host filesystem access.
