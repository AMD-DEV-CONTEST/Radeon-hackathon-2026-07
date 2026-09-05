from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evaluation import benchmark_agent, run_agent_eval, run_retrieval_eval, source_provenance

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_source_hash_is_shared_and_uses_only_tracked_c2_inputs(
    tmp_path: Path,
) -> None:
    for relative, content in (
        (".env.example", "SAFE_EXAMPLE=1\n"),
        ("LICENSE", "test license\n"),
        ("THIRD_PARTY_NOTICES.md", "test notices\n"),
        ("pyproject.toml", "[project]\nname = 'test'\n"),
        ("requirements.lock", "pytest==8.3.5\n"),
        ("src/radeonstay/app.py", "VALUE = 1\n"),
        ("data/policies/policy.md", "local policy\n"),
        ("scripts/run.sh", "#!/usr/bin/env bash\n"),
        ("tests/test_app.py", "def test_value(): pass\n"),
        ("evaluation/evaluator.py", "VERSION = 1\n"),
        ("evaluation/results/ignored.json", "{}\n"),
        ("docs/ignored.md", "draft\n"),
        ("output/playwright/ignored.json", "{}\n"),
        ("tmp/untracked.py", "ignored = True\n"),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "RadeonStay Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "radeonstay@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"], cwd=tmp_path, check=True
    )
    first = source_provenance.source_tree_sha256(tmp_path)
    (tmp_path / "docs/ignored.md").write_text("changed\n", encoding="utf-8")
    (tmp_path / "src/radeonstay/untracked.py").write_text(
        "ignored = True\n", encoding="utf-8"
    )
    assert source_provenance.source_tree_sha256(tmp_path) == first

    (tmp_path / "src/radeonstay/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="differs byte-for-byte from HEAD"):
        source_provenance.source_tree_sha256(tmp_path)
    subprocess.run(
        ["git", "add", "src/radeonstay/app.py"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "change frozen input"],
        cwd=tmp_path,
        check=True,
    )
    assert source_provenance.source_tree_sha256(tmp_path) != first
    assert benchmark_agent.source_tree_sha256 is source_provenance.source_tree_sha256
    assert run_agent_eval.source_tree_sha256 is source_provenance.source_tree_sha256
    assert run_retrieval_eval.source_tree_sha256 is source_provenance.source_tree_sha256
    collector = (PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh").read_text(
        encoding="utf-8"
    )
    assert "from evaluation.source_provenance import source_tree_sha256" in collector
    assert "source_sha256 = source_tree_sha256(project)" in collector
