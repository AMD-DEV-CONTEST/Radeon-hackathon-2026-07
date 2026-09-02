# Phase A — Document Import & Parsing

## 1. Overview

Phase A implements the document import pipeline. It scans a project's `source/` directory, validates file safety (no symlink escapes), computes file metadata (SHA-256, size, modification time), and parses supported document formats into structured chunks with citation-level location tracking.

### 1.1 Problem Statement

Users need to import mixed-format project materials (reports, spreadsheets, meeting notes) into the RAG system. The import must be secure, resilient to corrupt files, and produce structured output that allows downstream retrieval to cite exact locations (page, heading, sheet, etc.).

### 1.2 Target Users

Application developers integrating the RAG pipeline; end users importing project documents.

## 2. Supported Formats

| Format | Extension | Parser | Location Detail |
|--------|-----------|--------|-----------------|
| Markdown | `.md` | `parse_markdown` | Section headings, line range |
| Plain Text | `.txt` | `parse_txt` | Paragraph boundaries, line range |
| PDF | `.pdf` | `parse_pdf` | Page number |
| Word | `.docx` | `parse_docx` | Heading path, paragraph index |
| Excel | `.xlsx`, `.xlsm` | `parse_xlsx` | Sheet name, header columns, cell range |

## 3. Features

### 3.1 Source Directory Scanning

- Scan `data/projects/<project_id>/source/` recursively.
- Accept only regular files (no directories, no special files).
- Reject symlinks that resolve outside the project directory.
- Reject paths that escape the project root via relative traversal (`../`).
- Filter by supported extensions; record unsupported formats as skipped.

### 3.2 File Manifest

For every scanned file, record:

| Field | Description |
|-------|-------------|
| `relative_path` | Path relative to project root |
| `format` | Detected format string |
| `sha256` | Hex-encoded SHA-256 digest |
| `size_bytes` | File size in bytes |
| `modified_time` | POSIX timestamp of last modification |
| `parse_status` | `"success"`, `"failed"`, or `"unsupported"` |
| `error_message` | Error detail (null on success) |

### 3.3 Structured Parsing

Each supported format is parsed into `ContentChunk` objects:

- **Markdown**: Split by ATX headings (`#`, `##`, ...). Each section becomes a chunk tagged with `section_title`.
- **TXT**: Split by blank-line-delimited paragraphs. Each paragraph becomes a chunk tagged with `line_start` / `line_end`.
- **PDF**: Each page extracted as a separate chunk tagged with `page_number`.
- **DOCX**: Paragraphs extracted with heading style detection. Heading paragraphs recorded with `heading_path` and `paragraph_index`.
- **XLSX**: Each sheet extracted. First row treated as header; data rows as chunks tagged with `sheet_name`, `header_columns`, and `cell_range`.

### 3.4 Error Resilience

- A single corrupt file MUST NOT crash the entire import.
- Parse failures are recorded in the manifest with `parse_status = "failed"` and a descriptive `error_message`.
- The import result clearly separates success and failure lists.

### 3.5 Citation Location

Every `ContentChunk` carries enough metadata to reconstruct a precise citation:

- PDF → "file.pdf, page 3"
- DOCX → "report.docx, Chapter 1 > Section 1.1, paragraph 5"
- XLSX → "budget.xlsx, Sheet 'Q1', rows A–D"
- MD → "notes.md, ## Meeting Notes, lines 10–15"
- TXT → "log.txt, lines 3–6"

## 4. Acceptance Criteria

1. Import demo data with at least one file of each supported format.
2. `ImportResult` lists all files with `parse_status` and any errors.
3. Parsed chunks from a PDF carry correct `page_number` values.
4. Parsed chunks from a DOCX carry correct `heading_path` where applicable.
5. Parsed chunks from an XLSX carry correct `sheet_name`, `header_columns`, and `cell_range`.
6. A symlink pointing outside the project directory is rejected (not followed).
7. A corrupt/broken file results in `parse_status = "failed"` without interrupting other files.

## 5. Out of Scope

- Chunk splitting strategies for retrieval (Phase B).
- Embedding generation or vector store (Phase B).
- Gradio UI for import (Phase D).
- RAG query pipeline (Phase B/C).
