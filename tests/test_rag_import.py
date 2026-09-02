"""Tests for Phase A — Document Import & Parsing (app/rag/)."""

import hashlib
from pathlib import Path

import pytest

from app.rag.manifest import (
    compute_sha256,
    build_source_file,
)
from app.rag.scanner import scan_source_dir, scan_source_entries, is_path_safe, SUPPORTED_EXTENSIONS
from app.rag.parsers import (
    parse_markdown,
    parse_txt,
    parse_file,
    import_project,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str) -> Path:
    """Write content to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_project(project_id: str, files: dict[str, str], *, base_dir: Path) -> Path:
    """Create a project source tree under base_dir/data/projects/<id>/source/."""
    source_dir = base_dir / "data" / "projects" / project_id / "source"
    for rel_path, content in files.items():
        _make_file(source_dir / rel_path, content)
    return source_dir


# ---------------------------------------------------------------------------
# manifest.py tests
# ---------------------------------------------------------------------------


class TestComputeSha256:
    """Tests for compute_sha256."""

    def test_known_content(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        digest = compute_sha256(f)
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert digest == expected

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        digest = compute_sha256(f)
        expected = hashlib.sha256(b"").hexdigest()
        assert digest == expected

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            compute_sha256(tmp_path / "nonexistent.txt")


class TestBuildSourceFile:
    """Tests for build_source_file."""

    def test_basic_metadata(self, tmp_path: Path):
        f = tmp_path / "doc.md"
        f.write_text("# Hello\nworld", encoding="utf-8")
        sf = build_source_file(f, "sub/doc.md", "md")
        assert sf.relative_path == "sub/doc.md"
        assert sf.format == "md"
        assert sf.sha256 == compute_sha256(f)
        assert sf.size_bytes == f.stat().st_size
        assert sf.modified_time == pytest.approx(f.stat().st_mtime, abs=1)
        assert sf.parse_status == "pending"
        assert sf.error_message is None

    def test_unsupported_format(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00")
        sf = build_source_file(f, "data.bin", "unsupported")
        assert sf.parse_status == "unsupported"

    def test_custom_sha256(self, tmp_path: Path):
        f = tmp_path / "note.txt"
        f.write_text("abc")
        sf = build_source_file(f, "note.txt", "txt", sha256="deadbeef")
        assert sf.sha256 == "deadbeef"


# ---------------------------------------------------------------------------
# scanner.py tests
# ---------------------------------------------------------------------------


class TestIsPathSafe:
    """Tests for is_path_safe."""

    def test_file_inside_project(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        f = project / "file.txt"
        f.write_text("safe")
        assert is_path_safe(project, f) is True

    def test_file_outside_project(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("bad")
        assert is_path_safe(project, outside) is False

    def test_nonexistent_file(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        f = project / "ghost.txt"
        assert is_path_safe(project, f) is True  # resolve() works even if missing

    def test_symlink_escape(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "source").mkdir()
        outside = tmp_path / "escape.txt"
        outside.write_text("danger")
        symlink = project / "source" / "link.txt"
        try:
            symlink.symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation requires elevated privileges on this OS")
        assert is_path_safe(project, symlink) is False

    def test_project_itself(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        assert is_path_safe(project, project) is True

    def test_symlink_stays_inside(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "source").mkdir()
        target = project / "source" / "real.txt"
        target.write_text("ok")
        symlink = project / "link.txt"
        try:
            symlink.symlink_to(target)
        except OSError:
            pytest.skip("Symlink creation requires elevated privileges")
        assert is_path_safe(project, symlink) is True


class TestDetectFormat:
    """Tests for extension-to-format mapping."""

    def test_all_supported_extensions(self):
        assert SUPPORTED_EXTENSIONS[".md"] == "md"
        assert SUPPORTED_EXTENSIONS[".txt"] == "txt"
        assert SUPPORTED_EXTENSIONS[".pdf"] == "pdf"
        assert SUPPORTED_EXTENSIONS[".docx"] == "docx"
        assert SUPPORTED_EXTENSIONS[".xlsx"] == "xlsx"
        assert SUPPORTED_EXTENSIONS[".xlsm"] == "xlsx"

    def test_unsupported_extension(self):
        assert ".json" not in SUPPORTED_EXTENSIONS
        assert ".bin" not in SUPPORTED_EXTENSIONS


class TestScanSourceDir:
    """Tests for scan_source_dir."""

    def test_mixed_formats(self, tmp_path: Path):
        _make_project("p1", {
            "readme.md": "# Title\nContent",
            "notes.txt": "plain text",
            "data.bin": "binary",
        }, base_dir=tmp_path)
        results = scan_source_dir("p1", base_dir=tmp_path)
        rel_paths = [r[1] for r in results]
        assert "source/readme.md" in rel_paths
        assert "source/notes.txt" in rel_paths
        assert len(results) == 2  # .bin is unsupported

    def test_empty_directory(self, tmp_path: Path):
        source_dir = tmp_path / "data" / "projects" / "empty" / "source"
        source_dir.mkdir(parents=True)
        results = scan_source_dir("empty", base_dir=tmp_path)
        assert results == []

    def test_nonexistent_directory(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            scan_source_dir("noexist", base_dir=tmp_path)

    def test_rejects_project_id_path_traversal(self, tmp_path: Path):
        outside = tmp_path / "outside" / "source"
        outside.mkdir(parents=True)
        (outside / "secret.md").write_text("# private", encoding="utf-8")

        with pytest.raises(ValueError, match="project_id"):
            scan_source_dir("../../outside", base_dir=tmp_path)

    def test_detailed_scan_records_unsupported_file(self, tmp_path: Path):
        _make_project("p-audit", {"known.md": "# known", "unknown.json": "{}"}, base_dir=tmp_path)
        results = scan_source_entries("p-audit", base_dir=tmp_path)

        unsupported = next(entry for entry in results if entry.relative_path == "source/unknown.json")
        assert unsupported.format == "unsupported"
        assert unsupported.error_message is None

    def test_nested_directories(self, tmp_path: Path):
        _make_project("p2", {
            "a/one.md": "# One",
            "a/b/two.txt": "two",
        }, base_dir=tmp_path)
        results = scan_source_dir("p2", base_dir=tmp_path)
        rel_paths = [r[1] for r in results]
        assert "source/a/one.md" in rel_paths
        assert "source/a/b/two.txt" in rel_paths


# ---------------------------------------------------------------------------
# parsers.py tests — Markdown
# ---------------------------------------------------------------------------


class TestParseMarkdown:
    """Tests for parse_markdown."""

    def test_single_heading(self, tmp_path: Path):
        f = _make_file(tmp_path / "doc.md", "# Hello\n\nWorld content.")
        doc = parse_markdown(f)
        assert doc.format == "md"
        assert len(doc.chunks) == 1
        assert doc.chunks[0].section_title == "Hello"
        assert doc.chunks[0].heading_level == 1
        assert "World content" in doc.chunks[0].content

    def test_multiple_headings(self, tmp_path: Path):
        content = "# H1\n\nintro\n\n## H2-A\n\nbody A\n\n### H3\n\ndeep\n\n## H2-B\n\nbody B\n"
        f = _make_file(tmp_path / "doc.md", content)
        doc = parse_markdown(f)
        titles = [c.section_title for c in doc.chunks]
        assert "H1" in titles
        assert "H2-A" in titles
        assert "H3" in titles
        assert "H2-B" in titles

    def test_text_before_first_heading(self, tmp_path: Path):
        content = "preamble text\n\n# Main Title\n\nbody\n"
        f = _make_file(tmp_path / "doc.md", content)
        doc = parse_markdown(f)
        assert doc.chunks[0].section_title is None
        assert "preamble" in doc.chunks[0].content

    def test_empty_file(self, tmp_path: Path):
        f = _make_file(tmp_path / "empty.md", "")
        doc = parse_markdown(f)
        assert doc.chunks == []

    def test_no_headings(self, tmp_path: Path):
        f = _make_file(tmp_path / "plain.md", "just text\nno headings")
        doc = parse_markdown(f)
        assert len(doc.chunks) == 1
        assert doc.chunks[0].section_title is None

    def test_line_numbers(self, tmp_path: Path):
        content = "# H1\n\nbody line\n"
        f = _make_file(tmp_path / "doc.md", content)
        doc = parse_markdown(f)
        assert doc.chunks[0].line_start == 0
        assert doc.chunks[0].line_end == 3


# ---------------------------------------------------------------------------
# parsers.py tests — TXT
# ---------------------------------------------------------------------------


class TestParseTxt:
    """Tests for parse_txt."""

    def test_paragraphs(self, tmp_path: Path):
        content = "Para 1 line 1\nPara 1 line 2\n\nPara 2 single line\n\n\nPara 3\n"
        f = _make_file(tmp_path / "doc.txt", content)
        doc = parse_txt(f)
        assert doc.format == "txt"
        assert len(doc.chunks) == 3
        assert doc.chunks[0].content.startswith("Para 1")
        assert doc.chunks[1].content == "Para 2 single line"
        assert doc.chunks[2].content == "Para 3"

    def test_single_paragraph(self, tmp_path: Path):
        f = _make_file(tmp_path / "one.txt", "only one paragraph here")
        doc = parse_txt(f)
        assert len(doc.chunks) == 1
        assert doc.chunks[0].content == "only one paragraph here"

    def test_empty_file(self, tmp_path: Path):
        f = _make_file(tmp_path / "empty.txt", "")
        doc = parse_txt(f)
        assert doc.chunks == []

    def test_whitespace_only(self, tmp_path: Path):
        f = _make_file(tmp_path / "ws.txt", "\n\n   \n\n")
        doc = parse_txt(f)
        assert doc.chunks == []


# ---------------------------------------------------------------------------
# parsers.py tests — Dispatcher
# ---------------------------------------------------------------------------


class TestParseFile:
    """Tests for parse_file dispatcher."""

    def test_dispatch_md(self, tmp_path: Path):
        f = _make_file(tmp_path / "t.md", "# Title\n\nbody")
        doc = parse_file(f, "md")
        assert doc.format == "md"

    def test_dispatch_txt(self, tmp_path: Path):
        f = _make_file(tmp_path / "t.txt", "hello world")
        doc = parse_file(f, "txt")
        assert doc.format == "txt"

    def test_unsupported_format(self, tmp_path: Path):
        f = _make_file(tmp_path / "t.bin", "data")
        with pytest.raises(ValueError, match="Unsupported format"):
            parse_file(f, "bin")

    def test_pdf_without_dependency(self, tmp_path: Path):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("pypdf is installed — skipping missing-dep test")
        f = _make_file(tmp_path / "doc.pdf", "not a real pdf")
        with pytest.raises(ImportError, match="pypdf"):
            parse_file(f, "pdf")

    def test_docx_without_dependency(self, tmp_path: Path):
        try:
            import docx  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("python-docx is installed — skipping missing-dep test")
        f = _make_file(tmp_path / "doc.docx", "not a real docx")
        with pytest.raises(ImportError, match="python-docx"):
            parse_file(f, "docx")

    def test_xlsx_without_dependency(self, tmp_path: Path):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("openpyxl is installed — skipping missing-dep test")
        f = _make_file(tmp_path / "doc.xlsx", "not a real xlsx")
        with pytest.raises(ImportError, match="openpyxl"):
            parse_file(f, "xlsx")


# ---------------------------------------------------------------------------
# Integration tests — import_project
# ---------------------------------------------------------------------------


class TestImportProject:
    """Integration tests for the full import_project pipeline."""

    def test_full_import_md_txt(self, tmp_path: Path):
        _make_project("p-int", {
            "readme.md": "# Hello\n\nworld",
            "notes.txt": "note one\n\nnote two",
            "ignore.bin": "skip me",
        }, base_dir=tmp_path)
        result = import_project("p-int", base_dir=tmp_path)
        assert result.project_id == "p-int"
        assert result.total_files == 3
        assert result.success_count == 2
        assert result.failure_count == 0
        assert result.skipped_count == 1
        assert len(result.parsed) == 2
        assert len(result.files) == 3

        unsupported = next(sf for sf in result.files if sf.relative_path == "source/ignore.bin")
        assert unsupported.parse_status == "unsupported"
        assert unsupported.error_message is None

        for sf in result.files:
            if sf.parse_status == "unsupported":
                continue
            assert sf.parse_status == "success"
            assert sf.sha256 is not None
            assert len(sf.sha256) == 64

    def test_citation_locations(self, tmp_path: Path):
        _make_project("p-cite", {
            "doc.md": "# Report\n\nSummary text\n\n## Details\n\nDetailed info",
            "log.txt": "line one\n\nline two",
        }, base_dir=tmp_path)
        result = import_project("p-cite", base_dir=tmp_path)

        # Markdown citation
        md_doc = next(d for d in result.parsed if d.format == "md")
        assert any(c.section_title == "Report" for c in md_doc.chunks)
        assert any(c.section_title == "Details" for c in md_doc.chunks)
        # All chunks have relative_path set
        for d in result.parsed:
            for c in d.chunks:
                assert c.relative_path is not None

    def test_project_not_found(self, tmp_path: Path):
        result = import_project("nobody", base_dir=tmp_path)
        assert result.total_files == 0
        assert result.success_count == 0

    def test_success_failure_separation(self, tmp_path: Path):
        """Ensure a corrupt file doesn't crash import; good files still parse."""
        _make_project("p-err", {
            "good.md": "# OK\n\ncontent",
            "good.txt": "more data",
        }, base_dir=tmp_path)
        # Create a binary file with .txt extension — will fail UTF-8 decode
        binary_path = (
            tmp_path / "data" / "projects" / "p-err" / "source" / "corrupt.txt"
        )
        binary_path.write_bytes(b"\x80\x81\x82\x83")

        result = import_project("p-err", base_dir=tmp_path)
        assert result.success_count == 2  # MD + good TXT
        assert result.failure_count == 1  # corrupt binary TXT
        assert result.total_files == 3

        # Verify the corrupt file is recorded with proper error info
        failures = [sf for sf in result.files if sf.parse_status == "failed"]
        assert len(failures) == 1
        assert failures[0].relative_path == "source/corrupt.txt"
        assert failures[0].error_message is not None

    def test_file_manifest_fields(self, tmp_path: Path):
        _make_project("p-man", {
            "info.txt": "data here",
        }, base_dir=tmp_path)
        result = import_project("p-man", base_dir=tmp_path)
        sf = result.files[0]
        assert sf.relative_path == "source/info.txt"
        assert sf.format == "txt"
        assert sf.parse_status == "success"
        assert sf.size_bytes > 0
        assert sf.modified_time > 0
        assert sf.error_message is None

    def test_symlink_escape_is_recorded_without_hashing_target(self, tmp_path: Path):
        source_dir = _make_project("p-link", {}, base_dir=tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("# secret", encoding="utf-8")
        symlink = source_dir / "escape.md"
        try:
            symlink.symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation requires elevated privileges on this OS")

        result = import_project("p-link", base_dir=tmp_path)
        assert result.total_files == 1
        assert result.failure_count == 1
        rejected = result.files[0]
        assert rejected.parse_status == "failed"
        assert rejected.error_message == "symlink escape detected"
        assert rejected.sha256 is None
