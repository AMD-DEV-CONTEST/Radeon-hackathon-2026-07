"""
Non-interactive subcommand implementation (aetheris run).
Executes a single-shot prompt non-interactively using automated policy enforcement and strict exit code semantics.
"""

import hashlib
import os
import sys
from typing import Optional
from aetheris_cli.metrics.collector import MetricsCollector
from aetheris_cli.policy.automated import AutomatedAuthorizer
from aetheris_cli.policy.authorizer import ToolRequest
from aetheris_cli.policy.spec import PolicySpec
from aetheris_cli.render.jsonl import JSONLRenderer
from aetheris_cli.render.plain import PlainRenderer
from aetheris_cli.transport.backend import check_backend_availability
from aetheris_cli.transport.client import AetherisClient


def run_one_shot_command(
    prompt: str,
    json_mode: bool = False,
    allow: str = "",
    allow_bash: str = "false",
    plan_only: bool = False,
    egress_strict: bool = False,
    timeout: int = 300,
    max_rounds: int = 30,
    project_dir: Optional[str] = None,
    model: str = "",
) -> int:
    if prompt == "-":
        prompt = sys.stdin.read().strip()

    if not prompt:
        sys.stderr.write("Error: Empty prompt provided.\n")
        return 2

    spec = PolicySpec.parse(
        allow_str=allow,
        allow_bash_val=allow_bash,
        plan_only=plan_only,
        egress_strict=egress_strict,
    )
    spec_errors = spec.validate()
    if spec_errors:
        for err in spec_errors:
            sys.stderr.write(f"Usage Error: {err}\n")
        return 2

    client = AetherisClient()
    ok, msg = check_backend_availability(client)
    if not ok:
        sys.stderr.write(f"Backend Error: {msg}\n")
        return 3

    # os.getcwd() reflects where this process is actually running; PWD/ORIGINAL_PWD are
    # static env vars inherited from shell launch and can go stale, so they are only a
    # last-resort fallback (see aetheris_cli/commands/chat.py for the same fix).
    target_dir = project_dir or os.getcwd() or os.environ.get("ORIGINAL_PWD") or os.environ.get("PWD")
    session_id = f"cli-run-{hashlib.sha256(target_dir.encode('utf-8')).hexdigest()[:12]}"
    if target_dir:
        try:
            client.set_project_path(target_dir, chat_id=session_id)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to set project path: {e}\n")

    renderer = JSONLRenderer() if json_mode else PlainRenderer()
    authorizer = AutomatedAuthorizer(spec)
    collector = MetricsCollector()
    collector.start_turn()
    history = [{"role": "user", "content": prompt}]
    mode = "planner" if plan_only else "builder"

    turn_active = True
    final_answer = ""
    exit_code = 0

    while turn_active:
        try:
            stream = client.stream_chat(
                messages=history,
                mode=mode,
                chat_id=session_id,
                model=model,
                timeout=timeout,
            )
        except Exception as e:
            sys.stderr.write(f"Connection Error: {e}\n")
            collector.end_turn(session_id=session_id, mode="run", exit_code=3)
            return 3

        pending_confirm = None
        for event in stream:
            renderer.render_event(event)

            if event.type == "delta":
                collector.record_token()
                final_answer += event.data.get("delta", "")
            elif event.type == "tool_start":
                final_answer = ""
            elif event.type == "tool_output":
                final_answer = ""
            elif event.type == "confirm_tool":
                pending_confirm = event
                break
            elif event.type == "error":
                exit_code = 1
                turn_active = False

        if egress_strict:
            try:
                egress_data = client.get_egress_status()
                total_egress_bytes = egress_data.get("total_bytes_sent", 0) + egress_data.get("external_connections", 0)
                if total_egress_bytes > 0:
                    sys.stderr.write("\nEgress Violation: External connection detected while --egress-strict is active.\n")
                    renderer.on_finish(final_answer, exit_code=9)
                    collector.end_turn(session_id=session_id, mode="run", exit_code=9)
                    return 9
            except Exception:
                pass

        if pending_confirm:
            tool_name = pending_confirm.data.get("tool", "")
            content = pending_confirm.data.get("content", "")
            round_num = pending_confirm.data.get("round", 1)

            req = ToolRequest(tool=tool_name, content=content, round_num=round_num, session_id=session_id)
            decision = authorizer.decide(req)
            collector.record_decision(is_automated=decision.is_automated, is_allowed=decision.is_allowed)

            if decision.is_allowed:
                try:
                    exec_res = client.execute_tool(tool=tool_name, content=content, chat_id=session_id)
                    out_text = str(exec_res.get("result") or exec_res.get("output") or exec_res)
                    history.append({"role": "user", "content": f"[{tool_name} result]\n{out_text}"})
                except Exception as e:
                    sys.stderr.write(f"Execution Error: Failed to execute tool '{tool_name}': {e}\n")
                    exit_code = 1
                    turn_active = False
            else:
                try:
                    client.decline_tool(tool=tool_name, content=content, chat_id=session_id)
                except Exception:
                    pass
                sys.stderr.write(f"\nAction Blocked by Gate Policy: {decision.reason}\n")
                exit_code = 4
                turn_active = False
        else:
            turn_active = False

    renderer.on_finish(final_answer, exit_code=exit_code)
    collector.end_turn(session_id=session_id, mode="run", exit_code=exit_code)
    return exit_code
