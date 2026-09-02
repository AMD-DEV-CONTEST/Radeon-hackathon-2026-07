from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.programbench_task_root_resolver import (  # noqa: E402
    ProgramBenchTaskRootResolver,
    ResolutionConfig,
    ResolutionStatus,
)
from corpus.legacy_recovery.replay_hydration import (  # noqa: E402
    HydrationConfig,
    HydrationStatus,
    ProgramBenchReplayHydrator,
)


def _candidate(tool: str = "sharkdp__fd.40d8eb3") -> dict:
    return {
        "tool": tool,
        "failure_classes": ["path_env_dependency"],
        "language_guess": "rust",
        "legacy_row_hash": "legacy_cluster:abc123",
        "duplicate_cluster_id": "abc123",
        "expected_verifier": "programbench eval",
        "priority_score": 42,
    }


def _make_tool(root: Path, slug: str, *, executable: str = "executable") -> Path:
    path = root / slug
    path.mkdir(parents=True)
    (path / "source").mkdir()
    (path / "source" / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
    (path / executable).write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def _resolver(tmp_path: Path, roots: list[Path]) -> ProgramBenchTaskRootResolver:
    return ProgramBenchTaskRootResolver(
        ResolutionConfig(
            roots=roots,
            allowed_roots=roots,
            output_path=tmp_path / "resolution.json",
        )
    )


def test_exact_name_resolves_task_and_source(tmp_path):
    root = tmp_path / "roots"
    tool_root = _make_tool(root, "sharkdp__fd.40d8eb3")

    result = _resolver(tmp_path, [root]).resolve_candidate(_candidate())

    assert result.resolution_status == ResolutionStatus.TASK_AND_SOURCE_RESOLVED.value
    assert Path(result.task_root) == tool_root
    assert Path(result.source_root) == tool_root / "source"
    assert result.method == "exact_tool_name"
    assert result.confidence == 1.0


def test_alias_resolves_but_is_marked_alias_only(tmp_path):
    root = tmp_path / "roots"
    _make_tool(root, "sharkdp__fd.40d8eb3")

    result = _resolver(tmp_path, [root]).resolve_candidate(_candidate("fd"))

    assert result.resolution_status == ResolutionStatus.ALIAS_ONLY_MATCH.value
    assert result.method == "alias_table"
    assert result.task_root


def test_multiple_matches_are_not_resolved(tmp_path):
    r1 = tmp_path / "root1"
    r2 = tmp_path / "root2"
    _make_tool(r1, "sharkdp__fd.40d8eb3")
    _make_tool(r2, "sharkdp__fd.40d8eb3")

    result = _resolver(tmp_path, [r1, r2]).resolve_candidate(_candidate())

    assert result.resolution_status == ResolutionStatus.MULTIPLE_MATCHES.value
    assert not result.task_root


def test_binary_only_match_does_not_become_task_and_source(tmp_path):
    root = tmp_path / "roots"
    _make_tool(root, "example__custom.1234567", executable="mybin")
    result = _resolver(tmp_path, [root]).resolve_candidate(_candidate("mybin"))

    assert result.resolution_status == ResolutionStatus.BINARY_ONLY_MATCH.value
    assert result.method == "binary_name_scan"


def test_missing_tool_produces_no_match(tmp_path):
    result = _resolver(tmp_path, [tmp_path / "empty"]).resolve_candidate(
        _candidate("does-not-exist")
    )

    assert result.resolution_status == ResolutionStatus.NO_MATCH.value


def test_resolved_path_must_be_inside_allowed_roots(tmp_path):
    indexed_root = tmp_path / "indexed"
    outside_root = tmp_path / "outside"
    _make_tool(outside_root, "sharkdp__fd.40d8eb3")
    resolver = ProgramBenchTaskRootResolver(
        ResolutionConfig(
            roots=[outside_root],
            allowed_roots=[indexed_root],
            output_path=tmp_path / "resolution.json",
        )
    )

    result = resolver.resolve_candidate(_candidate())

    assert result.resolution_status == ResolutionStatus.NO_MATCH.value


def test_batch_resolution_artifact_written(tmp_path):
    root = tmp_path / "roots"
    _make_tool(root, "sharkdp__fd.40d8eb3")
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps({"selected": [_candidate(), _candidate("missing")]}), encoding="utf-8"
    )

    report = _resolver(tmp_path, [root]).resolve_batch(batch)

    assert report["candidates"] == 2
    assert report["resolved"] == 1
    assert report["missing"] == 1
    assert (tmp_path / "resolution.json").exists()


def test_hydration_consumes_task_and_source_resolution(tmp_path):
    root = tmp_path / "roots"
    tool_root = _make_tool(root, "sharkdp__fd.40d8eb3")
    harness = tmp_path / "programbench"
    harness.mkdir()
    (harness / "pyproject.toml").write_text("[project]\nname='programbench'\n", encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": [_candidate()]}), encoding="utf-8")
    resolution = _resolver(tmp_path, [root]).resolve_batch(batch)
    assert resolution["resolved"] == 1

    hydrator = ProgramBenchReplayHydrator(
        HydrationConfig(
            task_roots=[],
            candidate_roots=[],
            programbench_roots=[harness],
            image_roots=[],
            output_path=tmp_path / "hydration.json",
            resolution_report=tmp_path / "resolution.json",
            require_image=False,
        )
    )
    hydrated = hydrator.hydrate_candidate(_candidate())

    assert hydrated.status == HydrationStatus.HYDRATED_READY.value
    assert Path(hydrated.task_root) == tool_root
    assert Path(hydrated.candidate_root) == tool_root


def test_batch_001_names_resolve_or_miss_cleanly(tmp_path):
    root = tmp_path / "roots"
    _make_tool(root, "antonmedv__fx.86d0d34")
    _make_tool(root, "rcoh__angle-grinder.9c2fc88")
    candidates = [
        _candidate("antonmedv__fx.86d0d34"),
        _candidate("rcoh__angle-grinder.9c2fc88"),
        _candidate("missing__tool.000"),
    ]
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": candidates}), encoding="utf-8")

    report = _resolver(tmp_path, [root]).resolve_batch(batch)

    assert report["resolved"] == 2
    assert report["missing"] == 1
