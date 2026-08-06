#!/usr/bin/env python3
"""radeon-fix: a simple local repository repair CLI for AMD Radeon.

Product layer on top of the Track 2 mini-SWE experiment stack. It takes a
local git repository and an issue description, clones the repository into a
temporary workspace, runs the validated product composition
(C1R1 + J3/EditV2 + A1 + V1R1) against a local OpenAI-compatible vLLM
endpoint, and writes a patch, a Markdown report, a trajectory, and optional
AMD GPU metrics.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mini_swe_runner import MiniSWERunner
from swe_experiments.context import ContextResult
from track2_demo import read_gpu_metrics
from track2_harness_benchmark import extract_context


VERSION = "0.1.0"
DEFAULT_MODEL = "Qwen3-14B-BF16"
DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_TOOL_CALLS = 30
DEFAULT_MAX_WALL_TIME_SECONDS = 900
DEFAULT_SEED = 0

EXIT_OK = 0
EXIT_NO_PATCH = 1
EXIT_ERROR = 2
EXIT_UNVERIFIED = 3

_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


class CliError(Exception):
    """Fatal CLI error that maps to exit code 2."""


def _repo_name(repo: Path) -> str:
    return repo.resolve().name or "repository"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def _run_git(args: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise CliError(f"git failed: {exc}") from exc


def _clone_to_workspace(repo: Path) -> Path:
    repo = repo.resolve()
    if not repo.is_dir() or not (repo / ".git").is_dir():
        raise CliError(f"--repo is not a git repository: {repo}")
    workspace_root = Path(tempfile.mkdtemp(prefix="radeon-fix-"))
    workspace = workspace_root / "workspace"
    result = _run_git(
        ["clone", "--quiet", "--no-hardlinks", "--", str(repo), str(workspace)],
        cwd=workspace_root,
    )
    if result.returncode != 0:
        shutil.rmtree(workspace_root, ignore_errors=True)
        raise CliError(f"could not clone repository into a temporary workspace: {result.stdout.strip()}")
    return workspace


def _resolve_endpoint(args: argparse.Namespace) -> tuple[str, str, str]:
    base_url = args.base_url or os.getenv("TRACK2_BASE_URL", "")
    api_key = args.api_key or os.getenv("TRACK2_API_KEY", "")
    model = args.model or os.getenv("TRACK2_MODEL", "") or DEFAULT_MODEL
    if not base_url:
        raise CliError("missing endpoint: set TRACK2_BASE_URL or pass --base-url")
    if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")):
        raise CliError(
            "radeon-fix v1 requires a local OpenAI-compatible endpoint "
            "(http://127.0.0.1:... or http://localhost:...); got a non-local base URL"
        )
    if not api_key:
        api_key = "local-vllm"
    if not model:
        raise CliError("missing model: set TRACK2_MODEL or pass --model")
    return base_url, api_key, model


def _read_issue(args: argparse.Namespace) -> str:
    if args.issue and args.issue_file:
        raise CliError("use either --issue or --issue-file, not both")
    if args.issue:
        return args.issue
    if args.issue_file:
        try:
            return Path(args.issue_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CliError(f"could not read --issue-file: {exc}") from exc
    raise CliError("missing issue: pass --issue TEXT or --issue-file FILE")


def _safe_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SECRET_MARKERS)
    }


def _run_final_test(workspace: Path, command: str, timeout: int = 300) -> dict[str, Any] | None:
    """Run an auditable post-agent test command in the temporary workspace."""
    if not command or not command.strip():
        return None
    print(f"\n🧪 final check: {command}")
    returncode = 124
    output = ""
    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(workspace.resolve()),
            env=_safe_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        returncode = result.returncode
        output = result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
    tail = output.strip().splitlines()[-40:]
    if tail:
        print("\n".join(tail))
    else:
        print("(no output)")
    if returncode == 0:
        print("✓ Final check passed")
    else:
        print(f"✗ Final check failed (exit {returncode})")
    return {
        "command": command,
        "exit_code": returncode,
        "passed": returncode == 0,
        "output_tail": "\n".join(tail),
    }


def _make_context_refresh(
    workspace: Path,
    model: str,
    issue: str,
    context_info: dict[str, Any],
) -> Callable[[list[str], list[str]], ContextResult]:
    def refresh_context(focus_files: list[str], focus_identifiers: list[str]) -> ContextResult:
        refreshed_text, refreshed_details = extract_context(
            "aider",
            workspace,
            model,
            issue,
            focus_files=focus_files,
            focus_identifiers=focus_identifiers,
        )
        (workspace / ".track2-context-refresh.txt").write_text(refreshed_text, encoding="utf-8")
        context_info["refresh"] = refreshed_details
        return ContextResult(
            "C1R1",
            refreshed_text,
            "aider-repomap-focused",
            bool(refreshed_text.strip()) and bool(refreshed_details.get("available")),
            {
                "initial": dict(context_info.get("initial", {})),
                "refresh": refreshed_details,
                "token_budget": 2048,
                "focus_files": sorted(set(focus_files)),
                "focus_identifiers": sorted(set(focus_identifiers)),
            },
        )

    return refresh_context


def _run_repair(
    *,
    workspace: Path,
    issue: str,
    base_url: str,
    api_key: str,
    model: str,
    max_turns: int,
    max_tool_calls: int,
    max_wall_time: int,
    seed: int,
    verbose: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context_text, context_details = extract_context("aider", workspace, model, issue)
    (workspace / ".track2-context.txt").write_text(context_text, encoding="utf-8")
    context_info: dict[str, Any] = {"initial": context_details}
    context_refresh = _make_context_refresh(workspace, model, issue, context_info)

    old_env = os.environ.get("TRACK2_AIDER_REPOMAP_COMMAND")
    os.environ["TRACK2_AIDER_REPOMAP_COMMAND"] = "cat .track2-context.txt"
    try:
        runner = MiniSWERunner(
            model=model,
            base_url=base_url,
            api_key=api_key,
            env_type="local",
            cwd=str(workspace.resolve()),
            max_iterations=max_turns,
            max_model_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_wall_time_seconds=max_wall_time,
            max_completion_tokens=8192,
            top_p=0.95,
            top_k=20,
            presence_penalty=0.0,
            seed=seed,
            command_timeout=120,
            api_timeout=120,
            api_transport_retries=1,
            require_localhost=True,
            context_variant="C1",
            json_mode="J3",
            controller_policy="A1",
            verifier_mode="V1R1",
            max_json_retries=0,
            edit_protocol="replace-v2",
            context_refresh_callback=context_refresh,
            verbose=verbose,
        )
        for logger_name in ("openai", "httpx", "httpcore"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        raw = runner.run_task(issue)
    finally:
        if old_env is None:
            os.environ.pop("TRACK2_AIDER_REPOMAP_COMMAND", None)
        else:
            os.environ["TRACK2_AIDER_REPOMAP_COMMAND"] = old_env
    return raw, context_info


def _metadata_summary(metadata: dict[str, Any], api_calls: int) -> list[str]:
    verifier = metadata.get("verifier") or {}
    api = metadata.get("api") or {}
    usage = api.get("usage", {}) or {}
    refresh_info = metadata.get("context_refresh") or {}
    if isinstance(refresh_info, tuple):
        refresh_info = refresh_info[0] if refresh_info else {}
    return [
        f"- Model turns: {int(api_calls)}",
        f"- Tool calls: {int(metadata.get('tool_calls', 0))}",
        f"- Edit attempts: {int(metadata.get('edit_attempts', 0))}",
        f"- Replace attempts: {int(metadata.get('replace_attempts', 0))}",
        f"- Replace successes: {int(metadata.get('replace_successes', 0))}",
        f"- Patch apply results: {metadata.get('patch_apply_results', [])}",
        f"- Verifier verdict: {verifier.get('verdict', 'not run')} "
        f"(mode {verifier.get('mode', 'V1R1')}; deterministic syntax/structure "
        "gates, does not run tests)",
        f"- Total tokens: {int(usage.get('total_tokens', 0) or 0)}",
        f"- Wall time: {float(metadata.get('wall_time_ms', 0)) / 1000:.1f} s",
        f"- Context provider: {metadata.get('context_provider', 'unknown')} "
        f"(available: {metadata.get('context_available', False)})",
        f"- Context refresh: {'yes' if refresh_info.get('attempted') else 'no'}",
    ]


def _render_report(
    *,
    repo: Path,
    issue: str,
    base_url: str,
    model: str,
    raw: dict[str, Any],
    context_info: dict[str, Any],
    patch: str,
    gpu_metrics: dict[str, Any],
    final_test: dict[str, Any] | None,
    output_dir: Path,
) -> str:
    metadata = raw.get("metadata", {})
    lines = [
        "# radeon-fix report",
        "",
        f"- Repository: `{repo.resolve()}`",
        f"- Issue: {issue.strip()}",
        f"- Model: `{model}`",
        f"- Endpoint: `{base_url}` (local inference)",
        f"- Completed: {raw.get('completed', False)}",
        f"- Patch: {'non-empty' if patch.strip() else 'empty'}",
        "",
        "## Issue",
        "",
        issue.strip(),
        "",
        "## Trajectory summary",
        "",
    ]
    lines.extend(_metadata_summary(metadata, int(raw.get("api_calls", 0))))
    context_initial = context_info.get("initial", {})
    context_refresh = context_info.get("refresh")
    lines.extend(
        [
            "",
            "## Repository context",
            "",
            f"- Initial Repo Map available: {bool(context_initial.get('available'))}",
            f"- Initial Repo Map chars: {context_initial.get('chars', 0)}",
            f"- Focused refresh available: {bool(context_refresh and context_refresh.get('available'))}",
        ]
    )
    if gpu_metrics:
        lines.extend(["", "## AMD GPU inference", ""])
        labels = {
            "gpu_model": "GPU",
            "rocm_version": "ROCm",
            "vllm_version": "vLLM",
            "ttft_ms": "TTFT",
            "tokens_per_second": "Tokens/s",
            "p50_latency_ms": "P50 latency",
            "p95_latency_ms": "P95 latency",
            "vram_gb": "VRAM",
            "gpu_utilization_percent": "GPU utilization",
            "gpu_arch": "GPU arch",
            "model": "Model",
            "kv_cache": "KV cache",
            "ttft_p50_ms": "TTFT p50",
            "decode_tokens_per_second": "Decode",
        }
        for key, label in labels.items():
            if key in gpu_metrics:
                lines.append(f"- {label}: {gpu_metrics[key]}")
    if final_test is not None:
        lines.extend(
            [
                "",
                "## Final check",
                "",
                f"- Command: `{final_test['command']}`",
                f"- Exit code: {final_test['exit_code']}",
                f"- Passed: {final_test['passed']}",
                "",
                "```text",
                final_test.get("output_tail") or "(no output)",
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Patch",
            "",
            "```diff",
            patch.rstrip() or "(empty patch)",
            "```",
            "",
            "## Apply",
            "",
            "The patch was produced in an isolated temporary copy. To apply it "
            "to the original repository:",
            "",
            "```bash",
            f"cd {repo.resolve()} && git apply {output_dir / 'patch.diff'}",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def run_product(args: argparse.Namespace) -> int:
    if args.version:
        print(f"radeon-fix {VERSION}")
        return EXIT_OK
    repo = Path(args.repo).resolve() if args.repo else None
    if not repo:
        raise CliError("missing --repo PATH")
    issue = _read_issue(args)
    base_url, api_key, model = _resolve_endpoint(args)
    print("Environment: local command-guarded execution (not an OS-level sandbox)")
    print("Verifier: V1R1 deterministic syntax/structure gates (does not run tests)")
    if args.final_test_cmd:
        print(f"Final check: {args.final_test_cmd}")
    if not repo.is_dir() or not (repo / ".git").is_dir():
        raise CliError(f"--repo is not a git repository: {repo}")

    max_turns = max(1, int(args.max_turns))
    max_tool_calls = max(1, int(args.max_tool_calls))
    max_wall_time = max(1, int(args.max_wall_time))
    seed = int(args.seed)

    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path.cwd() / "radeon-fix-out" / f"{_repo_name(repo)}-{_timestamp()}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    workspace: Path | None = None
    try:
        workspace = _clone_to_workspace(repo)
        print(f"Cloned {repo} into temporary workspace {workspace}")
        raw, context_info = _run_repair(
            workspace=workspace,
            issue=issue,
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_wall_time=max_wall_time,
            seed=seed,
            verbose=bool(args.verbose),
        )
        initial_available = bool((context_info.get("initial") or {}).get("available"))
        if not initial_available:
            print(
                "WARNING: Aider Repo Map unavailable; continuing with degraded "
                "context (context_available=false).",
                file=sys.stderr,
            )
            if args.require_context:
                raise CliError(
                    "--require-context is set but the Aider Repo Map provider is unavailable"
                )
        metadata = raw.get("metadata", {})
        patch = str(metadata.get("final_patch") or "")
        final_test = _run_final_test(workspace, str(args.final_test_cmd or ""))
        gpu_metrics = read_gpu_metrics()

        (output_dir / "patch.diff").write_text(patch, encoding="utf-8")
        (output_dir / "trajectory.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "gpu.json").write_text(
            json.dumps(gpu_metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        verifier_info = metadata.get("verifier") or {}
        verified = (
            bool(patch.strip())
            and raw.get("completed") is True
            and verifier_info.get("verdict") == "accept"
        )
        if not patch.strip():
            exit_code = EXIT_NO_PATCH
        elif not verified:
            exit_code = EXIT_UNVERIFIED
        elif final_test is not None and not final_test.get("passed"):
            exit_code = EXIT_UNVERIFIED
        else:
            exit_code = EXIT_OK
        run_info = {
            "product": "radeon-fix",
            "version": VERSION,
            "repo": str(repo),
            "model": model,
            "base_url": base_url,
            "context": "C1R1",
            "action_protocol": "J3",
            "edit_protocol": "replace-v2",
            "controller_policy": "A1",
            "verifier_mode": "V1R1",
            "max_turns": max_turns,
            "max_tool_calls": max_tool_calls,
            "max_wall_time_seconds": max_wall_time,
            "seed": seed,
            "started_at": _timestamp(),
            "completed": raw.get("completed", False),
            "context_available": bool((context_info.get("initial") or {}).get("available")),
            "exit_code": exit_code,
            "verifier": {
                "mode": verifier_info.get("mode", "V1R1"),
                "verdict": verifier_info.get("verdict", "not run"),
                "note": "deterministic syntax/structure gates; does not run tests",
            },
            "final_test": final_test,
        }
        (output_dir / "run.json").write_text(
            json.dumps(run_info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report = _render_report(
            repo=repo,
            issue=issue,
            base_url=base_url,
            model=model,
            raw=raw,
            context_info=context_info,
            patch=patch,
            gpu_metrics=gpu_metrics,
            final_test=final_test,
            output_dir=output_dir,
        )
        (output_dir / "report.md").write_text(report, encoding="utf-8")

        print(f"\nArtifacts written to: {output_dir}")
        if exit_code == EXIT_OK:
            print("Patch produced and verified (exit 0)")
        elif exit_code == EXIT_NO_PATCH:
            print("No patch produced (exit 1)")
        else:
            print("Patch produced but verification/final check failed (exit 3)")
        return exit_code
    finally:
        if workspace is not None:
            shutil.rmtree(workspace.parent, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="radeon-fix",
        description="Repair a local git repository from an issue description using "
        "a local OpenAI-compatible model on AMD Radeon.",
    )
    parser.add_argument("--repo", help="path to a local git repository (cloned to a temp workspace)")
    parser.add_argument("--issue", help="issue description text")
    parser.add_argument("--issue-file", help="file containing the issue description")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL (default: $TRACK2_BASE_URL)")
    parser.add_argument("--model", help="model name (default: $TRACK2_MODEL or Qwen3-14B-BF16)")
    parser.add_argument("--api-key", help=argparse.SUPPRESS)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    parser.add_argument("--max-wall-time", type=int, default=DEFAULT_MAX_WALL_TIME_SECONDS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", help="directory for patch.diff, report.md, trajectory.json, run.json")
    parser.add_argument(
        "--final-test-cmd",
        help="optional shell command run after the agent in the temporary workspace "
        "(e.g. 'python -m pytest -q'); its failure maps to exit code 3",
    )
    parser.add_argument(
        "--require-context",
        action="store_true",
        help="fail fast (exit 2) when the Aider Repo Map provider is unavailable",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return run_product(args)
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
