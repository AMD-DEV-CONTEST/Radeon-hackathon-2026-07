"""Durable idempotent phase journal for formal Production batches."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Identifier
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


def _root(tmp_path: Path) -> tuple[int, Path]:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY), root


def test_batch_journal_records_ordered_phases_and_accepts_exact_replay(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.production_batch import ProductionBatchPhase
    from specstyle.workflow.production_batch_journal import ProductionBatchJournal

    root_fd, root = _root(tmp_path)
    try:
        journal = ProductionBatchJournal(root_fd)
        batch_id = Identifier("batch-1")
        binding = hash_bytes(b"manifest")
        for phase in tuple(ProductionBatchPhase)[:-1]:
            journal.record(batch_id, phase, binding)
        journal.record(batch_id, ProductionBatchPhase.COMPLETED, hash_bytes(b"bundle"))
        for phase in tuple(ProductionBatchPhase)[:-1]:
            journal.record(batch_id, phase, binding)
        journal.record(batch_id, ProductionBatchPhase.COMPLETED, hash_bytes(b"bundle"))
        journal.close()

        files = sorted((root / "batches" / "batch-1").iterdir())
        assert [item.name for item in files] == [
            f"{index:02d}_{phase.value}.json"
            for index, phase in enumerate(ProductionBatchPhase)
        ]
    finally:
        os.close(root_fd)


def test_batch_journal_rejects_gap_binding_drift_and_symlink_root(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.production_batch import ProductionBatchPhase
    from specstyle.workflow.production_batch_journal import ProductionBatchJournal

    root_fd, root = _root(tmp_path)
    journal = ProductionBatchJournal(root_fd)
    try:
        batch_id = Identifier("batch-1")
        binding = hash_bytes(b"manifest")
        with pytest.raises(DomainError, match="^invalid production batch journal$"):
            journal.record(batch_id, ProductionBatchPhase.COHORT_FROZEN, binding)
        journal.record(batch_id, ProductionBatchPhase.CANDIDATES_READY, binding)
        with pytest.raises(DomainError, match="^production batch journal drift$"):
            journal.record(
                batch_id,
                ProductionBatchPhase.CANDIDATES_READY,
                hash_bytes(b"other"),
            )
        journal.close()
        os.symlink(root / "batches" / "batch-1", root / "batches" / "batch-link")
        reopened = ProductionBatchJournal(root_fd)
        with pytest.raises(DomainError, match="^invalid production batch journal$"):
            reopened.record(
                Identifier("batch-link"),
                ProductionBatchPhase.CANDIDATES_READY,
                binding,
            )
        reopened.close()
    finally:
        os.close(root_fd)


def test_atomic_batch_persists_resume_safe_phase_bindings(tmp_path: Path) -> None:
    from tests.unit.workflow.test_production_batch import _Publisher, _case

    from specstyle.workflow.production_batch import run_atomic_production_batch
    from specstyle.workflow.production_batch_journal import ProductionBatchJournal

    root_fd, _root_path = _root(tmp_path)
    try:
        journal = ProductionBatchJournal(root_fd)
        plan, target, reservation, candidates, verify = _case()
        publisher = _Publisher([])
        first = run_atomic_production_batch(
            reservation,
            target,
            plan,
            lambda _reservation: candidates,
            verify,
            publisher,
            journal=journal,
        )
        second = run_atomic_production_batch(
            reservation,
            target,
            plan,
            lambda _reservation: candidates,
            verify,
            _Publisher([]),
            journal=journal,
        )
        assert second.manifest == first.manifest
        journal.close()
    finally:
        os.close(root_fd)


def test_atomic_batch_resume_rejects_changed_batch_result(tmp_path: Path) -> None:
    from tests.unit.workflow.test_production_batch import _Publisher, _case

    from specstyle.domain.enums import RuleStatus
    from specstyle.errors import DomainError
    from specstyle.workflow.production_batch import (
        ProductionBatchPhase,
        run_atomic_production_batch,
    )
    from specstyle.workflow.production_batch_journal import ProductionBatchJournal

    root_fd, _root_path = _root(tmp_path)
    try:
        journal = ProductionBatchJournal(root_fd)
        plan, target, reservation, candidates, passing = _case(RuleStatus.PASS)
        cancelled = False

        def stop_after_result(phase: ProductionBatchPhase) -> None:
            nonlocal cancelled
            if phase is ProductionBatchPhase.BATCH_VERIFIED:
                cancelled = True

        with pytest.raises(DomainError, match="^production batch cancelled$"):
            run_atomic_production_batch(
                reservation,
                target,
                plan,
                lambda _reservation: candidates,
                passing,
                _Publisher([]),
                checkpoint=stop_after_result,
                cancelled=lambda: cancelled,
                journal=journal,
            )
        _plan, _target, _reservation, _candidates, failing = _case(RuleStatus.FAIL)
        with pytest.raises(DomainError, match="^production batch journal drift$"):
            run_atomic_production_batch(
                reservation,
                target,
                plan,
                lambda _reservation: candidates,
                failing,
                _Publisher([]),
                journal=journal,
            )
        journal.close()
    finally:
        os.close(root_fd)
