from __future__ import annotations

import json
import hashlib
import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId, JobId, RuleId, Sha256
from specstyle.exporting.bundle import ExportedFile
from specstyle.ui.app import UiServices
from specstyle.workflow.run_one import ProductionRunOneCleanupError
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)
from tests.unit.spec.test_compiler import raw_spec


class _NamedString(str):
    pass


def test_unavailable_production_binding_returns_exact_threshold_reason_without_work() -> (
    None
):
    from specstyle.ui.production_run import bind_unavailable_production_services

    def compile_spec(_text: str) -> object:
        return object()

    services = bind_unavailable_production_services(
        UiServices(compile_spec), "PRODUCTION_THRESHOLD_NOT_VALIDATED"
    )
    arguments = (None, None, None, "", "", None, None, None, "")

    single = services.run_production_job(*arguments)
    batch = services.run_production_batch(*arguments, 4)
    replay = services.run_replay(*arguments)

    assert services.compile_spec is compile_spec
    assert single.status == "JOB_FAILED"
    assert single.message == "PRODUCTION_THRESHOLD_NOT_VALIDATED"
    assert single.approved_images == single.rejected_images == ()
    assert batch.status == "JOB_FAILED"
    assert batch.message == "PRODUCTION_THRESHOLD_NOT_VALIDATED"
    assert batch.items == ()
    assert replay == "PRODUCTION_THRESHOLD_NOT_VALIDATED"


def _roots(tmp_path: Path):
    from specstyle.ui.production_run import ProductionUiRuntimePaths

    paths = {}
    for name in (
        "config_root",
        "evidence_root",
        "model_root",
        "state_root",
        "artifact_root",
        "style_asset_root",
        "export_root",
        "staging_root",
    ):
        value = tmp_path / name
        value.mkdir()
        paths[name] = value
    return ProductionUiRuntimePaths(**paths)


def _file(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    path.chmod(0o600)
    return str(path)


def _production_spec():
    return raw_spec().model_copy(
        update={
            "repair": raw_spec().repair.model_copy(update={"policy_version": "1.0"})
        }
    )


def _uploads(tmp_path: Path) -> tuple[str, str, str]:
    source = _file(tmp_path / "source.png", b"source-image")
    style = _file(tmp_path / "style.png", b"style-image")
    spec = _file(
        tmp_path / "style.json",
        json.dumps(
            _production_spec().model_dump(mode="json"), separators=(",", ":")
        ).encode(),
    )
    return source, style, spec


def _qa_report() -> VerificationReport:
    aid = ArtifactId("artifact-1")
    policy = GatePolicy("reject", "reject", "reject")
    rule = RuleDefinition(
        RuleId("l2_style"),
        RuleLevel.L2,
        RuleScope.ITEM,
        True,
        StaticApplicability.APPLICABLE,
        policy,
    )
    return VerificationReport(
        (ArtifactRef(aid, Sha256("b" * 64)),),
        (rule,),
        (RuleResult(RuleId("l2_style"), RuleStatus.UNVERIFIABLE, (aid,), None),),
    )


def _batch_result(
    job_id: str,
    variation_index: int,
    initial_seed: int,
    final_seed: int,
    *,
    final_variation_index: int | None = None,
    rejected: bool = False,
):
    final_variation = (
        variation_index if final_variation_index is None else final_variation_index
    )
    route = "rejected" if rejected else "approved/xhs_grid"
    filename = f"artifact-{job_id}.png"
    request = SimpleNamespace(
        variation_index=final_variation,
        seed=SimpleNamespace(variation_index=final_variation, seed=final_seed),
    )
    initial_request = SimpleNamespace(
        variation_index=variation_index,
        seed=SimpleNamespace(variation_index=variation_index, seed=initial_seed),
    )
    return SimpleNamespace(
        job_result=SimpleNamespace(
            report=None,
            request=request,
            history=SimpleNamespace(
                initial_attempt=SimpleNamespace(request=initial_request)
            ),
        ),
        export_result=SimpleNamespace(
            bundle=SimpleNamespace(
                bundle_name=f"bundle-{job_id}",
                bundle_sha256=Sha256("d" * 64),
                files=(ExportedFile(f"{route}/{filename}", Sha256("e" * 64), 3),),
            ),
            job_state=SimpleNamespace(
                job=SimpleNamespace(
                    job_id=JobId(job_id),
                    status=SimpleNamespace(value="COMPLETED"),
                )
            ),
        ),
    )


class _BatchExecution:
    def __init__(
        self,
        result: object | None = None,
        *,
        error: BaseException | None = None,
        cleanup_error: bool = False,
    ) -> None:
        self._result = result
        self._error = error
        self._cleanup_error = cleanup_error

    def run(self):
        if self._error is not None:
            raise self._error
        return self._result

    def close(self) -> None:
        if self._cleanup_error:
            raise ProductionRunOneCleanupError(self._result)  # type: ignore[arg-type]


def _batch_args(tmp_path: Path, *, spec: object | None = None) -> tuple[object, ...]:
    uploads = _uploads(tmp_path)
    if spec is not None:
        _file(
            Path(uploads[2]),
            json.dumps(spec.model_dump(mode="json"), separators=(",", ":")).encode(),
        )
    return (
        *uploads,
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )


def test_production_ui_service_runs_one_job_and_returns_export_evidence(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    source_bytes = b"source-image"
    style_bytes = b"style-image"
    spec = _production_spec().model_copy(
        update={
            "assets": _production_spec().assets.model_copy(
                update={
                    "style_references": (
                        _production_spec()
                        .assets.style_references[0]
                        .model_copy(update={"asset_sha256": Sha256("c" * 64).value}),
                    )
                }
            )
        }
    )
    source_path = _NamedString(_file(tmp_path / "source.png", source_bytes))
    style_path = _NamedString(_file(tmp_path / "style.png", style_bytes))
    spec_path = _NamedString(
        _file(
            tmp_path / "style.json",
            json.dumps(spec.model_dump(mode="json"), separators=(",", ":")).encode(),
        )
    )
    approved = roots.export_root / "bundle-run-one-ui" / "approved" / "xhs_grid"
    rejected = roots.export_root / "bundle-run-one-ui" / "rejected"
    approved.mkdir(parents=True)
    rejected.mkdir(parents=True)
    (approved / "artifact-approved.png").write_bytes(b"png")
    (rejected / "artifact-rejected.png").write_bytes(b"png")
    calls: dict[str, object] = {}

    class _Reservation:
        job_id = JobId("run-one-ui")

    class _Execution:
        job_id = JobId("run-one-ui")

        def run(self):
            calls["ran"] = True
            return SimpleNamespace(
                job_result=SimpleNamespace(report=_qa_report()),
                export_result=SimpleNamespace(
                    bundle=SimpleNamespace(
                        bundle_name="bundle-run-one-ui",
                        bundle_sha256=Sha256("d" * 64),
                        files=(
                            ExportedFile(
                                "approved/xhs_grid/artifact-approved.png",
                                Sha256("e" * 64),
                                3,
                            ),
                            ExportedFile(
                                "rejected/artifact-rejected.png",
                                Sha256("f" * 64),
                                3,
                            ),
                            ExportedFile("manifest.json", Sha256("a" * 64), 2),
                        ),
                    ),
                    job_state=SimpleNamespace(
                        job=SimpleNamespace(status=SimpleNamespace(value="COMPLETED"))
                    ),
                ),
            )

        def close(self) -> None:
            calls["closed"] = True

    def opener(fds, reservation):
        calls["job_id"] = reservation.job_id.value
        descriptors = (
            fds.config_root_fd,
            fds.evidence_root_fd,
            fds.model_root_fd,
            fds.state_root_fd,
            fds.artifact_root_fd,
            fds.style_asset_root_fd,
            fds.export_root_fd,
        )
        identities = {(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in descriptors}
        assert len(identities) == 7
        for fd in (fds.source_fd, fds.style_fd, fds.spec_fd, fds.metadata_fd):
            info = os.fstat(fd)
            assert stat.S_ISREG(info.st_mode)
            assert stat.S_IMODE(info.st_mode) == 0o600
        metadata = json.loads(os.pread(fds.metadata_fd, 65536, 0))
        calls["metadata"] = metadata
        return _Execution()

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: _Reservation(),
        open_run_one=opener,
    )

    view = service.run_production_job(
        source_path,
        style_path,
        spec_path,
        "soft product lighting",
        "watermark",
        "https://example.test/source",
        "CC0-1.0",
        "Example",
        "obtained",
    )

    assert view.job_id == "run-one-ui"
    assert view.status == "COMPLETED"
    assert view.profile_label == "production"
    assert view.bundle_name == "bundle-run-one-ui"
    assert view.approved_images == (str(approved / "artifact-approved.png"),)
    assert view.rejected_images == (str(rejected / "artifact-rejected.png"),)
    assert "UNVERIFIABLE" in view.qa_table
    assert "\tpass" not in view.qa_table
    assert calls["job_id"] == "run-one-ui"
    assert calls["ran"] is True
    assert calls["closed"] is True
    assert calls["metadata"] == {
        "schema_version": "specstyle.production.job_input.v1",
        "source": {
            "asset_id": f"source-{hashlib.sha256(source_bytes).hexdigest()[:16]}",
            "credit": {
                "source_url": "https://example.test/source",
                "license": "CC0-1.0",
                "attribution": "Example",
                "consent": "obtained",
            },
        },
        "style": {"asset_id": f"style-{hashlib.sha256(style_bytes).hexdigest()[:16]}"},
        "prompt": {
            "template_pin": {
                "id": "ui-prompt-template",
                "revision": "v1",
                "sha256": (
                    "52e3054077274103b29878dc23626312ed3c4b27d4596579635d1af7bb90f84e"
                ),
            },
            "preset_id": "preset",
            "positive": "soft product lighting",
            "negative": "watermark",
        },
    }
    assert list(roots.staging_root.iterdir()) == []


def test_production_ui_service_rejects_missing_upload_without_opening(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    called = False

    def opener(_fds, _reservation):
        nonlocal called
        called = True
        raise AssertionError("should not open run_one")

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        _roots(tmp_path),
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-ui")),
        open_run_one=opener,
    )

    view = service.run_production_job(
        None,
        "style.png",
        "style.json",
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert called is False
    assert view.status == "JOB_FAILED"
    assert view.message == "source upload required"


def test_production_ui_service_cleans_staging_after_open_failure(
    tmp_path: Path,
) -> None:
    from specstyle.errors import InfrastructureError
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    source_path = _file(tmp_path / "source.png", b"source-image")
    style_path = _file(tmp_path / "style.png", b"style-image")
    spec_path = _file(
        tmp_path / "style.json",
        json.dumps(
            _production_spec().model_dump(mode="json"), separators=(",", ":")
        ).encode(),
    )

    def opener(_fds, _reservation):
        raise InfrastructureError("open failed")

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-ui")),
        open_run_one=opener,
    )

    view = service.run_production_job(
        source_path,
        style_path,
        spec_path,
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )

    assert view.status == "JOB_FAILED"
    assert view.message == "open failed"
    assert list(roots.staging_root.iterdir()) == []


def test_production_runtime_paths_reject_staging_alias(tmp_path: Path) -> None:
    from specstyle.errors import DomainError
    from specstyle.ui.production_run import ProductionUiRuntimePaths

    roots = _roots(tmp_path)
    values = {name: getattr(roots, name) for name in roots.__slots__}
    values["staging_root"] = roots.config_root

    with pytest.raises(DomainError, match="production runtime roots must be distinct"):
        ProductionUiRuntimePaths(**values)


def test_production_ui_service_allows_only_one_pipeline_lifecycle(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    uploads = _uploads(tmp_path)
    first_running = threading.Event()
    release_first = threading.Event()
    reservations: list[str] = []

    class _Execution:
        def __init__(self, sequence: int) -> None:
            self.sequence = sequence

        def run(self):
            if self.sequence == 1:
                first_running.set()
                assert release_first.wait(timeout=2)
            return SimpleNamespace(
                job_result=SimpleNamespace(report=None),
                export_result=SimpleNamespace(
                    bundle=SimpleNamespace(
                        bundle_name=f"bundle-run-one-{self.sequence}",
                        bundle_sha256=Sha256("d" * 64),
                        files=(),
                    ),
                    job_state=SimpleNamespace(
                        job=SimpleNamespace(status=SimpleNamespace(value="COMPLETED"))
                    ),
                ),
            )

        def close(self) -> None:
            pass

    def reserve():
        value = f"run-one-{len(reservations) + 1}"
        reservations.append(value)
        return SimpleNamespace(job_id=JobId(value))

    def opener(_fds, _reservation):
        return _Execution(len(reservations))

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    results = []

    def run_first() -> None:
        results.append(
            service.run_production_job(
                *uploads,
                "positive",
                "",
                None,
                None,
                None,
                "not_applicable",
            )
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    assert first_running.wait(timeout=2)

    busy = service.run_production_job(
        *uploads,
        "positive",
        "",
        None,
        None,
        None,
        "not_applicable",
    )
    release_first.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert busy.status == "BUSY"
    assert busy.message == "production run busy"
    assert reservations == ["run-one-1"]
    assert len(results) == 1
    assert results[0].status == "COMPLETED"


def test_production_batch_runs_four_disjoint_variation_ranges_and_emits_tsv(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    variations: list[int] = []

    def reserve(variation_index: int):
        variations.append(variation_index)
        return SimpleNamespace(
            job_id=JobId(f"run-one-{len(variations)}"),
            variation_index=variation_index,
        )

    def opener(_fds, reservation):
        index = len(variations)
        variation = reservation.variation_index
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                variation,
                1000 + index,
                2000 + index,
            )
        )

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )

    view = service.run_production_batch(*_batch_args(tmp_path), 4)

    assert variations == [0, 2, 4, 6]
    assert view.status == "COMPLETED"
    assert view.profile_label == "production"
    assert view.final_seed_collision is False
    assert view.diversity_evidence is True
    assert tuple(item.item_index for item in view.items) == (0, 1, 2, 3)
    assert tuple(item.requested_variation_index for item in view.items) == (0, 2, 4, 6)
    assert tuple(item.initial_seed for item in view.items) == (1001, 1002, 1003, 1004)
    assert tuple(item.final_seed for item in view.items) == (2001, 2002, 2003, 2004)
    assert all(
        item.final_variation_index == item.requested_variation_index
        for item in view.items
    )
    assert len(view.approved_images) == 4
    assert view.rejected_images == ()
    assert view.evidence_tsv.splitlines()[0].startswith(
        "item_index\trequested_variation"
    )
    assert "VALID_DIVERSITY_EVIDENCE" in view.evidence_tsv
    assert list(roots.staging_root.iterdir()) == []


@pytest.mark.parametrize("count", (True, 1, 5, 2.0))
def test_production_batch_rejects_noncontract_count_without_staging_or_reserve(
    tmp_path: Path, count: object
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    reservations: list[int] = []
    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda variation: reservations.append(variation),
        open_run_one=lambda *_args: pytest.fail("open not expected"),
    )

    view = service.run_production_batch(*_batch_args(tmp_path), count)

    assert view.status == "JOB_FAILED"
    assert view.message == "batch count must be an exact int from 2 to 4"
    assert reservations == []
    assert list(roots.staging_root.iterdir()) == []


def test_production_batch_validates_full_spec_contract_before_first_reserve(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    raw = _production_spec().model_copy(
        update={
            "repair": _production_spec().repair.model_copy(update={"max_rounds": 2})
        }
    )
    reservations: list[int] = []
    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda variation: reservations.append(variation),
        open_run_one=lambda *_args: pytest.fail("open not expected"),
    )

    view = service.run_production_batch(*_batch_args(tmp_path, spec=raw), 2)

    assert view.status == "JOB_FAILED"
    assert view.message == "invalid production job input"
    assert reservations == []
    assert list(roots.staging_root.iterdir()) == []


def test_production_batch_keeps_completed_cleanup_result_and_continues_failures(
    tmp_path: Path,
) -> None:
    from specstyle.errors import InfrastructureError
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    variations: list[int] = []

    def reserve(variation_index: int):
        variations.append(variation_index)
        return SimpleNamespace(
            job_id=JobId(f"run-one-{len(variations)}"),
            variation_index=variation_index,
        )

    def opener(_fds, reservation):
        sequence = len(variations)
        if sequence == 2:
            return _BatchExecution(
                error=InfrastructureError("run\tfailed\ncleanly"),
                cleanup_error=True,
            )
        result = _batch_result(
            reservation.job_id.value,
            reservation.variation_index,
            100 + sequence,
            200 + sequence,
        )
        return _BatchExecution(result, cleanup_error=sequence == 1)

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )

    view = service.run_production_batch(*_batch_args(tmp_path), 3)

    assert variations == [0, 2, 4]
    assert view.status == "PARTIAL"
    assert tuple(item.run.status for item in view.items) == (
        "COMPLETED",
        "JOB_FAILED",
        "COMPLETED",
    )
    assert view.items[0].cleanup_error == "production run-one cleanup failed"
    assert view.items[0].run.bundle_name == "bundle-run-one-1"
    assert view.items[1].initial_seed is None
    assert view.items[1].final_seed is None
    assert view.items[1].cleanup_error == "production run-one cleanup failed"
    assert view.items[2].run.bundle_name == "bundle-run-one-3"
    assert "run failed cleanly" in view.evidence_tsv
    assert all("\tfailed\n" not in line for line in view.evidence_tsv.splitlines())
    assert list(roots.staging_root.iterdir()) == []


def test_rejected_batch_can_complete_but_seed_collision_blocks_diversity_claim(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    variations: list[int] = []

    def reserve(variation_index: int):
        variations.append(variation_index)
        return SimpleNamespace(
            job_id=JobId(f"run-one-{len(variations)}"),
            variation_index=variation_index,
        )

    def opener(_fds, reservation):
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100 + len(variations),
                999,
                rejected=True,
            )
        )

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )

    view = service.run_production_batch(*_batch_args(tmp_path), 2)

    assert view.status == "COMPLETED"
    assert view.final_seed_collision is True
    assert view.diversity_evidence is False
    assert view.approved_images == ()
    assert len(view.rejected_images) == 2
    assert "NOT_DIVERSITY_EVIDENCE_FINAL_SEED_COLLISION" in view.evidence_tsv
    assert all(item.run.status == "COMPLETED" for item in view.items)


def test_production_batch_rejects_final_variation_outside_its_repair_range(
    tmp_path: Path,
) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    variations: list[int] = []

    def reserve(variation_index: int):
        variations.append(variation_index)
        return SimpleNamespace(
            job_id=JobId(f"run-one-{len(variations)}"),
            variation_index=variation_index,
        )

    def opener(_fds, reservation):
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100 + len(variations),
                200 + len(variations),
                final_variation_index=2,
            )
        )

    service = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )

    view = service.run_production_batch(*_batch_args(tmp_path), 2)

    assert variations == [0, 2]
    assert view.status == "PARTIAL"
    assert view.items[0].run.status == "JOB_FAILED"
    assert view.items[0].run.message == "production batch evidence unavailable"
    assert view.items[1].run.status == "COMPLETED"
