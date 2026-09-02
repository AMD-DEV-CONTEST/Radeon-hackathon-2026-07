# Phase A — Test Report

## 1. Test Cases

### 1.1 test_scan_source_dir

| ID | Description | Expected |
|----|-------------|----------|
| A-01 | Scan directory with mixed formats | Returns correct file list, all formats detected |
| A-02 | Scan empty source directory | Returns empty list, no errors |
| A-03 | Symlink pointing outside project dir | File rejected, error recorded |
| A-04 | Unsupported extension (.bin, .json) | File recorded as "unsupported", not parsed |
| A-05 | Source directory does not exist | Raises clear error |

### 1.2 test_file_manifest

| ID | Description | Expected |
|----|-------------|----------|
| A-06 | Compute SHA-256 for a known file | Matches expected digest |
| A-07 | File with correct size and mtime | Fields match `os.stat()` |
| A-08 | Non-existent file path | Raises `FileNotFoundError` |

### 1.3 test_parse_markdown

| ID | Description | Expected |
|----|-------------|----------|
| A-09 | Single heading + text | 1 chunk with correct section_title |
| A-10 | Multiple headings (H1, H2, H3) | Correct chunks, heading levels preserved |
| A-11 | Text before first heading | Chunk with section_title=None |
| A-12 | Empty markdown file | Returns ParsedDocument with 0 chunks |

### 1.4 test_parse_txt

| ID | Description | Expected |
|----|-------------|----------|
| A-13 | Paragraphs separated by blank lines | Correct chunk count and line ranges |
| A-14 | Single paragraph | 1 chunk |
| A-15 | Consecutive blank lines | Skipped, same paragraph count |

### 1.5 test_parse_pdf (requires pypdf)

| ID | Description | Expected |
|----|-------------|----------|
| A-16 | Single-page PDF | 1 chunk, page_number=1 |
| A-17 | Multi-page PDF | N chunks, correct page numbers |
| A-18 | pypdf not installed | Clear error message with install hint |

### 1.6 test_parse_docx (requires python-docx)

| ID | Description | Expected |
|----|-------------|----------|
| A-19 | DOCX with headings and paragraphs | Correct heading_path values |
| A-20 | DOCX without headings | All chunks have heading_path=None |
| A-21 | python-docx not installed | Clear error message |

### 1.7 test_parse_xlsx (requires openpyxl)

| ID | Description | Expected |
|----|-------------|----------|
| A-22 | XLSX with single sheet, headers + data | Correct sheet_name, header_columns, cell_range |
| A-23 | Multi-sheet XLSX | Correct number of sheets parsed |
| A-24 | openpyxl not installed | Clear error message |

### 1.8 test_error_resilience

| ID | Description | Expected |
|----|-------------|----------|
| A-25 | Import with one corrupt file + valid files | Corrupt file fails; valid files succeed; total matches |
| A-26 | All files unsupported | success_count=0, skipped_count=N, failure_count=0 |

### 1.9 test_import_integration

| ID | Description | Expected |
|----|-------------|----------|
| A-27 | Full import with MD + TXT + (optionally PDF/DOCX/XLSX) | Correct ImportResult with all stats |

## 2. How to Run

```bash
pytest tests/test_rag_import.py -v
```

## 3. Coverage Target

- `app/rag/scanner.py`: >90%
- `app/rag/parsers.py`: >85%
- `app/rag/manifest.py`: >95%
