from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID
from urllib import error, request

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.fingerprint import collect_fingerprint
from worker.heartbeat import HeartbeatThread


DEFAULT_ORCHESTRATOR_URL = "http://127.0.0.1:8000"
DEFAULT_LOG_PATH = "worker.log"


def post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"POST {url} failed: {exc.reason}") from exc

    if not body:
        return {}
    return json.loads(body)


def register_worker(args: argparse.Namespace) -> int:
    fingerprint = collect_fingerprint(args.workspace_root)
    payload = {
        "name": args.name,
        "agent_type": args.agent_type,
        "host_id": args.host_id,
        "os": fingerprint["os"],
        "shell": fingerprint["shell"],
        "python_version": fingerprint["python_version"],
        "available_commands": fingerprint["available_commands"],
        "workspace_root": fingerprint["workspace_root"],
        "model_policy": args.model_policy,
        "max_concurrency": args.max_concurrency,
        "network_capabilities": ["outbound-http"],
        "capabilities": json.loads(args.capabilities),
    }
    response = post_json(args.orchestrator_url, "/agents/register", payload)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def setup_logger(log_path: str) -> logging.Logger:
    logger = logging.getLogger("unionagents.worker")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def register_and_get_agent_id(args: argparse.Namespace) -> UUID:
    fingerprint = collect_fingerprint(args.workspace_root)
    payload = {
        "name": args.name,
        "agent_type": args.agent_type,
        "host_id": args.host_id,
        "os": fingerprint["os"],
        "shell": fingerprint["shell"],
        "python_version": fingerprint["python_version"],
        "available_commands": fingerprint["available_commands"],
        "workspace_root": fingerprint["workspace_root"],
        "model_policy": args.model_policy,
        "max_concurrency": args.max_concurrency,
        "network_capabilities": ["outbound-http"],
        "capabilities": json.loads(args.capabilities),
    }
    response = post_json(args.orchestrator_url, "/agents/register", payload)
    return UUID(response["agent_id"])


def run_worker(args: argparse.Namespace) -> int:
    logger = setup_logger(args.log_path)
    agent_id = register_and_get_agent_id(args)
    semaphore = threading.BoundedSemaphore(args.max_concurrency)
    logger.info("worker registered agent_id=%s max_concurrency=%s", agent_id, args.max_concurrency)

    while True:
        semaphore.acquire()
        try:
            response = post_json(args.orchestrator_url, "/tasks/poll", {"agent_id": str(agent_id)})
            task = response.get("task")
            if not task:
                semaphore.release()
                time.sleep(args.poll_interval)
                continue

            thread = threading.Thread(
                target=execute_placeholder_task,
                kwargs={
                    "args": args,
                    "agent_id": agent_id,
                    "task": task,
                    "semaphore": semaphore,
                    "logger": logger,
                },
                daemon=True,
            )
            thread.start()
        except Exception as exc:  # noqa: BLE001 - keep polling unless explicitly stopped.
            semaphore.release()
            logger.error("worker poll loop failed: %s", exc)
            time.sleep(args.poll_interval)


def task_requires_provider_auth(task: dict[str, Any]) -> bool:
    caps = task.get("required_capabilities") or {}
    return bool(caps.get("provider_auth"))


def run_acceptance_check(acceptance_check: dict[str, Any]) -> str:
    """Execute the acceptance check defined in the task and return 'pass', 'fail', or 'needs_review'."""
    import subprocess as _sp

    check_type = (acceptance_check.get("type") or "").strip().lower()
    if check_type == "manual":
        return "needs_review"

    if check_type == "command":
        cmd = acceptance_check.get("command")
        if not cmd or not isinstance(cmd, list):
            return "fail"
        expected = acceptance_check.get("expected_exit_code", 0)
        timeout = acceptance_check.get("timeout_seconds", 120)
        try:
            result = _sp.run(
                cmd,
                cwd=acceptance_check.get("cwd") or None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return "pass" if result.returncode == expected else "fail"
        except Exception:
            return "fail"

    if check_type == "file_exists":
        paths = acceptance_check.get("paths", [])
        mode = acceptance_check.get("mode", "all")
        results = []
        import glob as _glob
        for pattern in paths:
            results.append(len(_glob.glob(pattern, recursive=True)) > 0)
        if mode == "any":
            return "pass" if any(results) else "fail"
        return "pass" if all(results) else "fail"

    return "fail"


def execute_placeholder_task(
    *,
    args: argparse.Namespace,
    agent_id: UUID,
    task: dict[str, Any],
    semaphore: threading.BoundedSemaphore,
    logger: logging.Logger,
) -> None:
    task_id = UUID(task["id"])
    heartbeat = HeartbeatThread(
        orchestrator_url=args.orchestrator_url,
        task_id=task_id,
        agent_id=agent_id,
        post_json=post_json,
        logger=logger,
    )
    heartbeat.start()
    try:
        logger.info("task leased task_id=%s title=%s", task_id, task.get("title"))

        task_type = task.get("task_type", "")
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        workspace = args.workspace_root or os.getcwd()

        if task_type == "coding" and task_requires_provider_auth(task) and not api_key:
            message = "Provider credentials are required for this coding task, but DEEPSEEK_API_KEY is not set."
            post_json(
                args.orchestrator_url,
                f"/tasks/{task_id}/fail",
                {
                    "agent_id": str(agent_id),
                    "error_type": "blocked_auth",
                    "error_message": message,
                },
            )
            logger.warning("task blocked_auth task_id=%s reason=missing_provider_credentials", task_id)
            return

        if task_type == "coding" and api_key:
            from worker.executor import CodingExecutor
            logger.info("task routing to CodingExecutor task_id=%s workspace=%s", task_id, workspace)
            executor = CodingExecutor(workspace=workspace, api_key=api_key)
            acceptance_result, summary = executor.execute(task)
        else:
            acceptance_check = task.get("acceptance_check") or {}
            acceptance_result = run_acceptance_check(acceptance_check)
            summary = f"Worker executed acceptance check: {acceptance_result}"

        post_json(
            args.orchestrator_url,
            f"/tasks/{task_id}/complete",
            {
                "agent_id": str(agent_id),
                "summary": summary,
                "artifact_uris": [],
                "acceptance_result": acceptance_result,
            },
        )
        logger.info("task completed task_id=%s acceptance_result=%s", task_id, acceptance_result)
    except Exception as exc:  # noqa: BLE001
        logger.error("task execution failed task_id=%s error=%s", task_id, exc)
    finally:
        heartbeat.stop()
        semaphore.release()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UnionAgents worker CLI.")
    parser.add_argument(
        "--orchestrator-url",
        default=os.environ.get("ORCHESTRATOR_URL", DEFAULT_ORCHESTRATOR_URL),
        help="Base URL for the Orchestrator API.",
    )
    parser.add_argument("--name", default=socket.gethostname(), help="Worker display name.")
    parser.add_argument("--host-id", default=socket.gethostname(), help="Stable host id.")
    parser.add_argument(
        "--agent-type",
        default=os.environ.get("AGENT_TYPE", "generic"),
        choices=["reasonix", "codewhile", "opencode", "generic", "claude_code", "codex"],
        help="Agent type to register.",
    )
    parser.add_argument(
        "--workspace-root",
        default=os.environ.get("WORKSPACE_ROOT", os.getcwd()),
        help="Workspace root visible to this worker.",
    )
    parser.add_argument("--model-policy", default=os.environ.get("MODEL_POLICY"))
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.environ.get("MAX_CONCURRENCY", "1")),
        help="Maximum tasks this worker process may execute concurrently.",
    )
    parser.add_argument(
        "--log-path",
        default=os.environ.get("WORKER_LOG_PATH", DEFAULT_LOG_PATH),
        help="Local worker log path.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("POLL_INTERVAL", "5")),
        help="Seconds to wait between empty polls or poll errors.",
    )
    parser.add_argument(
        "--capabilities",
        default=os.environ.get("WORKER_CAPABILITIES", "{}"),
        help='JSON capabilities advertised to the orchestrator, e.g. \'{"international":true,"cloudflare":true}\'',
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("register", help="Register this worker and print the agent id.")
    subparsers.add_parser("run", help="Register and poll tasks with heartbeat protection.")
    return parser


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "register":
        return register_worker(args)
    if args.command == "run":
        return run_worker(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
