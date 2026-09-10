from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import json

import pytest

from specstyle.domain.identifiers import JobId, Sha256
from specstyle.errors import DomainError
from specstyle.ui.app import UiServices
from tests.unit.ui.test_production_run import (
    _BatchExecution,
    _batch_result,
    _roots,
    _production_spec,
    _uploads,
)


def _replay_evidence(job_id: str, form_fingerprint: Sha256):
    from specstyle.workflow.production_replay import (
        ProductionReplayEvidence,
        ReplayMetricObservation,
    )

    sequence = "a" if job_id.endswith("1") else "b"
    return ProductionReplayEvidence(
        job_id,
        f"bundle-{job_id}",
        Sha256(sequence * 64),
        Sha256(("c" if sequence == "a" else "d") * 64),
        form_fingerprint,
        Sha256("1" * 64),
        Sha256("2" * 64),
        Sha256("3" * 64),
        Sha256("4" * 64),
        Sha256("5" * 64),
        Sha256("6" * 64),
        Sha256("7" * 64),
        Sha256("8" * 64),
        "advisory",
        4,
        1234,
        (
            ReplayMetricObservation(
                "L2", "l2_style", "style_similarity", "PASS", 0.9, 0.02
            ),
        ),
        "NOT_APPLICABLE",
        "NO_L3_CONFIG",
    )


def test_same_input_replay_prechecks_form_before_reserving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    reservations: list[int | None] = []

    def reserve(variation: int | None = None) -> object:
        reservations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-replay-{len(reservations)}"),
            variation_index=0 if variation is None else variation,
        )

    def opener(_fds: object, reservation: object) -> object:
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100,
                200,
            )
        )

    monkeypatch.setattr(
        production_run,
        "_capture_replay_evidence",
        lambda result, form: _replay_evidence(
            result.export_result.job_state.job.job_id.value, form
        ),
    )
    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")

    first = services.run_production_job(*args)
    replay = services.run_replay(*args[:3], "changed prompt", *args[4:])

    assert first.status == "COMPLETED"
    assert replay == "REJECTED\tsame_input\tinput_form_fingerprint_mismatch"
    assert reservations == [None]
    assert list(roots.staging_root.iterdir()) == []


def test_same_input_replay_runs_new_job_with_original_variation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    reservations: list[int | None] = []

    def reserve(variation: int | None = None) -> object:
        reservations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-replay-{len(reservations)}"),
            variation_index=4 if variation is None else variation,
        )

    def opener(_fds: object, reservation: object) -> object:
        return _BatchExecution(
            _batch_result(
                reservation.job_id.value,
                reservation.variation_index,
                100,
                200,
            )
        )

    monkeypatch.setattr(
        production_run,
        "_capture_replay_evidence",
        lambda result, form: _replay_evidence(
            result.export_result.job_state.job.job_id.value, form
        ),
    )
    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")

    first = services.run_production_job(*args)
    replay = services.run_replay(*args)

    assert first.status == "COMPLETED"
    assert reservations == [None, 4]
    assert replay.startswith(
        "EXACT\tsame_input\tbaseline_job=run-one-replay-1\t"
        "replay_job=run-one-replay-2\t"
    )
    assert "artifact_hash_equal=NO" in replay
    assert "pixel_exact_required=NO" in replay
    assert "L2:l2_style=0" in replay
    assert "l3=NOT_APPLICABLE" in replay
    assert services.get_job_status().job_id == "run-one-replay-2"
    assert list(roots.staging_root.iterdir()) == []


def test_replay_form_uses_canonical_spec_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    reservations: list[int | None] = []

    def reserve(variation: int | None = None) -> object:
        reservations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-replay-{len(reservations)}"),
            variation_index=4 if variation is None else variation,
        )

    def opener(_fds: object, reservation: object) -> object:
        return _BatchExecution(
            _batch_result(reservation.job_id.value, reservation.variation_index, 1, 2)
        )

    monkeypatch.setattr(
        production_run,
        "_capture_replay_evidence",
        lambda result, form: _replay_evidence(
            result.export_result.job_state.job.job_id.value, form
        ),
    )
    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")
    assert services.run_production_job(*args).status == "COMPLETED"
    Path(args[2]).write_text(
        json.dumps(_production_spec().model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )

    replay = services.run_replay(*args)

    assert replay.startswith("EXACT\tsame_input")
    assert reservations == [None, 4]


def test_replay_shares_single_flight_with_active_production_run(tmp_path: Path) -> None:
    from specstyle.ui.production_run import bind_production_run_one_services

    roots = _roots(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class _Execution:
        def run(self) -> object:
            entered.set()
            assert release.wait(timeout=2)
            return _batch_result("run-one-busy", 0, 1, 2)

        def close(self) -> None:
            pass

    services = bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=lambda: SimpleNamespace(job_id=JobId("run-one-busy")),
        open_run_one=lambda _fds, _reservation: _Execution(),
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")
    thread = threading.Thread(target=lambda: services.run_production_job(*args))
    thread.start()
    assert entered.wait(timeout=2)

    replay = services.run_replay(*args)

    assert replay == "replay busy: production run active"
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_replay_cancel_uses_shared_execution_gate_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specstyle.ui import production_run

    roots = _roots(tmp_path)
    entered = threading.Event()
    cancelled = threading.Event()
    reservations: list[int | None] = []

    def reserve(variation: int | None = None) -> object:
        reservations.append(variation)
        return SimpleNamespace(
            job_id=JobId(f"run-one-replay-{len(reservations)}"),
            variation_index=4 if variation is None else variation,
        )

    class _ReplayExecution:
        def run(self) -> object:
            entered.set()
            assert cancelled.wait(timeout=2)
            raise DomainError("production job cancelled")

        def cancel(self, *, reason: str) -> object:
            assert reason == "user requested"
            cancelled.set()
            return SimpleNamespace(
                job=SimpleNamespace(status=SimpleNamespace(value="CANCELLED"))
            )

        def close(self) -> None:
            pass

    def opener(_fds: object, reservation: object) -> object:
        if len(reservations) == 1:
            return _BatchExecution(_batch_result(reservation.job_id.value, 4, 100, 200))
        return _ReplayExecution()

    monkeypatch.setattr(
        production_run,
        "_capture_replay_evidence",
        lambda result, form: _replay_evidence(
            result.export_result.job_state.job.job_id.value, form
        ),
    )
    services = production_run.bind_production_run_one_services(
        UiServices(lambda _text: pytest.fail("compile not used")),
        roots,
        reserve=reserve,
        open_run_one=opener,
    )
    args = (*_uploads(tmp_path), "positive", "", None, None, None, "not_applicable")
    assert services.run_production_job(*args).status == "COMPLETED"
    completed: list[str] = []
    thread = threading.Thread(
        target=lambda: completed.append(services.run_replay(*args))
    )
    thread.start()
    assert entered.wait(timeout=2)

    assert services.cancel_job() == "cancel requested; job status=CANCELLED"
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert completed == [
        "UNVERIFIABLE\tsame_input\treplay_evidence_unavailable=CANCELLED"
    ]
    assert services.get_job_status().status == "CANCELLED"
    assert list(roots.staging_root.iterdir()) == []
