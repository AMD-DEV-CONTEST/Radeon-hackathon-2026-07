#!/usr/bin/env python3
"""Standalone mini-SWE runner for AMD Track 2 experiments.

Features:
- Local or network-disabled Docker command execution
- OpenAI-compatible local vLLM or API inference
- Context, structured-action, and verifier ablation switches
- Serializable trajectories and per-task resource accounting
- Supports batch processing from JSONL prompt files

Usage:
    # Run a single task with local environment
    python mini_swe_runner.py --task "Create a hello world Python script" --env local
    
    # Run with Docker
    python mini_swe_runner.py --task "List files in /tmp" --env docker --image python:3.11-slim
    
    # Batch mode from JSONL file
    python mini_swe_runner.py --prompts_file prompts.jsonl --output_file trajectories.jsonl --env docker
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import sys
import time
import uuid
import difflib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Callable

try:
    import fire
except ImportError:  # The benchmark harness imports the runner without the CLI extra.
    fire = None
from dotenv import load_dotenv
from swe_experiments.actions import (
    ACTION_SCHEMA,
    VERIFIER_SCHEMA,
    ActionParseError,
    parse_action_envelope,
    parse_json_object,
)
from swe_experiments.api import add_usage, estimate_cost_usd, redact_secret
from swe_experiments.context import ContextResult, build_context
from swe_experiments.config import BudgetConfig, ExperimentConfig, SamplingConfig
from swe_experiments.structured_output import (
    json_system_instructions,
    merge_extra_body,
    structured_output_extra_body,
)
from swe_experiments.verifier import CodeVerifier, VerifierReport
from track2_runtime import create_environment, make_tool_result_message

# Load environment variables
load_dotenv()


def _effective_temperature_for_model(
    model: str,
    base_url: Optional[str] = None,
) -> Optional[float]:
    """Use Qwen's precise-coding temperature while respecting Kimi's API."""
    normalized = f"{model} {base_url or ''}".lower()
    if "kimi" in normalized or "moonshot" in normalized:
        return None
    return 0.6




# ============================================================================
# Terminal Tool Definition
# ============================================================================

TERMINAL_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "terminal",
        "description": """Execute bash commands in a sandboxed environment.

**Environment:**
- Isolated execution environment (local or network-disabled Docker)
- Filesystem persists between tool calls within the same task
- Internet access is disabled for this benchmark

**Command Execution:**
- Provide the command to execute via the 'command' parameter
- Optional 'timeout' parameter in seconds (default: 60)

**Examples:**
- Run command: `{"command": "ls -la"}`
- With timeout: `{"command": "long_task.sh", "timeout": 300}`

**Best Practices:**
- Use non-interactive commands (avoid vim, nano, interactive python)
- Pipe to cat if output might be large
- Use only dependencies already present in the task image; do not install packages

**Completion:**
- When task is complete, output: echo "MINI_SWE_AGENT_FINAL_OUTPUT" followed by your result
""",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 60)"
                }
            },
            "required": ["command"]
        }
    }
}


def compact_code_text(text: str, max_lines: int = 24, max_chars: int = 1400) -> str:
    """Truncate a code/diff block for compact terminal display."""
    lines = text.rstrip().splitlines()
    if len(lines) > max_lines:
        body = "\n".join(lines[:max_lines]) + f"\n… (+{len(lines) - max_lines} more lines)"
    else:
        body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[:max_chars].rsplit("\n", 1)[0] + "\n… (output truncated)"
    return body


NETWORK_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:pip(?:3)?\s+install|python(?:3)?\s+-m\s+pip\s+install|"
    r"apt-get\s+(?:update|install)|(?:git\s+)?clone\s+|git\s+(?:fetch|pull)|"
    r"curl\s+|wget\s+|npm\s+install)(?:\s|$)",
    re.I,
)


# ============================================================================
# Mini-SWE Runner with Hermes Trajectory Format
# ============================================================================

class MiniSWERunner:
    """Repository-repair runner with controlled ablation seams."""
    
    def __init__(
        self,
        model: str = "",
        base_url: str = None,
        api_key: str = None,
        env_type: str = "local",
        image: str = "python:3.11-slim",
        cwd: str = "/tmp",
        max_iterations: int = 15,
        command_timeout: int = 60,
        api_timeout: int = 120,
        api_transport_retries: int = 0,
        verbose: bool = False,
        context_variant: str = "C0",
        json_mode: str = "J0",
        verifier_mode: str = "V0",
        max_json_retries: int = 1,
        max_targeted_tests: int = 3,
        reproduction_before: str = None,
        reproduction_after: str = None,
        controller_policy: str = "A0",
        max_model_turns: int | None = None,
        max_tool_calls: int = 30,
        max_wall_time_seconds: int = 900,
        max_completion_tokens: int = 8192,
        top_p: float = 0.95,
        top_k: int = 20,
        presence_penalty: float = 0.0,
        seed: int | None = 0,
        require_localhost: bool = False,
        edit_protocol: str = "diff",
        context_refresh_callback: Callable[[list[str], list[str]], ContextResult] | None = None,
    ):
        """
        Initialize the Mini-SWE Runner.
        
        Args:
            model: Model name for OpenAI-compatible API
            base_url: API base URL (optional, uses env vars if not provided)
            api_key: API key (optional, uses env vars if not provided)
            env_type: Environment type - "local", "docker", or "modal"
            image: Docker image (ignored for local)
            cwd: Working directory for commands
            max_iterations: Maximum tool-calling iterations
            command_timeout: Default timeout for commands
            verbose: Enable verbose logging
        """
        self.model = model
        self.max_iterations = max(1, int(max_model_turns or max_iterations))
        self.max_tool_calls = max(1, int(max_tool_calls))
        self.max_wall_time_seconds = max(1, int(max_wall_time_seconds))
        self.command_timeout = command_timeout
        self.api_timeout = max(10, api_timeout)
        self.api_transport_retries = max(0, api_transport_retries)
        self.require_localhost = bool(require_localhost)
        self.edit_protocol = str(edit_protocol or "diff").lower()
        if self.edit_protocol not in {"diff", "replace-v2"}:
            raise ValueError(f"unsupported edit protocol: {edit_protocol}")
        self.context_refresh_callback = context_refresh_callback
        self.verbose = verbose
        self.env_type = env_type
        self.image = image
        self.cwd = cwd
        self.context_variant = context_variant.upper()
        self.json_mode = json_mode.upper()
        self.verifier_mode = verifier_mode.upper()
        self.controller_policy = controller_policy.upper()
        if self.context_variant == "C5":
            # Historical C5 was the loop/inspection controller.  Keep it
            # readable while ensuring all new result rows use A1 explicitly.
            self.context_variant = "C0"
            self.controller_policy = "A1"
        self.sampling = SamplingConfig(
            max_completion_tokens=max(1, int(max_completion_tokens)),
            top_p=float(top_p),
            top_k=int(top_k),
            presence_penalty=float(presence_penalty),
            seed=seed,
        )
        if self.controller_policy not in {"A0", "A1"}:
            raise ValueError(f"unsupported controller policy: {controller_policy}")
        if self.json_mode not in {"J0", "J1", "J2", "J3", "J4", "J5"}:
            raise ValueError(f"unsupported JSON mode: {json_mode}")
        if self.verifier_mode == "V1R1":
            self.verifier_base_mode = "V1"
        else:
            self.verifier_base_mode = self.verifier_mode
        self.max_json_retries = max(0, max_json_retries)
        self.max_targeted_tests = max(0, max_targeted_tests)
        self.reproduction_before = reproduction_before
        self.reproduction_after = reproduction_after
        
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)
        
        # Track 2 uses one explicit OpenAI-compatible endpoint. Credentials
        # remain in environment variables and are never written to results.
        base_url = base_url or os.getenv("TRACK2_BASE_URL")
        api_key = api_key or os.getenv("TRACK2_API_KEY")
        model = model or os.getenv("TRACK2_MODEL", "")
        if not base_url:
            raise ValueError("Set TRACK2_BASE_URL or pass base_url")
        if self.require_localhost and not base_url.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("local cloud runs require a loopback TRACK2_BASE_URL")
        if not model:
            raise ValueError("Set TRACK2_MODEL or pass model")
        if not api_key and base_url.startswith(("http://127.0.0.1", "http://localhost")):
            api_key = "local-vllm"
        if not api_key:
            raise ValueError("Set TRACK2_API_KEY or pass api_key")
        self.model = model
        self._api_key_for_redaction = api_key or ""
        from openai import OpenAI
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=float(self.api_timeout),
            max_retries=0,
        )
        
        # Environment will be created per-task
        self.env = None
        
        # Tool definition
        self.tools = [TERMINAL_TOOL_DEFINITION]
        
        print("🤖 Mini-SWE Runner initialized")
        print(f"   Model: {self.model}")
        print(f"   Environment: {self.env_type}")
        if self.env_type != "local":
            print(f"   Image: {self.image}")
        print(f"   Max iterations: {self.max_iterations}")
        print(f"   Max tool calls: {self.max_tool_calls}")
        print(f"   Wall budget: {self.max_wall_time_seconds}s")
        print(f"   Context variant: {self.context_variant}")
        print(f"   Controller policy: {self.controller_policy}")
        print(f"   JSON mode: {self.json_mode}")
        print(f"   Verifier mode: {self.verifier_mode}")
        print(f"   Edit protocol: {self.edit_protocol}")

    def _sampling_kwargs(self) -> dict[str, Any]:
        """Return the frozen Qwen coding sampling profile."""
        normalized = f"{self.model} {getattr(self.client, 'base_url', '')}".lower()
        if "kimi" in normalized or "moonshot" in normalized:
            return {}
        return self.sampling.to_openai_kwargs()

    def _request_extra_body(self) -> dict[str, Any]:
        return merge_extra_body(
            self.json_mode,
            ACTION_SCHEMA,
            top_k=self.sampling.top_k,
        )

    def _fit_api_messages(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """Keep requests below the frozen 32K service window.

        Tool output is bounded before it enters the conversation, but a
        twelve-turn run can still approach the model limit when a repository
        map is present.  Drop only the oldest assistant/tool result pairs;
        preserve the system prompt and original issue.  Then lower the
        requested completion budget just enough to leave a safety margin.
        """
        fitted = list(messages)
        target_input_tokens = 24000
        while len(fitted) > 4 and len(json.dumps(fitted, ensure_ascii=False)) // 3 > target_input_tokens:
            del fitted[2:4]
            self._context_pruned_messages += 2
        estimated_input_tokens = max(1, len(json.dumps(fitted, ensure_ascii=False)) // 3)
        available = 32768 - estimated_input_tokens - 512
        request_max_tokens = min(self.sampling.max_completion_tokens, max(256, available))
        if request_max_tokens < self.sampling.max_completion_tokens:
            self._max_tokens_adjustments += 1
        return fitted, request_max_tokens

    def _record_api_response(self, response: Any, started: float) -> None:
        """Record provider-neutral usage and latency for the current task."""
        self._api_latencies_ms.append(round((time.perf_counter() - started) * 1000, 2))
        add_usage(self._api_usage, response)

    def _api_metadata(self) -> dict[str, Any]:
        return {
            "usage": dict(self._api_usage),
            "latencies_ms": list(self._api_latencies_ms),
            "total_latency_ms": round(sum(self._api_latencies_ms), 2),
            "transport_attempts": len(self._api_latencies_ms),
            "estimated_cost_usd": estimate_cost_usd(self._api_usage),
            "errors": list(self._api_errors),
            "sampling": self.sampling.to_openai_kwargs(),
        }
    
    def _create_env(self):
        """Create the execution environment."""
        print(f"🔧 Creating {self.env_type} environment...")
        environment_cwd = self.cwd
        environment_options: dict[str, Any] = {}
        # Benchmark workspaces live on the host so the evaluator can inspect
        # the resulting patch.  Bind-mount only that exact directory into the
        # sandbox; never expose the parent repository or API credentials.
        if self.env_type == "docker" and Path(self.cwd).is_dir():
            environment_cwd = "/workspace"
            environment_options.update(
                host_cwd=self.cwd,
                auto_mount_cwd=True,
                run_as_host_user=True,
                network=False,
                # Benchmark sandboxes must expose only the checked-out task
                # repository, not host skills, credentials, or media caches.
                mount_support_files=False,
            )
        self.env = create_environment(
            env_type=self.env_type,
            image=self.image,
            cwd=environment_cwd,
            timeout=self.command_timeout,
            **environment_options,
        )
        print("✅ Environment ready")
    
    def _cleanup_env(self):
        """Cleanup the execution environment."""
        if self.env is not None:
            if hasattr(self.env, 'cleanup'):
                self.env.cleanup()
            elif hasattr(self.env, 'stop'):
                self.env.stop()
            self.env = None
    
    def _execute_command(self, command: str, timeout: int = None) -> Dict[str, Any]:
        """
        Execute a command in the environment.
        
        Args:
            command: Bash command to execute
            timeout: Optional timeout override
            
        Returns:
            Dict with 'output' and 'returncode'
        """
        if self.env is None:
            self._create_env()
        
        try:
            result = self.env.execute(command, timeout=timeout or self.command_timeout)
            return {
                "output": result.get("output", ""),
                "exit_code": result.get("returncode", 0),
                "error": None
            }
        except Exception as e:
            return {
                "output": "",
                "exit_code": -1,
                "error": str(e)
            }

    def _context_command(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        """Command runner adapter used by context providers and verifiers."""
        return self._execute_command(command, timeout)

    def _execute_agent_command(self, command: str, timeout: int = None) -> Dict[str, Any]:
        """Execute a model command, optionally rejecting tight repetition loops."""
        # SWE-bench trajectories commonly use /testbed, while this hardened
        # runner mounts the repository at /workspace.  Normalize that learned
        # alias so a correct command is not wasted on a harness-only path
        # mismatch.  The replacement never broadens filesystem access.
        command, path_rewrites = re.subn(
            r"(?<![\w.-])/(?:testbed|home/user(?:/repo)?)(?=/|\s|$)",
            ".",
            command,
        )
        if path_rewrites:
            self._path_alias_rewrites = getattr(self, "_path_alias_rewrites", 0) + path_rewrites
        normalized = command.strip()
        if getattr(self, "_tool_call_count", 0) >= getattr(self, "max_tool_calls", 30):
            self._tool_budget_rejections = getattr(self, "_tool_budget_rejections", 0) + 1
            return {
                "output": "TOOL_BUDGET_EXHAUSTED: no more agent tool calls are available for this task.",
                "exit_code": 2,
                "error": "tool budget exhausted",
            }
        if getattr(self, "_inspection_gate_active", False):
            diff_state = self._execute_command("git diff --quiet -- .", 20)
            workspace_is_clean = diff_state.get("exit_code") == 0
            mutation_markers = re.compile(
                r"(?:\bapply_patch\b|\bgit\s+apply\b|\bsed\s+[^\n]*-[A-Za-z]*i\b|"
                r"\bperl\s+[^\n]*-[A-Za-z]*i\b|\btee\b|\.write_(?:text|bytes)\s*\(|"
                r"open\s*\([^\n]*[\"'](?:w|a|x)[+b]?[\"']|(?<![0-9])>{1,2}(?![/&]))"
            )
            if workspace_is_clean and not mutation_markers.search(normalized):
                self._inspection_gate_rejections = (
                    getattr(self, "_inspection_gate_rejections", 0) + 1
                )
                return {
                    "output": (
                        "INSPECTION_BUDGET_EXHAUSTED: the repository is still unchanged. "
                        "Your next command must implement the smallest source-code fix "
                        "(for example with apply_patch, sed -i, or a file write). After a "
                        "diff exists, focused tests and inspection commands are allowed again."
                    ),
                    "exit_code": 2,
                    "error": "read-only command blocked after inspection budget",
                }
        if (
            normalized.startswith(("find /", "rg /", "grep -R /", "grep -r /"))
            or "find / -" in normalized
        ):
            return {
                "output": (
                    "OUTSIDE_REPO_GUARD: search only from the current repository "
                    "directory; do not scan the filesystem root."
                ),
                "exit_code": 2,
                "error": "outside repository search blocked",
            }
        if NETWORK_COMMAND_RE.search(normalized):
            return {
                "output": (
                    "NETWORK_POLICY_GUARD: package installation, repository cloning, "
                    "and URL fetches are disabled. Use dependencies already present "
                    "in the task image and continue with the repair."
                ),
                "exit_code": 2,
                "error": "network command blocked",
            }
        absolute_paths = re.findall(r"(?:^|\s)(/(?:[^\s'\";,]+)?)", normalized)
        allowed_prefixes = ("/workspace", "/testbed", "/home/user", "/tmp", "/dev/null")
        outside_paths = [
            path for path in absolute_paths if not path.startswith(allowed_prefixes)
        ]
        if outside_paths:
            return {
                "output": (
                    "OUTSIDE_REPO_GUARD: absolute paths outside the repository are disabled. "
                    "Use the current working directory and relative paths."
                ),
                "exit_code": 2,
                "error": "outside repository path blocked",
            }
        if getattr(self, "_loop_guard_enabled", False):
            recent = getattr(self, "_recent_agent_commands", [])
            if len(recent) >= 2 and recent[-1] == command and recent[-2] == command:
                return {
                    "output": "LOOP_GUARD: identical command repeated twice; choose a different diagnostic or recovery action.",
                    "exit_code": 2,
                    "error": "repeated command",
                }
            recent.append(command)
            del recent[:-8]
            self._recent_agent_commands = recent
        self._tool_call_count = getattr(self, "_tool_call_count", 0) + 1
        return self._execute_command(command, timeout)

    def _build_context(self, task: str) -> ContextResult:
        """Build exactly one context variant for a controlled ablation."""
        return build_context(self.context_variant, self._context_command, task)

    def _refresh_context(
        self,
        focus_files: list[str],
        focus_identifiers: list[str],
    ) -> ContextResult | None:
        """Run the one permitted focused Repo Map refresh.

        The callback is supplied by the benchmark harness so the runner does
        not import Aider or perform a second model call.  A failed extraction
        is retained as unavailable evidence rather than silently falling back
        to a file listing.
        """
        if not self.context_refresh_callback or getattr(self, "_context_refresh_done", False):
            return None
        self._context_refresh_done = True
        root = Path(self.cwd).resolve()
        normalized_files: list[str] = []
        for raw_path in focus_files:
            candidate = Path(str(raw_path))
            if candidate.is_absolute():
                try:
                    candidate = candidate.resolve().relative_to(root)
                except ValueError:
                    continue
            normalized = candidate.as_posix().lstrip("./")
            if normalized and (root / normalized).is_file():
                normalized_files.append(normalized)
        self._context_refresh_focus_files = sorted(set(normalized_files))
        self._context_refresh_focus_identifiers = sorted(set(focus_identifiers))
        try:
            result = self.context_refresh_callback(
                self._context_refresh_focus_files,
                self._context_refresh_focus_identifiers,
            )
        except Exception as exc:
            self._context_refresh_result = ContextResult(
                "C1R1",
                "",
                "aider-repomap-focused",
                False,
                {"error": str(exc)[:2000]},
            )
            return self._context_refresh_result
        if not isinstance(result, ContextResult):
            raise TypeError("context refresh callback must return ContextResult")
        self._context_refresh_result = result
        return result

    @staticmethod
    def _command_focus(command: str) -> tuple[list[str], list[str]]:
        """Extract conservative file/symbol hints from a successful shell look."""
        files: list[str] = []
        for token in re.findall(r"(?:^|\s|--)['\"]?([^\s'\";|]+)['\"]?", command):
            candidate = token.strip(".,()")
            if (
                "/" in candidate
                or candidate.endswith((".py", ".js", ".ts", ".java", ".go", ".rs", ".md"))
            ) and not candidate.startswith(("-", "$", "/")):
                files.append(candidate)
        identifiers = [
            word
            for word in re.split(r"\W+", command)
            if len(word) >= 5 and not word.isdigit()
        ]
        return files[:32], identifiers[:64]

    def _build_system_prompt(self, context: ContextResult) -> str:
        """Build the compact system prompt shared by all experiment variants."""
        protocol = json_system_instructions(self.json_mode)
        inspection_limit = max(1, self.max_iterations // 2)
        action_checkpoint = (
            "The controller will report a budget checkpoint after turn 6 and a final convergence checkpoint after turn 8; "
            "do not repeat an identical command and reserve time to edit and verify."
            if self.controller_policy == "A1"
            else ""
        )
        context_block = context.text.strip()
        if len(context_block) > 16000:
            context_block = context_block[:16000] + "\n[context truncated]"
        context_instruction = (
            "No additional repository context was enabled."
            if not context_block
            else f"Repository context ({context.provider}, available={context.available}):\n{context_block}"
        )
        if self.json_mode == "J0":
            action_instruction = (
                "Use /no_think for tool-call turns so the action is emitted within the tool-call budget. "
                "When you need to run commands, use the terminal tool. "
                "This is an implementation task: do not stop at analysis. "
                f"Use at most {max(2, inspection_limit - 1)} inspection commands and edit by turn {inspection_limit}; "
                "do not spend the second half browsing. Edit the smallest correct fix, "
                "run a focused check, "
                "and then run: echo MINI_SWE_AGENT_FINAL_OUTPUT followed by a summary. "
                f"{action_checkpoint}"
            )
        else:
            edit_instruction = (
                "For any existing-file single-file change, MUST use action=replace with a repository-relative path, "
                "exact old_text, and new_text; old_text must match exactly once. Use action=edit with a unified "
                "diff only for file creation or genuinely complex multi-file changes. Never put host absolute "
                "paths in path or patch."
                if self.edit_protocol == "replace-v2"
                else "For edit, include a unified diff in patch."
            )
            action_example = (
                'A simple fix must look like {"action":"replace","path":"pkg/file.py",'
                '"query":null,"command":null,"patch":null,"old_text":"old code",'
                '"new_text":"new code","reason":"apply the fix"}.'
                if self.edit_protocol == "replace-v2"
                else 'An edit must look like {"action":"edit","path":null,"query":null,"command":null,'
                '"patch":"diff --git a/file.py b/file.py\\n...","old_text":null,"new_text":null,'
                '"reason":"apply the fix"}.'
            )
            action_instruction = (
                "Use /no_think for every action turn; the action envelope must be the complete response. "
                "For each turn, emit exactly one action JSON object. "
                "Always include all eight keys (use null for unused keys). "
                "For inspect/search/execute/recover, command is required and must run from the current repository; "
                f"{edit_instruction} This is an implementation task: use at most {max(2, inspection_limit - 1)} "
                f"inspect/search actions and edit by turn {inspection_limit}; then run a focused check and "
                "use finish only after verification. "
                'If you need a first look, use command "pwd && ls -la" rather than omitting the command. '
                f"{action_example} "
                f"{action_checkpoint}"
            )
        return (
            "You are an AI software-engineering agent working in a repository.\n"
                "The terminal's current working directory is the repository root. "
            "Only inspect or modify files under the current directory; never run "
            "find or rg from /, /root, /home, or other locations outside this repository.\n"
            "The repository is already checked out and hydrated. Never clone, fetch, pull, "
            "install packages, or access URLs; use the files and dependencies already present.\n"
            f"{protocol}\n"
            f"{action_instruction}\n"
            "When a symbol delegates to another method, search for every same-named "
            "implementation in subclasses or sibling modules before concluding. "
            "Be concise and do not invent files or test results.\n\n"
            f"{context_instruction}"
        )

    def _apply_patch(self, patch: str) -> Dict[str, Any]:
        """Apply a model-provided unified diff inside the task environment."""
        if not patch.strip():
            return {"output": "empty patch", "exit_code": 2, "error": "empty patch"}
        normalized = patch.strip().replace("\r\n", "\n")
        if normalized.startswith("```"):
            normalized_lines = normalized.splitlines()
            normalized_lines = normalized_lines[1:]
            if normalized_lines and normalized_lines[-1].strip() == "```":
                normalized_lines.pop()
            normalized = "\n".join(normalized_lines)
        # Small models sometimes hallucinate abbreviated blob hashes or emit
        # a stray "--git a/file" line before the real diff header.  Neither
        # carries edit semantics, so remove them deterministically while
        # preserving file paths and every hunk.
        normalized_lines = []
        for line in normalized.splitlines():
            if re.match(r"^index\s+\S+\.\.\S+(?:\s+\d+)?$", line):
                continue
            if line.startswith("--git a/"):
                continue
            normalized_lines.append(line)
        normalized = "\n".join(normalized_lines).strip() + "\n"
        # Passing a patch through stdin is not supported by every Hermes
        # environment, so use a temporary shell-safe heredoc.  The delimiter
        # is checked to avoid accidentally truncating a model-produced patch.
        delimiter = "__TRACK2_PATCH_EOF__"
        if delimiter in normalized:
            return {"output": "patch contains reserved delimiter", "exit_code": 2, "error": "unsafe patch"}
        # --recount is Git's built-in recovery for incorrect hunk line counts;
        # it does not relax path or context matching.
        command = (
            f"cat <<'{delimiter}' | git apply --recount --whitespace=nowarn -\n"
            f"{normalized}{delimiter}"
        )
        result = self._execute_command(command, self.command_timeout)
        if result.get("exit_code") == 0:
            self._print_code_change(self._patch_title(normalized), normalized)
            return result

        output = str(result.get("output") or "")
        if "corrupt patch" not in output and "unexpected line" not in output:
            return result

        # A common constrained-output failure is a syntactically valid hunk
        # header followed by newly generated code whose leading '+' markers
        # were omitted.  Prefix only otherwise-illegal lines *inside* hunks,
        # then submit the repaired candidate to git apply again.  Git still
        # enforces every path and context line, so this cannot bypass patch
        # validation.
        repaired_lines: list[str] = []
        in_hunk = False
        repairing_bare_additions = False
        for line in normalized.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                repairing_bare_additions = False
                repaired_lines.append(line)
                continue
            if line.startswith(("diff --git ", "--- ", "+++ ")):
                in_hunk = False
                repairing_bare_additions = False
                repaired_lines.append(line)
                continue
            if in_hunk and not line.startswith(("+", "-", " ", "\\")):
                repaired_lines.append("+" + line)
                repairing_bare_additions = True
            elif in_hunk and repairing_bare_additions and (line.startswith(" ") or line == ""):
                repaired_lines.append("+" + line)
            else:
                repaired_lines.append(line)
                if in_hunk and line.startswith(("+", "-", "\\")):
                    repairing_bare_additions = False
        repaired = "\n".join(repaired_lines).strip() + "\n"
        retry_command = (
            f"cat <<'{delimiter}' | git apply --recount --whitespace=nowarn -\n"
            f"{repaired}{delimiter}"
        )
        retry = self._execute_command(retry_command, self.command_timeout)
        if retry.get("exit_code") != 0:
            retry["output"] = (output + "\nREPAIRED_PATCH_ATTEMPT:\n" + str(retry.get("output") or ""))[-4000:]
        else:
            self._print_code_change(self._patch_title(repaired), repaired)
        return retry

    def _patch_title(self, patch: str) -> str:
        """Extract a short file path from a unified diff for terminal display."""
        match = re.search(r"^diff --git a/(?P<path>\S+)", patch, re.M)
        if match:
            return f"edit {match.group('path')}"
        match = re.search(r"^\+\+\+ b/(?P<path>\S+)", patch, re.M)
        if match:
            return f"edit {match.group('path')}"
        return "edit"

    def _action_summary(self, action) -> str:
        """Render one market-style action line for the terminal."""
        name = action.action
        target = str(action.path or action.command or action.query or "").rstrip()
        if name == "inspect":
            return f"🔍 inspect {target}".rstrip()
        if name == "search":
            return f"🔎 search {target}".rstrip()
        if name == "replace":
            return f"✏️ replace {target}".rstrip()
        if name == "edit":
            return f"📝 edit {target}".rstrip()
        if name == "execute":
            return f"🧪 execute {target}".rstrip()
        if name == "recover":
            return f"🛠 recover {target}".rstrip()
        return "🏁 finish"

    def _print_code_change(self, title: str, text: str) -> None:
        """Print the code the agent is writing directly to the terminal."""
        print(f"\n🧾 {title}")
        print(compact_code_text(text))
        print("✓ applied")

    def _apply_replace(self, path: str | None, old_text: str | None, new_text: str | None) -> Dict[str, Any]:
        """Apply one exact, deterministic replacement inside the repository."""
        if not path or not old_text:
            return {"output": "replace requires path and non-empty old_text", "exit_code": 2, "error": "invalid replace payload"}
        if Path(path).is_absolute():
            return {"output": "REPLACE_PATH_GUARD: path must be repository-relative", "exit_code": 2, "error": "absolute path rejected"}
        if new_text is None:
            return {"output": "replace requires new_text; use an empty string to delete", "exit_code": 2, "error": "invalid replace payload"}
        root = Path(self.cwd).resolve()
        candidate = (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return {"output": "REPLACE_PATH_GUARD: path must stay inside the repository", "exit_code": 2, "error": "outside repository path"}
        if not candidate.is_file():
            return {"output": f"REPLACE_FAILED: file does not exist: {path}", "exit_code": 2, "error": "file not found"}
        try:
            original = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {"output": f"REPLACE_FAILED: cannot read {path}: {exc}", "exit_code": 2, "error": "unreadable file"}
        matches = original.count(old_text)
        if matches != 1:
            occurrences: list[str] = []
            cursor = 0
            while len(occurrences) < 4:
                position = original.find(old_text, cursor)
                if position < 0:
                    break
                line_number = original.count("\n", 0, position) + 1
                start = max(0, position - 220)
                end = min(len(original), position + len(old_text) + 220)
                occurrences.append(
                    f"occurrence {len(occurrences) + 1} (line {line_number}):\n"
                    + original[start:end]
                )
                cursor = position + max(1, len(old_text))
            nearby = "\n\n".join(occurrences) or original[:600]
            return {
                "output": (
                    f"REPLACE_FAILED: old_text matched {matches} times in {path}. "
                    "Include a longer, function-specific old_text so it matches exactly once; "
                    "do not repeat the same replacement. Nearby content:\n"
                    + nearby
                )[-3600:],
                "exit_code": 2,
                "error": "old_text must match exactly once",
            }
        try:
            candidate.write_text(original.replace(old_text, new_text, 1), encoding="utf-8")
        except OSError as exc:
            return {"output": f"REPLACE_FAILED: cannot write {path}: {exc}", "exit_code": 2, "error": "write failed"}
        def _ensure_newline(text: str) -> str:
            return text if text.endswith("\n") else text + "\n"
        diff_text = "".join(
            difflib.unified_diff(
                _ensure_newline(old_text).splitlines(keepends=True),
                _ensure_newline(new_text).splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=2,
            )
        )
        self._print_code_change(f"replace {path}", diff_text)
        return {
            "output": f"REPLACE_APPLIED: {path} (exact match)",
            "exit_code": 0,
            "error": None,
            "edited_path": path,
        }

    def _repository_files(self, directory: Path, limit: int = 48) -> list[str]:
        """Return bounded repository-relative file candidates for recovery."""
        root = Path(self.cwd).resolve()
        try:
            directory = directory.resolve()
            directory.relative_to(root)
        except (OSError, ValueError):
            directory = root
        candidates: list[str] = []
        try:
            paths = sorted(directory.rglob("*"), key=lambda item: str(item))
        except OSError:
            paths = []
        for item in paths:
            if len(candidates) >= limit:
                break
            if not item.is_file() or ".git" in item.parts or item.name.startswith(".aider"):
                continue
            try:
                candidates.append(item.resolve().relative_to(root).as_posix())
            except (OSError, ValueError):
                continue
        return candidates

    def _inspect_path_recovery(self, path: str | None) -> Dict[str, Any] | None:
        """Give a structured action a useful listing instead of a directory error.

        Small models often emit ``path='.'`` or a path from a newer repository
        revision.  Returning bounded, repository-relative candidates lets the
        next action recover without spending several turns repeating ``sed``
        on a directory or nonexistent file.
        """
        if not hasattr(self, "_path_recovery_events"):
            self._path_recovery_events = []
        if not path or Path(path).is_absolute():
            return None
        root = Path(self.cwd).resolve()
        candidate = (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return {
                "output": "PATH_RECOVERY: inspect path must stay inside the repository; use a relative path.",
                "exit_code": 2,
                "error": "outside repository path",
                "finished": False,
            }
        if candidate.is_file():
            return None
        if candidate.is_dir():
            files = self._repository_files(candidate, limit=48)
            getattr(self, "_path_recovery_events", []).append(
                {"kind": "directory", "path": path, "candidates": len(files)}
            )
            listing = "\n".join(f"- {item}" for item in files) or "(directory has no readable files)"
            return {
                "output": (
                    f"INSPECT_DIRECTORY: {path} is a directory. Choose one repository-relative file "
                    f"from this bounded listing instead of repeating the directory path:\n{listing}"
                ),
                "exit_code": 0,
                "error": None,
                "finished": False,
            }

        # Prefer the nearest existing parent, then add basename variants (for
        # example ``_logistic.py`` -> ``logistic.py``) from the whole checkout.
        parent = candidate.parent
        while parent != root and not parent.is_dir():
            parent = parent.parent
        files = self._repository_files(parent if parent.is_dir() else root, limit=96)
        requested_name = candidate.name
        stripped_name = requested_name.lstrip("_")
        scored: list[tuple[int, str]] = []
        for item in files:
            name = Path(item).name
            score = 0
            if name == requested_name:
                score += 100
            if name == stripped_name:
                score += 80
            if name.rsplit(".", 1)[-1:] == requested_name.rsplit(".", 1)[-1:]:
                score += 5
            if str(parent.relative_to(root)) in item:
                score += 20
            if score:
                scored.append((score, item))
        alternatives = [item for _, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]))[:24]]
        if not alternatives:
            alternatives = files[:24]
        getattr(self, "_path_recovery_events", []).append(
            {"kind": "missing", "path": path, "candidates": len(alternatives)}
        )
        listing = "\n".join(f"- {item}" for item in alternatives) or "(no candidate files found)"
        return {
            "output": (
                f"PATH_NOT_FOUND: {path} does not exist in this checkout. "
                "Use one of these repository-relative candidates and do not repeat the failed path:\n"
                + listing
            ),
            "exit_code": 2,
            "error": "file not found",
            "finished": False,
        }

    def _dispatch_json_action(self, action) -> Dict[str, Any]:
        """Dispatch one validated JSON action and return model-visible evidence."""
        self._action_counts[action.action] = self._action_counts.get(action.action, 0) + 1
        if action.action == "finish":
            return {"output": action.reason or "agent requested finish", "exit_code": 0, "finished": True}
        if getattr(self, "_tool_call_count", 0) >= getattr(self, "max_tool_calls", 30):
            self._tool_budget_rejections = getattr(self, "_tool_budget_rejections", 0) + 1
            return {
                "output": "TOOL_BUDGET_EXHAUSTED: no more agent actions are available.",
                "exit_code": 2,
                "error": "tool budget exhausted",
                "finished": False,
            }
        self._tool_call_count = getattr(self, "_tool_call_count", 0) + 1
        if action.action == "inspect":
            recovered = self._inspect_path_recovery(action.path)
            if recovered is not None:
                return recovered
        if action.action == "replace":
            self._replace_attempts += 1
            if self.edit_protocol != "replace-v2":
                self._replace_errors.append("replace action requires edit_protocol=replace-v2")
                return {
                    "output": "REPLACE_PROTOCOL_DISABLED: use a unified diff edit action.",
                    "exit_code": 2,
                    "error": "replace protocol disabled",
                    "finished": False,
                }
            result = self._apply_replace(action.path, action.old_text, action.new_text)
            if result.get("exit_code") == 0:
                self._replace_successes += 1
            else:
                self._replace_errors.append(str(result.get("output") or result.get("error") or "")[-2000:])
            self._patch_apply_results.append(result.get("exit_code", -1) == 0)
            return {
                "output": result.get("output", ""),
                "exit_code": result.get("exit_code", -1),
                "error": result.get("error"),
                "finished": False,
            }
        if action.action == "edit":
            self._edit_attempts += 1
        if action.action == "edit" and action.patch:
            result = self._apply_patch(action.patch)
            getattr(self, "_patch_apply_results", []).append(result.get("exit_code", -1) == 0)
            if result.get("exit_code", -1) == 0:
                self._edit_successes += 1
            else:
                self._edit_errors.append(str(result.get("output") or result.get("error") or "")[-2000:])
                getattr(self, "_patch_apply_errors", []).append(
                    str(result.get("output") or result.get("error") or "")[-2000:]
                )
        else:
            command = action.command
            if not command and action.action == "inspect" and action.path:
                command = f"sed -n '1,240p' -- {shlex.quote(action.path)}"
            if not command and action.action == "search" and action.query:
                command = f"rg -n --hidden --glob '!.git' {shlex.quote(action.query)} . | head -120"
            # Some providers honor the JSON grammar but still omit the
            # semantically useful payload.  A safe deterministic first look
            # is preferable to spending an entire turn on a rejected action.
            if not command and action.action == "inspect":
                command = "pwd && ls -la"
            if not command and action.action == "search":
                command = "rg --files --hidden --glob '!.git' . | head -120"
            if not command:
                if action.action == "edit":
                    self._edit_errors.append("action did not provide an executable command")
                return {"output": "action did not provide an executable command", "exit_code": 2}
            result = self._execute_agent_command(command, self.command_timeout)
            if action.action == "edit":
                if result.get("exit_code") == 0:
                    self._edit_successes += 1
                else:
                    self._edit_errors.append(str(result.get("output") or result.get("error") or "")[-2000:])
        return {
            "output": result.get("output", ""),
            "exit_code": result.get("exit_code", -1),
            "error": result.get("error"),
            "finished": False,
        }

    def _verify_current_workspace(self) -> VerifierReport | None:
        """Run the selected deterministic verifier before cleaning the env."""
        if self.verifier_mode == "V0":
            return None
        verifier = CodeVerifier(
            self._context_command,
            mode=self.verifier_base_mode,
            max_targeted_tests=self.max_targeted_tests,
            command_timeout=max(self.command_timeout, 120),
        )
        return verifier.verify(
            reproduction_before=self.reproduction_before,
            reproduction_after=self.reproduction_after,
        )

    def _queue_verifier_repair(
        self,
        task: str,
        messages: list[dict[str, Any]],
    ) -> tuple[VerifierReport | None, bool]:
        """Run a checkpoint and queue one bounded repair instruction.

        The verifier remains deterministic and authoritative.  A repair is
        merely a chance for the same model to act on rejected evidence; it
        cannot turn a failed report into an accepted result by itself.
        """
        report = self._verify_current_workspace()
        if report is None:
            return None, False
        if report.passed:
            return report, False
        if self.verifier_mode != "V1R1" or self._repair_attempts >= 1:
            return report, False
        self._repair_attempts += 1
        messages.append(
            {
                "role": "user",
                "content": (
                    "VERIFIER_REJECTED: the deterministic verifier rejected the current candidate. "
                    "Use the evidence below to make one concrete repair, then run the smallest relevant "
                    "check. You have only the remaining model/tool budget; do not merely explain.\n"
                    + report.to_json()
                ),
            }
        )
        return report, True

    def _request_llm_verifier_review(
        self,
        task: str,
        report: VerifierReport,
    ) -> dict[str, Any] | None:
        """Ask the same model for a structured review of verifier evidence.

        This is advisory only: the deterministic report remains authoritative
        and a model cannot turn a failed check into an accepted patch.
        """
        review_messages = [
            {
                "role": "system",
                "content": (
                    "You are a code-patch verifier. Review only the supplied evidence. "
                    "Return exactly one JSON object with verdict, confidence, summary, and risks. "
                    "Do not claim tests passed unless the evidence says so."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"task": task, "deterministic_report": report.to_dict()},
                    ensure_ascii=False,
                ),
            },
        ]
        started = time.perf_counter()
        response_recorded = False
        try:
            kwargs = {
                "model": self.model,
                "messages": review_messages,
                "timeout": float(self.api_timeout),
                "extra_body": structured_output_extra_body("J3", VERIFIER_SCHEMA),
            }
            fixed_temperature = _effective_temperature_for_model(
                self.model,
                str(getattr(self.client, "base_url", "") or ""),
            )
            if fixed_temperature is not None:
                kwargs["temperature"] = fixed_temperature
            started = time.perf_counter()
            response = self.client.chat.completions.create(**kwargs)
            self._record_api_response(response, started)
            response_recorded = True
            content = response.choices[0].message.content or ""
            review = parse_json_object(content)
            verdict = review.get("verdict")
            confidence = review.get("confidence")
            summary = review.get("summary")
            if verdict not in {"accept", "reject", "needs_more_tests"}:
                raise ActionParseError("invalid verifier verdict")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ActionParseError("invalid verifier confidence")
            if not isinstance(summary, str):
                raise ActionParseError("invalid verifier summary")
            risks = review.get("risks", [])
            if not isinstance(risks, list) or not all(isinstance(item, str) for item in risks):
                raise ActionParseError("invalid verifier risks")
            return {
                "verdict": verdict,
                "confidence": float(confidence),
                "summary": summary,
                "risks": risks,
            }
        except Exception as exc:
            self._api_errors.append(redact_secret(exc, self._api_key_for_redaction))
            if not response_recorded:
                self._api_latencies_ms.append(round((time.perf_counter() - started) * 1000, 2))
            self.logger.warning("LLM verifier review unavailable: %s", exc)
            return {"verdict": "needs_more_tests", "confidence": 0.0, "summary": str(exc), "risks": []}
    
    def _format_tools_for_system_message(self) -> str:
        """Format tool definitions for the system message."""
        formatted_tools = []
        for tool in self.tools:
            func = tool["function"]
            formatted_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
                "required": None
            })
        return json.dumps(formatted_tools, ensure_ascii=False)
    
    def _convert_to_hermes_format(
        self,
        messages: List[Dict[str, Any]],
        user_query: str,
        completed: bool
    ) -> List[Dict[str, Any]]:
        """
        Convert internal message format to Hermes trajectory format.
        
        This produces the exact format used by batch_runner.py.
        """
        trajectory = []
        
        # System message with tool definitions
        system_msg = (
            "You are a function calling AI model. You are provided with function signatures within <tools> </tools> XML tags. "
            "You may call one or more functions to assist with the user query. If available tools are not relevant in assisting "
            "with user query, just respond in natural conversational language. Don't make assumptions about what values to plug "
            "into functions. After calling & executing the functions, you will be provided with function results within "
            "<tool_response> </tool_response> XML tags. Here are the available tools:\n"
            f"<tools>\n{self._format_tools_for_system_message()}\n</tools>\n"
            "For each function call return a JSON object, with the following pydantic model json schema for each:\n"
            "{'title': 'FunctionCall', 'type': 'object', 'properties': {'name': {'title': 'Name', 'type': 'string'}, "
            "'arguments': {'title': 'Arguments', 'type': 'object'}}, 'required': ['name', 'arguments']}\n"
            "Each function call should be enclosed within <tool_call> </tool_call> XML tags.\n"
            "Example:\n<tool_call>\n{'name': <function-name>,'arguments': <args-dict>}\n</tool_call>"
        )
        
        trajectory.append({"from": "system", "value": system_msg})
        trajectory.append({"from": "human", "value": user_query})
        
        # Process messages (skip first user message as we already added it)
        i = 1
        while i < len(messages):
            msg = messages[i]
            
            if msg["role"] == "assistant":
                if "tool_calls" in msg and msg["tool_calls"]:
                    # Assistant message with tool calls
                    content = ""
                    
                    # Add reasoning if present
                    if msg.get("reasoning"):
                        content = f"<think>{msg['reasoning']}</think>"
                    
                    if msg.get("content"):
                        content += msg["content"] + "\n"
                    
                    # Add tool calls in XML format
                    for tool_call in msg["tool_calls"]:
                        if not tool_call or not isinstance(tool_call, dict): continue
                        try:
                            arguments = json.loads(tool_call["function"]["arguments"]) \
                                if isinstance(tool_call["function"]["arguments"], str) \
                                else tool_call["function"]["arguments"]
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        tool_call_json = {
                            "name": tool_call["function"]["name"],
                            "arguments": arguments
                        }
                        content += f"<tool_call>\n{json.dumps(tool_call_json, ensure_ascii=False)}\n</tool_call>\n"
                    
                    trajectory.append({"from": "gpt", "value": content.rstrip()})
                    
                    # Collect subsequent tool responses
                    tool_responses = []
                    j = i + 1
                    while j < len(messages) and messages[j]["role"] == "tool":
                        tool_msg = messages[j]
                        tool_content = tool_msg["content"]
                        
                        # Try to parse as JSON
                        try:
                            if tool_content.strip().startswith(("{", "[")):
                                tool_content = json.loads(tool_content)
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        
                        tool_response = "<tool_response>\n"
                        tool_response += json.dumps({
                            "tool_call_id": tool_msg.get("tool_call_id", ""),
                            "name": msg["tool_calls"][len(tool_responses)]["function"]["name"] \
                                if len(tool_responses) < len(msg["tool_calls"]) else "unknown",
                            "content": tool_content
                        }, ensure_ascii=False)
                        tool_response += "\n</tool_response>"
                        tool_responses.append(tool_response)
                        j += 1
                    
                    if tool_responses:
                        trajectory.append({"from": "tool", "value": "\n".join(tool_responses)})
                        i = j - 1
                
                else:
                    # Regular assistant message (no tool calls)
                    content = ""
                    if msg.get("reasoning"):
                        content = f"<think>{msg['reasoning']}</think>"
                    content += msg.get("content") or ""
                    trajectory.append({"from": "gpt", "value": content})
            
            elif msg["role"] == "user":
                trajectory.append({"from": "human", "value": msg["content"]})
            
            i += 1
        
        return trajectory
    
    def run_task(self, task: str) -> Dict[str, Any]:
        """
        Run a single task and return the result with trajectory.
        
        Args:
            task: The task/prompt to execute
            
        Returns:
            Dict with trajectory, completion status, and metadata
        """
        print(f"\n{'='*60}")
        print(f"📝 Task: {task[:80]}{'...' if len(task) > 80 else ''}")
        print(f"{'='*60}")
        
        # Initialize environment
        self._create_env()

        # Per-task accounting is reset here rather than in __init__, because a
        # runner instance is reused for every task in a variant.
        self._api_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self._api_latencies_ms: list[float] = []
        self._api_errors: list[str] = []
        self._patch_apply_results: list[bool] = []
        self._patch_apply_errors: list[str] = []
        self._action_counts: dict[str, int] = {}
        self._edit_attempts = 0
        self._edit_successes = 0
        self._edit_errors: list[str] = []
        self._replace_attempts = 0
        self._replace_successes = 0
        self._replace_errors: list[str] = []
        self._path_recovery_events: list[dict[str, Any]] = []
        self._path_alias_rewrites = 0
        self._inspection_gate_active = False
        self._inspection_gate_rejections = 0
        self._tool_call_count = 0
        self._tool_budget_rejections = 0
        self._repair_attempts = 0
        self._repair_turns_used = 0
        self._wall_time_exhausted = False
        self._context_refresh_done = False
        self._context_refresh_result: ContextResult | None = None
        self._context_refresh_focus_files: list[str] = []
        self._context_refresh_focus_identifiers: list[str] = []
        self._context_pruned_messages = 0
        self._max_tokens_adjustments = 0
        task_started = time.perf_counter()

        # Build one and only one context variant for this run.  The provider
        # metadata is returned in the result so unavailable optional tools do
        # not masquerade as successful ablations.
        context_result = self._build_context(task)
        self._loop_guard_enabled = self.controller_policy == "A1"
        self._recent_agent_commands: list[str] = []
        
        # Message history
        # Qwen3's soft switch prevents its reasoning block from consuming the
        # small action/tool-call completion budget. Thinking remains covered
        # by the separate service acceptance probe.
        model_task = f"{task.rstrip()}\n/no_think"
        messages = [{"role": "user", "content": model_task}]
        
        # System prompt for the LLM (ephemeral - not saved to trajectory)
        system_prompt = self._build_system_prompt(context_result)
        active_context_result = context_result
        
        api_call_count = 0
        completed = False
        final_response = None
        json_parse_retries = 0
        total_json_parse_retries = 0
        json_responses = 0
        json_valid_responses = 0
        verification_report: VerifierReport | None = None
        final_patch = ""
        changed_files: list[str] = []
        
        try:
            while api_call_count < self.max_iterations:
                if time.perf_counter() - task_started >= self.max_wall_time_seconds:
                    self._wall_time_exhausted = True
                    print(f"⚠️  Reached wall-time budget ({self.max_wall_time_seconds}s)")
                    break
                call_number = api_call_count + 1
                print(f"\n🔄 API call #{call_number}/{self.max_iterations}")
                
                # Prepare API messages
                api_messages, fitted_max_tokens = self._fit_api_messages(
                    [{"role": "system", "content": system_prompt}] + messages
                )
                
                # Make API call
                api_kwargs = {
                    "model": self.model,
                    "messages": api_messages,
                    "timeout": float(self.api_timeout),
                }
                api_kwargs.update(self._sampling_kwargs())
                api_kwargs["max_tokens"] = fitted_max_tokens
                if self.json_mode == "J0":
                    api_kwargs["tools"] = self.tools
                    api_kwargs["extra_body"] = {"top_k": self.sampling.top_k}
                else:
                    # JSON modes use a control-plane action envelope.  Do
                    # not also send function tools, otherwise providers
                    # may choose a tool call and bypass the JSON protocol.
                    extra_body = self._request_extra_body()
                    if extra_body:
                        api_kwargs["extra_body"] = extra_body

                response = None
                for transport_attempt in range(self.api_transport_retries + 1):
                    request_started = time.perf_counter()
                    try:
                        response = self.client.chat.completions.create(**api_kwargs)
                        self._record_api_response(response, request_started)
                        break
                    except Exception as e:
                        safe_error = redact_secret(e, self._api_key_for_redaction)
                        self.logger.error("API call failed: %s", safe_error)
                        self._api_errors.append(safe_error)
                        self._api_latencies_ms.append(
                            round((time.perf_counter() - request_started) * 1000, 2)
                        )
                        if transport_attempt < self.api_transport_retries:
                            print(
                                "   ↻ transport retry "
                                f"{transport_attempt + 1}/{self.api_transport_retries}"
                            )
                if response is None:
                    break

                # Only a successfully returned model response consumes the
                # semantic call budget. Network timeouts and gateway errors
                # are recorded separately as transport attempts.
                api_call_count += 1
                # A1 leaves the first half of the trajectory unconstrained,
                # then blocks read-only commands only in the final convergence
                # phase. This keeps C0/C1/C2 context ablations independent.
                self._inspection_gate_active = (
                    self.controller_policy == "A1"
                    and api_call_count >= min(self.max_iterations, max(8, (self.max_iterations * 2 + 2) // 3))
                )
                
                assistant_message = response.choices[0].message
                
                # Log assistant response
                if self.json_mode == "J0" and assistant_message.content:
                    print(f"🤖 Assistant: {assistant_message.content[:100]}...")

                if self.json_mode != "J0":
                    # JSON action mode has no function-call messages.  Keep
                    # the raw response in the trajectory and make only the
                    # validated action visible to the dispatcher.
                    raw_content = assistant_message.content or ""
                    json_responses += 1
                    messages.append({"role": "assistant", "content": raw_content})
                    try:
                        action = parse_action_envelope(raw_content)
                    except ActionParseError as exc:
                        if self.json_mode == "J2" and json_parse_retries < self.max_json_retries:
                            json_parse_retries += 1
                            total_json_parse_retries += 1
                            retry_message = (
                                "Your previous response was not a valid action JSON object. "
                                f"Parser error: {exc}. Return only the required JSON envelope."
                            )
                            messages.append({"role": "user", "content": retry_message})
                            print(f"⚠️  JSON parse failed; retry {json_parse_retries}/{self.max_json_retries}")
                            continue
                        print(f"❌ JSON action rejected: {exc}")
                        messages.append({"role": "user", "content": f"ACTION_REJECTED: {exc}"})
                        final_response = raw_content
                        break

                    json_valid_responses += 1
                    json_parse_retries = 0
                    print(self._action_summary(action))
                    action_result = self._dispatch_json_action(action)
                    result_json = json.dumps(action_result, ensure_ascii=False)
                    messages.append({"role": "user", "content": f"ACTION_RESULT\n{result_json}"})
                    ok = action_result.get("exit_code") == 0
                    target = str(action.path or action.command or "").rstrip()
                    print(
                        f"   {'✓' if ok else '✗'} {action.action} {target} → exit "
                        f"{action_result.get('exit_code')}, "
                        f"{len(action_result.get('output', ''))} chars"
                    )
                    if (
                        action.action == "inspect"
                        and action_result.get("exit_code") == 0
                        and self.context_refresh_callback
                        and not self._context_refresh_done
                    ):
                        focus_files = [action.path] if action.path else []
                        command_files, command_identifiers = self._command_focus(action.command or "")
                        refreshed = self._refresh_context(focus_files + command_files, command_identifiers)
                        if refreshed is not None:
                            active_context_result = refreshed
                            system_prompt = self._build_system_prompt(refreshed)
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "CONTEXT_UPDATE: one focused repository map refresh is now available. "
                                        "Use it to choose the edit; do not request another map refresh."
                                    ),
                                }
                            )
                    if action_result.get("finished"):
                        checkpoint, should_repair = self._queue_verifier_repair(task, messages)
                        if checkpoint is not None:
                            verification_report = checkpoint
                        if should_repair:
                            completed = False
                            final_response = raw_content
                            continue
                        completed = True
                        final_response = raw_content
                        break
                    # Small coding models can spend every structured-action
                    # turn browsing.  Add one deterministic phase transition
                    # at the halfway point so the controller explicitly asks
                    # for an implementation and leaves time for verification.
                    halfway = max(1, self.max_iterations // 2)
                    if (
                        self.controller_policy == "A1"
                        and
                        api_call_count == halfway
                        and not any(self._patch_apply_results)
                        and action.action not in {"edit", "replace"}
                    ):
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "BUDGET_CHECKPOINT: six model turns have elapsed. Stop broad inspection now. "
                                    "Based on the evidence collected, implement the smallest correct fix with an edit "
                                    + (
                                        "or replace action, then run a focused test or syntax check; do not install "
                                        if self.edit_protocol == "replace-v2"
                                        else "action and unified diff, then run a focused test or syntax check; do not install "
                                    )
                                    + "packages or search outside cwd."
                                ),
                            }
                        )
                    continue
                
                # Check for tool calls
                if assistant_message.tool_calls:
                    print(f"🔧 Tool calls: {len(assistant_message.tool_calls)}")
                    
                    # Add assistant message with tool calls
                    messages.append({
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in assistant_message.tool_calls
                        ]
                    })
                    
                    # Execute each tool call
                    for tc in assistant_message.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {}
                        
                        command = args.get("command", "echo 'No command provided'")
                        timeout = args.get("timeout", self.command_timeout)
                        
                        print(f"   🔧 $ {command}")
                        
                        # Execute command
                        result = self._execute_agent_command(command, timeout)
                        if (
                            result.get("exit_code") == 0
                            and self.context_refresh_callback
                            and not self._context_refresh_done
                            and not re.search(r"\b(?:pytest|tox|nox|unittest|git\s+(?:apply|commit))\b", command, re.I)
                            and re.search(r"\b(?:pwd|ls|cat|sed|head|tail|less|rg|grep|git\s+(?:show|status|log))\b", command, re.I)
                        ):
                            focus_files, focus_identifiers = self._command_focus(command)
                            refreshed = self._refresh_context(focus_files, focus_identifiers)
                            if refreshed is not None:
                                active_context_result = refreshed
                                system_prompt = self._build_system_prompt(refreshed)
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "CONTEXT_UPDATE: one focused repository map refresh is now available. "
                                            "Use it to choose the edit; do not request another map refresh."
                                        ),
                                    }
                                )
                        
                        # Keep the rolling conversation bounded.  Large source
                        # dumps otherwise make each subsequent API request
                        # progressively slower (and can crowd the issue and
                        # repository context out of a small model's window).
                        raw_output = str(result.get("output") or "")
                        max_tool_output_chars = 3000
                        if len(raw_output) > max_tool_output_chars:
                            visible_output = (
                                raw_output[:3200]
                                + "\n...[tool output truncated by harness]...\n"
                                + raw_output[-700:]
                            )
                        else:
                            visible_output = raw_output

                        # Format result
                        result_json = json.dumps({
                            "content": {
                                "output": visible_output,
                                "exit_code": result["exit_code"],
                                "error": result["error"]
                            }
                        }, ensure_ascii=False)
                        
                        # Check for task completion signal
                        if "MINI_SWE_AGENT_FINAL_OUTPUT" in result["output"]:
                            print("   ✅ Task completion signal detected!")
                            completed = True
                        
                        # Add tool response
                        messages.append(make_tool_result_message(
                            tc.function.name, result_json, tc.id,
                        ))
                        
                        print(f"   ✅ exit_code={result['exit_code']}, output={len(result['output'])} chars")
                    
                    # If task completed, we can stop
                    if completed:
                        checkpoint, should_repair = self._queue_verifier_repair(task, messages)
                        if checkpoint is not None:
                            verification_report = checkpoint
                        if should_repair:
                            completed = False
                            final_response = assistant_message.content
                            continue
                        final_response = assistant_message.content
                        break

                    # Apply the same budget-aware phase transition used by
                    # structured actions.  Without this, small models often
                    # consume an entire short benchmark budget searching for
                    # hidden tests instead of implementing the supplied task.
                    halfway = max(1, self.max_iterations // 2)
                    if self.controller_policy == "A1" and api_call_count == halfway:
                        diff_state = self._execute_command("git diff --quiet -- .", 20)
                        if diff_state.get("exit_code") == 0:
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "BUDGET_CHECKPOINT: six model turns have elapsed. Stop inspection now. Check all same-named overrides "
                                        "and dispatch paths, then implement the smallest correct fix in the "
                                        "supplied source files. Run a focused syntax check. Hidden tests are "
                                        "intentionally unavailable; do not search for them."
                                    ),
                                }
                            )
                
                else:
                    # No tool calls - final response
                    final_response = assistant_message.content or ""
                    messages.append({
                        "role": "assistant",
                        "content": final_response
                    })
                    checkpoint, should_repair = self._queue_verifier_repair(task, messages)
                    if checkpoint is not None:
                        verification_report = checkpoint
                    if should_repair:
                        completed = False
                        continue
                    completed = True
                    print("🎉 Agent finished (no more tool calls)")
                    break
            
            if api_call_count >= self.max_iterations and not completed:
                print(f"⚠️  Reached max iterations ({self.max_iterations})")

        finally:
            if self.verifier_mode != "V0":
                try:
                    verification_report = self._verify_current_workspace()
                    if verification_report is not None:
                        print(
                            f"🔍 Verifier {verification_report.mode}: "
                            f"{verification_report.verdict}"
                        )
                        # For verifier variants, a deterministic accepted
                        # patch is the completion signal even if the model did
                        # not emit a separate finish action.
                        completed = verification_report.passed
                        if self.verifier_mode == "V5":
                            api_call_count += 1
                            verification_report.llm_review = self._request_llm_verifier_review(
                                task,
                                verification_report,
                            )
                except Exception as exc:
                    self.logger.exception("Verifier failed")
                    verification_report = VerifierReport(
                        "reject",
                        self.verifier_mode,
                        failure_summary=f"verifier exception: {exc}",
                    )
                    completed = False
            # Persist the actual candidate before the task environment is
            # destroyed.  External benchmark evaluators need the patch; an
            # agent's self-reported completion flag is not an objective score.
            try:
                patch_result = self._execute_command(
                    "git diff --binary --no-ext-diff -- . ':!.aider*'",
                    30,
                )
                if patch_result.get("exit_code") == 0:
                    final_patch = str(patch_result.get("output", ""))
                files_result = self._execute_command(
                    "git diff --name-only -- . ':!.aider*'",
                    30,
                )
                if files_result.get("exit_code") == 0:
                    changed_files = [
                        line.strip()
                        for line in str(files_result.get("output", "")).splitlines()
                        if line.strip()
                    ]
            except Exception as exc:
                self.logger.warning("Could not capture final patch: %s", exc)
            # Cleanup environment
            self._cleanup_env()
        
        # Convert to Hermes trajectory format
        trajectory = self._convert_to_hermes_format(messages, task, completed)
        
        return {
            "conversations": trajectory,
            "completed": completed,
            "api_calls": api_call_count,
            "metadata": {
                "model": self.model,
                "env_type": self.env_type,
                "require_localhost": self.require_localhost,
                "context_variant": self.context_variant,
                "context_provider": active_context_result.provider,
                "context_available": active_context_result.available,
                "context_metadata": context_result.metadata,
                "context_initial_provider": context_result.provider,
                "context_initial_available": context_result.available,
                "context_refresh_enabled": bool(self.context_refresh_callback),
                "context_refresh": (
                    {
                        "attempted": bool(self._context_refresh_done),
                        "available": bool(self._context_refresh_result and self._context_refresh_result.available),
                        "provider": self._context_refresh_result.provider if self._context_refresh_result else None,
                        "metadata": self._context_refresh_result.metadata if self._context_refresh_result else {},
                        "focus_files": list(self._context_refresh_focus_files),
                        "focus_identifiers": list(self._context_refresh_focus_identifiers),
                    }
                    if self.context_refresh_callback
                    else {"attempted": False, "available": False},
                ),
                "controller_policy": self.controller_policy,
                "json_mode": self.json_mode,
                "json_parse_retries": total_json_parse_retries,
                "json_responses": json_responses,
                "json_valid_responses": json_valid_responses,
                "patch_apply_results": list(self._patch_apply_results),
                "patch_apply_errors": list(self._patch_apply_errors),
                "action_counts": dict(self._action_counts),
                "edit_attempts": self._edit_attempts,
                "edit_successes": self._edit_successes,
                "edit_errors": list(self._edit_errors),
                "replace_attempts": self._replace_attempts,
                "replace_successes": self._replace_successes,
                "replace_errors": list(self._replace_errors),
                "path_recovery_events": list(self._path_recovery_events),
                "edit_protocol": self.edit_protocol,
                "final_patch": final_patch,
                "changed_files": changed_files,
                "path_alias_rewrites": self._path_alias_rewrites,
                "inspection_gate_rejections": self._inspection_gate_rejections,
                "tool_calls": self._tool_call_count,
                "tool_budget_rejections": self._tool_budget_rejections,
                "context_pruned_messages": self._context_pruned_messages,
                "max_tokens_adjustments": self._max_tokens_adjustments,
                "repair_attempts": self._repair_attempts,
                "wall_time_exhausted": bool(getattr(self, "_wall_time_exhausted", False)),
                "verifier_mode": self.verifier_mode,
                "verifier": verification_report.to_dict() if verification_report else None,
                "api": self._api_metadata(),
                "wall_time_ms": round((time.perf_counter() - task_started) * 1000, 2),
                "timestamp": datetime.now().isoformat()
            }
        }
    
    def run_batch(
        self,
        prompts: List[str],
        output_file: str
    ) -> List[Dict[str, Any]]:
        """
        Run multiple tasks and save trajectories to a JSONL file.
        
        Args:
            prompts: List of task prompts
            output_file: Output JSONL file path
            
        Returns:
            List of results
        """
        results = []
        
        print(f"\n📦 Running batch of {len(prompts)} tasks")
        print(f"📁 Output: {output_file}")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, prompt in enumerate(prompts, 1):
                print(f"\n{'='*60}")
                print(f"📋 Task {i}/{len(prompts)}")
                print(f"{'='*60}")
                
                try:
                    result = self.run_task(prompt)
                    results.append(result)
                    
                    # Write to file immediately
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    f.flush()
                    
                    print(f"✅ Task {i} completed (api_calls={result['api_calls']})")
                    
                except Exception as e:
                    self.logger.error(f"Error on task {i}: {e}")
                    error_result = {
                        "conversations": [],
                        "completed": False,
                        "api_calls": 0,
                        "error": str(e),
                        "metadata": {"timestamp": datetime.now().isoformat()}
                    }
                    results.append(error_result)
                    f.write(json.dumps(error_result, ensure_ascii=False) + "\n")
                    f.flush()
        
        print(f"\n✅ Batch complete! {len(results)} trajectories saved to {output_file}")
        return results


# ============================================================================
# CLI Interface
# ============================================================================

def main(
    task: str = None,
    prompts_file: str = None,
    output_file: str = "swe-runner-test1.jsonl",
    model: str = "",
    base_url: str = None,
    api_key: str = None,
    env: str = "local",
    image: str = "python:3.11-slim",
    cwd: str = "/tmp",
    max_iterations: int = 15,
    timeout: int = 60,
    api_timeout: int = 120,
    verbose: bool = False,
    context_variant: str = "C0",
    json_mode: str = "J0",
    verifier_mode: str = "V0",
    max_json_retries: int = 1,
    max_targeted_tests: int = 3,
    reproduction_before: str = None,
    reproduction_after: str = None,
    controller_policy: str = "A0",
    max_model_turns: int = None,
    max_tool_calls: int = 30,
    max_wall_time_seconds: int = 900,
    max_completion_tokens: int = 8192,
    top_p: float = 0.95,
    top_k: int = 20,
    presence_penalty: float = 0.0,
    seed: int = 0,
):
    """
    Run SWE tasks with Hermes trajectory format output.
    
    Args:
        task: Single task to run (use this OR prompts_file)
        prompts_file: JSONL file with prompts (each line: {"prompt": "..."})
        output_file: Output JSONL file for trajectories
        model: Model name (default: claude-sonnet-4-20250514)
        base_url: API base URL (optional)
        api_key: API key (optional, uses env vars)
        env: Environment type - "local", "docker", or "modal"
        image: Docker image (default: python:3.11-slim)
        cwd: Working directory (default: /tmp)
        max_iterations: Maximum tool-calling iterations (default: 15)
        timeout: Command timeout in seconds (default: 60)
        verbose: Enable verbose logging
        context_variant: One of C0-C5; only one context provider is enabled
        json_mode: One of J0-J5; J3/J4 require a structured-output vLLM server
        verifier_mode: One of V0-V5
        max_json_retries: Maximum parse retries per JSON action
        max_targeted_tests: Maximum inferred test files run by the verifier
        reproduction_before: Optional command that must fail before the fix
        reproduction_after: Optional command that must pass after the fix
        
    Examples:
        # Single task with local environment
        python mini_swe_runner.py --task "Create hello.py that prints Hello World"
        
        # Single task with Docker
        python mini_swe_runner.py --task "List files" --env docker
        
        # Batch from file
        python mini_swe_runner.py --prompts_file tasks.jsonl --output_file results.jsonl
    """
    print("🚀 Mini-SWE Runner with Hermes Trajectory Format")
    print("=" * 60)
    
    # Initialize runner
    runner = MiniSWERunner(
        model=model,
        base_url=base_url,
        api_key=api_key,
        env_type=env,
        image=image,
        cwd=cwd,
        max_iterations=max_iterations,
        command_timeout=timeout,
        api_timeout=api_timeout,
        verbose=verbose,
        context_variant=context_variant,
        json_mode=json_mode,
        verifier_mode=verifier_mode,
        max_json_retries=max_json_retries,
        max_targeted_tests=max_targeted_tests,
        reproduction_before=reproduction_before,
        reproduction_after=reproduction_after,
        controller_policy=controller_policy,
        max_model_turns=max_model_turns,
        max_tool_calls=max_tool_calls,
        max_wall_time_seconds=max_wall_time_seconds,
        max_completion_tokens=max_completion_tokens,
        top_p=top_p,
        top_k=top_k,
        presence_penalty=presence_penalty,
        seed=seed,
    )
    
    if task:
        # Single task mode
        result = runner.run_task(task)
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        
        print(f"\n📁 Trajectory saved to: {output_file}")
        print(f"✅ Completed: {result['completed']}")
        print(f"📞 API calls: {result['api_calls']}")
        print(f"💬 Turns: {len(result['conversations'])}")
        
    elif prompts_file:
        # Batch mode
        prompts = []
        with open(prompts_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        prompts.append(entry.get("prompt", entry.get("task", "")))
                    except json.JSONDecodeError:
                        prompts.append(line)
        
        if not prompts:
            print(f"❌ No prompts found in {prompts_file}")
            return
        
        runner.run_batch(prompts, output_file)
    
    else:
        print("❌ Please provide either --task or --prompts_file")
        print("   Example: python mini_swe_runner.py --task 'Create a hello world script'")


if __name__ == "__main__":
    if fire is None:
        raise SystemExit("The standalone CLI requires the optional 'fire' package")
    fire.Fire(main)
