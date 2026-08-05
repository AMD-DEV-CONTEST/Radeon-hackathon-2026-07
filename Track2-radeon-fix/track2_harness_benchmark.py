#!/usr/bin/env python3
"""Run a leakage-free API harness comparison on Aider Polyglot Python.

Every run gets the same model, task prompt, semantic-call budget and isolated
source workspace. Hidden tests are never exposed to a model or used for retry
feedback; they are copied into the sandbox exactly once, after the final
candidate is frozen. The objective score is the fraction of runs whose full
test suite passes, never an agent/verifier self-report.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import re
import signal
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mini_swe_runner import MiniSWERunner
from swe_experiments.actions import ActionParseError, parse_action_envelope
from swe_experiments.context import ContextResult
from track2_qwen_code import QWEN_CODE_VERSION, run_qwen_code


ROOT = Path(__file__).resolve().parent
POLYGLOT_ROOT = ROOT / "benchmarks" / "polyglot-benchmark"
AIDER_ROOT = ROOT / "benchmarks" / "aider"
REPOGRAPH_ROOT = ROOT / "benchmarks" / "RepoGraph"
AIDER_PYTHON = AIDER_ROOT / ".venv-track2" / "bin" / "python"
AIDER_BIN = AIDER_ROOT / ".venv-track2" / "bin" / "aider"
REPOGRAPH_PYTHON = REPOGRAPH_ROOT / ".venv-track2" / "bin" / "python"
QWEN_ROOT = ROOT / "benchmarks" / "qwen-code"
QWEN_BIN = QWEN_ROOT / "node_modules" / ".bin" / "qwen"

DEFAULT_HARNESSES = (
    "mini-original",
    "mini-repomap",
    "mini-repograph-clean",
    "mini-budget",
    "mini-verifier-repair",
    "mini-json-structured",
    "qwen-code",
)

MINI_CONFIGS = {
    "mini-original": ("C0", "J0", "A0", "V0"),
    # Clean single-factor context ablations.  These names deliberately differ
    # from the historical J3+V1 combinations below so old result directories
    # cannot be mistaken for C-only evidence.
    "mini-repomap": ("C1", "J0", "A0", "V0"),
    # Final-product development variants.  The focused refresh and Edit V2
    # switches are carried in MINI_HARNESS_OPTIONS to preserve tuple-shaped
    # historical configuration records.
    "mini-repomap-refresh": ("C1", "J0", "A0", "V0"),
    "mini-edit-v2": ("C0", "J3", "A0", "V0"),
    "mini-repomap-final": ("C1", "J3", "A1", "V1R1"),
    "mini-repograph-clean": ("C2", "J0", "A0", "V0"),
    "mini-budget": ("C0", "J0", "A1", "V0"),
    "mini-verifier-repair": ("C0", "J0", "A0", "V1R1"),
    "mini-json-structured": ("C0", "J3", "A0", "V0"),
    # B6: the pilot-selected combination.  RepoGraph was the only context
    # provider with a non-empty patch in the five-task pilot; J3 was schema
    # valid on every response; keep one deterministic verifier-repair turn.
    "mini-combo": ("C2", "J3", "A0", "V1R1"),
    # Historical names remain readable in old result directories.
    "mini-json-prompt": ("C0", "J1", "A0", "V0"),
    "mini-json-retry": ("C0", "J2", "A0", "V0"),
    "mini-json-verifier": ("C0", "J3", "A0", "V1"),
    "mini-aider-repomap": ("C1", "J3", "A0", "V1"),
    "mini-repograph": ("C2", "J3", "A0", "V1"),
}

MINI_HARNESS_OPTIONS: dict[str, dict[str, Any]] = {
    "mini-repomap-refresh": {"context_refresh": True},
    "mini-edit-v2": {"edit_protocol": "replace-v2"},
    "mini-repomap-final": {"context_refresh": True, "edit_protocol": "replace-v2"},
}


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


@contextlib.contextmanager
def wall_time_limit(seconds: int | None):
    """Enforce one comparable agent wall-clock budget on Unix runners."""

    if not seconds:
        yield
        return

    def expire(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"agent wall-clock budget exceeded after {seconds}s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(int(seconds))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def git_output(cwd: Path, *args: str) -> str:
    result = run_command(["git", *args], cwd=cwd, timeout=30)
    return result.stdout if result.returncode == 0 else ""


def keychain_secret() -> str:
    value = os.getenv("TRACK2_API_KEY", "")
    if value:
        return value
    try:
        result = run_command(
            [
                "security",
                "find-generic-password",
                "-s",
                "hermes-track2-amd",
                "-a",
                os.getenv("USER", ""),
                "-w",
            ],
            timeout=10,
        )
    except FileNotFoundError:
        # Linux/RadeonX Cloud has no macOS Keychain.  Localhost vLLM runs
        # intentionally use the provider-neutral placeholder handled by main.
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_task(exercise: Path) -> dict[str, Any]:
    config = json.loads((exercise / ".meta" / "config.json").read_text())
    solution_files = config.get("files", {}).get("solution", [])
    test_files = config.get("files", {}).get("test", [])
    prompt_parts: list[str] = []
    for relative in (
        ".docs/introduction.md",
        ".docs/instructions.md",
        ".docs/instructions.append.md",
    ):
        path = exercise / relative
        if path.exists():
            prompt_parts.append(path.read_text())
    file_list = " ".join(Path(item).name for item in solution_files)
    prompt_parts.append(
        "\n####\n\n"
        f"Use the above instructions to modify the supplied files: {file_list}\n"
        "Don't change the names of existing functions or classes, as they may be "
        "referenced from hidden unit tests.\n"
        "Only use standard libraries. Do not install packages. Implement the solution now.\n"
    )
    prompt = "\n".join(prompt_parts)
    return {
        "task_id": exercise.name,
        "exercise": str(exercise.resolve()),
        "solution_files": solution_files,
        "test_files": test_files,
        "prompt": prompt,
        "prompt_sha256": sha256_text(prompt),
    }


def create_or_load_manifest(output_dir: Path, count: int, seed: int) -> list[dict[str, Any]]:
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if int(manifest.get("seed", -1)) != seed:
            raise RuntimeError(
                f"existing manifest seed={manifest.get('seed')} does not match requested seed={seed}"
            )
        if int(manifest.get("requested_count", -1)) != count:
            raise RuntimeError(
                "existing manifest task count does not match this run; use a new output directory"
            )
        return list(manifest["tasks"])

    practice = POLYGLOT_ROOT / "python" / "exercises" / "practice"
    candidates = sorted(path for path in practice.iterdir() if path.is_dir())
    if not candidates:
        raise RuntimeError(f"no exercises found under {practice}")
    selected = random.Random(seed).sample(candidates, min(count, len(candidates)))
    tasks = [load_task(path) for path in selected]
    payload = {
        "benchmark": "Aider Polyglot Python fixed subset",
        "seed": seed,
        "requested_count": count,
        "polyglot_commit": git_output(POLYGLOT_ROOT, "rev-parse", "HEAD").strip(),
        "tasks": tasks,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return tasks


def prepare_workspace(task: dict[str, Any], workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    exercise = Path(task["exercise"])
    for relative in task["solution_files"]:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exercise / relative, destination)
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Track2 Benchmark"],
        ["git", "config", "user.email", "track2@example.invalid"],
        ["git", "add", "--", *task["solution_files"]],
        ["git", "commit", "-q", "-m", "benchmark baseline"],
    )
    for command in commands:
        result = run_command(command, cwd=workspace, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"workspace setup failed: {' '.join(command)}\n{result.stdout}")


def copy_hidden_tests(task: dict[str, Any], workspace: Path) -> None:
    exercise = Path(task["exercise"])
    for relative in task["test_files"]:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exercise / relative, destination)


def remove_hidden_tests(task: dict[str, Any], workspace: Path) -> None:
    for relative in task["test_files"]:
        path = workspace / relative
        if path.exists():
            path.unlink()


def hidden_test(task: dict[str, Any], workspace: Path, image: str) -> dict[str, Any]:
    copy_hidden_tests(task, workspace)
    started = time.perf_counter()
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "128",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,size=64m",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        f"{workspace.resolve()}:/work:ro",
        "-w",
        "/work",
        image,
        "python",
        "-m",
        "unittest",
        "discover",
        "-v",
        "-p",
        "*_test.py",
    ]
    try:
        result = run_command(command, timeout=180)
        return {
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "output": result.stdout[-20000:],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {
            "passed": False,
            "exit_code": 124,
            "output": (output + "\nTEST_TIMEOUT")[-20000:],
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    finally:
        remove_hidden_tests(task, workspace)


def sanitize_context_output(value: str) -> str:
    """Remove extractor UI noise without changing repository-map content."""
    ignored = (
        "Detected dumb terminal, disabling fancy input and pretty output.",
        "Initial repo scan can be slow in larger repos, but only happens once.",
    )
    ignored_prefixes = (
        "Scanning repo:",
        "Updating repo map:",
        # Aider's tree-sitter adapter reports unsupported files on stdout.
        # Those diagnostics include absolute workspace paths and are not map
        # content; retaining them leaks host paths into the agent prompt.
        "Skipping file ",
    )
    lines = [
        line
        for line in value.splitlines()
        if line.strip() not in ignored
        and not line.strip().startswith(ignored_prefixes)
    ]
    return "\n".join(lines).strip() + ("\n" if any(line.strip() for line in lines) else "")


def extract_context(
    provider: str,
    workspace: Path,
    model: str,
    issue: str = "",
    focus_files: list[str] | None = None,
    focus_identifiers: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    if provider == "aider":
        command = [
            str(AIDER_PYTHON),
            str(ROOT / "track2_context_extract.py"),
            "--provider",
            "aider",
            "--root",
            str(workspace),
            "--aider-root",
            str(AIDER_ROOT),
            "--model",
            f"openai/{model.removeprefix('openai/')}",
            "--map-tokens",
            "2048",
            "--issue",
            issue,
        ]
        for focus_file in focus_files or []:
            command.extend(["--focus-file", focus_file])
        for focus_identifier in focus_identifiers or []:
            command.extend(["--focus-identifier", focus_identifier])
    else:
        command = [
            str(REPOGRAPH_PYTHON),
            str(ROOT / "track2_context_extract.py"),
            "--provider",
            "repograph",
            "--root",
            str(workspace),
            "--repograph-root",
            str(REPOGRAPH_ROOT),
        ]
    started = time.perf_counter()
    try:
        # Aider emits progress/debug text to stderr during its initial scan.
        # Keep that out of the model context; only extractor stdout is a map.
        result = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        rendered = sanitize_context_output(result.stdout)
        if provider == "aider" and len(rendered) > 2048 * 4:
            rendered = rendered[: 2048 * 4].rsplit("\n", 1)[0]
        context_text = rendered if result.returncode == 0 else ""
        return context_text, {
            "provider": provider,
            "available": bool(context_text.strip()) and result.returncode == 0,
            "exit_code": result.returncode,
            "chars": len(context_text),
            "sha256": sha256_text(context_text),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": "" if result.returncode == 0 else sanitize_context_output(
                (result.stdout or "") + "\n" + (result.stderr or "")
            )[-2000:],
        }
    except Exception as exc:
        return "", {
            "provider": provider,
            "available": False,
            "exit_code": -1,
            "chars": 0,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc)[:2000],
        }


MINI_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
MINI_TEST_RE = re.compile(
    r"(?:^|\s)(?:pytest|py\.test|tox|nox|unittest|python\s+-m\s+pytest|"
    r"python\d*(?:\.\d+)?\s+-c|npm\s+test|make\s+test)(?:\s|$)",
    re.I,
)
MINI_NETWORK_RE = re.compile(
    r"(?:^|\s)(?:curl|wget|git\s+clone|pip\s+install|npm\s+install)(?:\s|$)",
    re.I,
)


def diagnose_mini_trajectory(trajectory: Any) -> dict[str, Any]:
    """Extract comparable process metrics from mini-SWE Hermes trajectories."""

    calls: list[dict[str, Any]] = []
    if isinstance(trajectory, list):
        for event_index, event in enumerate(trajectory):
            if not isinstance(event, dict) or event.get("from") != "gpt":
                continue
            raw_value = str(event.get("value", ""))
            # JSON-action trajectories do not contain <tool_call> wrappers.
            # Count their validated actions here as well so J3 edit/search
            # behavior is not reported as zero tool calls.
            try:
                structured = parse_action_envelope(raw_value)
            except (ActionParseError, TypeError, ValueError):
                structured = None
            if structured is not None:
                calls.append(
                    {
                        "event_index": event_index,
                        "name": structured.action,
                        "input": structured.to_dict(),
                        "structured": True,
                    }
                )
            for match in MINI_TOOL_CALL_RE.finditer(str(event.get("value", ""))):
                try:
                    decoded = json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
                arguments = decoded.get("arguments", {})
                if isinstance(arguments, dict):
                    calls.append(
                        {
                            "event_index": event_index,
                            "name": str(decoded.get("name", "")),
                            "input": arguments,
                        }
                    )
    commands = [
        str(call["input"].get("command", "")).strip()
        for call in calls
        if call["input"].get("command")
    ]
    edit_calls = [
        call
        for call in calls
        if any(
            token in str(call["input"].get("command", "")).lower()
            for token in ("apply_patch", "sed -i", "python - <<", "cat >", "tee ")
        )
        or call["name"] in {"edit", "replace"}
    ]
    test_calls = [call for call in calls if MINI_TEST_RE.search(str(call["input"].get("command", "")))]
    repeated = sum(count - 1 for count in Counter(commands).values() if count > 1)
    first_edit = edit_calls[0] if edit_calls else None
    first_test = test_calls[0] if test_calls else None
    rendered_tool_inputs = json.dumps([call["input"] for call in calls], ensure_ascii=False)
    tool_errors = 0
    blocked_network_attempts = 0
    blocked_outside_attempts = 0
    if isinstance(trajectory, list):
        for event in trajectory:
            if isinstance(event, dict) and event.get("from") == "tool":
                value = str(event.get("value", ""))
                tool_errors += value.count('"exit_code": 2') + value.count('"exit_code": 1')
                blocked_network_attempts += value.count("NETWORK_POLICY_GUARD")
                blocked_outside_attempts += value.count("OUTSIDE_REPO_GUARD")
    network_attempts = sum(bool(MINI_NETWORK_RE.search(command)) for command in commands)
    allowed_path_prefixes = ("/workspace", "/testbed", "/home/user", "/tmp", "/dev/null")
    # URLs are network-policy evidence, not filesystem paths.  Strip them
    # before the absolute-path guard so a blocked `git clone https://...` is
    # counted once as a network event rather than also as a spurious outside
    # workspace access.
    path_scan_commands = [re.sub(r"https?://[^\s'\";,]+", "", command) for command in commands]
    outside_attempts = sum(
        any(
            not path.startswith(allowed_path_prefixes)
            for path in re.findall(r"(?:^|\s)(/(?:[^\s'\";,]+)?)", command)
        )
        for command in path_scan_commands
    )
    return {
        "tool_calls": len(calls),
        "edit_tool_calls": len(edit_calls),
        "structured_actions": sum(bool(call.get("structured")) for call in calls),
        "structured_action_counts": dict(Counter(call["name"] for call in calls if call.get("structured"))),
        "test_tool_calls": len(test_calls),
        "first_edit_event": first_edit["event_index"] if first_edit else None,
        "first_edit_ms": None,
        "first_test_event": first_test["event_index"] if first_test else None,
        "first_test_ms": None,
        "tests_after_edit": bool(
            first_edit and any(call["event_index"] > first_edit["event_index"] for call in test_calls)
        ),
        "repeated_commands": repeated,
        "tool_errors": tool_errors,
        "network_tool_attempts": network_attempts,
        "blocked_network_attempts": blocked_network_attempts,
        "hidden_data_attempts": int(
            bool(re.search(r"FAIL_TO_PASS|PASS_TO_PASS|test_patch|gold[_ -]?patch", rendered_tool_inputs, re.I))
        ),
        "outside_workspace_attempts": outside_attempts,
        "blocked_outside_attempts": blocked_outside_attempts,
        "integrity_eligible": not bool(
            (network_attempts > blocked_network_attempts)
            or (outside_attempts > blocked_outside_attempts)
            or re.search(r"FAIL_TO_PASS|PASS_TO_PASS|test_patch|gold[_ -]?patch", rendered_tool_inputs, re.I)
        ),
    }


def run_mini(
    harness: str,
    task: dict[str, Any],
    workspace: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_calls: int,
    api_timeout: int,
    transport_retries: int,
    agent_image: str,
    agent_env: str = "docker",
    max_wall_time: int | None = None,
    max_tool_calls: int = 30,
    seed: int | None = 0,
) -> dict[str, Any]:
    context_variant, json_mode, controller_policy, verifier_mode = MINI_CONFIGS[harness]
    harness_options = MINI_HARNESS_OPTIONS.get(harness, {})
    context_refresh_enabled = bool(harness_options.get("context_refresh"))
    edit_protocol = str(harness_options.get("edit_protocol", "diff"))
    context_extraction: dict[str, Any] | None = None
    context_text = ""
    old_values: dict[str, str | None] = {}
    if context_variant in {"C1", "C2"}:
        provider = "aider" if context_variant == "C1" else "repograph"
        context_text, context_extraction = extract_context(provider, workspace, model, task["prompt"])
        (workspace / ".track2-context.txt").write_text(context_text)
        variable = (
            "TRACK2_AIDER_REPOMAP_COMMAND"
            if context_variant == "C1"
            else "TRACK2_REPOGRAPH_COMMAND"
        )
        old_values[variable] = os.environ.get(variable)
        os.environ[variable] = "cat .track2-context.txt"

    context_refresh_callback = None
    if context_refresh_enabled and context_variant == "C1":
        def refresh_context(focus_files: list[str], focus_identifiers: list[str]) -> ContextResult:
            nonlocal context_extraction
            refreshed_text, refreshed_details = extract_context(
                "aider",
                workspace,
                model,
                task["prompt"],
                focus_files=focus_files,
                focus_identifiers=focus_identifiers,
            )
            (workspace / ".track2-context-refresh.txt").write_text(refreshed_text)
            if context_extraction is None:
                context_extraction = {}
            context_extraction["refresh"] = refreshed_details
            return ContextResult(
                "C1R1",
                refreshed_text,
                "aider-repomap-focused",
                bool(refreshed_text.strip()) and bool(refreshed_details.get("available")),
                {
                    "initial": dict(context_extraction),
                    "refresh": refreshed_details,
                    "token_budget": 2048,
                    "focus_files": sorted(set(focus_files)),
                    "focus_identifiers": sorted(set(focus_identifiers)),
                },
            )

        context_refresh_callback = refresh_context

    try:
        runner = MiniSWERunner(
            model=model,
            base_url=base_url,
            api_key=api_key,
            env_type=agent_env,
            image=agent_image,
            cwd=str(workspace.resolve()),
            max_iterations=max_calls,
            max_model_turns=max_calls,
            max_tool_calls=max_tool_calls,
            max_wall_time_seconds=max_wall_time or 900,
            max_completion_tokens=8192,
            top_p=0.95,
            top_k=20,
            presence_penalty=0.0,
            seed=seed,
            command_timeout=45,
            api_timeout=api_timeout,
            api_transport_retries=transport_retries,
            require_localhost=agent_env == "local",
            context_variant=context_variant,
            json_mode=json_mode,
            controller_policy=controller_policy,
            verifier_mode=verifier_mode,
            max_json_retries=1 if json_mode == "J2" else 0,
            edit_protocol=edit_protocol,
            context_refresh_callback=context_refresh_callback,
        )
        with wall_time_limit(max_wall_time):
            raw = runner.run_task(task["prompt"])
    finally:
        for variable, value in old_values.items():
            if value is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = value

    metadata = raw.get("metadata", {})
    api = metadata.get("api", {})
    trajectory = raw.get("conversations", [])
    # Docker runs bind-mount the exact host workspace.  In some Docker/bash
    # combinations the final in-container `git diff` output is lost when the
    # session wrapper appends its CWD marker, even though the mutation is
    # present on the host.  Capture the frozen candidate from the host as a
    # deterministic fallback before the evaluator sees it.
    final_patch = str(metadata.get("final_patch", ""))
    changed_files = list(metadata.get("changed_files", []))
    if not final_patch:
        fallback = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--binary", "--no-ext-diff", "--", ".", ":!.aider*"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if fallback.returncode == 0:
            final_patch = fallback.stdout
    if not changed_files:
        fallback_files = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--name-only", "--", ".", ":!.aider*"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        if fallback_files.returncode == 0:
            changed_files = [line.strip() for line in fallback_files.stdout.splitlines() if line.strip()]
    return {
        "metrics_version": 3,
        "semantic_calls": int(raw.get("api_calls", 0)),
        "model_turns": int(raw.get("api_calls", 0)),
        "usage": api.get("usage", {}),
        "api_errors": api.get("errors", []),
        "model_latency_ms": api.get("total_latency_ms", 0),
        "transport_attempts": api.get(
            "transport_attempts",
            int(raw.get("api_calls", 0)) + len(api.get("errors", [])),
        ),
        "wall_time_ms": metadata.get("wall_time_ms", 0),
        "agent_completed": bool(raw.get("completed")),
        "final_patch": final_patch,
        "changed_files": changed_files,
        "json_valid_responses": metadata.get("json_valid_responses", 0),
        "json_responses": metadata.get("json_responses", 0),
        "patch_apply_results": metadata.get("patch_apply_results", []),
        "patch_apply_errors": metadata.get("patch_apply_errors", []),
        "action_counts": metadata.get("action_counts", {}),
        "edit_protocol": metadata.get("edit_protocol", edit_protocol),
        "edit_attempts": metadata.get("edit_attempts", 0),
        "edit_successes": metadata.get("edit_successes", 0),
        "edit_errors": metadata.get("edit_errors", []),
        "replace_attempts": metadata.get("replace_attempts", 0),
        "replace_successes": metadata.get("replace_successes", 0),
        "replace_errors": metadata.get("replace_errors", []),
        "path_recovery_events": metadata.get("path_recovery_events", []),
        "context_refresh": metadata.get("context_refresh", {"attempted": False}),
        "path_alias_rewrites": metadata.get("path_alias_rewrites", 0),
        "inspection_gate_rejections": metadata.get("inspection_gate_rejections", 0),
        "verifier": metadata.get("verifier"),
        "context_extraction": context_extraction,
        "runner_context": {
            "provider": metadata.get("context_provider"),
            "available": metadata.get("context_available"),
            "metadata": metadata.get("context_metadata", {}),
        },
        "trajectory_diagnostics": diagnose_mini_trajectory(trajectory),
        # Private payloads are popped by main() and persisted as separate
        # artifacts, keeping results.jsonl compact while retaining auditability.
        "_trajectory": trajectory,
        "_context_text": context_text,
    }


TOKEN_RE = re.compile(
    r"Tokens:\s*([\d.]+)([kKmM]?) sent(?:,\s*([\d.]+)([kKmM]?) received)?"
)


def scaled_number(number: str | None, suffix: str | None) -> int:
    if not number:
        return 0
    multiplier = {"": 1, "k": 1000, "m": 1_000_000}.get((suffix or "").lower(), 1)
    return int(float(number) * multiplier)


def parse_aider_usage(output: str) -> dict[str, int]:
    sent = received = 0
    for match in TOKEN_RE.finditer(output):
        sent += scaled_number(match.group(1), match.group(2))
        received += scaled_number(match.group(3), match.group(4))
    return {"input_tokens": sent, "output_tokens": received, "total_tokens": sent + received}


def run_aider_call(
    workspace: Path,
    solution_files: list[str],
    message_file: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    api_timeout: int,
) -> dict[str, Any]:
    aider_model = model if model.startswith("openai/") else f"openai/{model}"
    env = dict(os.environ)
    env.update(
        OPENAI_API_KEY=api_key,
        OPENAI_API_BASE=base_url,
        AIDER_ANALYTICS_DISABLE="true",
        AIDER_CHECK_UPDATE="false",
        LITELLM_LOG="ERROR",
    )
    command = [
        str(AIDER_PYTHON),
        str(ROOT / "track2_aider_entrypoint.py"),
        "--model",
        aider_model,
        "--weak-model",
        aider_model,
        "--openai-api-base",
        base_url,
        "--edit-format",
        "whole",
        "--map-tokens",
        "2048",
        "--message-file",
        str(message_file.resolve()),
        "--yes-always",
        "--no-stream",
        "--no-pretty",
        "--no-fancy-input",
        "--no-show-model-warnings",
        "--no-check-model-accepts-settings",
        "--no-auto-commits",
        "--no-dirty-commits",
        "--no-gitignore",
        "--no-restore-chat-history",
        # Benchmark prompts contain reference URLs.  Aider's interactive URL
        # detector otherwise launches a browser/pandoc scraping path before
        # coding, adding unrelated network failures and leaking web content
        # into only this comparator.
        "--no-detect-urls",
        "--analytics-disable",
        "--timeout",
        str(api_timeout),
        *solution_files,
    ]
    started = time.perf_counter()
    try:
        result = run_command(command, cwd=workspace, env=env, timeout=api_timeout + 30)
        output = result.stdout[-30000:]
        return {
            "returncode": result.returncode,
            "output": output,
            "usage": parse_aider_usage(output),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {
            "returncode": 124,
            "output": (output + "\nAIDER_TIMEOUT")[-30000:],
            "usage": parse_aider_usage(output),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def aider_call_produced_generation(
    call: dict[str, Any],
    patch_before: str,
    patch_after: str,
) -> bool:
    """Return whether an Aider subprocess produced a model generation.

    Aider can exit successfully after an HTTP 403 and the outer subprocess can
    time out after a model edit was already applied. Token usage or an actual
    solution-file diff is therefore a more reliable semantic-call boundary
    than the subprocess return code alone.
    """
    usage = call.get("usage", {})
    return int(usage.get("total_tokens", 0) or 0) > 0 or patch_before != patch_after


def run_aider(
    task: dict[str, Any],
    workspace: Path,
    prompt_dir: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_calls: int,
    api_timeout: int,
    transport_retries: int,
) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    transport_attempts: list[dict[str, Any]] = []
    transport_errors: list[str] = []
    prompt_dir.mkdir(parents=True, exist_ok=True)
    message = task["prompt"]
    for attempt in range(1, max_calls + 1):
        message_path = prompt_dir / f"{task['task_id']}-attempt-{attempt}.md"
        message_path.write_text(message)
        call: dict[str, Any] | None = None
        for transport_attempt in range(transport_retries + 1):
            patch_before = git_output(
                workspace,
                "diff",
                "--binary",
                "--no-ext-diff",
                "--",
                *task["solution_files"],
            )
            candidate = run_aider_call(
                workspace,
                task["solution_files"],
                message_path,
                base_url=base_url,
                api_key=api_key,
                model=model,
                api_timeout=api_timeout,
            )
            patch_after = git_output(
                workspace,
                "diff",
                "--binary",
                "--no-ext-diff",
                "--",
                *task["solution_files"],
            )
            candidate["transport_attempt"] = transport_attempt + 1
            candidate["produced_generation"] = aider_call_produced_generation(
                candidate,
                patch_before,
                patch_after,
            )
            transport_attempts.append(candidate)
            if candidate["produced_generation"]:
                call = candidate
                if candidate["returncode"] != 0:
                    transport_errors.append(candidate["output"][-2000:])
                break
            transport_errors.append(candidate["output"][-2000:])
        if call is None:
            break
        calls.append(call)
        if attempt < max_calls:
            message = (
                task["prompt"]
                + "\n\nYour previous pass may already have edited the files. Review the current "
                "implementation against the original request, correct any remaining issue, "
                "and keep public APIs intact. Hidden tests are unavailable and must not be "
                "searched for.\n"
            )

    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for call in calls:
        for key in usage:
            usage[key] += int(call["usage"].get(key, 0))
    final_patch = git_output(workspace, "diff", "--binary", "--no-ext-diff", "--", *task["solution_files"])
    return {
        "metrics_version": 3,
        "semantic_calls": len(calls),
        "model_turns": len(calls),
        "usage": usage,
        "api_errors": transport_errors,
        "model_latency_ms": round(
            sum(call["duration_ms"] for call in transport_attempts), 2
        ),
        "wall_time_ms": round(
            sum(call["duration_ms"] for call in transport_attempts),
            2,
        ),
        "agent_completed": bool(final_patch),
        "final_patch": final_patch,
        "changed_files": git_output(
            workspace, "diff", "--name-only", "--", *task["solution_files"]
        ).splitlines(),
        "aider_returncodes": [int(call.get("returncode", -1)) for call in calls],
        "trajectory_diagnostics": {
            "tool_calls": 0,
            "edit_tool_calls": sum(bool(call.get("produced_generation")) for call in calls),
            "test_tool_calls": 0,
            "first_edit_event": 0 if final_patch else None,
            "first_edit_ms": None,
            "first_test_event": None,
            "first_test_ms": None,
            "tests_after_edit": False,
            "repeated_commands": 0,
            "tool_errors": sum(int(call.get("returncode", 0)) != 0 for call in calls),
            "network_tool_attempts": 0,
            "hidden_data_attempts": 0,
            "outside_workspace_attempts": 0,
            "integrity_eligible": True,
        },
        "_trajectory": {
            "semantic_calls": calls,
            "transport_attempts": transport_attempts,
        },
        "_context_text": "",
        "hidden_test_feedback_exposed": False,
    }


def add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        total[key] += int(usage.get(key, 0) or 0)


def infrastructure_incomplete(row: dict[str, Any]) -> bool:
    """Whether transport failure prevented a full, scoreable task run."""
    return bool(
        not row.get("resolved")
        and row.get("api_errors")
        and int(row.get("semantic_calls", 0)) < int(row.get("max_calls", 0))
    )


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def repeat_reliability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task_id"])].append(bool(row.get("resolved")))
    repeated = [outcomes for outcomes in by_task.values() if len(outcomes) > 1]
    return {
        "repeat_tasks": len(repeated),
        "pass_at_k": (
            sum(any(outcomes) for outcomes in repeated) / len(repeated) if repeated else None
        ),
        "pass_power_k": (
            sum(all(outcomes) for outcomes in repeated) / len(repeated) if repeated else None
        ),
    }


def summarize(results: list[dict[str, Any]], harness_order: list[str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["harness"]].append(result)
    summaries: list[dict[str, Any]] = []
    for harness in harness_order:
        rows = grouped.get(harness, [])
        passed = sum(bool(row.get("resolved")) for row in rows)
        low, high = wilson(passed, len(rows))
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for row in rows:
            add_usage(usage, row.get("usage", {}))
        responded_tasks = sum(int(row.get("semantic_calls", 0)) > 0 for row in rows)
        incomplete_tasks = sum(infrastructure_incomplete(row) for row in rows)
        json_responses = sum(int(row.get("json_responses", 0)) for row in rows)
        json_valid_responses = sum(int(row.get("json_valid_responses", 0)) for row in rows)
        patch_attempts = [
            bool(value)
            for row in rows
            for value in row.get("patch_apply_results", [])
        ]
        verifier_rows = [row for row in rows if row.get("verifier")]
        verifier_accepts = sum(
            bool(row.get("verifier", {}).get("passed")) for row in verifier_rows
        )
        diagnostics = [row.get("trajectory_diagnostics", {}) for row in rows]
        integrity_failures = sum(
            not bool(item.get("integrity_eligible", True)) for item in diagnostics
        ) + sum(bool(row.get("qwen_settings_contains_secret")) for row in rows)
        wall_times = [float(row.get("wall_time_ms", 0)) for row in rows]
        repeat_ids = sorted({int(row.get("repeat", 1)) for row in rows})
        per_repeat_scores = {}
        for repeat_id in repeat_ids:
            repeat_rows = [row for row in rows if int(row.get("repeat", 1)) == repeat_id]
            per_repeat_scores[str(repeat_id)] = (
                sum(bool(row.get("resolved")) for row in repeat_rows) / len(repeat_rows)
                if repeat_rows
                else 0.0
            )
        summaries.append(
            {
                "harness": harness,
                "tasks": len(rows),
                "resolved": passed,
                "score": passed / len(rows) if rows else 0.0,
                "wilson_95_low": low,
                "wilson_95_high": high,
                "total_semantic_calls": sum(int(row.get("semantic_calls", 0)) for row in rows),
                "mean_semantic_calls": (
                    statistics.mean(int(row.get("semantic_calls", 0)) for row in rows)
                    if rows
                    else 0
                ),
                "usage": usage,
                "mean_tokens": usage["total_tokens"] / len(rows) if rows else 0,
                "responded_tasks": responded_tasks,
                "mean_tokens_per_responded_task": (
                    usage["total_tokens"] / responded_tasks if responded_tasks else 0
                ),
                "mean_wall_time_ms": (
                    statistics.mean(wall_times)
                    if rows
                    else 0
                ),
                "p95_wall_time_ms": percentile(wall_times, 0.95),
                "api_error_tasks": sum(bool(row.get("api_errors")) for row in rows),
                "infrastructure_incomplete_tasks": incomplete_tasks,
                "complete_task_runs": len(rows) - incomplete_tasks,
                "json_responses": json_responses,
                "json_valid_responses": json_valid_responses,
                "json_valid_rate": (
                    json_valid_responses / json_responses if json_responses else None
                ),
                "patch_apply_attempts": len(patch_attempts),
                "patch_apply_successes": sum(patch_attempts),
                "patch_apply_rate": (
                    sum(patch_attempts) / len(patch_attempts) if patch_attempts else None
                ),
                "verifier_tasks": len(verifier_rows),
                "verifier_accepts": verifier_accepts,
                "verifier_false_accepts": sum(
                    bool(row.get("verifier", {}).get("passed")) and not row.get("resolved")
                    for row in verifier_rows
                ),
                "verifier_false_rejects": sum(
                    not bool(row.get("verifier", {}).get("passed")) and bool(row.get("resolved"))
                    for row in verifier_rows
                ),
                "patch_rate": (
                    sum(bool(row.get("patch_bytes")) for row in rows) / len(rows) if rows else 0
                ),
                "total_model_turns": sum(int(row.get("model_turns", 0)) for row in rows),
                "total_tool_calls": sum(int(item.get("tool_calls", 0)) for item in diagnostics),
                "mean_tool_calls": (
                    statistics.mean(int(item.get("tool_calls", 0)) for item in diagnostics)
                    if diagnostics
                    else 0
                ),
                "edit_rate": (
                    sum(int(item.get("edit_tool_calls", 0)) > 0 for item in diagnostics)
                    / len(diagnostics)
                    if diagnostics
                    else 0
                ),
                "test_after_edit_rate": (
                    sum(bool(item.get("tests_after_edit")) for item in diagnostics)
                    / len(diagnostics)
                    if diagnostics
                    else 0
                ),
                "repeated_commands": sum(
                    int(item.get("repeated_commands", 0)) for item in diagnostics
                ),
                "tool_errors": sum(int(item.get("tool_errors", 0)) for item in diagnostics),
                "network_tool_attempts": sum(
                    int(item.get("network_tool_attempts", 0)) for item in diagnostics
                ),
                "hidden_data_attempts": sum(
                    int(item.get("hidden_data_attempts", 0)) for item in diagnostics
                ),
                "outside_workspace_attempts": sum(
                    int(item.get("outside_workspace_attempts", 0)) for item in diagnostics
                ),
                "integrity_failures": integrity_failures,
                **repeat_reliability(rows),
                "per_repeat_scores": per_repeat_scores,
            }
        )
    ranked = sorted(
        summaries,
        key=lambda row: (
            row["infrastructure_incomplete_tasks"],
            -row["score"],
            row["mean_tokens"],
            row["mean_wall_time_ms"],
        ),
    )
    return {
        "metrics_version": 3,
        "harnesses": summaries,
        "ranking": [row["harness"] for row in ranked],
        "ranking_valid": all(
            row["infrastructure_incomplete_tasks"] == 0
            and row["integrity_failures"] == 0
            for row in summaries
        ),
    }


def mcnemar_exact(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    a_only = sum(x and not y for x, y in zip(a, b))
    b_only = sum(y and not x for x, y in zip(a, b))
    discordant = a_only + b_only
    if discordant == 0:
        return a_only, b_only, 1.0
    tail = sum(math.comb(discordant, k) for k in range(0, min(a_only, b_only) + 1))
    p_value = min(1.0, 2 * tail / (2**discordant))
    return a_only, b_only, p_value


def write_report(
    output_dir: Path,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    tasks: list[dict[str, Any]],
    harnesses: list[str],
    *,
    model: str,
    base_url: str,
    max_calls: int,
    transport_retries: int,
    repeats: int,
) -> None:
    rows_by_key = {
        (row["harness"], int(row.get("repeat", 1)), row["task_id"]): row
        for row in results
    }
    completed_all = all(
        (harness, repeat_id, task["task_id"]) in rows_by_key
        for harness in harnesses
        for repeat_id in range(1, repeats + 1)
        for task in tasks
    )
    ranking = summary["ranking"]
    best = ranking[0] if ranking and summary.get("ranking_valid", False) else "n/a"
    table_lines = [
        "| Harness | 完整任务 | 通过/任务 | 严格 E2E 分数 | Wilson 95% CI | 总语义调用 | tokens/有回复题 | 平均耗时 | API 错误题 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(summary["harnesses"], key=lambda item: ranking.index(item["harness"])):
        table_lines.append(
            f"| {row['harness']} | {row['complete_task_runs']}/{row['tasks']} | "
            f"{row['resolved']}/{row['tasks']} | {row['score']:.1%} | "
            f"{row['wilson_95_low']:.1%}–{row['wilson_95_high']:.1%} | "
            f"{row['total_semantic_calls']} | {row['mean_tokens_per_responded_task']:.0f} | "
            f"{row['mean_wall_time_ms']/1000:.1f}s | {row['api_error_tasks']} |"
        )

    protocol_lines = [
        "| Harness | JSON 合法 | patch apply | verifier 接受 | 假接受 | 假拒绝 | 最终补丁率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    summary_by_harness = {row["harness"]: row for row in summary["harnesses"]}
    for harness in harnesses:
        row = summary_by_harness[harness]
        json_cell = (
            f"{row['json_valid_responses']}/{row['json_responses']} "
            f"({row['json_valid_rate']:.1%})"
            if row["json_valid_rate"] is not None
            else "—"
        )
        patch_cell = (
            f"{row['patch_apply_successes']}/{row['patch_apply_attempts']} "
            f"({row['patch_apply_rate']:.1%})"
            if row["patch_apply_rate"] is not None
            else "—"
        )
        verifier_cell = (
            f"{row['verifier_accepts']}/{row['verifier_tasks']}"
            if row["verifier_tasks"]
            else "—"
        )
        protocol_lines.append(
            f"| {harness} | {json_cell} | {patch_cell} | {verifier_cell} | "
            f"{row['verifier_false_accepts']} | {row['verifier_false_rejects']} | "
            f"{row['patch_rate']:.1%} |"
        )

    matrix = [
        "| 重复 | 任务 | " + " | ".join(harnesses) + " |",
        "|---:|---|" + "---:|" * len(harnesses),
    ]
    for repeat_id in range(1, repeats + 1):
        for task in tasks:
            cells = []
            for harness in harnesses:
                row = rows_by_key.get((harness, repeat_id, task["task_id"]))
                if row and row.get("resolved"):
                    cells.append("✅")
                elif row and infrastructure_incomplete(row):
                    cells.append("⚠️ infra")
                else:
                    cells.append("❌" if row else "—")
            matrix.append(
                f"| {repeat_id} | {task['task_id']} | " + " | ".join(cells) + " |"
            )

    paired_lines = []
    if completed_all and ranking and best != "n/a":
        paired_units = [
            (repeat_id, task["task_id"])
            for repeat_id in range(1, repeats + 1)
            for task in tasks
        ]
        best_values = [
            bool(rows_by_key[(best, repeat_id, task_id)]["resolved"])
            for repeat_id, task_id in paired_units
        ]
        for harness in harnesses:
            if harness == best:
                continue
            comparator_rows = [
                rows_by_key[(harness, repeat_id, task_id)]
                for repeat_id, task_id in paired_units
            ]
            if any(infrastructure_incomplete(row) for row in comparator_rows):
                paired_lines.append(
                    f"- `{best}` 对 `{harness}`：存在基础设施未完成任务，不计算 McNemar，"
                    "避免把缺失响应当作模型失败。"
                )
                continue
            values = [
                bool(rows_by_key[(harness, repeat_id, task_id)]["resolved"])
                for repeat_id, task_id in paired_units
            ]
            best_only, other_only, p_value = mcnemar_exact(best_values, values)
            paired_lines.append(
                f"- `{best}` 对 `{harness}`：最佳独赢 {best_only} 题，对方独赢 {other_only} 题，"
                f"McNemar 精确检验 p={p_value:.4f}。"
            )

    polyglot_commit = git_output(POLYGLOT_ROOT, "rev-parse", "HEAD").strip()
    aider_commit = git_output(AIDER_ROOT, "rev-parse", "HEAD").strip()
    repograph_commit = git_output(REPOGRAPH_ROOT, "rev-parse", "HEAD").strip()
    endpoint_host = re.sub(r"^https?://", "", base_url).split("/")[0]
    incomplete_count = sum(infrastructure_incomplete(row) for row in results)
    status = (
        f"已完成记录（含 {incomplete_count} 个基础设施未完成单元）"
        if completed_all and incomplete_count
        else ("完整" if completed_all else "进行中")
    )
    conclusion = (
        f"在这次固定 API 条件下，当前排名第一的是 **`{best}`**。"
        if completed_all and summary.get("ranking_valid", False)
        else "存在基础设施未完成单元，当前结果不产生 harness 胜负排名。"
        if completed_all
        else "实验尚未覆盖所有 harness×任务组合，当前排名只是中间结果。"
    )
    report = f"""# Track 2 API Harness 完整对比报告

生成时间：{datetime.now(timezone.utc).astimezone().isoformat()}  
实验状态：**{status}**

## 结论

{conclusion}

最终分数是完整隐藏测试通过率，不是 agent 的 `completed`、补丁可应用率或 verifier 接受率。
在并列时，仅用更低 token、再用更低耗时作为工程排序；并列并不代表统计上存在胜负。
本表的严格 E2E 分数把 API 未完成计为端到端失败；`完整任务` 用于区分 harness 能力失败和基础设施缺失。

本报告不写死推荐或历史分数；排名和统计完全由本目录的 `results.jsonl` 动态生成。
如果存在基础设施未完成单元，只报告端到端分数，不把它解释成纯 harness 能力差异。

## 最终评分

{chr(10).join(table_lines)}

`tokens/有回复题` 只在至少取得一次模型回复的任务上取平均，避免 0-call 基础设施失败把成本虚假压低。

## 逐题结果

{chr(10).join(matrix)}

图例：✅ 隐藏测试通过；❌ 已完整运行但未通过；⚠️ infra 在用完语义调用预算前耗尽 transport retry。

## 协议层与 Verifier 诊断

{chr(10).join(protocol_lines)}

这里仅记录实际产生的 JSON、patch apply 与 verifier 指标。隐藏测试始终是最终裁判，
verifier 不能覆盖失败的最终测试。

## 配对统计

{chr(10).join(paired_lines) if paired_lines else '- 样本尚未完整，暂不计算。'}

样本量较小，Wilson 区间会较宽；McNemar p 值大于 0.05 时，不应声称差异具有统计显著性。

## 实验设计

- Benchmark：Aider 官方 Polyglot Benchmark 的固定 Python 子集，题目列表和 seed 固化在 `manifest.json`。
- 重复：{repeats} 次；每个 `(repeat, task, harness)` 都从干净源码开始。
- 模型：`{model}`；API 主机：`{endpoint_host}`。
- 公平预算：每个 harness 每题最多 {max_calls} 次语义模型调用；每次语义调用最多
  {transport_retries + 1} 次 transport 尝试，网络/403/超时不消耗语义预算；温度由同一模型/服务端契约决定。
- 模型只看到官方自然语言说明与待修改源码。隐藏测试只在最终候选冻结后复制并执行一次，
  中间重试不接收隐藏测试的存在、名称或输出。
- 判分：完整 `unittest` 测试套件在 `--network none`、只读挂载的 Docker 容器中执行。
- 每个任务和 harness 都从相同原始源码重新初始化，避免补丁污染后续实验。
- API key 从环境变量或 macOS Keychain 读取，不写入代码、命令行结果或报告。

## Harness 定义

- `mini-original`：原始 mini-SWE 控制器，C0/J0/V0。
- `mini-repomap`：只增加 Aider Repo Map，C1/J0/V0；这是 Repo Map 的主单因素消融。
- `mini-repograph-clean`：只增加 RepoGraph，C2/J0/V0；与 Repo Map 分开运行。
- `mini-json-verifier`：mini-SWE + 请求 vLLM-style `structured_outputs` 的 J3 JSON action + V1
  确定性 verifier；API 接受请求不等于能证明服务端执行了 grammar constrained decoding。
- `mini-aider-repomap`：上一项再单独加入 Aider Repo Map 初始上下文。
- `mini-repograph`：上一项改为 RepoGraph 图上下文；与 Repo Map 不同时开启。
- `aider-whole`：独立 Aider harness，使用 `whole` 编辑格式。后续调用只要求根据原始任务复核当前实现，
  不会得到隐藏测试反馈；这是完整 harness 的端到端比较，不是只替换 controller prompt 的纯消融。

## 可复现版本

- 本项目代码：工作区当前版本（原始实验文件未强制提交）。
- Polyglot commit：`{polyglot_commit}`。
- Aider commit：`{aider_commit}`。
- RepoGraph commit：`{repograph_commit}`。
- transport-aware 最终记录：`results.jsonl`；汇总：`summary.json`；补丁：`patches/`。
- 完整轨迹：`trajectories/`；上下文快照：`contexts/`；不可变运行配置：`run-config.json`。

## 解释与 Track 2 建议

这个 benchmark 能客观比较“小模型能否通过 harness 把自然语言需求变成可执行代码”，尤其适合测试
JSON action、编辑协议和测试反馈。但 Python 子集多数是单文件题，因此它对 Repo Map/RepoGraph 的仓库级定位收益
并不敏感。若上下文模块在此处没有提升，不能推出它在 SWE-bench 多文件仓库中无效。

`mini-original` 对 `mini-repomap` 才能回答 Repo Map 的单因素问题；历史上的
`mini-aider-repomap` 同时启用了 J3 和 V1，只保留为协议诊断，不能用于这项归因。
Polyglot Python 主要衡量编辑与控制可靠性。Repo Map/RepoGraph 的最终选型仍需在多文件 SWE-bench
任务上用官方 evaluator 复验。

## 局限

1. 固定子集规模有限，置信区间宽；完整 34 题 Python 或多语言 225 题才适合 leaderboard 级结论。
2. 这是 API-only 阶段，不能测 AMD Cloud 本地 vLLM 的 tokens/s、TTFT、显存或 xgrammar 解码开销。
3. 任何 403、超时或限流都单独标为 infrastructure incomplete；Aider 的 token 数来自 CLI usage 输出，
   仍应以 API 侧账单复核。
4. 单文件 Exercism 题不能替代 SWE-bench 的大型仓库定位能力评测。
5. API 未提供可验证的随机 seed 契约；固定温度、任务和预算不能完全消除服务端非确定性。
"""
    (output_dir / "report.zh-CN.md").write_text(report)


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs" / "harness-final")
    parser.add_argument("--task-count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--harness",
        action="append",
        choices=tuple(MINI_CONFIGS) + ("aider-whole", "qwen-code"),
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--base-url", default=os.getenv("TRACK2_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--model", default=os.getenv("TRACK2_MODEL", "Qwen3-14B-BF16"))
    parser.add_argument("--api-timeout", type=int, default=60)
    parser.add_argument(
        "--transport-retries",
        type=int,
        default=3,
        help="transport retries per semantic model call (do not consume the call budget)",
    )
    parser.add_argument("--agent-image", default="track2-python-agent:py312")
    parser.add_argument("--agent-env", choices=("local", "docker"), default="docker")
    parser.add_argument("--test-image", default="python:3.12-slim")
    parser.add_argument("--qwen-bin", type=Path, default=QWEN_BIN)
    parser.add_argument("--max-wall-time", type=int, default=900)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="drop and rerun rows whose transport failures exhausted retries before the semantic budget",
    )
    args = parser.parse_args()

    if (
        args.task_count <= 0
        or args.max_calls <= 0
        or args.repeats <= 0
        or args.transport_retries < 0
        or args.max_wall_time <= 0
        or args.max_tool_calls <= 0
    ):
        parser.error(
            "task count/max calls/repeats/wall time/tool calls must be positive and "
            "transport retries non-negative"
        )
    harnesses = args.harness or list(DEFAULT_HARNESSES)
    api_key = keychain_secret()
    if not api_key and args.base_url.startswith(("http://127.0.0.1", "http://localhost")):
        api_key = "local-vllm"
    if not api_key:
        raise SystemExit("TRACK2_API_KEY is missing and macOS Keychain entry was not found")
    required = [POLYGLOT_ROOT]
    if any(harness in {"aider-whole", "mini-repomap", "mini-aider-repomap"} for harness in harnesses):
        required.extend([AIDER_BIN, AIDER_PYTHON])
    if any(harness in {"mini-repograph-clean", "mini-repograph"} for harness in harnesses):
        required.append(REPOGRAPH_PYTHON)
    if "qwen-code" in harnesses:
        required.append(args.qwen_bin)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing benchmark dependencies: " + ", ".join(missing))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tasks = create_or_load_manifest(args.output_dir, args.task_count, args.seed)
    run_config = {
        "protocol_version": 3,
        "benchmark": "aider-polyglot-python-hidden-final-only",
        "harnesses": harnesses,
        "mini_configs": {
            harness: list(MINI_CONFIGS[harness])
            for harness in harnesses
            if harness in MINI_CONFIGS
        },
        "task_count": args.task_count,
        "seed": args.seed,
        "repeats": args.repeats,
        "max_calls": args.max_calls,
        "transport_retries": args.transport_retries,
        "api_timeout": args.api_timeout,
        "max_wall_time": args.max_wall_time,
        "max_tool_calls": args.max_tool_calls,
        "model": args.model,
        "base_url": args.base_url,
        "agent_image": args.agent_image,
        "agent_env": args.agent_env,
        "test_image": args.test_image,
        "hidden_test_policy": "final-only-no-feedback",
        "polyglot_commit": git_output(POLYGLOT_ROOT, "rev-parse", "HEAD").strip(),
        "aider_commit": git_output(AIDER_ROOT, "rev-parse", "HEAD").strip(),
        "repograph_commit": git_output(REPOGRAPH_ROOT, "rev-parse", "HEAD").strip(),
        "qwen_code_version": QWEN_CODE_VERSION if "qwen-code" in harnesses else None,
    }
    config_path = args.output_dir / "run-config.json"
    if config_path.exists() and json.loads(config_path.read_text()) != run_config:
        raise SystemExit("existing run-config.json differs; use a new output directory")
    config_path.write_text(json.dumps(run_config, ensure_ascii=False, indent=2) + "\n")
    results_path = args.output_dir / "results.jsonl"
    results = load_results(results_path)
    if args.retry_incomplete:
        retry_keys = {
            (row["harness"], int(row.get("repeat", 1)), row["task_id"])
            for row in results
            if infrastructure_incomplete(row)
        }
        if retry_keys:
            results = [
                row
                for row in results
                if (row["harness"], int(row.get("repeat", 1)), row["task_id"])
                not in retry_keys
            ]
            results_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results)
            )
            print(f"RETRY {len(retry_keys)} infrastructure-incomplete run(s)", flush=True)
    completed = {
        (row["harness"], int(row.get("repeat", 1)), row["task_id"])
        for row in results
    }

    for repeat_id in range(1, args.repeats + 1):
        for index, task in enumerate(tasks, 1):
            unit_harnesses = list(harnesses)
            random.Random(f"{args.seed}:{repeat_id}:{task['task_id']}").shuffle(unit_harnesses)
            for harness in unit_harnesses:
                key = (harness, repeat_id, task["task_id"])
                if key in completed:
                    print(
                        f"SKIP r{repeat_id} {harness} {task['task_id']} (already recorded)",
                        flush=True,
                    )
                    continue
                print(
                    f"RUN r{repeat_id}/{args.repeats} {harness} {index}/{len(tasks)} {task['task_id']}",
                    flush=True,
                )
                workspace = (
                    args.output_dir
                    / "workspaces"
                    / harness
                    / f"repeat-{repeat_id:02d}"
                    / task["task_id"]
                )
                prepare_workspace(task, workspace)
                started = time.perf_counter()
                try:
                    if harness == "aider-whole":
                        agent_result = run_aider(
                            task,
                            workspace,
                            args.output_dir / "prompts" / harness / f"repeat-{repeat_id:02d}",
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            max_calls=args.max_calls,
                            api_timeout=args.api_timeout,
                            transport_retries=args.transport_retries,
                        )
                    elif harness == "qwen-code":
                        agent_result = run_qwen_code(
                            task,
                            workspace,
                            args.output_dir
                            / "qwen-runtime"
                            / f"repeat-{repeat_id:02d}"
                            / task["task_id"],
                            qwen_bin=args.qwen_bin,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            max_calls=args.max_calls,
                            max_tool_calls=args.max_tool_calls,
                            max_wall_time=args.max_wall_time,
                            api_timeout=args.api_timeout,
                            transport_retries=args.transport_retries,
                        )
                    else:
                        agent_result = run_mini(
                            harness,
                            task,
                            workspace,
                            base_url=args.base_url,
                            api_key=api_key,
                            model=args.model,
                            max_calls=args.max_calls,
                            api_timeout=args.api_timeout,
                            transport_retries=args.transport_retries,
                            agent_image=args.agent_image,
                            agent_env=args.agent_env,
                            max_wall_time=args.max_wall_time,
                            max_tool_calls=args.max_tool_calls,
                        )

                    # Freeze the candidate before running hidden tests. Neither
                    # their names nor output are ever fed back to the harness.
                    patch = str(agent_result.pop("final_patch", ""))
                    trajectory = agent_result.pop("_trajectory", [])
                    context_text = str(agent_result.pop("_context_text", ""))
                    stderr_text = str(agent_result.pop("_stderr", ""))
                    final_test = hidden_test(task, workspace, args.test_image)

                    artifact_suffix = f"repeat-{repeat_id:02d}/{task['task_id']}"
                    patch_path = args.output_dir / "patches" / harness / f"{artifact_suffix}.patch"
                    trajectory_path = (
                        args.output_dir / "trajectories" / harness / f"{artifact_suffix}.json"
                    )
                    context_path = args.output_dir / "contexts" / harness / f"{artifact_suffix}.txt"
                    stderr_path = args.output_dir / "stderr" / harness / f"{artifact_suffix}.log"
                    for artifact in (patch_path, trajectory_path, context_path, stderr_path):
                        artifact.parent.mkdir(parents=True, exist_ok=True)
                    patch_path.write_text(patch)
                    trajectory_path.write_text(
                        json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n"
                    )
                    context_path.write_text(context_text)
                    stderr_path.write_text(stderr_text)
                    result = {
                        "harness": harness,
                        "repeat": repeat_id,
                        "task_id": task["task_id"],
                        "resolved": bool(final_test["passed"]),
                        "test": final_test,
                        "patch_path": str(patch_path.resolve()),
                        "trajectory_path": str(trajectory_path.resolve()),
                        "context_path": str(context_path.resolve()),
                        "stderr_path": str(stderr_path.resolve()),
                        "context_sha256": sha256_text(context_text),
                        "patch_sha256": sha256_text(patch),
                        "patch_bytes": len(patch.encode("utf-8")),
                        "model": args.model,
                        "max_calls": args.max_calls,
                        "hidden_test_runs": 1,
                        "hidden_test_feedback_exposed": False,
                        "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **agent_result,
                    }
                except Exception as exc:
                    result = {
                        "harness": harness,
                        "repeat": repeat_id,
                        "task_id": task["task_id"],
                        "resolved": False,
                        "test": {"passed": False, "exit_code": -1, "output": str(exc), "duration_ms": 0},
                        "patch_path": "",
                        "trajectory_path": "",
                        "context_path": "",
                        "context_sha256": sha256_text(""),
                        "patch_sha256": sha256_text(""),
                        "patch_bytes": 0,
                        "model": args.model,
                        "max_calls": args.max_calls,
                        "semantic_calls": 0,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        "api_errors": [str(exc)[:2000]],
                        "hidden_test_runs": 0,
                        "hidden_test_feedback_exposed": False,
                        "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "exception": repr(exc),
                    }
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                results.append(result)
                completed.add(key)
                summary = summarize(results, harnesses)
                (args.output_dir / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
                )
                write_report(
                    args.output_dir,
                    results,
                    summary,
                    tasks,
                    harnesses,
                    model=args.model,
                    base_url=args.base_url,
                    max_calls=args.max_calls,
                    transport_retries=args.transport_retries,
                    repeats=args.repeats,
                )
                print(
                    f"DONE r{repeat_id} {harness} {task['task_id']} resolved={result['resolved']} "
                    f"calls={result.get('semantic_calls', 0)} tokens={result.get('usage', {}).get('total_tokens', 0)}",
                    flush=True,
                )

    summary = summarize(results, harnesses)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    write_report(
        args.output_dir,
        results,
        summary,
        tasks,
        harnesses,
        model=args.model,
        base_url=args.base_url,
        max_calls=args.max_calls,
        transport_retries=args.transport_retries,
        repeats=args.repeats,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
