"""Isolated Qwen Code adapter for Track 2 harness comparisons.

The adapter deliberately keeps credentials out of argv and settings files,
creates a fresh QWEN_HOME for every task, and returns only public trajectory
diagnostics.  Hidden evaluator data is never accepted by this module.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


QWEN_CODE_VERSION = "0.21.0"
USAGE_KEYS = {
    "input_tokens": ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens"),
    "output_tokens": (
        "output_tokens",
        "completion_tokens",
        "outputTokens",
        "completionTokens",
    ),
}
TEST_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:pytest|py\.test|tox|nox|unittest|python\s+-m\s+pytest|"
    r"python\d*(?:\.\d+)?\s+-c|npm\s+test|make\s+test)(?:\s|$)",
    re.I,
)
NETWORK_COMMAND_RE = re.compile(r"(?:^|\s)(?:curl|wget|git\s+clone|pip\s+install|npm\s+install)(?:\s|$)", re.I)
HIDDEN_DATA_RE = re.compile(r"FAIL_TO_PASS|PASS_TO_PASS|test_patch|gold[_ -]?patch", re.I)


def qwen_settings(
    *,
    base_url: str,
    model: str,
    api_timeout: int,
    transport_retries: int,
    max_completion_tokens: int = 8192,
    top_p: float = 0.95,
    top_k: int = 20,
    temperature: float = 0.6,
    presence_penalty: float = 0.0,
    seed: int | None = 0,
) -> dict[str, Any]:
    """Return a credential-free Qwen Code settings document."""

    return {
        "$version": 5,
        "security": {"auth": {"selectedType": "openai"}},
        "model": {
            "name": model,
            "skipLoopDetection": False,
            "maxSessionTurns": 12,
            "maxToolCalls": 30,
            "maxToolCallsPerTurn": 40,
            "skipStartupContext": True,
        },
        "tools": {"approvalMode": "yolo"},
        "modelProviders": {
            "openai": [
                {
                    "id": model,
                    "name": model,
                    "envKey": "TRACK2_API_KEY",
                    "baseUrl": base_url.rstrip("/"),
                    "contextWindowSize": 32768,
                    "generationConfig": {
                        "timeout": int(api_timeout * 1000),
                        "maxRetries": transport_retries,
                        "samplingParams": {
                            "temperature": temperature,
                            "top_p": top_p,
                            "top_k": top_k,
                            "presence_penalty": presence_penalty,
                            "max_tokens": max_completion_tokens,
                            **({"seed": seed} if seed is not None else {}),
                        },
                    },
                }
            ]
        },
        "telemetry": {"enabled": False},
    }


def parse_qwen_stream(stdout: str) -> list[dict[str, Any]]:
    """Parse Qwen Code stream-json, tolerating bounded non-JSON CLI noise."""

    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            events.append(decoded)
        elif isinstance(decoded, list):
            events.extend(item for item in decoded if isinstance(item, dict))
    if events:
        return events

    # `--output-format json` compatibility fallback.
    start = stdout.find("[")
    end = stdout.rfind("]")
    if start >= 0 and end > start:
        try:
            decoded = json.loads(stdout[start : end + 1])
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [item for item in decoded if isinstance(item, dict)]
    return []


def _usage_value(usage: dict[str, Any], aliases: Iterable[str]) -> int:
    for key in aliases:
        value = usage.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


def _event_usage(event: dict[str, Any]) -> dict[str, Any]:
    direct = event.get("usage")
    if isinstance(direct, dict):
        return direct
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    return {}


def qwen_usage(events: list[dict[str, Any]]) -> dict[str, int]:
    """Use the terminal result usage when present, else sum assistant turns."""

    result_events = [event for event in events if event.get("type") == "result"]
    sources = result_events[-1:] or [event for event in events if event.get("type") == "assistant"]
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for event in sources:
        usage = _event_usage(event)
        input_tokens = _usage_value(usage, USAGE_KEYS["input_tokens"])
        output_tokens = _usage_value(usage, USAGE_KEYS["output_tokens"])
        total = usage.get("total_tokens", usage.get("totalTokens"))
        try:
            total_tokens = int(total) if total is not None else input_tokens + output_tokens
        except (TypeError, ValueError):
            total_tokens = input_tokens + output_tokens
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["total_tokens"] += max(0, total_tokens)
    return totals


def qwen_model_turns(events: list[dict[str, Any]]) -> int:
    """Count semantic model responses, not stream fragments.

    Qwen emits thinking, text and tool-use fragments as separate assistant
    events. Exactly one terminal fragment for a response carries non-zero
    usage, so usage-bearing events form a stable turn boundary.
    """

    assistant_turns = sum(
        _usage_value(_event_usage(event), USAGE_KEYS["input_tokens"]) > 0
        or _usage_value(_event_usage(event), USAGE_KEYS["output_tokens"]) > 0
        for event in events
        if event.get("type") == "assistant"
    )
    if assistant_turns:
        return assistant_turns
    terminal = next((event for event in reversed(events) if event.get("type") == "result"), {})
    for key in ("num_turns", "numTurns", "turns"):
        if terminal.get(key) is not None:
            try:
                return max(0, int(terminal[key]))
            except (TypeError, ValueError):
                pass
    return 1 if _event_usage(terminal) else 0


def qwen_terminal_error(event: dict[str, Any]) -> bool:
    text = str(event.get("result") or event.get("error") or "")
    return (
        bool(event.get("is_error"))
        or "[API Error:" in text
        or event.get("subtype") in {"error", "failed", "timeout"}
    )


def _content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content", [])
    if isinstance(content, dict):
        return [content]
    return [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []


def _tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event_index, event in enumerate(events):
        for block in _content_blocks(event):
            if block.get("type") not in {"tool_use", "tool_call", "function_call"}:
                continue
            name = str(block.get("name") or block.get("tool_name") or "")
            payload = block.get("input", block.get("arguments", {}))
            calls.append(
                {
                    "call_index": len(calls),
                    "event_index": event_index,
                    "observed_ms": event.get("_observed_ms"),
                    "name": name,
                    "input": payload if isinstance(payload, dict) else {"value": payload},
                }
            )
    return calls


def _call_text(call: dict[str, Any]) -> str:
    return json.dumps(call.get("input", {}), ensure_ascii=False, sort_keys=True)


def _command(call: dict[str, Any]) -> str:
    payload = call.get("input", {})
    if not isinstance(payload, dict):
        return ""
    for key in ("command", "cmd", "script"):
        if payload.get(key):
            return str(payload[key])
    return ""


def qwen_diagnostics(events: list[dict[str, Any]], workspace: Path) -> dict[str, Any]:
    calls = _tool_calls(events)
    edit_tool_names = {
        "apply_patch",
        "edit",
        "edit_file",
        "multi_edit",
        "replace",
        "replace_file_content",
        "write_file",
    }
    edit_calls = [
        call
        for call in calls
        if call["name"].lower() in edit_tool_names
    ]
    test_calls = [call for call in calls if TEST_COMMAND_RE.search(_command(call))]
    commands = [_command(call).strip() for call in calls if _command(call).strip()]
    repeats = sum(count - 1 for count in Counter(commands).values() if count > 1)
    first_edit = edit_calls[0] if edit_calls else None
    first_test = test_calls[0] if test_calls else None
    tool_errors = 0
    for event in events:
        if event.get("is_error") is True or event.get("error"):
            tool_errors += 1
        for block in _content_blocks(event):
            if block.get("type") == "tool_result" and block.get("is_error") is True:
                tool_errors += 1

    network_calls = [call for call in calls if NETWORK_COMMAND_RE.search(_command(call))]
    hidden_attempts = [call for call in calls if HIDDEN_DATA_RE.search(_call_text(call))]
    outside_attempts = []
    workspace_text = str(workspace.resolve())
    for call in calls:
        payload = call.get("input", {})
        values = payload.values() if isinstance(payload, dict) else []
        absolute_paths = [value for value in values if isinstance(value, str) and value.startswith("/")]
        command = _command(call)
        if command:
            absolute_paths.extend(re.findall(r"(?<![\w.-])(/[^\s'\";,]+)", command))
        if any(
            not path.startswith(
                (workspace_text, "/workspace", "/project", "/home/user", "/tmp", "/dev/null")
            )
            for path in absolute_paths
        ):
            outside_attempts.append(call)

    return {
        "tool_calls": len(calls),
        "edit_tool_calls": len(edit_calls),
        "test_tool_calls": len(test_calls),
        "first_edit_event": first_edit["event_index"] if first_edit else None,
        "first_edit_ms": first_edit.get("observed_ms") if first_edit else None,
        "first_test_event": first_test["event_index"] if first_test else None,
        "first_test_ms": first_test.get("observed_ms") if first_test else None,
        "tests_after_edit": bool(
            first_edit and any(call["call_index"] > first_edit["call_index"] for call in test_calls)
        ),
        "repeated_commands": repeats,
        "tool_errors": tool_errors,
        "network_tool_attempts": len(network_calls),
        "hidden_data_attempts": len(hidden_attempts),
        "outside_workspace_attempts": len(outside_attempts),
        "integrity_eligible": not (network_calls or hidden_attempts or outside_attempts),
    }


def _run_streaming(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    timed_out = False
    deadline = started + timeout
    while selector.get_map():
        if time.perf_counter() >= deadline:
            timed_out = True
            process.kill()
            break
        for key, _ in selector.select(timeout=min(1.0, max(0.01, deadline - time.perf_counter()))):
            line = key.fileobj.readline()
            if not line:
                selector.unregister(key.fileobj)
                continue
            if key.data == "stdout":
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    stdout_lines.append(line)
                else:
                    if isinstance(decoded, dict):
                        decoded["_observed_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        stdout_lines.append(json.dumps(decoded, ensure_ascii=False) + "\n")
                    else:
                        stdout_lines.append(line)
            else:
                stderr_lines.append(line)
    if timed_out:
        try:
            tail_out, tail_err = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            tail_out, tail_err = process.communicate()
    else:
        tail_out, tail_err = process.communicate()
    if tail_out:
        stdout_lines.append(tail_out)
    if tail_err:
        stderr_lines.append(tail_err)
    return {
        "returncode": 124 if timed_out else int(process.returncode or 0),
        "timed_out": timed_out,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "<redacted>")[-12000:] if secret else value[-12000:]


def run_qwen_code(
    task: dict[str, Any],
    workspace: Path,
    runtime_dir: Path,
    *,
    qwen_bin: Path,
    base_url: str,
    api_key: str,
    model: str,
    max_calls: int,
    max_tool_calls: int,
    max_wall_time: int,
    api_timeout: int,
    transport_retries: int,
    max_completion_tokens: int = 8192,
    top_p: float = 0.95,
    top_k: int = 20,
    temperature: float = 0.6,
    presence_penalty: float = 0.0,
    seed: int | None = 0,
) -> dict[str, Any]:
    """Run one isolated, non-interactive Qwen Code task."""

    runtime_dir.mkdir(parents=True, exist_ok=True)
    home = runtime_dir / "home"
    logs = runtime_dir / "runtime"
    home.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    settings = qwen_settings(
        base_url=base_url,
        model=model,
        api_timeout=api_timeout,
        transport_retries=transport_retries,
        max_completion_tokens=max_completion_tokens,
        top_p=top_p,
        top_k=top_k,
        temperature=temperature,
        presence_penalty=presence_penalty,
        seed=seed,
    )
    settings["model"]["maxToolCallsPerTurn"] = max_tool_calls
    settings["model"]["maxToolCalls"] = max_tool_calls
    settings["model"]["maxSessionTurns"] = max_calls
    settings["model"]["maxWallTimeSeconds"] = max_wall_time
    (home / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

    env = dict(os.environ)
    env.update(
        TRACK2_API_KEY=api_key,
        QWEN_HOME=str(home.resolve()),
        QWEN_RUNTIME_DIR=str(logs.resolve()),
        QWEN_TELEMETRY_ENABLED="false",
        QWEN_CODE_SAFE_MODE="true",
        CI="true",
        NO_COLOR="1",
    )
    command = [
        str(qwen_bin.resolve()),
        "--prompt",
        (
            f"Tool path contract: the exact repository root visible to file tools is "
            f"{workspace.resolve()}. File tools that require absolute paths must use paths under "
            "that root. Shell commands already start at that root and may use relative paths. "
            "Do not use /home/user or /home/user/repo; those sandbox aliases are invalid in this "
            "runtime. This is a bounded repair run: spend at most half of the "
            f"{max_calls}-turn budget inspecting, then inspect all same-named "
            "overrides and implement the smallest fix before testing. Do not use "
            "todo or package installation; run focused checks before finishing.\n\n"
            + str(task["prompt"])
        ),
        "--model",
        model,
        "--auth-type",
        "openai",
        "--output-format",
        "stream-json",
        "--safe-mode",
        "--sandbox",
        "--yolo",
        # Qwen Code registers a broad built-in tool catalog. These tools do
        # not help a SWE-bench repair and consume schema/context budget; keep
        # the terminal, read/search, edit and test tools available.
        "--exclude-tools",
        "todo_write",
        "--exclude-tools",
        "computer_use__*",
        "--exclude-tools",
        "tool_search",
        "--exclude-tools",
        "read_mcp_resource",
        "--exclude-tools",
        "list_mcp_resources",
        "--exclude-tools",
        "list_mcp_resource_templates",
        "--max-session-turns",
        str(max_calls),
        "--max-tool-calls",
        str(max_tool_calls),
        "--max-wall-time",
        f"{max_wall_time}s",
    ]
    raw = _run_streaming(
        command,
        cwd=workspace,
        env=env,
        timeout=max_wall_time + 30,
    )
    events = parse_qwen_stream(raw["stdout"])
    usage = qwen_usage(events)
    diagnostics = qwen_diagnostics(events, workspace)
    model_turns = qwen_model_turns(events)
    result_events = [event for event in events if event.get("type") == "result"]
    terminal = result_events[-1] if result_events else {}
    terminal_text = str(terminal.get("result") or terminal.get("error") or "")
    final_patch = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    ).stdout
    changed_files = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    ).stdout.splitlines()
    diff_check = subprocess.run(
        ["git", "diff", "--check"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    stderr = _redact(raw["stderr"], api_key)
    terminal_error = qwen_terminal_error(terminal)
    budget_exhausted = (
        raw["returncode"] == 53
        and model_turns >= max_calls
        and "Reached max session turns" in stderr
    )
    api_errors = []
    if (raw["returncode"] != 0 and not budget_exhausted) or terminal_error:
        api_errors.append(stderr or terminal_text or "qwen-code failed")
    try:
        transport_attempts = int(terminal.get("num_turns", model_turns))
    except (TypeError, ValueError):
        transport_attempts = model_turns
    return {
        "metrics_version": 3,
        "semantic_calls": model_turns,
        "model_turns": model_turns,
        "usage": usage,
        "api_errors": api_errors,
        "transport_attempts": transport_attempts,
        "api_retry_count": max(0, transport_attempts - model_turns),
        "sampling": {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "presence_penalty": presence_penalty,
            "max_tokens": max_completion_tokens,
            "seed": seed,
        },
        "model_latency_ms": terminal.get("duration_api_ms", terminal.get("duration_ms", 0)),
        "wall_time_ms": raw["duration_ms"],
        "agent_completed": (
            bool(final_patch)
            or budget_exhausted
            or (bool(result_events) and not terminal_error)
        ),
        "termination_reason": (
            "wall_timeout"
            if raw["timed_out"] or "wall-clock budget" in stderr
            else (
                "max_model_turns"
                if budget_exhausted
                else ("api_error" if terminal_error else str(terminal.get("subtype") or "process_exit"))
            )
        ),
        "qwen_returncode": raw["returncode"],
        "final_patch": final_patch,
        "changed_files": changed_files,
        "patch_apply_results": [diff_check.returncode == 0] if final_patch else [],
        "patch_apply_errors": [diff_check.stdout[-4000:]] if diff_check.returncode else [],
        "trajectory_diagnostics": diagnostics,
        "hidden_test_feedback_exposed": False,
        "qwen_code_version": QWEN_CODE_VERSION,
        "qwen_settings_contains_secret": api_key in json.dumps(settings),
        "_trajectory": events,
        "_context_text": "",
        "_stderr": stderr,
    }
