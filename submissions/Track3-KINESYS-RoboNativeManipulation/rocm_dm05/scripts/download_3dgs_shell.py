#!/usr/bin/env python3
"""Download and verify the public AMD BiGym 3DGS kitchen shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from pathlib import Path
from typing import Any

DEFAULT_REPO = "eustance/amd-bigym-3dgs-kitchen-shell"
DEFAULT_REVISION = "amd-rocm-w7900d-20260804"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_asset(profile_path: Path, value: object) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe shell asset path in {profile_path}: {relative}")
    return profile_path.parent / relative


def validate_profile(profile_path: Path) -> dict[str, Any]:
    profile_path = profile_path.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    layer_files = profile.get("layer_files")
    if not isinstance(layer_files, dict):
        raise TypeError(f"{profile_path} has no layer_files object")

    layered = all(name in layer_files for name in ("walls_decor", "ceiling"))
    if layered:
        names = ["walls_decor", "ceiling"]
        ground_mode = str(profile.get("ground_visual", {}).get("mode", "gaussian"))
        if ground_mode in {"gaussian", "gaussian_with_metric_fallback"}:
            names.append("floor")
        elif ground_mode != "metric_procedural":
            raise ValueError(f"unsupported layered ground mode: {ground_mode}")
        assets = {name: _safe_asset(profile_path, layer_files[name]) for name in names}
        mode = "layered"
    elif "combined" in layer_files:
        ground_mode = str(profile.get("ground_visual", {}).get("mode", ""))
        if ground_mode not in {
            "gaussian_combined",
            "gaussian_combined_with_confidence_fallback",
        }:
            raise ValueError(f"unsupported combined ground mode: {ground_mode}")
        assets = {"combined": _safe_asset(profile_path, layer_files["combined"])}
        mode = "combined"
    else:
        raise ValueError(f"{profile_path} has neither layered nor combined assets")

    missing = [str(path) for path in assets.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"missing shell assets referenced by profile: {missing}"
        )

    records: dict[str, dict[str, object]] = {}
    for name, path in assets.items():
        records[name] = {
            "path": str(path.relative_to(profile_path.parent)),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    if mode == "combined":
        contract = profile.get("asset")
        if not isinstance(contract, dict):
            raise ValueError(f"{profile_path} lacks the combined asset contract")
        record = records["combined"]
        expected_path = str(layer_files["combined"])
        if str(contract.get("path")) != expected_path:
            raise ValueError("combined asset path does not match profile contract")
        if int(contract.get("bytes", -1)) != record["bytes"]:
            raise ValueError("combined asset size does not match profile contract")
        if str(contract.get("sha256", "")).lower() != record["sha256"]:
            raise ValueError("combined asset SHA-256 does not match profile contract")

    return {"profile": str(profile_path), "mode": mode, "assets": records}


def discover_profile(root: Path, requested: str | None) -> tuple[Path, dict[str, Any]]:
    if requested:
        candidate = (root / requested).resolve()
        if root.resolve() not in candidate.parents:
            raise ValueError("--profile must stay inside --output-dir")
        return candidate, validate_profile(candidate)

    valid: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(root.rglob("*.json")):
        try:
            valid.append((candidate, validate_profile(candidate)))
        except (
            FileNotFoundError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            continue
    if not valid:
        raise RuntimeError(f"no complete visual-shell profile found under {root}")

    priorities = ("scene-shell-profile-combined.json", "scene-shell-profile.json")
    for name in priorities:
        matches = [item for item in valid if item[0].name == name]
        if len(matches) == 1:
            return matches[0]
    if len(valid) == 1:
        return valid[0]
    choices = "\n".join(str(path.relative_to(root)) for path, _ in valid)
    raise RuntimeError(f"multiple valid profiles found; pass --profile:\n{choices}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--profile", help="profile path relative to output-dir")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from huggingface_hub import HfApi, snapshot_download

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    info = HfApi().dataset_info(args.repo_id, revision=args.revision)
    snapshot_download(
        repo_id=args.repo_id,
        repo_type="dataset",
        revision=info.sha,
        local_dir=output_dir,
    )
    profile_path, validation = discover_profile(output_dir, args.profile)
    manifest = {
        "repo_id": args.repo_id,
        "requested_revision": args.revision,
        "resolved_commit": info.sha,
        **validation,
    }
    (output_dir / "download_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    env_path = output_dir / "shell.env"
    env_path.write_text(
        "\n".join(
            (
                f"THREE_DGS_SHELL_ROOT={shlex.quote(str(output_dir))}",
                f"VISUAL_SHELL_PROFILE={shlex.quote(str(profile_path))}",
                f"THREE_DGS_SHELL_REPO={shlex.quote(args.repo_id)}",
                f"THREE_DGS_SHELL_REVISION={shlex.quote(args.revision)}",
                f"THREE_DGS_SHELL_COMMIT={shlex.quote(info.sha)}",
                "",
            )
        ),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"source {env_path}")


if __name__ == "__main__":
    main()
