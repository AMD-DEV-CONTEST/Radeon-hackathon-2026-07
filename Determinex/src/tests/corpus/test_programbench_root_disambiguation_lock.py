from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.programbench_root_disambiguator import (  # noqa: E402
    DisambiguationStatus,
    ProgramBenchRootDisambiguator,
    RootDisambiguationConfig,
)
from corpus.legacy_recovery.replay_hydration import (  # noqa: E402
    HydrationConfig,
    HydrationStatus,
    ProgramBenchReplayHydrator,
)


def _candidate(tool: str = "sharkdp__fd.40d8eb3", **extra) -> dict:
    row = {
        "tool": tool,
        "failure_classes": ["path_env_dependency"],
        "language_guess": "rust",
        "legacy_row_hash": "legacy_cluster:abc123",
        "duplicate_cluster_id": "abc123",
        "expected_verifier": "programbench eval",
        "priority_score": 42,
    }
    row.update(extra)
    return row


def _make_tool(root: Path, slug: str, *, manifest: dict | None = None) -> Path:
    path = root / slug
    path.mkdir(parents=True)
    (path / "source").mkdir()
    (path / "source" / "Cargo.toml").write_text("[package]\nname='demo'\n", encoding="utf-8")
    (path / "executable").write_text("#!/bin/sh\n", encoding="utf-8")
    if manifest is not None:
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _disambiguator(
    tmp_path: Path, roots: list[Path], overrides: Path | None = None
) -> ProgramBenchRootDisambiguator:
    return ProgramBenchRootDisambiguator(
        RootDisambiguationConfig(
            roots=roots,
            allowed_roots=roots,
            overrides_path=overrides or tmp_path / "missing_overrides.json",
            output_path=tmp_path / "disambiguation.json",
        )
    )


def test_per_tool_overrides_wins(tmp_path):
    overrides_root = tmp_path / "corpus" / "programbench" / "per_tool_overrides"
    in_progress = tmp_path / "corpus" / "programbench" / "in_progress"
    selected = _make_tool(overrides_root, "sharkdp__fd.40d8eb3")
    _make_tool(in_progress, "sharkdp__fd.40d8eb3")

    result = _disambiguator(tmp_path, [overrides_root, in_progress]).disambiguate_candidate(
        _candidate()
    )

    assert result.status == DisambiguationStatus.CANONICAL_ROOT_SELECTED.value
    assert Path(result.selected_root) == selected
    assert "per_tool_override_root" in result.evidence


def test_locked_root_beats_in_progress(tmp_path):
    locked = tmp_path / "corpus" / "programbench" / "locked"
    in_progress = tmp_path / "corpus" / "programbench" / "in_progress"
    selected = _make_tool(locked, "sharkdp__fd.40d8eb3")
    _make_tool(in_progress, "sharkdp__fd.40d8eb3")

    result = _disambiguator(tmp_path, [locked, in_progress]).disambiguate_candidate(_candidate())

    assert result.status == DisambiguationStatus.LOCKED_ROOT_SELECTED.value
    assert Path(result.selected_root) == selected


def test_in_progress_beats_historical_root(tmp_path):
    in_progress = tmp_path / "corpus" / "programbench" / "in_progress"
    historical = tmp_path / "runs" / "historical"
    selected = _make_tool(in_progress, "sharkdp__fd.40d8eb3")
    _make_tool(historical, "sharkdp__fd.40d8eb3")

    result = _disambiguator(tmp_path, [historical, in_progress]).disambiguate_candidate(
        _candidate()
    )

    assert result.status == DisambiguationStatus.ACTIVE_RUN_ROOT_SELECTED.value
    assert Path(result.selected_root) == selected


def test_t_drive_root_selected_only_if_manifest_matches(tmp_path):
    t_drive_like = tmp_path / "T" / "determinex-programbench"
    selected = _make_tool(t_drive_like, "sharkdp__fd.40d8eb3", manifest={"shard_id": "shard-a"})

    result = _disambiguator(tmp_path, [t_drive_like]).disambiguate_candidate(
        _candidate(shard_id="shard-a")
    )

    assert result.status == DisambiguationStatus.T_DRIVE_RUN_ROOT_SELECTED.value
    assert Path(result.selected_root) == selected


def test_newest_root_alone_does_not_win_equal_roots(tmp_path):
    r1 = tmp_path / "runs1"
    r2 = tmp_path / "runs2"
    _make_tool(r1, "sharkdp__fd.40d8eb3")
    newer = _make_tool(r2, "sharkdp__fd.40d8eb3")
    os.utime(newer, None)

    result = _disambiguator(tmp_path, [r1, r2]).disambiguate_candidate(_candidate())

    assert result.status == DisambiguationStatus.AMBIGUOUS_NEEDS_OVERRIDE.value
    assert not result.selected_root


def test_manual_override_wins_when_evidence_backed(tmp_path):
    root = tmp_path / "roots"
    selected = _make_tool(root, "sharkdp__fd.40d8eb3")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fd": {
                    "canonical_root": str(selected),
                    "reason": "strict locked source root",
                    "approved_by": "ryan",
                    "created_at": "2026-05-27",
                    "evidence": ["lock_manifest", "gated_run"],
                }
            }
        ),
        encoding="utf-8",
    )

    result = _disambiguator(tmp_path, [root], overrides).disambiguate_candidate(_candidate("fd"))

    assert result.status == DisambiguationStatus.OVERRIDE_ROOT_SELECTED.value
    assert Path(result.selected_root) == selected
    assert "manual_override" in result.evidence


def test_override_outside_allowed_roots_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    selected = _make_tool(outside, "sharkdp__fd.40d8eb3")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "fd": {
                    "canonical_root": str(selected),
                    "reason": "outside root",
                    "evidence": ["manual"],
                }
            }
        ),
        encoding="utf-8",
    )

    result = _disambiguator(tmp_path, [allowed], overrides).disambiguate_candidate(_candidate("fd"))

    assert result.status == DisambiguationStatus.UNSAFE_ROOT_REJECTED.value


def test_symlink_escape_rejected_when_supported(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    target = _make_tool(outside, "sharkdp__fd.40d8eb3")
    allowed.mkdir()
    link = allowed / "sharkdp__fd.40d8eb3"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if not target.exists():
            link.touch()
        elif target.is_dir():
            link.mkdir()
        else:
            link.write_text("mock", encoding="utf-8")
        orig_resolve = Path.resolve

        def mock_resolve(self, strict=False):
            self_abs = str(self.absolute())
            link_abs = str(link.absolute())
            if self_abs == link_abs:
                return target.resolve(strict=strict)
            elif self_abs.startswith(link_abs + os.sep):
                remainder = self_abs[len(link_abs) + 1 :]
                return target.resolve(strict=strict) / remainder
            return orig_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", mock_resolve)

    result = _disambiguator(tmp_path, [allowed]).disambiguate_candidate(_candidate())

    assert result.status in {
        DisambiguationStatus.NO_RUNNABLE_ROOT.value,
        DisambiguationStatus.UNSAFE_ROOT_REJECTED.value,
    }


def test_selected_root_passes_to_hydration(tmp_path):
    per_tool = tmp_path / "corpus" / "programbench" / "per_tool_overrides"
    selected = _make_tool(per_tool, "sharkdp__fd.40d8eb3")
    harness = tmp_path / "programbench"
    harness.mkdir()
    (harness / "pyproject.toml").write_text("[project]\nname='programbench'\n", encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": [_candidate()]}), encoding="utf-8")
    disambiguator = _disambiguator(tmp_path, [per_tool])
    report = disambiguator.disambiguate_batch(batch)
    assert report["selected"] == 1

    hydrated = ProgramBenchReplayHydrator(
        HydrationConfig(
            task_roots=[],
            candidate_roots=[],
            programbench_roots=[harness],
            image_roots=[],
            output_path=tmp_path / "hydration.json",
            disambiguation_report=tmp_path / "disambiguation.json",
            require_image=False,
        )
    ).hydrate_candidate(_candidate())

    assert hydrated.status == HydrationStatus.HYDRATED_READY.value
    assert Path(hydrated.task_root) == selected


def test_batch_artifact_written(tmp_path):
    per_tool = tmp_path / "corpus" / "programbench" / "per_tool_overrides"
    _make_tool(per_tool, "sharkdp__fd.40d8eb3")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": [_candidate()]}), encoding="utf-8")

    report = _disambiguator(tmp_path, [per_tool]).disambiguate_batch(batch)

    assert report["selected"] == 1
    assert (tmp_path / "disambiguation.json").exists()
