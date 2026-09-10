"""Command-line adapter for the offline calibration evidence protocol."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from specstyle.calibration.evidence import prepare_evidence, reveal_test
from specstyle.errors import DomainError


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    for flag in (
        "study-plan",
        "annotation-protocol",
        "sample-manifest",
        "calibration-observations",
        "validation-observations",
        "test-commitment",
        "label-approval-receipt",
    ):
        prepare.add_argument(f"--{flag}", required=True, type=Path)
    prepare.add_argument("--out", required=True, type=Path)
    reveal = commands.add_parser("reveal-test")
    for flag in (
        "prepared-evidence",
        "test-observations",
        "reveal-authorization-receipt",
    ):
        reveal.add_argument(f"--{flag}", required=True, type=Path)
    reveal.add_argument("--out", required=True, type=Path)
    return parser


def _read(path: Path, name: str) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise DomainError(f"invalid {name} path")
        return path.read_bytes()
    except DomainError:
        raise
    except OSError as exc:
        raise DomainError(f"unable to read {name}") from exc


def _write_new(path: Path, content: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise DomainError("invalid evidence output directory")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise DomainError("evidence output already exists") from exc
    except OSError as exc:
        raise DomainError("unable to create evidence output") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _prepare(arguments: argparse.Namespace) -> bytes:
    return prepare_evidence(
        _read(arguments.study_plan, "study plan"),
        _read(arguments.annotation_protocol, "annotation protocol"),
        _read(arguments.sample_manifest, "sample manifest"),
        _read(arguments.calibration_observations, "calibration observations"),
        _read(arguments.validation_observations, "validation observations"),
        _read(arguments.test_commitment, "test commitment"),
        _read(arguments.label_approval_receipt, "label approval receipt"),
    )


def _reveal(arguments: argparse.Namespace) -> bytes:
    return reveal_test(
        _read(arguments.prepared_evidence, "prepared evidence"),
        _read(arguments.test_observations, "test observations"),
        _read(
            arguments.reveal_authorization_receipt,
            "reveal authorization receipt",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the offline prepare or explicit test-reveal command."""
    arguments = _argument_parser().parse_args(argv)
    content = (
        _prepare(arguments) if arguments.command == "prepare" else _reveal(arguments)
    )
    _write_new(arguments.out, content)
    status = json.loads(content)["status"]
    return (
        0
        if status
        in {
            "VALIDATION_PASSED",
            "TEST_PASSED_PENDING_PRODUCTION_APPROVAL",
        }
        else 2
    )


def run() -> None:
    try:
        raise SystemExit(main())
    except DomainError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
