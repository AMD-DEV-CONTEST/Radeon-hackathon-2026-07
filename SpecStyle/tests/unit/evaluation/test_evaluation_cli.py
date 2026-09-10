"""Offline formal-evaluation CLI has no generation execution surface."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from specstyle.errors import DomainError
from specstyle.evaluation.evaluation_cli import main

from tests.unit.evaluation._formal_fixtures import (
    blind_labels,
    label_approval_receipt,
    machine_ledger,
    protocol_document,
    sealed_protocol,
)


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_prepare_protocol_publishes_private_canonical_file_once(tmp_path: Path) -> None:
    source = _write(tmp_path / "draft.json", protocol_document())
    output = tmp_path / "prepared.json"

    assert main(["prepare-protocol", "--input", str(source), "--out", str(output)]) == 0
    assert output.read_bytes() == source.read_bytes()
    assert os.stat(output).st_mode & 0o777 == 0o600

    with pytest.raises(DomainError, match="already exists"):
        main(["prepare-protocol", "--input", str(source), "--out", str(output)])


def test_cli_exposes_validation_import_and_finalize_without_run(tmp_path: Path) -> None:
    protocol = protocol_document()
    sealed = sealed_protocol(protocol)
    ledger = machine_ledger(protocol, sealed)
    labels = blind_labels(protocol, sealed, ledger)
    approval = label_approval_receipt(protocol, sealed, ledger, labels)
    paths = {
        "protocol": _write(tmp_path / "protocol.json", protocol),
        "sealed": _write(tmp_path / "sealed.json", sealed),
        "ledger": _write(tmp_path / "ledger.json", ledger),
        "labels": _write(tmp_path / "labels.json", labels),
        "approval": _write(tmp_path / "approval.json", approval),
    }

    validate_out = tmp_path / "machine-validation.json"
    assert (
        main(
            [
                "validate-machine-ledger",
                "--protocol",
                str(paths["protocol"]),
                "--sealed-protocol",
                str(paths["sealed"]),
                "--machine-ledger",
                str(paths["ledger"]),
                "--out",
                str(validate_out),
            ]
        )
        == 0
    )
    assert json.loads(validate_out.read_bytes())["status"] == (
        "STRUCTURALLY_VALIDATED_AWAITING_BLIND_LABELS"
    )

    labels_out = tmp_path / "label-import.json"
    assert (
        main(
            [
                "import-blind-labels",
                "--protocol",
                str(paths["protocol"]),
                "--sealed-protocol",
                str(paths["sealed"]),
                "--machine-ledger",
                str(paths["ledger"]),
                "--blind-labels",
                str(paths["labels"]),
                "--label-approval-receipt",
                str(paths["approval"]),
                "--out",
                str(labels_out),
            ]
        )
        == 2
    )
    assert json.loads(labels_out.read_bytes())["status"] == "BLIND_LABELS_COMPLETE"

    final_out = tmp_path / "final.json"
    assert (
        main(
            [
                "finalize",
                "--protocol",
                str(paths["protocol"]),
                "--sealed-protocol",
                str(paths["sealed"]),
                "--machine-ledger",
                str(paths["ledger"]),
                "--blind-labels",
                str(paths["labels"]),
                "--label-approval-receipt",
                str(paths["approval"]),
                "--out",
                str(final_out),
            ]
        )
        == 2
    )
    final = json.loads(final_out.read_bytes())
    assert final["status"] == "FORMAL_PENDING_EXTERNAL_AUTHORIZATION"
    assert final["formal_eligible"] is False

    with pytest.raises(SystemExit):
        main(["run"])


def test_seal_protocol_fails_closed_before_writing_without_validated_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol = _write(tmp_path / "protocol.json", protocol_document())
    config = tmp_path / "config"
    evidence = tmp_path / "evidence"
    config.mkdir()
    evidence.mkdir()
    output = tmp_path / "sealed.json"
    monkeypatch.setattr(
        "specstyle.evaluation.evaluation_cli._load_production_context",
        lambda _config, _evidence: (object(), "d" * 64),
    )

    with pytest.raises(DomainError, match="PRODUCTION_THRESHOLD_NOT_VALIDATED"):
        main(
            [
                "seal-protocol",
                "--protocol",
                str(protocol),
                "--config-root",
                str(config),
                "--context-evidence-root",
                str(evidence),
                "--sealed-at",
                "2026-08-03T10:00:00Z",
                "--repo-sha",
                "c" * 64,
                "--out",
                str(output),
            ]
        )

    assert not output.exists()


def test_output_is_complete_before_atomic_no_replace_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "draft.json", protocol_document())
    output = tmp_path / "prepared.json"
    real_link = os.link
    observed: list[str] = []

    def inspect_link(source_name, target_name, **kwargs):
        source_fd = os.open(source_name, os.O_RDONLY, dir_fd=kwargs["src_dir_fd"])
        try:
            assert (
                os.read(source_fd, len(protocol_document()) + 1) == protocol_document()
            )
        finally:
            os.close(source_fd)
        with pytest.raises(FileNotFoundError):
            os.stat(
                target_name,
                dir_fd=kwargs["dst_dir_fd"],
                follow_symlinks=False,
            )
        observed.append(source_name)
        return real_link(source_name, target_name, **kwargs)

    monkeypatch.setattr(os, "link", inspect_link)

    assert main(["prepare-protocol", "--input", str(source), "--out", str(output)]) == 0
    assert observed and observed[0].startswith(".evaluation-")
    assert output.read_bytes() == protocol_document()
