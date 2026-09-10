"""Tests for the explicit, audited Preview LCM context migration."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from tests.unit.production.test_context_config import (
    _load,
    _read_document,
    _write_document,
    _write_roots,
)

SCRIPT = (
    Path(__file__).parents[3] / "deployment/amd/scripts/enable_preview_lcm_context.py"
)


def load_migrator():
    spec = importlib.util.spec_from_file_location("enable_preview_lcm_context", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit(tmp_path: Path) -> Path:
    path = tmp_path / "audit"
    path.mkdir(mode=0o700)
    return path


def _replace_context(config: Path, raw: bytes) -> None:
    staged = config / ".test-context-swap"
    staged.write_bytes(raw)
    staged.chmod(0o600)
    os.replace(staged, config / "context.json")


def _migrate(module, config: Path, evidence: Path, audit: Path, **changes):
    arguments = {
        "config_root": config,
        "context_evidence_root": evidence,
        "audit_root": audit,
        "expected_before_sha256": _sha(config / "context.json"),
        "apply": True,
    }
    arguments.update(changes)
    return module.migrate_preview_lcm_context(**arguments)


def test_apply_changes_only_three_canonical_model_pipeline_lists(
    tmp_path: Path,
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = _read_document(config)

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "APPLIED"
    assert (
        result["before_sha256"]
        != result["after_sha256"]
        == _sha(config / "context.json")
    )
    after = _read_document(config)
    expected = json.loads(json.dumps(before))
    for support in expected["model_support"]:
        support["supported_pipelines"] = ["sdxl_turbo", "lcm", "sdxl_base"]
    assert after == expected
    context = _load(config, evidence)
    from specstyle.production.context_config import require_model_pipeline_support

    require_model_pipeline_support(context, "lcm", ("base", "ip_adapter", "controlnet"))
    assert sorted(path.name for path in audit.iterdir()) == sorted(
        (
            f"context-before-{result['before_sha256']}.json",
            "migration-enable-preview-lcm-"
            f"{result['before_sha256']}-{result['after_sha256']}.committed.json",
            "migration-enable-preview-lcm-"
            f"{result['before_sha256']}-{result['after_sha256']}.prepared.json",
            "production-context-migration.lock",
        )
    )


def test_dry_run_validates_but_writes_nothing(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()

    result = _migrate(module, config, evidence, audit, apply=False)

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "DRY_RUN"
    assert (config / "context.json").read_bytes() == before
    assert list(audit.iterdir()) == []


def test_already_enabled_is_idempotent_without_rewrite(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    first = _migrate(module, config, evidence, audit)
    path = config / "context.json"
    identity = (path.stat().st_ino, path.stat().st_mtime_ns)

    result = module.migrate_preview_lcm_context(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=first["before_sha256"],
        apply=True,
    )

    assert result["status"] == "ALREADY_ENABLED"
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == identity


@pytest.mark.parametrize("mutation", ("partial", "order", "unknown"))
def test_refuses_noncanonical_or_partial_model_support_without_writes(
    tmp_path: Path, mutation: str
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    document = _read_document(config)
    if mutation == "partial":
        document["model_support"][0]["supported_pipelines"].insert(1, "lcm")
    elif mutation == "order":
        document["model_support"][0]["supported_pipelines"].reverse()
    else:
        document["model_support"][0]["supported_pipelines"].insert(1, "other")
    _write_document(config, document)
    before = (config / "context.json").read_bytes()

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "REFUSED"
    assert (config / "context.json").read_bytes() == before
    assert list(audit.iterdir()) == [audit / "production-context-migration.lock"]


def test_expected_digest_mismatch_refuses_before_audit_or_write(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()

    result = _migrate(
        module,
        config,
        evidence,
        audit,
        expected_before_sha256="f" * 64,
    )

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "EXPECTED_DIGEST_MISMATCH"
    assert (config / "context.json").read_bytes() == before


def test_staging_failure_leaves_original_and_no_hidden_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()
    engine = module.engine
    real_validate = engine._validate_snapshot

    def fail_target(snapshot, plan, *, source: bool) -> None:
        if not source:
            raise engine.ContextMigrationError("injected")
        real_validate(snapshot, plan, source=source)

    monkeypatch.setattr(engine, "_validate_snapshot", fail_target)

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "REFUSED"
    assert (config / "context.json").read_bytes() == before
    assert not list(config.glob(".production-context-*"))


def test_staging_write_failure_leaves_original_and_no_hidden_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()
    engine = module.engine
    real_write_all = engine._write_all
    calls = 0

    def fail_staged_write(descriptor: int, value: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise engine.ContextMigrationError("injected staged write")
        real_write_all(descriptor, value)

    monkeypatch.setattr(engine, "_write_all", fail_staged_write)

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "REFUSED"
    assert (config / "context.json").read_bytes() == before
    assert not list(config.glob(".production-context-*"))


def test_post_publish_validation_failure_rolls_back_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()
    engine = module.engine
    real_validate = engine._validate_snapshot
    target_calls = 0

    def fail_second_target(snapshot, plan, *, source: bool) -> None:
        nonlocal target_calls
        if not source:
            target_calls += 1
            if target_calls == 2:
                raise engine.ContextMigrationError("injected post validation")
        real_validate(snapshot, plan, source=source)

    monkeypatch.setattr(engine, "_validate_snapshot", fail_second_target)

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "ROLLED_BACK"
    assert (config / "context.json").read_bytes() == before
    assert not list(config.glob(".production-context-*"))


def test_config_directory_fsync_failure_after_replace_rolls_back_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()
    config_inode = config.stat().st_ino
    engine = module.engine
    real_fsync = engine.os.fsync
    failed = False

    def fail_after_replace(descriptor: int) -> None:
        nonlocal failed
        online = (config / "context.json").read_bytes()
        if (
            not failed
            and os.fstat(descriptor).st_ino == config_inode
            and online != before
        ):
            failed = True
            raise OSError("injected config directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(engine.os, "fsync", fail_after_replace)

    result = _migrate(module, config, evidence, audit)

    assert failed
    assert result["status"] == "ROLLED_BACK"
    assert (config / "context.json").read_bytes() == before
    assert not list(config.glob(".production-context-*"))


def test_committed_audit_sync_failure_rolls_back_without_false_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before = (config / "context.json").read_bytes()
    audit_inode = audit.stat().st_ino
    engine = module.engine
    real_fsync = engine.os.fsync
    failed = False

    def fail_committed_sync(descriptor: int) -> None:
        nonlocal failed
        committed = list(audit.glob("*.committed.json"))
        if not failed and os.fstat(descriptor).st_ino == audit_inode and committed:
            failed = True
            raise OSError("injected committed audit sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(engine.os, "fsync", fail_committed_sync)

    result = _migrate(module, config, evidence, audit)

    assert failed
    assert result["status"] == "ROLLED_BACK"
    assert (config / "context.json").read_bytes() == before
    assert not list(audit.glob("*.committed.json"))


def test_rerun_completes_commit_audit_after_crash_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before_sha256 = _sha(config / "context.json")
    engine = module.engine
    real_write_once = engine._write_once

    class SimulatedCrash(BaseException):
        pass

    def crash_before_commit(root_fd: int, name: str, value: bytes) -> None:
        if name.endswith(".committed.json"):
            raise SimulatedCrash
        real_write_once(root_fd, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_write_once", crash_before_commit)
        with pytest.raises(SimulatedCrash):
            _migrate(module, config, evidence, audit)

    assert _sha(config / "context.json") != before_sha256
    assert list(audit.glob("*.prepared.json"))
    assert not list(audit.glob("*.committed.json"))

    result = module.migrate_preview_lcm_context(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=before_sha256,
        apply=True,
    )

    assert result["status"] == "ALREADY_ENABLED"
    assert result["reason_code"] == "RECOVERED_COMMIT"
    assert list(audit.glob("*.committed.json"))


def test_rerun_recovers_after_partial_committed_temp_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    before_sha256 = _sha(config / "context.json")
    engine = module.engine
    real_write_all = engine._write_all
    calls = 0

    class SimulatedCrash(BaseException):
        pass

    def crash_during_committed_write(descriptor: int, value: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            os.write(descriptor, b"x")
            raise SimulatedCrash
        real_write_all(descriptor, value)

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_write_all", crash_during_committed_write)
        with pytest.raises(SimulatedCrash):
            _migrate(module, config, evidence, audit)

    assert _sha(config / "context.json") != before_sha256
    assert not list(audit.glob("*.committed.json"))
    assert list(audit.glob(".*.committed.json.tmp-*"))

    result = module.migrate_preview_lcm_context(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=before_sha256,
        apply=True,
    )

    assert result["status"] == "ALREADY_ENABLED"
    assert result["reason_code"] == "RECOVERED_COMMIT"
    assert list(audit.glob("*.committed.json"))
    assert not list(audit.glob(".*.tmp-*"))


def test_apply_refuses_target_swap_before_committed_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    engine = module.engine
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    source = (config / "context.json").read_bytes()
    real_validate = engine._validate_snapshot
    target_calls = 0

    def swap_after_online_validation(snapshot, plan, *, source: bool) -> None:
        nonlocal target_calls
        real_validate(snapshot, plan, source=source)
        if not source:
            target_calls += 1
            if target_calls == 2:
                _replace_context(config, source_bytes)

    source_bytes = source
    monkeypatch.setattr(engine, "_validate_snapshot", swap_after_online_validation)

    result = _migrate(module, config, evidence, audit)

    assert result["status"] == "ROLLED_BACK"
    assert (config / "context.json").read_bytes() == source
    assert not list(audit.glob("*.committed.json"))


def test_recovery_refuses_online_swap_before_committed_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    engine = module.engine
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    source = (config / "context.json").read_bytes()
    before_sha256 = hashlib.sha256(source).hexdigest()
    real_write_once = engine._write_once

    class SimulatedCrash(BaseException):
        pass

    def crash_before_commit(root_fd: int, name: str, value: bytes) -> None:
        if name.endswith(".committed.json"):
            raise SimulatedCrash
        real_write_once(root_fd, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(engine, "_write_once", crash_before_commit)
        with pytest.raises(SimulatedCrash):
            _migrate(module, config, evidence, audit)

    real_target_raw = engine._target_raw

    def swap_after_recovery_validation(plan, snapshot) -> bytes:
        target = real_target_raw(plan, snapshot)
        _replace_context(config, source)
        return target

    monkeypatch.setattr(engine, "_target_raw", swap_after_recovery_validation)
    result = module.migrate_preview_lcm_context(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=before_sha256,
        apply=True,
    )

    assert result["status"] == "REFUSED"
    assert (config / "context.json").read_bytes() == source
    assert not list(audit.glob("*.committed.json"))


def test_busy_lock_refuses_without_blocking_or_writing(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    lock = audit / "production-context-migration.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    descriptor = os.open(lock, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = _migrate(module, config, evidence, audit)
    finally:
        os.close(descriptor)

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "MIGRATION_BUSY"


def test_untrusted_lock_rejections_do_not_leak_descriptors(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence = _write_roots(tmp_path)
    audit = _audit(tmp_path)
    lock = audit / "production-context-migration.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o644)
    before = len(os.listdir("/dev/fd"))

    results = [_migrate(module, config, evidence, audit) for _ in range(20)]

    assert all(
        result["reason_code"] == "MIGRATION_LOCK_UNTRUSTED" for result in results
    )
    assert len(os.listdir("/dev/fd")) == before
