#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


PINNED = {
    "huggingface-hub": "1.26.0",
    "mlx": "0.32.0",
    "mlx-lm": "0.31.3",
    "transformers": "5.14.1",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-fast preflight for the pinned ProofLaunch Apple MLX runtime."
    )
    parser.add_argument(
        "--skip-metal",
        action="store_true",
        help="Check package pins without opening the Metal device.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optionally seal the preflight JSON inside the project root.",
    )
    args = parser.parse_args()
    observed: dict[str, str | None] = {}
    failures: list[str] = []
    for package, expected in PINNED.items():
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = None
        observed[package] = actual
        if actual != expected:
            failures.append(f"{package}: expected {expected}, observed {actual}")
    metal_available: bool | None = None
    if not failures and not args.skip_metal:
        import mlx.core as mx
        import mlx_lm

        if not callable(getattr(mlx_lm, "load", None)):
            failures.append("mlx_lm.load is not importable")

        metal_available = bool(mx.metal.is_available())
        if not metal_available:
            failures.append("Apple Metal is not available to this process")
    payload = {
        "schema": "ProofLaunchAppleMLXRuntimePreflightV1",
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "pinned_packages": PINNED,
        "observed_packages": observed,
        "metal_checked": not args.skip_metal,
        "metal_available": metal_available,
        "passed": not failures,
        "failures": failures,
        "repair_command": "uv sync --extra social --offline",
    }
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if args.output is not None:
        output = args.output.expanduser().resolve()
        try:
            output.relative_to(ROOT.resolve())
        except ValueError as error:
            raise SystemExit("preflight output must remain inside the project root") from error
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
