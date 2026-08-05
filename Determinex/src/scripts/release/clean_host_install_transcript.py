"""Create and validate Determinex clean-host install transcript files.

This helper does not install Determinex by itself. It defines the evidence
packet that a clean Windows runner must produce after executing the packaged
installer, launching the app, smoking the core IDE surfaces, and uninstalling.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.release import determinex_release_gates


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_template(generated_at_utc: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": determinex_release_gates.CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "product_name": "Determinex",
        "clean_host_fresh_install": False,
        "runner": {
            "is_clean_host": False,
            "host_reused_from_developer_machine": True,
            "os": "",
            "runner_id": "",
        },
        "bundle": {
            "manifest_path": "",
            "bundle_zip_path": "",
            "source_commit": "",
            "installer_path": "",
            "installer_sha256": "",
            "installer_sha256_verified": False,
        },
        "dry_run": True,
        "installer_execution_performed": False,
        "launch_performed": False,
        "proof_center_smoke_performed": False,
        "workspace_command_smoke_performed": False,
        "uninstall_performed": False,
        "release_ready": False,
        "authority_granted": False,
        "required_steps": [
            "verify packaged bundle and installer SHA-256 against download_manifest.json",
            "install Determinex setup artifact on a clean Windows runner",
            "launch Determinex from the installed application path",
            "open Proof Center or equivalent proof-governance surface",
            "run one workspace command smoke from the installed app",
            "uninstall Determinex and verify the installed app path is removed",
        ],
        "operator_notes": [
            "Set dry_run to false only after executing the installer on a clean Windows runner.",
            "Do not mark release_ready or authority_granted true in this transcript.",
        ],
    }


def validate_payload(payload: Any) -> dict[str, Any]:
    errors = determinex_release_gates._clean_host_transcript_errors(payload)
    return {
        "schema_version": determinex_release_gates.CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION,
        "status": "passed" if not errors else "blocked",
        "errors": errors,
        "release_ready": False,
        "authority_granted": False,
    }


def validate_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": determinex_release_gates.CLEAN_HOST_TRANSCRIPT_SCHEMA_VERSION,
            "status": "blocked",
            "errors": [f"transcript could not be read as JSON: {exc}"],
            "release_ready": False,
            "authority_granted": False,
        }
    result = validate_payload(payload)
    result["path"] = str(path)
    return result


def write_template(path: Path) -> dict[str, Any]:
    payload = build_template()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-output", type=Path, default=None)
    parser.add_argument("--validate", type=Path, default=None)
    args = parser.parse_args()

    if not args.template_output and not args.validate:
        parser.error("provide --template-output or --validate")

    exit_code = 0
    if args.template_output:
        payload = write_template(args.template_output)
        print(
            json.dumps(
                {
                    "status": "template_written",
                    "path": str(args.template_output),
                    "template": payload,
                },
                indent=2,
            )
        )
    if args.validate:
        result = validate_file(args.validate)
        print(json.dumps(result, indent=2))
        if result["status"] != "passed":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
