#!/usr/bin/env python3
"""Run the same simulator-side evaluation against exactly two HTTP providers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
import urllib.request


IDENTITY_KEYS = (
    "provider",
    "model_id",
    "model_revision",
    "adapter_source_sha256",
)
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ENV_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("model matrix schema_version must be 1")
    models = manifest.get("models")
    if not isinstance(models, list) or len(models) != 2:
        raise ValueError("model matrix must contain exactly two models")

    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"models[{index}] must be an object")
        name = model.get("name")
        base_url_env = model.get("base_url_env")
        expected = model.get("expected_identity", {})
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise ValueError(f"models[{index}].name is invalid")
        if name in names:
            raise ValueError(f"duplicate model name: {name}")
        if not isinstance(base_url_env, str) or not ENV_PATTERN.fullmatch(base_url_env):
            raise ValueError(f"models[{index}].base_url_env is invalid")
        if not isinstance(expected, dict) or any(
            key not in IDENTITY_KEYS or not isinstance(value, str) or not value
            for key, value in expected.items()
        ):
            raise ValueError(f"models[{index}].expected_identity is invalid")
        names.add(name)
        normalized.append(
            {
                "name": name,
                "base_url_env": base_url_env,
                "expected_identity": expected,
            }
        )
    return normalized


def validate_health(
    payload: Any, expected_identity: dict[str, str]
) -> dict[str, Any]:
    identity = payload.get("policy_identity") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
        or payload.get("protocol_version") != 2
        or not isinstance(identity, dict)
        or any(not identity.get(key) for key in IDENTITY_KEYS)
    ):
        raise ValueError(f"provider does not implement inference protocol v2: {payload!r}")
    mismatches = {
        key: {"expected": expected, "actual": identity.get(key)}
        for key, expected in expected_identity.items()
        if identity.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"provider identity mismatch: {mismatches}")
    return payload


def fetch_health(base_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"health endpoint returned HTTP {response.status}")
        return json.loads(response.read())


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    evaluation_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "formal", "custom"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--runner",
        type=Path,
        default=evaluation_dir / "bin" / "run_eval.sh",
    )
    parser.add_argument("--run-name")
    parser.add_argument("--episodes", type=int)
    parser.add_argument(
        "--human-visual-review",
        choices=("pending", "passed", "failed"),
        default="pending",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    models = load_manifest(args.manifest.resolve())
    runner = args.runner.resolve()
    if not runner.is_file():
        raise FileNotFoundError(runner)
    if args.mode == "custom" and not args.episodes:
        raise ValueError("custom mode requires --episodes")
    if args.episodes is not None and args.episodes <= 0:
        raise ValueError("--episodes must be positive")

    output_root = args.output_root.resolve()
    run_name = args.run_name or f"{args.mode}-full-v2"
    matrix_results: list[dict[str, Any]] = []

    for model in models:
        name = model["name"]
        base_url = os.environ.get(model["base_url_env"])
        record: dict[str, Any] = {
            "name": name,
            "base_url_env": model["base_url_env"],
            "run_name": run_name,
        }
        if not base_url:
            record.update(status="not_run", error="base URL environment variable is unset")
            matrix_results.append(record)
            continue

        try:
            health = validate_health(
                fetch_health(base_url), model["expected_identity"]
            )
            record["policy_health"] = health
            model_root = output_root / name
            environment = os.environ.copy()
            environment.update(
                {
                    "INFERENCE_BASE_URL": base_url,
                    "INFERENCE_PROVIDER": health["policy_identity"]["provider"],
                    "RESULTS_ROOT": str(model_root),
                    "RUNTIME_EVIDENCE_DIR": str(model_root / "runtime"),
                    "RUN_NAME": run_name,
                    "HUMAN_VISUAL_REVIEW": args.human_visual_review,
                }
            )
            if args.episodes is not None:
                environment["N_EPISODES"] = str(args.episodes)
            completed = subprocess.run(
                [str(runner), args.mode],
                env=environment,
                check=False,
            )
            summary_path = model_root / run_name / "evaluation-summary.json"
            summary = (
                json.loads(summary_path.read_text(encoding="utf-8"))
                if summary_path.is_file()
                else None
            )
            record.update(
                status=("complete" if completed.returncode == 0 else "failed"),
                return_code=completed.returncode,
                evaluation_summary=str(summary_path),
                summary=summary,
            )
        except Exception as error:  # Continue so both model endpoints are audited.
            record.update(
                status="failed",
                error=f"{type(error).__name__}: {error}",
            )
        matrix_results.append(record)

    complete = all(item.get("status") == "complete" for item in matrix_results)
    tasks = {
        item.get("summary", {}).get("task")
        for item in matrix_results
        if isinstance(item.get("summary"), dict)
    }
    episodes = {
        item.get("summary", {}).get("episodes")
        for item in matrix_results
        if isinstance(item.get("summary"), dict)
    }
    comparison = {
        "schema_version": 1,
        "status": "matrix_complete" if complete else "matrix_failed",
        "mode": args.mode,
        "run_name": run_name,
        "model_count": len(matrix_results),
        "same_task": len(tasks) == 1 and len(matrix_results) == 2,
        "same_episode_count": len(episodes) == 1 and len(matrix_results) == 2,
        "models": matrix_results,
    }
    output = output_root / "model-matrix-summary.json"
    write_json_atomic(output, comparison)
    print(json.dumps(comparison, indent=2))
    if not complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
