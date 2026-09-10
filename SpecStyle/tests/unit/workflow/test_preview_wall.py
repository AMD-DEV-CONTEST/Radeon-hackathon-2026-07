from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.workflow.preview_evidence import PreviewEvidencePublication
from specstyle.workflow.preview_run_one import PreviewRunOneResult, PreviewRunStatus


def _publication(
    run_id: str, variation_index: int, content: str
) -> PreviewEvidencePublication:
    return PreviewEvidencePublication(
        run_id,
        f"{run_id}-{content[:16]}.png",
        ArtifactId(f"preview-{'a' * 64}"),
        Sha256(content),
        Sha256("c" * 64),
        Sha256("b" * 64),
        "specstyle.preview.evidence.v3",
        variation_index,
        "specstyle.seed.v1",
        1000 + variation_index,
        (512, 512),
        "ENGINEERING_ONLY",
        "float16",
        "float16",
        "float32",
        "diffusers_force_upcast_roundtrip_v1",
    )


def _fds(tmp_path: Path):
    from specstyle.workflow.preview_run_one import PreviewRunOneFds

    descriptors: list[int] = []
    for name in (
        "production-config",
        "production-evidence",
        "preview-config",
        "models",
        "preview-evidence",
        "display",
        "styles",
    ):
        path = tmp_path / name
        path.mkdir()
        descriptors.append(os.open(path, os.O_RDONLY | os.O_DIRECTORY))
    for name in ("source", "style", "spec", "metadata"):
        path = tmp_path / name
        path.write_bytes(b"input")
        descriptors.append(os.open(path, os.O_RDONLY))
    return PreviewRunOneFds(*descriptors), descriptors


class _Session:
    def __init__(self, results: list[PreviewRunOneResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []
        self.closed = 0

    def run_item(self, run_id: str, variation_index: int) -> PreviewRunOneResult:
        self.calls.append((run_id, variation_index))
        return self.results[variation_index]

    def close(self) -> bool:
        self.closed += 1
        return False


def test_wall_reuses_one_lane_and_runtime_and_publishes_all_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall as module
    import specstyle.workflow.preview_wall_evidence as evidence

    fds, descriptors = _fds(tmp_path)
    reservation = module.reserve_preview_wall(4)
    run_ids = reservation.run_ids
    results = [
        PreviewRunOneResult(
            run_id,
            PreviewRunStatus.COMPLETED,
            "OK",
            _publication(run_id, index, f"{index + 1:064x}"),
        )
        for index, run_id in enumerate(run_ids)
    ]
    session = _Session(results)
    lane = SimpleNamespace(closed=0)
    lane.close = lambda: setattr(lane, "closed", lane.closed + 1)
    acquire_calls: list[None] = []
    monkeypatch.setattr(
        module,
        "try_acquire_gpu_runtime_lane",
        lambda: acquire_calls.append(None) or lane,
    )
    monkeypatch.setattr(module, "open_preview_runtime_session", lambda _fds: session)
    monkeypatch.setattr(evidence, "_verify_stored_publication", lambda *_args: None)

    result = module.run_preview_wall(fds, reservation)

    assert result.status.value == "COMPLETED"
    assert [item.variation_index for item in result.items] == [0, 1, 2, 3]
    assert all(item.attempted for item in result.items)
    assert session.calls == list(zip(run_ids, range(4), strict=True))
    assert len(acquire_calls) == 1
    assert session.closed == 1
    assert lane.closed == 1
    assert result.publication is not None
    manifest = json.loads(
        (
            tmp_path
            / "preview-evidence"
            / result.publication.evidence_name
            / "manifest.json"
        ).read_text()
    )
    assert manifest["evidence_class"] == "ENGINEERING_ONLY"
    assert manifest["metrics"] == {
        "busy": 0,
        "completed": 4,
        "duplicate_count": 0,
        "failed": 0,
        "requested": 4,
        "unique_content_hash_count": 4,
    }
    assert manifest["quality"] == "NOT_EVALUATED"
    assert manifest["diversity"] == "NOT_EVALUATED"
    assert manifest["planes"] == {
        "verification": "NOT_RUN",
        "repair": "NOT_RUN",
        "export": "NOT_RUN",
    }
    for descriptor in descriptors:
        os.close(descriptor)


def test_wall_opens_preflight_and_pipeline_once_for_all_variations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_run_one as one
    import specstyle.workflow.preview_wall as module
    import specstyle.workflow.preview_wall_evidence as evidence

    fds, descriptors = _fds(tmp_path)
    calls = {"preflight": 0, "load": 0, "inputs": 0, "pipeline_close": 0}

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name
            self.style_assets = object()

        def close(self) -> None:
            if self.name == "pipeline":
                calls["pipeline_close"] += 1

    preflight = one._PreviewPreflight(
        object(), object(), object(), Resource("supply"), Resource("adapter"), object()
    )
    loaded = Resource("pipeline")

    def open_preflight(_owned: object):
        calls["preflight"] += 1
        return preflight

    def load_runtime(_preflight: object):
        calls["load"] += 1
        return loaded

    def open_input(_owned: object, _preflight: object, variation_index: int):
        calls["inputs"] += 1
        item = Resource(f"input-{variation_index}")
        item.variation_index = variation_index
        return item

    def publish(_owned: object, run_id: str, artifact: object):
        variation_index = int(run_id.rsplit("v", 1)[1])
        assert artifact == (loaded, variation_index)
        return _publication(run_id, variation_index, f"{variation_index + 1:064x}")

    monkeypatch.setattr(one, "_open_preflight", open_preflight)
    monkeypatch.setattr(one, "_load_runtime", load_runtime)
    monkeypatch.setattr(one, "_open_input", open_input)
    monkeypatch.setattr(
        one, "_compile_request", lambda _run, job_input, _pre: job_input.variation_index
    )
    monkeypatch.setattr(
        one,
        "_generate_artifact",
        lambda runtime, _job, request: (runtime, request),
    )
    monkeypatch.setattr(one, "_publish_artifact", publish)
    monkeypatch.setattr(evidence, "_verify_stored_publication", lambda *_args: None)

    result = module.run_preview_wall(fds, module.reserve_preview_wall(3))

    assert result.status is module.PreviewWallStatus.COMPLETED
    assert calls == {
        "preflight": 1,
        "load": 1,
        "inputs": 3,
        "pipeline_close": 1,
    }
    for descriptor in descriptors:
        os.close(descriptor)


def test_wall_busy_publishes_four_unattempted_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall as module

    fds, descriptors = _fds(tmp_path)
    reservation = module.reserve_preview_wall(4)
    monkeypatch.setattr(module, "try_acquire_gpu_runtime_lane", lambda: None)
    monkeypatch.setattr(
        module,
        "open_preview_runtime_session",
        lambda _fds: pytest.fail("runtime must not open while busy"),
    )

    result = module.run_preview_wall(fds, reservation)

    assert result.status.value == "BUSY"
    assert [
        (item.attempted, item.run.status, item.run.reason_code) for item in result.items
    ] == [(False, PreviewRunStatus.BUSY, "GPU_BUSY")] * 4
    assert result.publication is not None
    for descriptor in descriptors:
        os.close(descriptor)


def test_wall_aborts_remaining_items_after_runtime_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall as module
    import specstyle.workflow.preview_wall_evidence as evidence

    fds, descriptors = _fds(tmp_path)
    reservation = module.reserve_preview_wall(4)
    run_ids = reservation.run_ids
    results = [
        PreviewRunOneResult(
            run_ids[0],
            PreviewRunStatus.COMPLETED,
            "OK",
            _publication(run_ids[0], 0, "1" * 64),
        ),
        PreviewRunOneResult(
            run_ids[1],
            PreviewRunStatus.UNAVAILABLE,
            "RUNTIME_INTEGRITY_FAILED",
            None,
        ),
    ]
    session = _Session(results)
    lane = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(module, "try_acquire_gpu_runtime_lane", lambda: lane)
    monkeypatch.setattr(module, "open_preview_runtime_session", lambda _fds: session)
    monkeypatch.setattr(evidence, "_verify_stored_publication", lambda *_args: None)

    result = module.run_preview_wall(fds, reservation)

    assert result.status.value == "PARTIAL"
    assert session.calls == [(run_ids[0], 0), (run_ids[1], 1)]
    assert [item.attempted for item in result.items] == [True, True, False, False]
    assert [item.run.reason_code for item in result.items] == [
        "OK",
        "RUNTIME_INTEGRITY_FAILED",
        "WALL_ABORTED",
        "WALL_ABORTED",
    ]
    for descriptor in descriptors:
        os.close(descriptor)


@pytest.mark.parametrize("count", (True, 0, 5, 2.0))
def test_wall_rejects_invalid_count(count: object) -> None:
    from specstyle.workflow.preview_wall import reserve_preview_wall

    with pytest.raises(DomainError):
        reserve_preview_wall(count)  # type: ignore[arg-type]


def test_wall_reservation_is_single_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall as module

    fds, descriptors = _fds(tmp_path)
    reservation = module.reserve_preview_wall(1)
    monkeypatch.setattr(module, "try_acquire_gpu_runtime_lane", lambda: None)
    module.run_preview_wall(fds, reservation)
    with pytest.raises(DomainError, match="consumed"):
        module.run_preview_wall(fds, reservation)
    for descriptor in descriptors:
        os.close(descriptor)


def test_wall_returns_persist_failed_when_manifest_cannot_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_wall as module

    fds, descriptors = _fds(tmp_path)
    monkeypatch.setattr(module, "try_acquire_gpu_runtime_lane", lambda: None)
    monkeypatch.setattr(
        module,
        "publish_preview_wall_evidence",
        lambda *_args: (_ for _ in ()).throw(InfrastructureError("broken")),
    )

    result = module.run_preview_wall(fds, module.reserve_preview_wall(2))

    assert result.status.value == "FAILED"
    assert result.reason_code == "PERSIST_FAILED"
    assert result.publication is None
    for descriptor in descriptors:
        os.close(descriptor)


def test_wall_result_rejects_completed_persist_failure() -> None:
    from specstyle.workflow.preview_wall import (
        PreviewWallItemResult,
        PreviewWallResult,
        PreviewWallStatus,
    )

    wall_id = "preview-wall-" + "9" * 32
    publication = _publication(f"{wall_id}-v0", 0, "f" * 64)
    item = PreviewWallItemResult(
        0,
        True,
        PreviewRunOneResult(
            f"{wall_id}-v0", PreviewRunStatus.COMPLETED, "OK", publication
        ),
    )
    with pytest.raises(DomainError, match="status"):
        PreviewWallResult(
            wall_id,
            PreviewWallStatus.COMPLETED,
            "PERSIST_FAILED",
            (item,),
            1.0,
            None,
        )
