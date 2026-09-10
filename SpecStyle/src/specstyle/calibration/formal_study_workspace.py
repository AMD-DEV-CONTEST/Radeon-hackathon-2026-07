"""Offline operator workspace for formal metric evidence and approvals."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from specstyle.calibration.formal_approval import (
    ApprovedMetricBinding,
    MetricEvidenceChain,
    ValidatedProfileApproval,
    validate_metric_production_approval,
    validate_profile_approval,
)
from specstyle.calibration.evidence_io import _load_canonical, _pin
from specstyle.calibration.formal_evidence import (
    prepare_metric_evidence,
    reveal_metric_test,
)
from specstyle.errors import DomainError, InfrastructureError
from specstyle.domain.identifiers import Sha256
from specstyle.spec.compiled_models import ResourcePin

__all__ = (
    "prepare_workspace",
    "reveal_workspace",
    "validate_metric_workspace",
    "validate_profile_workspace",
)

_MAX_DOCUMENT = 16 * 1024 * 1024
_PREPARE_INPUTS = (
    "target_cell.json",
    "study_plan.json",
    "annotation_protocol.json",
    "sample_manifest.json",
    "calibration_observations.json",
    "validation_observations.json",
    "test_commitment.json",
    "label_approval_receipt.json",
)


def _invalid() -> None:
    raise DomainError("invalid formal study workspace") from None


def _unavailable() -> None:
    raise InfrastructureError("formal study workspace unavailable") from None


def _root(value: object) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _invalid()
    try:
        observed = value.lstat()
    except OSError:
        _invalid()
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_uid != os.geteuid()
        or stat.S_IMODE(observed.st_mode) != 0o700
    ):
        _invalid()
    return value


def _read(root: Path, name: str) -> bytes:
    path = root / name
    try:
        observed = path.lstat()
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or stat.S_IMODE(observed.st_mode) != 0o600
            or not 1 <= observed.st_size <= _MAX_DOCUMENT
        ):
            _invalid()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except DomainError:
        raise
    except OSError:
        _invalid()
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            observed.st_dev,
            observed.st_ino,
            observed.st_size,
        ):
            _invalid()
        content = os.read(fd, observed.st_size + 1)
    except OSError:
        _unavailable()
    finally:
        os.close(fd)
    if len(content) != observed.st_size or b"${" in content:
        _invalid()
    return content


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(fd, content[offset:])
        except OSError:
            _unavailable()
        if written <= 0:
            _unavailable()
        offset += written


def _write_output(root: Path, name: str, content: bytes) -> Path:
    path = root / name
    if path.exists():
        if _read(root, name) != content:
            raise DomainError("formal study output drift") from None
        return path
    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    except FileExistsError:
        if _read(root, name) != content:
            raise DomainError("formal study output drift") from None
        return path
    except OSError:
        _unavailable()
    try:
        _write_all(fd, content)
        os.fsync(fd)
    except OSError:
        _unavailable()
    finally:
        os.close(fd)
    try:
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        os.fsync(directory_fd)
        os.close(directory_fd)
    except OSError:
        _unavailable()
    return path


def prepare_workspace(workspace: Path, /) -> Path:
    """Prepare calibration/validation evidence without reading test labels."""
    root = _root(workspace)
    values = tuple(_read(root, name) for name in _PREPARE_INPUTS)
    prepared = prepare_metric_evidence(*values)
    return _write_output(root, "prepared_evidence.json", prepared)


def reveal_workspace(workspace: Path, /) -> Path:
    """Reveal the precommitted test set after an external reveal approval."""
    root = _root(workspace)
    revealed = reveal_metric_test(
        _read(root, "target_cell.json"),
        _read(root, "prepared_evidence.json"),
        _read(root, "sealed_test_observations.json"),
        _read(root, "reveal_receipt.json"),
    )
    return _write_output(root, "test_reveal.json", revealed)


def _chain(root: Path) -> MetricEvidenceChain:
    return MetricEvidenceChain(
        study_plan=_read(root, "study_plan.json"),
        annotation_protocol=_read(root, "annotation_protocol.json"),
        sample_manifest=_read(root, "sample_manifest.json"),
        calibration_observations=_read(root, "calibration_observations.json"),
        validation_observations=_read(root, "validation_observations.json"),
        test_commitment=_read(root, "test_commitment.json"),
        label_approval_receipt=_read(root, "label_approval_receipt.json"),
        prepared_evidence=_read(root, "prepared_evidence.json"),
        test_observations=_read(root, "sealed_test_observations.json"),
        reveal_authorization_receipt=_read(root, "reveal_receipt.json"),
        test_reveal=_read(root, "test_reveal.json"),
    )


def validate_metric_workspace(workspace: Path, /) -> ApprovedMetricBinding:
    """Validate the complete chain and a separately issued Production approval."""
    root = _root(workspace)
    return validate_metric_production_approval(
        _read(root, "target_cell.json"),
        _chain(root),
        _read(root, "metric_production_approval.json"),
    )


def _profile_pin(root: Path) -> ResourcePin:
    raw = _pin(
        _load_canonical(_read(root, "threshold_profile_pin.json")),
        "threshold profile pin",
    )
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def validate_profile_workspace(
    workspace: Path,
    metric_workspaces: tuple[Path, ...],
    /,
) -> ValidatedProfileApproval:
    """Validate one exact L2 or L3 envelope over approved metric chains."""
    root = _root(workspace)
    if (
        type(metric_workspaces) is not tuple
        or not metric_workspaces
        or any(not isinstance(item, Path) for item in metric_workspaces)
    ):
        _invalid()
    bindings = tuple(validate_metric_workspace(item) for item in metric_workspaces)
    return validate_profile_approval(
        _read(root, "target_cell.json"),
        bindings,
        _read(root, "profile_approval.json"),
        _profile_pin(root),
    )


def _summary(binding: ApprovedMetricBinding) -> str:
    return json.dumps(
        {
            "metric_approval_sha256": binding.metric_approval_sha256.value,
            "metric_id": binding.metric_id.value,
            "observation_unit": binding.observation_unit,
            "operator": binding.operator,
            "status": "VALIDATED",
            "target_cell_sha256": binding.target_cell_sha256.value,
            "threshold": binding.threshold,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _profile_summary(approval: ValidatedProfileApproval) -> str:
    return json.dumps(
        {
            "metric_ids": [item.metric_id.value for item in approval.metrics],
            "profile_approval_sha256": approval.production_approval_sha256.value,
            "source": approval.source,
            "status": "VALIDATED",
            "target_cell_sha256": approval.target_cell_sha256.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "reveal", "validate", "validate-profile")
    )
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--metric-workspace", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    if args.command == "prepare":
        output = prepare_workspace(args.workspace)
        print(output)
    elif args.command == "reveal":
        output = reveal_workspace(args.workspace)
        print(output)
    elif args.command == "validate":
        print(_summary(validate_metric_workspace(args.workspace)))
    else:
        print(
            _profile_summary(
                validate_profile_workspace(args.workspace, tuple(args.metric_workspace))
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
