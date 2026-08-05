import json
import tarfile
from pathlib import Path

from scripts import pb_parity_artifact as parity


def write_report(path: Path, rows: list[dict]) -> Path:
    path.write_text(json.dumps({"test_results": rows}, indent=2), encoding="utf-8")
    return path


def write_source(root: Path, body: str) -> Path:
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / "test_demo.py").write_text(body, encoding="utf-8")
    return root


def row(name: str, status: str, branch: str = "abc123") -> dict:
    return {"name": name, "branch": branch, "status": status}


def test_tier_a_unconditional_skip_writes_complete_artifact(tmp_path):
    report = write_report(
        tmp_path / "report.json",
        [
            row("tests.test_demo.test_static_skip", "skipped"),
            row("tests.test_demo.test_ok", "passed"),
        ],
    )
    source = write_source(
        tmp_path / "src",
        """
import pytest

@pytest.mark.skip("upstream disabled")
def test_static_skip():
    assert False
""",
    )

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[source],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "TIER_A_COMPLETE"
    text = result.artifact_path.read_text(encoding="utf-8")
    assert "test_static_skip" in text
    assert "@pytest.mark.skip" in text
    assert "TIER A" in text


def test_tier_b_skipif_requires_reference_run(tmp_path):
    report = write_report(
        tmp_path / "report.json", [row("tests.test_demo.test_runtime_skip", "skipped")]
    )
    source = write_source(
        tmp_path / "src",
        """
import pytest

@pytest.mark.skipif(True, reason="slow on this host")
def test_runtime_skip():
    assert False
""",
    )

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[source],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "TIER_B_NEEDS_REFERENCE_RUN"
    assert "skipif" in result.artifact_path.read_text(encoding="utf-8")


def test_ineligible_when_report_has_failure(tmp_path):
    report = write_report(
        tmp_path / "report.json",
        [
            row("tests.test_demo.test_static_skip", "skipped"),
            row("tests.test_demo.test_fail", "failure"),
        ],
    )
    source = write_source(
        tmp_path / "src",
        """
import pytest

@pytest.mark.skip("upstream disabled")
def test_static_skip():
    assert False
""",
    )

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[source],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "INELIGIBLE"
    assert "failed/error count: 1" in result.artifact_path.read_text(encoding="utf-8")


def test_mixed_tier_a_and_b_uses_tier_b_verdict(tmp_path):
    report = write_report(
        tmp_path / "report.json",
        [
            row("tests.test_demo.test_static_skip", "skipped"),
            row("tests.test_demo.test_runtime_skip", "skipped"),
        ],
    )
    source = write_source(
        tmp_path / "src",
        """
import pytest

@pytest.mark.skip("upstream disabled")
def test_static_skip():
    assert False

@pytest.mark.skipif(True, reason="slow")
def test_runtime_skip():
    assert False
""",
    )

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[source],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "TIER_B_NEEDS_REFERENCE_RUN"
    text = result.artifact_path.read_text(encoding="utf-8")
    assert "test_static_skip" in text
    assert "test_runtime_skip" in text


def test_can_search_compile_tarball_source(tmp_path):
    report = write_report(
        tmp_path / "report.json", [row("tests.test_demo.test_static_skip", "skipped")]
    )
    src_file = tmp_path / "test_demo.py"
    src_file.write_text(
        """
import pytest

@pytest.mark.skip("upstream disabled")
def test_static_skip():
    assert False
""",
        encoding="utf-8",
    )
    tar_path = tmp_path / "submission.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(src_file, arcname="source/tests/test_demo.py")

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[tar_path],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "TIER_A_COMPLETE"


def test_diff_requires_reference_same_skips(tmp_path):
    candidate = write_report(
        tmp_path / "candidate.json", [row("tests.test_demo.test_a", "skipped")]
    )
    reference = write_report(
        tmp_path / "reference.json", [row("tests.test_demo.test_b", "skipped")]
    )

    diff = parity.diff_reference(candidate, reference)

    assert diff["verdict"] == "INELIGIBLE"
    assert diff["candidate_only_skips"] == ["abc123/tests.test_demo.test_a"]
    assert diff["reference_only_skips"] == ["abc123/tests.test_demo.test_b"]


def test_missing_report_writes_ineligible_artifact(tmp_path):
    result = parity.build_missing_report_artifact(
        "demo", out_root=tmp_path / "out", missing_report="missing.json"
    )

    assert result.verdict == "INELIGIBLE"
    text = result.artifact_path.read_text(encoding="utf-8")
    assert "raw report missing" in text
    assert "missing.json" in text


def test_runtime_skip_message_is_used_when_source_missing(tmp_path):
    report = write_report(
        tmp_path / "report.json",
        [
            {
                "name": "tests.test_demo.test_runtime",
                "branch": "abc123",
                "status": "skipped",
                "extra": {
                    "output": '<skipped type="pytest.skip" message="running as root">/workspace/eval/tests/test_demo.py:12: running as root</skipped>'
                },
            }
        ],
    )

    result = parity.build_artifact(
        "demo",
        report_path=report,
        source_paths=[],
        out_root=tmp_path / "out",
        upstream_commit="abc123",
    )

    assert result.verdict == "TIER_B_NEEDS_REFERENCE_RUN"
    text = result.artifact_path.read_text(encoding="utf-8")
    assert "running as root" in text
    assert "/workspace/eval/tests/test_demo.py:12" in text
