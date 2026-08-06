#!/usr/bin/env python3
"""
CC Worker — P3-C1
Polls Orchestrator for tasks with capabilities:{agent:"claude"},
runs `claude -p "..."` CLI (OAuth subscription, NOT API key),
completes/fails via Orchestrator.

IMPORTANT: Uses Claude Code CLI (subscription OAuth), not Anthropic API.
No ANTHROPIC_API_KEY needed. Requires `claude` to be installed and logged in.

Usage:
    python worker/cc_worker.py --orchestrator http://111.228.42.18:8000
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import urllib.error
from typing import Any, Optional

logger = logging.getLogger("cc_worker")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://111.228.42.18:8000")
POLL_INTERVAL = 3.0
# claude -p timeout: 30 min max per task
CLAUDE_TIMEOUT = 1800


# ---------------------------------------------------------------------------
# Orchestrator REST helpers
# ---------------------------------------------------------------------------

def post_json(base_url: str, path: str, payload: dict) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def register(base_url: str) -> str:
    result = post_json(base_url, "/agents/register", {
        "name": "cc-reviewer",
        "agent_type": "claude_code",
        "host_id": "local-cc",
        "model_policy": "claude-subscription",
        "max_concurrency": 1,
        "network_capabilities": ["outbound-http"],
        "capabilities": {"agent": "claude", "claude": True, "coding": True},
    })
    return result["agent_id"]


def poll(base_url: str, agent_id: str) -> Optional[dict]:
    result = post_json(base_url, "/tasks/poll", {"agent_id": agent_id})
    return result.get("task")


def heartbeat(base_url: str, task_id: str, agent_id: str) -> None:
    try:
        post_json(base_url, f"/tasks/{task_id}/heartbeat", {"agent_id": agent_id})
    except Exception:
        pass


def extend_lease(base_url: str, task_id: str, agent_id: str, extend_seconds: int = 300) -> None:
    """Extend task lease to prevent scanner from killing long-running tasks (UAS-006)."""
    try:
        post_json(base_url, f"/tasks/{task_id}/extend-lease", {
            "agent_id": agent_id,
            "extend_seconds": extend_seconds,
        })
        logger.debug("Lease extended for task %s (+%ds)", task_id, extend_seconds)
    except Exception as exc:
        logger.warning("extend_lease failed for task %s: %s", task_id, exc)


def complete_task(base_url: str, task_id: str, agent_id: str, summary: str, artifacts: list[str]) -> None:
    post_json(base_url, f"/tasks/{task_id}/complete", {
        "agent_id": agent_id,
        "summary": summary,
        "artifact_uris": artifacts,
        "acceptance_result": "pass",
    })


def fail_task(base_url: str, task_id: str, agent_id: str, error_type: str, message: str) -> None:
    post_json(base_url, f"/tasks/{task_id}/fail", {
        "agent_id": agent_id,
        "error_type": error_type,
        "error_message": message,
    })


# ---------------------------------------------------------------------------
# Task execution — calls `claude -p` CLI (subscription, not API key)
# ---------------------------------------------------------------------------

def claude_command(extra_args: list[str]) -> list[str]:
    cli = shutil.which("claude") or shutil.which("claude.cmd")
    if cli:
        suffix = Path(cli).suffix.lower()
        if suffix == ".ps1":
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                cli,
                *extra_args,
            ]
        return [cli, *extra_args]

    npm_dir = Path.home() / "AppData" / "Roaming" / "npm"
    for candidate in (npm_dir / "claude.cmd", npm_dir / "claude.ps1"):
        if candidate.exists():
            if candidate.suffix.lower() == ".ps1":
                return [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(candidate),
                    *extra_args,
                ]
            return [str(candidate), *extra_args]

    raise FileNotFoundError("claude CLI not found in PATH")


def execute_task(base_url: str, task: dict[str, Any], agent_id: str) -> None:
    task_id = task["id"]
    payload = task.get("payload", {})
    instruction = (
        payload.get("instruction")
        or payload.get("description")
        or task.get("title", "")
    )

    # Inline file content if provided
    if payload.get("files"):
        file_ctx = "\n\n".join(
            f"=== {name} ===\n{content}"
            for name, content in payload["files"].items()
        )
        prompt = f"{file_ctx}\n\n---\n\n{instruction}"
    else:
        prompt = instruction

    # Background heartbeat + lease extension (UAS-006: prevent scanner from killing long tasks)
    _stop_hb = threading.Event()
    _HEARTBEAT_INTERVAL = 20
    _LEASE_EXTEND_INTERVAL = 120  # extend lease every 120s

    def _hb_loop() -> None:
        ticks = 0
        while not _stop_hb.wait(_HEARTBEAT_INTERVAL):
            heartbeat(base_url, task_id, agent_id)
            ticks += 1
            if ticks % (_LEASE_EXTEND_INTERVAL // _HEARTBEAT_INTERVAL) == 0:
                extend_lease(base_url, task_id, agent_id, extend_seconds=300)

    threading.Thread(target=_hb_loop, daemon=True).start()

    try:
        # Use Claude Code CLI with --output-format stream-json (subscription OAuth)
        result = subprocess.run(
            claude_command(["-p", prompt, "--output-format", "stream-json", "--verbose"]),
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )

        if result.returncode != 0:
            err = result.stderr.strip() or f"exit code {result.returncode}"
            fail_task(base_url, task_id, agent_id, "retryable", err)
            logger.error("Task %s claude CLI failed: %s", task_id, err)
            return

        # Extract final text from stream-json output
        summary = _extract_summary(result.stdout)
        artifacts = payload.get("output_artifacts", [])
        complete_task(base_url, task_id, agent_id, summary, artifacts)
        logger.info("Task %s completed", task_id)

    except subprocess.TimeoutExpired:
        fail_task(base_url, task_id, agent_id, "retryable", "claude CLI timed out")
        logger.error("Task %s timed out", task_id)
    except FileNotFoundError:
        fail_task(base_url, task_id, agent_id, "retryable", "claude CLI not found in PATH")
        logger.error("claude not in PATH — is Claude Code installed?")
    except Exception as e:
        fail_task(base_url, task_id, agent_id, "retryable", str(e))
        logger.error("Task %s unexpected error: %s", task_id, e)
    finally:
        _stop_hb.set()


def _extract_summary(stream_json_output: str) -> str:
    """Extract last assistant text from claude --output-format stream-json."""
    texts: list[str] = []
    for line in stream_json_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # stream_event with text delta
            if obj.get("type") == "stream_event":
                ev = obj.get("event", {})
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta", {})
                    if delta.get("type") == "text_delta":
                        texts.append(delta.get("text", ""))
            # result type (final summary)
            elif obj.get("type") == "result":
                if obj.get("result"):
                    return str(obj["result"])
        except (json.JSONDecodeError, AttributeError):
            continue

    return "".join(texts).strip() or "(no output)"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="CC Worker — Claude Code CLI worker (subscription, no API key)"
    )
    parser.add_argument("--orchestrator", default=ORCHESTRATOR_URL)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    base_url = args.orchestrator.rstrip("/")

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Verify claude CLI is available before registering
    try:
        ver = subprocess.run(
            claude_command(["--version"]), capture_output=True, text=True, timeout=10
        )
        logger.info("Claude Code CLI: %s", ver.stdout.strip() or "ok")
    except FileNotFoundError:
        logger.error("claude CLI not found — install Claude Code first: https://claude.ai/code")
        return 1

    agent_id = register(base_url)
    logger.info("Registered as agent %s (using claude CLI / subscription)", agent_id)

    while True:
        try:
            task = poll(base_url, agent_id)
            if task:
                logger.info("Got task %s: %s", task["id"], task["title"][:60])
                execute_task(base_url, task, agent_id)
            else:
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down")
            return 0
        except urllib.error.URLError as e:
            logger.error("Orchestrator unreachable: %s", e)
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            logger.error("Poll loop error: %s", e)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
