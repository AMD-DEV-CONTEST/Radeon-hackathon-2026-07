"""Small-batch runner isolation tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError
from specstyle.generation.fake_backend import FakeBackend
from specstyle.workflow.batch_runner import BatchItem, run_small_batch
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.orchestrator import FakeJobPlan
from specstyle.workflow.real_pipeline import CancelToken, PipelineServices
from tests.integration.test_fake_vertical_slice import (
    FakeVerifier,
    _CannyBuilder,
    _compiled,
    _context_with_style_low,
    _env,
    _plan,
    _prompt,
    _source,
    _spec_text,
)


def _root_fd(tmp_path: Path) -> int:
    return os.open(os.fspath(tmp_path), os.O_RDONLY | os.O_DIRECTORY)


def test_batch_rejects_oversized(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    plan = _plan()
    items = tuple(
        BatchItem(
            JobId(f"job{i}"),
            plan,
            f"b{i}",
            _spec_text(),
            _source(),
            _prompt(_compiled()),
            _CannyBuilder(),
        )
        for i in range(3)
    )
    with pytest.raises(DomainError, match="max_items"):
        run_small_batch(
            items,
            context=_context_with_style_low(),
            environment=_env(),
            job_store=JobStore(store_dir),
            root_fd=-1,
            services=PipelineServices(FakeBackend(), FakeVerifier()),
            max_items=2,
        )


def test_batch_happy_path_single_item(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    store = JobStore(store_dir)
    root = _root_fd(out)
    plan = _plan()
    items = (
        BatchItem(
            plan.job_id,
            plan,
            "batch-b1",
            _spec_text(),
            _source(),
            _prompt(_compiled()),
            _CannyBuilder(),
        ),
    )
    try:
        result = run_small_batch(
            items,
            context=_context_with_style_low(),
            environment=_env(),
            job_store=store,
            root_fd=root,
            services=PipelineServices(FakeBackend(), FakeVerifier()),
            max_items=8,
        )
    finally:
        os.close(root)
    assert result.completed == 1
    assert result.failed == 0
    assert result.results[0].bundle is not None


def test_batch_pre_cancelled_skips_work(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    store = JobStore(store_dir)
    root = _root_fd(out)
    token = CancelToken()
    token.cancel()
    plan = _plan()
    items = (
        BatchItem(
            plan.job_id,
            plan,
            "batch-c1",
            _spec_text(),
            _source(),
            _prompt(_compiled()),
            _CannyBuilder(),
        ),
    )
    try:
        result = run_small_batch(
            items,
            context=_context_with_style_low(),
            environment=_env(),
            job_store=store,
            root_fd=root,
            services=PipelineServices(FakeBackend(), FakeVerifier()),
            cancel=token,
            max_items=8,
        )
    finally:
        os.close(root)
    assert result.completed == 0
    assert result.cancelled >= 1


def test_batch_item_plan_type() -> None:
    plan = _plan()
    assert isinstance(plan, FakeJobPlan)
