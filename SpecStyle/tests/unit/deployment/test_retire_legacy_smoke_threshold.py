"""Tests for explicit retirement of the known AMD legacy smoke threshold."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from specstyle.errors import DomainError
from tests.unit.production.test_context_config import (
    _context_document,
    _load,
    _read_document,
    _write_document,
)

SCRIPT = (
    Path(__file__).parents[3]
    / "deployment/amd/scripts/retire_legacy_smoke_threshold.py"
)
_EVIDENCE = {
    "calibration_dataset_sha256": b"calibration manifest lookfile v1",
    "validation_dataset_sha256": b"validation manifest lookfile v1",
    "annotation_protocol_sha256": b"annotation protocol lookfile v1",
}


def load_migrator():
    spec = importlib.util.spec_from_file_location(
        "retire_legacy_smoke_threshold", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    config = tmp_path / "config"
    evidence = tmp_path / "evidence"
    audit = tmp_path / "audit"
    for path in (config, evidence, audit):
        path.mkdir(mode=0o700)
    digests = {
        key: hashlib.sha256(content).hexdigest() for key, content in _EVIDENCE.items()
    }
    for key, content in _EVIDENCE.items():
        digest = digests[key]
        directory = evidence / "sha256" / digest[:2]
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        (evidence / "sha256").chmod(0o700)
        target = directory / digest
        target.write_bytes(content)
        target.chmod(0o400)
    context = config / "context.json"
    context.write_text(
        json.dumps(
            _context_document(digests, status="VALIDATED"),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    context.chmod(0o600)
    return config, evidence, audit


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retire(module, config: Path, evidence: Path, audit: Path, **changes):
    arguments = {
        "config_root": config,
        "context_evidence_root": evidence,
        "audit_root": audit,
        "expected_before_sha256": _sha(config / "context.json"),
        "apply": True,
    }
    arguments.update(changes)
    return module.retire_legacy_smoke_threshold(**arguments)


def test_retires_only_known_smoke_status_and_target_passes_loader(
    tmp_path: Path,
) -> None:
    module = load_migrator()
    config, evidence, audit = _roots(tmp_path)
    before = _read_document(config)
    with pytest.raises(DomainError, match="requires production context v3"):
        _load(config, evidence)

    result = _retire(module, config, evidence, audit)

    assert result["status"] == "RETIRED"
    assert (
        result["before_sha256"]
        != result["after_sha256"]
        == _sha(config / "context.json")
    )
    after = _read_document(config)
    expected = json.loads(json.dumps(before))
    expected["l2_threshold_profile"]["status"] = "DRAFT"
    assert after == expected
    loaded = _load(config, evidence)
    assert loaded.schema_version == "specstyle.production.context.v1"
    assert loaded.l2_threshold_profile.status == "DRAFT"
    assert loaded.l2_threshold_profile.production_binding is None
    stem = (
        "migration-retire-legacy-smoke-threshold-"
        f"{result['before_sha256']}-{result['after_sha256']}"
    )
    assert sorted(path.name for path in audit.iterdir()) == sorted(
        (
            f"context-before-{result['before_sha256']}.json",
            f"{stem}.prepared.json",
            f"{stem}.committed.json",
            "production-context-migration.lock",
        )
    )


@pytest.mark.parametrize("mutation", ("schema", "pin", "metric", "evidence"))
def test_refuses_any_nonmatching_smoke_signature_without_context_write(
    tmp_path: Path, mutation: str
) -> None:
    module = load_migrator()
    config, evidence, audit = _roots(tmp_path)
    document = _read_document(config)
    if mutation == "schema":
        document["schema_version"] = "specstyle.production.context.v2"
        document["output_profiles"] = [document.pop("output_profile")]
    elif mutation == "pin":
        document["l2_threshold_profile"]["pin"]["revision"] = "other"
    elif mutation == "metric":
        document["l2_threshold_profile"]["metric"]["value"] = 0.9
    else:
        document["l2_threshold_profile"]["evidence"]["calibration_dataset_sha256"] = (
            "f" * 64
        )
    _write_document(config, document)
    before = (config / "context.json").read_bytes()

    result = _retire(module, config, evidence, audit)

    assert result["status"] == "REFUSED"
    assert (config / "context.json").read_bytes() == before
    assert not list(audit.glob("*.prepared.json"))


def test_expected_digest_mismatch_and_dry_run_never_write(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence, audit = _roots(tmp_path)
    before = (config / "context.json").read_bytes()

    mismatch = _retire(
        module,
        config,
        evidence,
        audit,
        expected_before_sha256="f" * 64,
    )
    dry_run = _retire(module, config, evidence, audit, apply=False)

    assert mismatch["reason_code"] == "EXPECTED_DIGEST_MISMATCH"
    assert dry_run["reason_code"] == "DRY_RUN"
    assert (config / "context.json").read_bytes() == before


def test_already_retired_is_idempotent_without_context_rewrite(tmp_path: Path) -> None:
    module = load_migrator()
    config, evidence, audit = _roots(tmp_path)
    first = _retire(module, config, evidence, audit)
    context = config / "context.json"
    identity = (context.stat().st_ino, context.stat().st_mtime_ns)

    result = module.retire_legacy_smoke_threshold(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=first["before_sha256"],
        apply=True,
    )

    assert result["status"] == "ALREADY_RETIRED"
    assert (context.stat().st_ino, context.stat().st_mtime_ns) == identity


def test_post_publish_failure_rolls_back_to_known_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    engine = module.engine
    config, evidence, audit = _roots(tmp_path)
    context = config / "context.json"
    before = context.read_bytes()
    real_validate = engine._validate_snapshot
    target_calls = 0

    def fail_online_target(snapshot, plan, *, source: bool) -> None:
        nonlocal target_calls
        if not source:
            target_calls += 1
            if target_calls == 2:
                raise engine.ContextMigrationError("injected post validation")
        real_validate(snapshot, plan, source=source)

    monkeypatch.setattr(engine, "_validate_snapshot", fail_online_target)

    result = _retire(module, config, evidence, audit)

    assert result["status"] == "ROLLED_BACK_TO_KNOWN_INVALID_SOURCE"
    assert context.read_bytes() == before
    with pytest.raises(DomainError, match="requires production context v3"):
        _load(config, evidence)
    assert not list(audit.glob("*.committed.json"))


def test_crash_after_publish_recovers_retirement_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_migrator()
    engine = module.engine
    config, evidence, audit = _roots(tmp_path)
    before_sha256 = _sha(config / "context.json")
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
            _retire(module, config, evidence, audit)

    assert _load(config, evidence).l2_threshold_profile.status == "DRAFT"
    result = module.retire_legacy_smoke_threshold(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=before_sha256,
        apply=True,
    )

    assert result["status"] == "ALREADY_RETIRED"
    assert result["reason_code"] == "RECOVERED_COMMIT"
    assert list(audit.glob("*.committed.json"))


def test_retirement_after_hash_is_required_for_separate_lcm_migration(
    tmp_path: Path,
) -> None:
    retirement = load_migrator()
    lcm_path = SCRIPT.with_name("enable_preview_lcm_context.py")
    spec = importlib.util.spec_from_file_location(
        "enable_preview_lcm_context", lcm_path
    )
    assert spec and spec.loader
    lcm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lcm)
    config, evidence, audit = _roots(tmp_path)

    retired = _retire(retirement, config, evidence, audit)
    enabled = lcm.migrate_preview_lcm_context(
        config_root=config,
        context_evidence_root=evidence,
        audit_root=audit,
        expected_before_sha256=retired["after_sha256"],
        apply=True,
    )

    assert retired["status"] == "RETIRED"
    assert enabled["status"] == "APPLIED"
    document = _read_document(config)
    assert document["l2_threshold_profile"]["status"] == "DRAFT"
    assert all(
        item["supported_pipelines"] == ["sdxl_turbo", "lcm", "sdxl_base"]
        for item in document["model_support"]
    )
