#!/usr/bin/env python3
"""Verify the pinned AMD visual-shell layout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--shell", type=Path, required=True)
    args = parser.parse_args()

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    shell = args.shell.resolve()

    checks = {
        "scene-shell-profile.json": lock["visual_shell"]["profile_sha256"],
        "alignment.json": lock["visual_shell"]["alignment_sha256"],
        "gaussians_shell.ply": lock["visual_shell"]["combined_ply_sha256"],
    }
    receipt_name = lock["visual_shell"].get("calibration_receipt")
    if receipt_name:
        checks[receipt_name] = lock["visual_shell"]["calibration_receipt_sha256"]
    for name, expected in checks.items():
        path = shell / name
        if not path.is_file():
            raise SystemExit(f"missing shell file: {path}")
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"sha256 mismatch for {name}: {actual}")

    profile = json.loads((shell / "scene-shell-profile.json").read_text())
    if profile.get("status") != "passed":
        raise SystemExit(f"unexpected shell status: {profile.get('status')}")
    if profile.get("human_visual_review", {}).get("status") != "passed":
        raise SystemExit("calibrated shell human visual review is not passed")
    if profile["alignment"]["path"] != "alignment.json":
        raise SystemExit("visual-shell alignment path is not pinned alignment.json")
    if profile["integration_contract"]["camera_names"] != [
        "head",
        "left_wrist",
        "right_wrist",
    ]:
        raise SystemExit("visual-shell camera contract changed")

    print(
        json.dumps(
            {
                "status": "visual_shell_verified",
                "shell_profile": str(shell / "scene-shell-profile.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
