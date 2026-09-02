from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.programbench_image_hydrator import (  # noqa: E402
    ImageHydrationConfig,
    ImageHydrationStatus,
    ProgramBenchImageHydrator,
)


def _candidate(tool: str = "bat", **extra) -> dict:
    row = {
        "tool": tool,
        "legacy_row_hash": "legacy_cluster:bat-001",
        "failure_classes": ["stdout_stderr_mismatch"],
        "language_guess": "rust",
    }
    row.update(extra)
    return row


def _root(tmp_path: Path, tool: str = "bat", metadata: dict | None = None) -> Path:
    root = tmp_path / "roots" / tool
    root.mkdir(parents=True)
    if metadata is not None:
        (root / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    return root


def _report(tmp_path: Path, tool: str = "bat", selected_root: Path | None = None) -> Path:
    selected_root = selected_root or _root(tmp_path, tool)
    path = tmp_path / "disambiguation.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "tool": tool,
                        "status": "CANONICAL_ROOT_SELECTED",
                        "selected_root": str(selected_root),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _hydrator(tmp_path: Path, **extra) -> ProgramBenchImageHydrator:
    disambiguation_report = extra.pop("disambiguation_report", None)
    if disambiguation_report is None:
        disambiguation_report = _report(tmp_path)
    config = ImageHydrationConfig(
        image_roots=[tmp_path / "images"],
        output_path=tmp_path / "image_hydration.json",
        disambiguation_report=disambiguation_report,
        **extra,
    )
    return ProgramBenchImageHydrator(config)


def test_local_docker_image_found_is_ready(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)
    hydrator = _hydrator(
        tmp_path,
        disambiguation_report=report,
        docker_image_lister=lambda: ["programbench/bat@sha256:abc"],
    )

    result = hydrator.hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_LOCAL_READY.value
    assert result.reason == "docker_image_list_match"


def test_missing_image_when_metadata_exists_but_pull_disabled(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)
    called = {"pull": False}

    def puller(_image: str) -> bool:
        called["pull"] = True
        return True

    result = _hydrator(
        tmp_path,
        disambiguation_report=report,
        image_puller=puller,
        allow_pull=False,
    ).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_MISSING.value
    assert called["pull"] is False


def test_ambiguous_image_name_is_rejected(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "latest"})
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(tmp_path, disambiguation_report=report).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_NAME_AMBIGUOUS.value


def test_image_metadata_missing_is_explicit_status(tmp_path):
    root = _root(tmp_path)
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(tmp_path, disambiguation_report=report).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_METADATA_MISSING.value
    assert result.reason == "no_explicit_image_metadata"


def test_cache_artifact_hydrates_image(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)
    cache = tmp_path / "images"
    cache.mkdir()
    (cache / "programbench_bat_sha256_abc.tar").write_text("cached image bytes", encoding="utf-8")

    result = _hydrator(tmp_path, disambiguation_report=report).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_HYDRATED_FROM_CACHE.value
    assert "cache_artifact" in result.reason


def test_pull_allowed_without_runner_marks_pull_ready(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(
        tmp_path,
        disambiguation_report=report,
        allow_pull=True,
    ).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_PULL_READY.value


def test_pull_failure_is_explicit_status(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(
        tmp_path,
        disambiguation_report=report,
        allow_pull=True,
        image_puller=lambda _image: False,
    ).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.IMAGE_PULL_FAILED.value


def test_local_no_image_verifier_ready_requires_explicit_metadata(tmp_path):
    root = _root(tmp_path)
    (root / "fixtures").mkdir()
    (root / "fixtures" / "input.txt").write_text("demo", encoding="utf-8")
    (root / "local_verifier.json").write_text(
        json.dumps(
            {
                "local_verifier_allowed": True,
                "local_verifier_command": "python replay.py",
                "required_fixtures": ["fixtures/input.txt"],
                "deterministic": True,
            }
        ),
        encoding="utf-8",
    )
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(tmp_path, disambiguation_report=report).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_READY.value
    assert result.verifier_scope == "local_replay"
    assert "not_official_programbench_score" in result.local_verifier_limitations


def test_local_no_image_verifier_blocked_when_fixtures_missing(tmp_path):
    root = _root(tmp_path)
    (root / "local_verifier.json").write_text(
        json.dumps(
            {
                "local_verifier_allowed": True,
                "local_verifier_command": "python replay.py",
                "required_fixtures": ["fixtures/missing.txt"],
            }
        ),
        encoding="utf-8",
    )
    report = _report(tmp_path, selected_root=root)

    result = _hydrator(tmp_path, disambiguation_report=report).hydrate_candidate(_candidate())

    assert result.status == ImageHydrationStatus.LOCAL_NO_IMAGE_VERIFIER_UNSUPPORTED.value
    assert result.reason.startswith("local_verifier_fixtures_missing")


def test_batch_report_writes_status_counts(tmp_path):
    root = _root(tmp_path, metadata={"task_image": "programbench/bat@sha256:abc"})
    report = _report(tmp_path, selected_root=root)
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": [_candidate()]}), encoding="utf-8")
    hydrator = _hydrator(
        tmp_path,
        disambiguation_report=report,
        docker_image_lister=lambda: ["programbench/bat@sha256:abc"],
    )

    output = hydrator.hydrate_batch(batch)

    assert output["candidates"] == 1
    assert output["image_local_ready"] == 1
    assert output["status_counts"][ImageHydrationStatus.IMAGE_LOCAL_READY.value] == 1
    assert (tmp_path / "image_hydration.json").exists()
