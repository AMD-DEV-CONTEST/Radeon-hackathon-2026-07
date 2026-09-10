"""WF-003 real_pipeline — drive run_production_job, cancel, OOM, resume."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from specstyle.domain.identifiers import JobId
from specstyle.errors import DomainError
from specstyle.generation.fake_backend import FakeBackend
from specstyle.workflow.job_store import JobStore
from specstyle.workflow.real_pipeline import (
    CancelToken,
    PipelineServices,
    _FaultyBackend,
    assert_export_isolation,
    job_is_resumable,
    run_production_job,
)
from tests.integration.test_fake_vertical_slice import (
    FakeVerifier,
    _CannyBuilder,
    _compiled,
    _env,
    _materials,
    _plan,
    _prompt,
    _source,
    _spec_text,
    _context_with_style_low,
)


def _root_fd(tmp_path: Path) -> int:
    return os.open(os.fspath(tmp_path), os.O_RDONLY | os.O_DIRECTORY)


def _services(backend=None, verifier=None) -> PipelineServices:
    return PipelineServices(
        backend or FakeBackend(),
        verifier or FakeVerifier(),
    )


def _store(tmp_path: Path) -> JobStore:
    d = tmp_path / "store"
    d.mkdir(parents=True, exist_ok=True)
    return JobStore(d)


def test_run_production_job_approved_export(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (tmp_path / "out").mkdir()
    root = _root_fd(tmp_path / "out")
    try:
        result = run_production_job(
            spec_text=_spec_text(),
            context=_context_with_style_low(),
            source=_source(),
            prompt=_prompt(_compiled()),
            control_builder=_CannyBuilder(),
            environment=_env(),
            plan=_plan(),
            job_store=store,
            root_fd=root,
            bundle_name="prod1",
            services=_services(),
        )
    finally:
        os.close(root)
    assert result.final_status == "COMPLETED"
    assert result.bundle is not None
    assert_export_isolation(result)
    # resume: not resumable after COMPLETED
    assert job_is_resumable(store, JobId("wf002-job")) is False
    # second run short-circuits without re-export (bundle None on resume)
    root2 = _root_fd(tmp_path / "out")
    try:
        again = run_production_job(
            spec_text=_spec_text(),
            context=_context_with_style_low(),
            source=_source(),
            prompt=_prompt(_compiled()),
            control_builder=_CannyBuilder(),
            environment=_env(),
            plan=_plan(),
            job_store=store,
            root_fd=root2,
            bundle_name="prod1",
            services=_services(),
        )
    finally:
        os.close(root2)
    assert again.final_status == "COMPLETED"
    assert again.bundle is None  # resume short-circuit


def test_prestart_cancel_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (tmp_path / "out").mkdir()
    root = _root_fd(tmp_path / "out")
    token = CancelToken()
    token.cancel()
    try:
        with pytest.raises(DomainError, match="job cancelled"):
            run_production_job(
                spec_text=_spec_text(),
                context=_context_with_style_low(),
                source=_source(),
                prompt=_prompt(_compiled()),
                control_builder=_CannyBuilder(),
                environment=_env(),
                plan=_plan(),
                job_store=store,
                root_fd=root,
                bundle_name="cancel0",
                services=_services(),
                cancel=token,
            )
    finally:
        os.close(root)


def test_oom_fail_closed_no_bundle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (tmp_path / "out").mkdir()
    root = _root_fd(tmp_path / "out")
    backend = _FaultyBackend(
        FakeBackend(), fail_after=0, error_message="generation OOM"
    )
    try:
        result = run_production_job(
            spec_text=_spec_text(),
            context=_context_with_style_low(),
            source=_source(),
            prompt=_prompt(_compiled()),
            control_builder=_CannyBuilder(),
            environment=_env(),
            plan=_plan(),
            job_store=store,
            root_fd=root,
            bundle_name="oom1",
            services=_services(backend=backend),
        )
    finally:
        os.close(root)
    assert result.final_status == "JOB_FAILED"
    assert result.bundle is None
    assert_export_isolation(result)
    assert not (tmp_path / "out" / "oom1").exists()


def test_mid_cancel_during_generate_fail_closed(tmp_path: Path) -> None:
    """Cancel token checked on each generate — refuse after cancel."""
    from specstyle.workflow.real_pipeline import _CancellableBackend
    from tests.integration.test_fake_vertical_slice import _req0

    token = CancelToken()
    proxy = _CancellableBackend(FakeBackend(), token)
    token.cancel()
    compiled, source, prompt, env, env_hash = _materials()
    req = _req0(compiled, source, prompt, env_hash)
    with pytest.raises(DomainError, match="job cancelled"):
        proxy.generate(req)
    assert proxy.refused_after_cancel == 1
