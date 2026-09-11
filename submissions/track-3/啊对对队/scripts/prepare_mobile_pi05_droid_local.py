#!/usr/bin/env python3
"""Build an immutable local PI0.5-DROID bundle with an offline tokenizer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_droid_bundle(
    *,
    droid_snapshot: Path,
    base_bundle: Path,
    tokenizer: Path,
    output: Path,
) -> dict[str, object]:
    droid_snapshot = droid_snapshot.resolve()
    base_bundle = base_bundle.resolve()
    tokenizer = tokenizer.resolve()
    output = output.resolve()
    required = {
        "model": droid_snapshot / "model.safetensors",
        "preprocessor": droid_snapshot / "policy_preprocessor.json",
        "config": base_bundle / "config.json",
        "postprocessor": base_bundle / "policy_postprocessor.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if not tokenizer.is_dir():
        missing.append("tokenizer")
    if missing:
        raise ValueError(f"missing DROID bundle inputs: {sorted(missing)}")
    if output.exists():
        raise ValueError(f"output already exists: {output}")

    output.mkdir(parents=True)
    (output / "model.safetensors").symlink_to(required["model"])
    shutil.copy2(required["config"], output / "config.json")
    shutil.copy2(required["postprocessor"], output / "policy_postprocessor.json")
    preprocessor = json.loads(required["preprocessor"].read_text(encoding="utf-8"))
    tokenizer_steps = [
        step
        for step in preprocessor.get("steps", ())
        if step.get("registry_name") == "tokenizer_processor"
    ]
    if len(tokenizer_steps) != 1:
        raise ValueError("DROID preprocessor must contain exactly one tokenizer step")
    tokenizer_steps[0].setdefault("config", {})["tokenizer_name"] = str(tokenizer)
    (output / "policy_preprocessor.json").write_text(
        json.dumps(preprocessor, indent=2) + "\n", encoding="utf-8"
    )

    manifest = {
        "schema_version": 1,
        "protocol": "pi05-droid-offline-bundle-v1",
        "droid_snapshot": str(droid_snapshot),
        "base_bundle": str(base_bundle),
        "tokenizer": str(tokenizer),
        "model_sha256": _sha256(required["model"]),
        "preprocessor_sha256": _sha256(output / "policy_preprocessor.json"),
        "config_sha256": _sha256(output / "config.json"),
        "postprocessor_sha256": _sha256(output / "policy_postprocessor.json"),
        "claim_boundary": (
            "Local loading bundle only; model weights are the unmodified DROID "
            "checkpoint and this artifact is not task-performance evidence."
        ),
    }
    (output / "DROID_LOCAL_BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--droid-snapshot", type=Path, required=True)
    parser.add_argument("--base-bundle", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = prepare_droid_bundle(
            droid_snapshot=args.droid_snapshot,
            base_bundle=args.base_bundle,
            tokenizer=args.tokenizer,
            output=args.output,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
