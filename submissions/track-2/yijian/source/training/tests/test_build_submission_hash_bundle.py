from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_submission_hash_bundle.py"
SPEC = importlib.util.spec_from_file_location("build_submission_hash_bundle", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bundle_hashes_status_and_evidence_but_not_itself(tmp_path: Path) -> None:
    (tmp_path / "submission-status.json").write_text("{}\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "metric.json").write_text('{"passed":true}\n', encoding="utf-8")
    output = evidence / "hash-bundle.json"

    first = MODULE.build(tmp_path, output)
    assert set(first["files"]) == {"submission-status.json", "evidence/metric.json"}
    assert len(first["bundleSha256"]) == 64

    output.write_text("stale", encoding="utf-8")
    second = MODULE.build(tmp_path, output)
    assert first["files"] == second["files"]
