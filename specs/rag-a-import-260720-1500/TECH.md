# Phase A — Technical Design

- Level: S2
- Status: verified

## 1. Architecture

```
app/rag/
├── __init__.py        # Public exports
├── manifest.py        # SourceFile, ParsedDocument, ImportResult models
├── scanner.py         # scan_source_dir(), is_path_safe()
└── parsers.py         # parse_file() dispatcher + per-format parsers
```

### 1.1 Data Flow

```
data/projects/<id>/source/
        │
        ▼
   scanner.py ──► File list (relative_path, format)
        │
        ▼
   manifest.py ──► SourceFile (sha256, size, mtime, status)
        │
        ▼
   parsers.py  ──► ParsedDocument (chunks with locations)
        │
        ▼
   ImportResult (aggregated success/failure/skipped)
```

### 1.2 Module Boundaries

- `scanner.py`: Filesystem operations only. Produces `Path` objects.
- `manifest.py`: Pure data models and hashing. No filesystem access except reading for SHA-256.
- `parsers.py`: Content extraction only. Consumes `Path`, produces `ParsedDocument`.

## 2. Data Models

### 2.1 SourceFile

```python
class SourceFile(BaseModel):
    relative_path: str
    format: str               # "md"|"txt"|"pdf"|"docx"|"xlsx"|"unsupported"
    sha256: str               # hex digest
    size_bytes: int
    modified_time: float      # os.path.getmtime()
    parse_status: str         # "success"|"failed"|"unsupported"
    error_message: str | None # null on success
```

### 2.2 ContentChunk

```python
class ContentChunk(BaseModel):
    content: str
    relative_path: str
    chunk_index: int
    # Common
    line_start: int | None
    line_end: int | None
    # PDF specific
    page_number: int | None
    # DOCX specific
    heading_path: str | None     # e.g. "1. Introduction > 1.1 Background"
    paragraph_index: int | None
    # XLSX specific
    sheet_name: str | None
    header_columns: list[str] | None
    cell_range: str | None       # e.g. "A2:D2"
    # MD specific
    section_title: str | None
    heading_level: int | None
```

### 2.3 ParsedDocument

```python
class ParsedDocument(BaseModel):
    relative_path: str
    format: str
    chunks: list[ContentChunk]
```

### 2.4 ImportResult

```python
class ImportResult(BaseModel):
    project_id: str
    total_files: int
    success_count: int
    failure_count: int
    skipped_count: int
    files: list[SourceFile]
    parsed: list[ParsedDocument]  # only successfully parsed
```

## 3. Security

### 3.1 Symlink Escape Prevention

```python
def is_path_safe(project_dir: Path, candidate: Path) -> bool:
    """Reject if resolved path falls outside project_dir."""
    try:
        resolved = candidate.resolve()
        project_dir_resolved = project_dir.resolve()
        return resolved.is_relative_to(project_dir_resolved)
    except (OSError, ValueError):
        return False
```

- Uses `Path.resolve()` to follow all symlinks.
- Uses `is_relative_to()` (Python 3.9+) to check containment.
- Rejected files are logged as `parse_status = "failed"` with `error_message = "symlink escape detected"`.

### 3.2 Path Traversal

- All `relative_path` values are computed via `Path.relative_to()`.
- Any path containing `..` components is rejected before resolution.

## 4. Parser Details

### 4.1 Markdown Parser

- Uses stdlib `re` for ATX heading detection.
- Splits content at headings; preceding text becomes a chunk tagged with the heading.
- Lines are counted for `line_start` / `line_end`.

### 4.2 TXT Parser

- Uses stdlib string operations.
- Splits on `\n\n+` to find paragraphs.
- Empty paragraphs are skipped.

### 4.3 PDF Parser

- Uses `pypdf` (PyPDF2 successor) for text extraction.
- Falls back gracefully if `pypdf` is not installed (raises `ImportError` with install hint).
- Iterates `reader.pages`, extracts text per page.

### 4.4 DOCX Parser

- Uses `python-docx`.
- Iterates `doc.paragraphs`, reads `style.name` to detect headings.
- Builds `heading_path` by tracking heading levels (e.g. "1.", "1.1.").

### 4.5 XLSX Parser

- Uses `openpyxl`.
- Iterates `wb.worksheets`, reads rows.
- First non-empty row is treated as header.
- Each subsequent row is a chunk.

## 5. Error Handling

| Scenario | Behavior |
|----------|----------|
| Unsupported format | `parse_status = "unsupported"`, recorded file, no parse attempt |
| Missing optional dependency (pypdf/docx/xlsx) | `parse_status = "failed"`, `error_message` includes install instruction |
| Corrupt file | `parse_status = "failed"`, `error_message` includes traceback summary |
| Symlink escape | `parse_status = "failed"`, `error_message = "symlink escape detected"` |
| Empty file (0 bytes) | `parse_status = "failed"`, `error_message = "empty file"` |

All failures are collected; the import continues.

## 6. Dependencies

Optional (graceful fallback):
- `pypdf` (PDF)
- `python-docx` (DOCX)
- `openpyxl` (XLSX)

To install: `pip install pypdf python-docx openpyxl`
