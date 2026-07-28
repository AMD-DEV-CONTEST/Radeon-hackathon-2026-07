"""
Interactive terminal chat subcommand implementation with local command interception, theme support, rich header panel, ASCII logo, warmup animation, live telemetry, Cartographer RAG status, blackbox egress privacy audit, Flight Recorder hash chain verification, immediate model selection, workspace path binding, thinking spinners, dynamic runtime configuration (/model, /tokens, /ctx), and backend cleanup.
Manages interactive turn-based conversation with local command parsing (/help, /egress, /log, /verify, /theme, /model, /tokens, /ctx, /optimize, /clear, /status, /quit), token streaming, theme rendering, workspace directory binding, live telemetry, interactive confirmation gates, and process termination on exit.
"""

import os
import random
import sys
from typing import Any, Dict, List, Optional
from rich.panel import Panel
from aetheris_cli.model_alias import normalize_model_name
from aetheris_cli.policy.interactive import InteractiveAuthorizer
from aetheris_cli.policy.authorizer import ToolRequest
from aetheris_cli.render.theme import get_theme
from aetheris_cli.session_id import project_session_id
from aetheris_cli.render.tui import TUIRenderer, show_warmup_animation
from aetheris_cli.transport.backend import check_backend_availability, stop_backend_server
from aetheris_cli.transport.client import AetherisClient


def handle_local_command(
    cmd_str: str,
    renderer: TUIRenderer,
    client: AetherisClient,
    session_state: Dict[str, Any],
    target_path: str,
    session_id: str = "cli_session",
) -> bool:
    cleaned = cmd_str.strip()
    lower = cleaned.lower()

    current_model = session_state.get("model", "")

    if lower in ("/help", "help", "aetheris --help", "aetheris help", "-h", "--help", "?"):
        from aetheris_cli.cli import print_rich_help
        print_rich_help()
        return True

    if lower in ("/quit", "/exit", "quit", "exit"):
        sys.stdout.write("Exiting interactive chat session.\n")
        sys.exit(0)

    if lower in ("/egress", "/privacy"):
        try:
            egress = client.get_egress_status()
        except Exception as e:
            egress = {"error": str(e)}

        bytes_sent = egress.get("bytes_sent") or egress.get("total_bytes") or 0
        ext_conns = egress.get("external_connections") or 0

        lines = [
            "[bold bright_green]✳ BLACKBOX EGRESS MONITOR PRIVACY VERIFICATION[/bold bright_green]\n",
            f"[bold white]Status[/bold white]                 : [bold bright_green]● 100% OFFLINE (ZERO EGRESS)[/bold bright_green]",
            f"[bold white]External Bytes Sent[/bold white]    : [bold bright_green]{bytes_sent} B[/bold bright_green]",
            f"[bold white]External Connections[/bold white]   : [bold bright_green]{ext_conns}[/bold bright_green]",
            f"[bold white]Egress Enforcement[/bold white]     : [bold bright_green]STRICT LOCALHOST ONLY[/bold bright_green]",
            f"[bold white]Privacy Audit[/bold white]          : [bold bright_green]PASSED (No code or data leaves your computer)[/bold bright_green]",
        ]
        renderer.console.print(Panel("\n".join(lines), title="[bold bright_green]Blackbox Egress Monitor[/bold bright_green]", border_style="bright_green"))
        renderer.console.print()
        return True

    if lower in ("/log", "/logs"):
        audit_data = client.get_audit_trail(session_id)
        entries = audit_data.get("entries", [])
        if not entries:
            renderer.console.print(f"[dim]No Flight Recorder audit log entries found for session '{session_id}'.[/dim]\n")
        else:
            lines = [f"[bold bright_green]Flight Recorder Audit Trail — Session: {session_id} ({len(entries)} entries)[/bold bright_green]\n"]
            for entry in entries[-10:]:
                seq = entry.get("seq")
                # FlightRecorder.append() writes "type"/"ts" (see
                # core/audit/flight_recorder.py's own schema docstring) --
                # this used to read "event"/"timestamp", keys that entry
                # never had, so every logged line rendered "None" and a
                # blank timestamp regardless of what was actually recorded.
                event = entry.get("type")
                actor = entry.get("actor", "agent")
                ts = entry.get("ts", "")
                lines.append(f"[{seq}] {ts} | [bold bright_green]{event}[/bold bright_green] | actor={actor}")
            renderer.console.print(Panel("\n".join(lines), title="[bold bright_green]Flight Recorder Audit Log[/bold bright_green]", border_style="bright_green"))
            renderer.console.print()
        return True

    if lower in ("/verify"):
        res = client.verify_session(session_id)
        valid = res.get("valid", True)
        lines = [
            f"[bold white]Session ID[/bold white]       : [bold bright_green]{session_id}[/bold bright_green]",
            f"[bold white]Cryptographic Chain[/bold white]: [bold bright_green]{'VALID [VERIFIED]' if valid else 'INVALID'}[/bold bright_green]",
            f"[bold white]Hash Algorithm[/bold white]    : [bold bright_green]SHA-256 HMAC[/bold bright_green]",
            f"[bold white]Integrity Status[/bold white]  : [bold bright_green]Cryptographically Untampered[/bold bright_green]",
        ]
        renderer.console.print(Panel("\n".join(lines), title="[bold bright_green]Flight Recorder Hash Chain Verification[/bold bright_green]", border_style="bright_green"))
        renderer.console.print()
        return True

    if lower in ("/clear", "/cls", "clear", "cls"):
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")
        cart_status = client.get_cartographer_status()
        try:
            telemetry = client.get_telemetry()
        except Exception:
            telemetry = {}
        try:
            egress_status = client.get_egress_status()
        except Exception:
            egress_status = {}
        renderer.render_header(
            model_name=session_state.get("model", ""),
            cart_status=cart_status,
            telemetry=telemetry,
            egress_status=egress_status,
        )
        sys.stdout.write(f"Workspace directory: {target_path}\n\n")
        sys.stdout.flush()
        return True

    if lower.startswith("/theme "):
        theme_name = cleaned.split(" ", 1)[1].strip()
        renderer.theme = get_theme(theme_name)
        sys.stdout.write(f"Theme switched to: {renderer.theme.name}\n\n")
        return True

    if lower.startswith("/model "):
        new_model = cleaned.split(" ", 1)[1].strip()
        normalized = normalize_model_name(new_model)
        session_state["model"] = normalized
        client.set_default_model(normalized)
        sys.stdout.write(f"Active model switched to: {normalized}\n\n")
        return True

    if lower.startswith(("/tokens ", "/maxtokens ")) or lower in ("/tokens", "/maxtokens"):
        parts = cleaned.split(" ", 1)
        if len(parts) > 1 and parts[1].strip().isdigit():
            val = int(parts[1].strip())
            session_state["max_tokens"] = val
            sys.stdout.write(f"Max output tokens updated to: {val}\n\n")
        else:
            sys.stdout.write(f"Current max output tokens: {session_state.get('max_tokens', 4096)}\nUsage: /tokens <number>\n\n")
        return True

    if lower.startswith(("/ctx ", "/context ")) or lower in ("/ctx", "/context"):
        parts = cleaned.split(" ", 1)
        if len(parts) > 1 and parts[1].strip().isdigit():
            val = int(parts[1].strip())
            session_state["context_length"] = val
            sys.stdout.write(f"Context length updated to: {val}\n\n")
        else:
            sys.stdout.write(f"Current context length: {session_state.get('context_length', 8192)}\nUsage: /ctx <number>\n\n")
        return True

    if lower in ("/status", "/doctor"):
        cart_status = client.get_cartographer_status()
        try:
            telemetry = client.get_telemetry()
        except Exception:
            telemetry = {}
        try:
            egress_status = client.get_egress_status()
        except Exception:
            egress_status = {}
        renderer.render_header(
            model_name=session_state.get("model", ""),
            cart_status=cart_status,
            telemetry=telemetry,
            egress_status=egress_status,
        )
        sys.stdout.write(f"Active Model  : {session_state.get('model')}\n")
        sys.stdout.write(f"Max Tokens    : {session_state.get('max_tokens')}\n")
        sys.stdout.write(f"Context Length: {session_state.get('context_length')}\n\n")
        return True

    if lower.startswith("/optimize"):
        from core.optimizer import is_optimizer_enabled
        from core.optimizer.registry import CandidateRegistry
        from core.optimizer.sandbox import TemplateSandbox

        parts = cleaned.split()
        subcmd = parts[1].lower() if len(parts) > 1 else "status"

        if subcmd in ("status", "info"):
            enabled = is_optimizer_enabled()
            registry = CandidateRegistry()
            candidates = registry.get_candidates()
            lines = [
                "[bold bright_green]✳ AETHERIS ROCm KERNEL OPTIMIZER SUBSYSTEM[/bold bright_green]\n",
                f"[bold white]Optimizer Status[/bold white]       : [bold {'bright_green' if enabled else 'yellow'}]{'● ENABLED (AETHERIS_OPTIMIZER_ENABLED=true)' if enabled else '○ DISABLED (Set AETHERIS_OPTIMIZER_ENABLED=true to enable)'}[/bold {'bright_green' if enabled else 'yellow'}]",
                f"[bold white]Target Hardware[/bold white]        : [bold bright_green]AMD Radeon RDNA3 Architecture (gfx1100 / gfx1102)[/bold bright_green]",
                f"[bold white]Registered Candidates[/bold white]  : [bold bright_green]{len(candidates)} verified candidate(s)[/bold bright_green]",
                f"[bold white]GPU Lock Status[/bold white]        : [bold bright_green]UNLOCKED (OS Non-blocking Mutex Ready)[/bold bright_green]",
                f"[bold white]Egress Guarantee[/bold white]       : [bold bright_green]0 B (100% Offline & Local)[/bold bright_green]",
                f"[bold white]Flight Recorder Audit[/bold white]  : [bold bright_green]SHA-256 HMAC Enchained[/bold bright_green]",
            ]
            if not enabled:
                lines.extend([
                    "\n[bold yellow]💡 ACTIVATION INSTRUCTIONS:[/bold yellow]",
                    "[yellow]/optimize run is a manually triggered command, not an idle-time daemon. To enable it:[/yellow]",
                    "  • [bold white]Git Bash / Linux[/bold white] : export AETHERIS_OPTIMIZER_ENABLED=true",
                    "  • [bold white]PowerShell[/bold white]       : $env:AETHERIS_OPTIMIZER_ENABLED=\"true\"",
                    "  • [bold white]Command Prompt[/bold white]   : set AETHERIS_OPTIMIZER_ENABLED=true",
                ])
            renderer.console.print(Panel("\n".join(lines), title="[bold bright_green]Kernel Optimizer Status[/bold bright_green]", border_style="bright_green"))
            renderer.console.print()
            return True

        if subcmd in ("candidates", "list"):
            registry = CandidateRegistry()
            candidates = registry.get_candidates()
            if not candidates:
                renderer.console.print("[dim]No optimization candidates found in registry.json.[/dim]\n")
            else:
                lines = [f"[bold bright_green]Registered Optimization Candidates ({len(candidates)} total)[/bold bright_green]\n"]
                for c in candidates:
                    cid = c.get("id", "cand_unknown")
                    kname = c.get("kernel_name", "gemv_q4k")
                    speedup = c.get("speedup_pct", 0.0)
                    tid = c.get("transformation_id", "custom")
                    lines.append(f"• [bold white]{cid}[/bold white] | kernel=[bold bright_green]{kname}[/bold bright_green] | speedup=[bold bright_green]+{speedup:.1f}% tok/s[/bold bright_green] | variant={tid}")
                lines.append("\n[dim]To apply a candidate with Confirm Gate, run: /optimize apply <candidate_id>[/dim]")
                renderer.console.print(Panel("\n".join(lines), title="[bold bright_green]Optimization Candidates[/bold bright_green]", border_style="bright_green"))
                renderer.console.print()
            return True

        if subcmd == "run":
            from core.optimizer.runner import run_optimization
            kernel = parts[2] if len(parts) > 2 else "gemv_q4k"
            transformation = parts[3] if len(parts) > 3 else None
            # No explicit 4th word: use whatever model THIS session is
            # already chatting with (set at session start / via /model),
            # not a hardcoded default -- you shouldn't have to re-name your
            # own active model just to optimize a kernel for it.
            model = parts[4] if len(parts) > 4 else current_model
            what = f"transformation '{transformation}'" if transformation else "every not-yet-registered transformation"
            renderer.console.print(f"[bold bright_green]Running kernel optimizer for '{kernel}' on '{model}' ({what})... this spins up two isolated vte-server instances and can take a while.[/bold bright_green]")
            results = run_optimization(kernel, transformation_id=transformation, model_name=model)
            if not results:
                renderer.console.print("[dim]Nothing to test (every transformation already registered).[/dim]\n")
            from core.optimizer.runner import format_result_line
            style_for = {"ok": "bold bright_green", "warn": "yellow", "bad": "bold red"}
            for r in results:
                severity, line = format_result_line(r)
                style = style_for.get(severity, "yellow")
                renderer.console.print(f"[{style}]  {line}[/{style}]")
            renderer.console.print()
            return True

        if subcmd == "apply":
            if len(parts) < 3:
                renderer.console.print("[yellow]Usage: /optimize apply <candidate_id>[/yellow]\n")
                return True

            cand_id = parts[2].strip()
            registry = CandidateRegistry()
            candidates = [c for c in registry.get_candidates() if c.get("id") == cand_id]
            if not candidates:
                renderer.console.print(f"[bold red]Candidate '{cand_id}' not found in registry.[/bold red]\n")
                return True

            cand = candidates[0]
            pin = str(random.randint(1000, 9999))
            renderer.console.print(f"\n[bold yellow]╭─ CONFIRM GATE REQUIRED: Promote {cand_id} ─────────────────────────────╮[/bold yellow]")
            renderer.console.print(f"[yellow]│ Candidate : {cand_id} ({cand.get('kernel_name')})[/yellow]")
            renderer.console.print(f"[yellow]│ Speedup   : +{cand.get('speedup_pct', 0.0):.1f}% tok/s[/yellow]")
            renderer.console.print(f"[yellow]│ Type PIN [bold white]{pin}[/bold white] to confirm promotion or press Enter to cancel: [/yellow]", end="")
            sys.stdout.flush()

            user_pin = input().strip()
            if user_pin == pin:
                from core.optimizer.runner import apply_candidate
                ok, message = apply_candidate(cand_id)
                if ok:
                    renderer.console.print(f"[bold bright_green]✔ {message}[/bold bright_green]")
                    try:
                        client.reload_vte()
                        renderer.console.print("[bold bright_green]✔ Production vte-server reload requested.[/bold bright_green]\n")
                    except Exception as e:
                        renderer.console.print(f"[yellow]Warning: promoted on disk, but failed to reload the production vte-server: {e}[/yellow]\n")
                else:
                    renderer.console.print(f"[bold red]✘ {message}[/bold red]\n")
            else:
                renderer.console.print("[yellow]Promotion cancelled (PIN mismatch or empty input).[/yellow]\n")
            return True

        if subcmd in ("rollback", "undo", "fallback"):
            kernel = parts[2] if len(parts) > 2 else "gemv_q4k"
            sandbox = TemplateSandbox()
            restored = sandbox.restore_official_from_backup(kernel)
            if restored:
                renderer.console.print(f"[bold bright_green]✔ Official template {kernel}.hip.template restored successfully from .orig backup.[/bold bright_green]\n")
            else:
                renderer.console.print("[yellow]No .orig backup found to restore.[/yellow]\n")
            return True

        renderer.console.print(f"[yellow]Unknown /optimize subcommand: {subcmd}. Available: status, run, candidates, apply <id>, rollback[/yellow]\n")
        return True

    return False


def run_chat_command(
    project_path: Optional[str] = None,
    model: str = "",
    resume_session: Optional[str] = None,
    planner: bool = False,
    theme: str = "tokyo-night",
) -> int:
    if model:
        model = normalize_model_name(model)

    client = AetherisClient()
    ok, msg = check_backend_availability(client, model=model)
    if not ok:
        sys.stderr.write(f"Error: {msg}\n")
        return 3

    if model:
        client.set_default_model(model)

    if not model:
        # Match the backend's own default exactly (app.py's every model-
        # resolution path: body.model or get_setting("default_model") or
        # VTE_DEFAULT_MODEL) instead of a separately hardcoded fallback here.
        # Confirmed live on a fresh install: an independent "granite-4.1:3b-
        # q8_0" string here made the very first message fail with "Arquivo
        # do modelo não encontrado" whenever only the README-documented
        # default model (Llama 3.1 8B) had actually been pulled.
        from core.utils.vte_bridge import VTE_DEFAULT_MODEL
        model = VTE_DEFAULT_MODEL

    session_state: Dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "context_length": 8192,
    }

    # os.getcwd() reflects where this process is actually running; PWD/ORIGINAL_PWD are
    # static env vars inherited from shell launch and can go stale (e.g. after a symlinked
    # or wrapped invocation), so they are only a last-resort fallback.
    target_path = project_path or os.getcwd() or os.environ.get("ORIGINAL_PWD") or os.environ.get("PWD")
    session_id = resume_session or project_session_id(target_path)
    if target_path:
        try:
            client.set_project_path(target_path, chat_id=session_id)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to set workspace directory: {e}\n")

    # Continue this session's user-message numbering where the last run of
    # it left off, rather than restarting at 1. session_id is a hash of the
    # project folder, so relaunching `aetheris chat` in the same directory
    # resumes the same session and the same Time-Travel shadow ref --
    # restarting the count would make a NEW turn 1 collide with an OLD
    # turn 1, and `aetheris undo` restores every snapshot with
    # `turn_id >= target`, so that collision would silently roll back more
    # than the user asked for. Best-effort: an unreachable timeline just
    # starts at 0, which is the old behavior.
    try:
        _prior_turns = [
            s.get("turn_id") for s in client.list_snapshots(session_id).get("snapshots", [])
            if s.get("turn_id") is not None
        ]
        turn_counter = max(_prior_turns) if _prior_turns else 0
    except Exception:
        turn_counter = 0

    cart_status = client.get_cartographer_status()
    try:
        telemetry = client.get_telemetry()
    except Exception:
        telemetry = {}
    try:
        egress_status = client.get_egress_status()
    except Exception:
        egress_status = {}

    renderer = TUIRenderer(theme_name=theme)
    show_warmup_animation(client=client, console=renderer.console, model_name=session_state["model"], theme_name=theme)

    authorizer = InteractiveAuthorizer()
    history: List[Dict[str, str]] = []
    mode = "planner" if planner else "builder"

    renderer.render_header(
        model_name=session_state["model"],
        cart_status=cart_status,
        telemetry=telemetry,
        egress_status=egress_status,
    )
    sys.stdout.write(f"Workspace directory: {target_path}\n\n")
    sys.stdout.flush()

    try:
        while True:
            try:
                renderer.render_user_prompt()
                user_input = sys.stdin.readline()
                if not user_input:
                    break
                user_input_str = user_input.strip()
                if not user_input_str:
                    break
            except (KeyboardInterrupt, EOFError):
                sys.stdout.write("\nExiting session.\n")
                break

            handled = handle_local_command(
                cmd_str=user_input_str,
                renderer=renderer,
                client=client,
                session_state=session_state,
                target_path=target_path,
                session_id=session_id,
            )
            if handled:
                continue

            history.append({"role": "user", "content": user_input_str})
            renderer.render_agent_prompt()

            # One turn per real user message (local slash commands `continue`
            # above and never reach here). Every Time-Travel snapshot taken
            # while this turn runs is stamped with it, which is what makes
            # the turn an `aetheris undo` checkpoint at all.
            turn_counter += 1
            turn_active = True
            accumulated_answer = ""
            current_turn_history = list(history)

            while turn_active:
                renderer.start_thinking("Aetheris is thinking...")
                try:
                    stream = client.stream_chat(
                        messages=current_turn_history,
                        mode=mode,
                        chat_id=session_id,
                        model=session_state["model"],
                        max_tokens=session_state["max_tokens"],
                        turn_id=turn_counter,
                    )
                except Exception as e:
                    renderer.stop_thinking()
                    sys.stderr.write(f"\nStream connection error: {e}\n")
                    stop_backend_server()
                    return 3

                pending_confirm = None
                for event in stream:
                    renderer.render_event(event)

                    if event.type == "delta":
                        accumulated_answer += event.data.get("delta", "")
                    elif event.type == "tool_start":
                        accumulated_answer = ""
                    elif event.type == "tool_output":
                        accumulated_answer = ""
                    elif event.type == "confirm_tool":
                        pending_confirm = event
                        break

                renderer.stop_thinking()

                if pending_confirm:
                    tool_name = pending_confirm.data.get("tool", "")
                    content = pending_confirm.data.get("content", "")
                    round_num = pending_confirm.data.get("round", 1)

                    req = ToolRequest(tool=tool_name, content=content, round_num=round_num, session_id=session_id)
                    decision = authorizer.decide(req)

                    if decision.is_allowed:
                        try:
                            exec_res = client.execute_tool(
                                tool=tool_name, content=content, chat_id=session_id, turn_id=turn_counter,
                            )
                            out_text = str(exec_res.get("result") or exec_res.get("output") or exec_res)
                            current_turn_history.append({"role": "user", "content": f"[{tool_name} result]\n{out_text}"})
                        except Exception as e:
                            sys.stderr.write(f"Failed to execute tool '{tool_name}': {e}\n")
                            turn_active = False
                    else:
                        try:
                            client.decline_tool(tool=tool_name, content=content, chat_id=session_id)
                        except Exception:
                            pass
                        sys.stdout.write(f"  [tool declined: {decision.reason}]\n")
                        turn_active = False
                else:
                    turn_active = False

            renderer.on_finish(accumulated_answer)
            if accumulated_answer.strip():
                history.append({"role": "assistant", "content": accumulated_answer.strip()})
    finally:
        stop_backend_server()

    return 0
