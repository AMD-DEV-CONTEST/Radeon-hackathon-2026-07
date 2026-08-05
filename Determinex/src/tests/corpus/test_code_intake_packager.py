from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corpus.code_ingest.corpus_packager import assess_source, write_manifest


def test_packager_accepts_green_licensed_java_source(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "LICENSE").write_text("MIT License", encoding="utf-8")
    (source / "Example.java").write_text(
        "public class Example { public int add(int a, int b) { return a + b; } }\n",
        encoding="utf-8",
    )
    payload = assess_source(source, benchmark="unit", staging_root=tmp_path / "stage")
    assert payload["decision"]["ingest_allowed"] is True
    assert payload["license"]["spdx_id"] == "MIT"
    assert payload["quality"]["code_files"] == 1


def test_packager_rejects_unlicensed_cpp_source(tmp_path: Path) -> None:
    source = tmp_path / "cpp"
    source.mkdir()
    (source / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    payload = assess_source(source, benchmark="unit", staging_root=tmp_path / "stage")
    assert payload["decision"]["ingest_allowed"] is False
    assert any(reason.startswith("license_not_green") for reason in payload["decision"]["reasons"])


def test_packager_writes_manifest_to_requested_dir(tmp_path: Path) -> None:
    source = tmp_path / "pkg"
    source.mkdir()
    (source / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004", encoding="utf-8")
    (source / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    payload = assess_source(source, benchmark="unit", staging_root=tmp_path / "stage")
    path = write_manifest(payload, tmp_path / "manifests")
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip().startswith("{")
