#!/usr/bin/env python3
"""Create a fail-closed recovery seal for one cleanly interrupted A/B arm."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval_ab import (
    EvaluationError,
    JsonHttpClient,
    MANIFEST_SCHEMA,
    adapter_runtime_path,
    canonical_digest,
    read_api_key,
    reject_symlink_ancestors,
    sha256_file,
    verify_health,
    verify_identity_files,
    verify_service_process,
)
from summarize_ab import (
    SummaryError,
    capped_composition,
    jsonl_prefix_snapshot,
    load_arm,
    load_frozen_rows,
    select_capped_prefix,
    plan_prefix_sha256,
    validate_arm_identity,
    validate_records_against_test,
)


SEAL_SCHEMA = "rdk_model_ab_interrupted_recovery_seal.v1"
FROZEN_EVALUATOR_SHA256 = (
    "645f29a31afa510c313f8e979507babf5037446d33da6b67d486c452024f5012"
)


class SealError(RuntimeError):
    """An interrupted arm cannot be recovery-sealed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def readonly_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SealError(f"seal input is missing or unsafe: {path}")
    reject_symlink_ancestors(path)
    details = path.stat()
    mode = stat.S_IMODE(details.st_mode)
    if mode & 0o222:
        raise SealError(f"seal input remains writable: {path}")
    if details.st_nlink != 1:
        raise SealError(f"seal input must not have hard links: {path}")
    return {
        "file": path.name,
        "sha256": sha256_file(path),
        "bytes": details.st_size,
        "mode": f"{mode:04o}",
        "device": details.st_dev,
        "inode": details.st_ino,
        "links": details.st_nlink,
        "uid": details.st_uid,
        "gid": details.st_gid,
        "mtime_ns": details.st_mtime_ns,
        "ctime_ns": details.st_ctime_ns,
    }


def write_new_readonly_json(path: Path, payload: dict[str, Any], directory_fd: int) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    created = False
    linked = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        linked = True
        os.chmod(path, 0o444)
        os.fsync(directory_fd)
    finally:
        if created and temporary.exists():
            temporary.unlink()
        if linked:
            os.fsync(directory_fd)


def load_manifest_for_lock(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise SealError(f"manifest is missing or unsafe: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise SealError("manifest schema mismatch")
    contract = manifest.get("contract")
    if not isinstance(contract, dict) or canonical_digest(contract) != manifest.get(
        "contract_sha256"
    ):
        raise SealError("manifest contract digest mismatch")
    return manifest


def create_seal_locked(
    manifest_path: Path,
    test_path: Path,
    api_key_file: Path,
    out_path: Path,
    directory_fd: int,
) -> dict[str, Any]:
    manifest_preview = load_manifest_for_lock(manifest_path)
    if manifest_preview.get("status") != "INTERRUPTED":
        raise SealError("recovery seal requires status=INTERRUPTED")
    if manifest_preview.get("last_error") != "SIGTERM":
        raise SealError("recovery seal requires last_error=SIGTERM")
    if manifest_preview.get("raw_sha256") is not None:
        raise SealError("recovery seal is only for an unsealed interrupted manifest")
    if manifest_preview["contract"].get("evaluator_sha256") != FROZEN_EVALUATOR_SHA256:
        raise SealError("manifest evaluator SHA-256 is not the reviewed collector")
    if sha256_file(Path(__file__).resolve().with_name("eval_ab.py")) != FROZEN_EVALUATOR_SHA256:
        raise SealError("local evaluator source is not the reviewed collector")

    raw_name = manifest_preview.get("raw_file")
    if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
        raise SealError("manifest raw_file is unsafe")
    raw_path = manifest_path.parent / raw_name
    before = {
        "manifest": readonly_snapshot(manifest_path),
        "raw": readonly_snapshot(raw_path),
    }

    manifest, captured, loaded_raw_path = load_arm(
        manifest_path,
        capped_prefix=True,
        recovery_raw_sha256=before["raw"]["sha256"],
    )
    if loaded_raw_path != raw_path:
        raise SealError("loaded raw path drift")
    label = manifest.get("label")
    if label not in {"base", "sft"}:
        raise SealError("manifest arm label is invalid")
    validate_arm_identity(manifest, label)
    frozen_rows = load_frozen_rows(test_path)
    validate_records_against_test(manifest, captured, frozen_rows)
    selected = select_capped_prefix(captured, label)

    config = manifest["contract"]["config"]
    if config.get("base_url") != "http://127.0.0.1:8000":
        raise SealError("recovery identity check must remain host-local")
    expected_hashes = config.get("expected_file_sha256")
    if not isinstance(expected_hashes, dict):
        raise SealError("manifest has no identity-file contract")
    identity_specs = [(Path(path), digest) for path, digest in expected_hashes.items()]
    identity_files = verify_identity_files(identity_specs)
    if identity_files != expected_hashes:
        raise SealError("identity files changed before recovery seal")

    expected_adapter_path = None
    if label == "sft":
        expected_adapter_path = adapter_runtime_path(expected_hashes)
    service = verify_service_process(
        Path(config["service_pid_file"]),
        config["expected_process_arguments"],
        config["forbidden_process_arguments"],
        expected_adapter_path,
    )
    if service != manifest.get("initial_service"):
        raise SealError("service process differs from the arm's initial identity")

    key = read_api_key(api_key_file)
    try:
        client = JsonHttpClient(config["base_url"], key, config["timeout_seconds"])
        health = verify_health(client, config["expected_health"])
    finally:
        key = ""
    if health != manifest.get("initial_health"):
        raise SealError("service health differs from the arm's initial identity")

    after = {
        "manifest": readonly_snapshot(manifest_path),
        "raw": readonly_snapshot(raw_path),
    }
    if after != before:
        raise SealError("manifest or raw changed while the recovery seal was built")

    payload = {
        "schema_version": SEAL_SCHEMA,
        "status": "RECOVERY_SEALED",
        "evidence_class": "post_stop_recovery_snapshot",
        "sealed_at_utc": utc_now(),
        "run_id": manifest["run_id"],
        "label": label,
        "training_use": False,
        "api_key_persisted": False,
        "collector_evaluator_sha256": FROZEN_EVALUATOR_SHA256,
        "sealer_sha256": sha256_file(Path(__file__).resolve()),
        "validator_sha256": sha256_file(
            Path(__file__).resolve().with_name("summarize_ab.py")
        ),
        "original_manifest": {
            **after["manifest"],
            "status": manifest["status"],
            "last_error": manifest["last_error"],
            "raw_sha256_field": manifest["raw_sha256"],
            "contract_sha256": manifest["contract_sha256"],
        },
        "raw": {
            **after["raw"],
            "captured_records": len(captured),
        },
        "selection": {
            "method": "deterministic_ordered_frozen_prefix",
            "selected_records": len(selected),
            "selected_tasks": len({record["task_id"] for record in selected}),
            "first_task_index": selected[0]["task_index"],
            "last_task_index": selected[-1]["task_index"],
            "optional_excluded_record_key": (
                captured[170]["key"] if len(captured) == 171 else None
            ),
            "raw_prefix": jsonl_prefix_snapshot(raw_path, 170),
            "plan_prefix_sha256": plan_prefix_sha256(selected),
            "composition": capped_composition(selected),
        },
        "identity_at_seal": {
            "health": health,
            "service": service,
            "identity_file_sha256": identity_files,
            "matches_initial_health": True,
            "matches_initial_service": True,
        },
        "closure": {
            "kind": "POST_STOP_RECOVERY_ONLY",
            "stop_time_closure_proven": False,
        },
        "limitations": [
            "The collector manifest did not hash raw output on SIGTERM; this sidecar "
            "seals the later read-only snapshot and does not recreate a stop-time hash.",
            "Identity was revalidated at seal time, not captured by the collector at "
            "the SIGTERM safe point.",
            "The selected tasks are a non-random ordered prefix and are not "
            "representative of the full 113-task Test.",
        ],
    }
    write_new_readonly_json(out_path, payload, directory_fd)
    return payload


def create_seal(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.absolute()
    test_path = args.test.absolute()
    api_key_file = args.api_key_file.absolute()
    out_path = args.out.absolute()
    for path in (manifest_path, test_path, api_key_file, out_path):
        reject_symlink_ancestors(path)
    if manifest_path.parent != out_path.parent:
        raise SealError("seal and manifest must share one arm directory")
    if out_path.exists() or out_path.is_symlink():
        raise SealError(f"refusing to overwrite seal: {out_path}")

    directory_fd = os.open(manifest_path.parent, os.O_RDONLY | os.O_DIRECTORY)
    service_fd: int | None = None
    try:
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SealError("arm directory is locked by another evaluator or sealer") from error
        manifest = load_manifest_for_lock(manifest_path)
        service_pid_file = Path(manifest["contract"]["config"]["service_pid_file"])
        if not service_pid_file.is_absolute():
            raise SealError("service PID path is not absolute")
        reject_symlink_ancestors(service_pid_file)
        service_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            service_flags |= os.O_NOFOLLOW
        try:
            service_fd = os.open(service_pid_file, service_flags)
            fcntl.flock(service_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            if service_fd is not None:
                os.close(service_fd)
                service_fd = None
            raise SealError("service PID file is missing, unsafe, or locked") from error
        return create_seal_locked(
            manifest_path, test_path, api_key_file, out_path, directory_fd
        )
    finally:
        if service_fd is not None:
            os.close(service_fd)
        os.close(directory_fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        payload = create_seal(parse_args())
    except (EvaluationError, SummaryError, SealError, OSError, ValueError) as error:
        print(f"recovery seal failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    json.dump(
        {
            "status": payload["status"],
            "run_id": payload["run_id"],
            "label": payload["label"],
            "raw_sha256": payload["raw"]["sha256"],
            "captured_records": payload["raw"]["captured_records"],
        },
        sys.stdout,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
