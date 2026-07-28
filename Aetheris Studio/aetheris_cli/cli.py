"""
Main CLI entry point and subcommand dispatcher for Aetheris CLI.
Parses command-line arguments using argparse and routes control to individual subcommand implementations with structured Rich help formatting divided into clear sections in English.
"""

import argparse
import os
import sys
from typing import List, Optional

from aetheris_cli.commands.chat import run_chat_command
from aetheris_cli.commands.doctor import doctor_command
from aetheris_cli.commands.export import export_command
from aetheris_cli.commands.log import log_command
from aetheris_cli.commands.run import run_one_shot_command
from aetheris_cli.commands.skills import skills_command
from aetheris_cli.commands.undo import undo_command
from aetheris_cli.commands.verify import verify_session_command
from aetheris_cli.policy.spec import KNOWN_TOOLS
from aetheris_cli.session_id import project_session_id

# Tools inspect_session/verify_chain/search_workspace/list_dir/read_file/
# read_browser_page never write anything -- the rest of KNOWN_TOOLS
# (write_file, edit_file, bash, manage_todo, navigate_browser, undo)
# either mutate state or take an action, so --allow-read stays a strict
# subset of --allow-all.
_READ_ONLY_TOOLS = {
    "read_file", "list_dir", "search_workspace", "inspect_session",
    "verify_chain", "read_browser_page",
}


def print_rich_help() -> None:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console(force_terminal=True, color_system="truecolor")

        panel_header = Panel(
            "[bold bright_green]⚡ AETHERIS ROCm CLI — Local AI Coding Assistant[/bold bright_green]\n"
            "[bold white]AMD Radeon RX 7600 / W7900 (RDNA3) | 100% Offline | Zero Cloud Dependencies[/bold white]\n"
            "[dim green]Privacy-first local intelligence with Cartographer RAG, Flight Recorder, Time-Travel, and Kernel Optimizer.[/dim green]",
            border_style="bright_green",
        )
        console.print(panel_header)
        console.print()

        slash_table = Table(
            title="[bold bright_green]1. INTERACTIVE CHAT SLASH COMMANDS[/bold bright_green]",
            border_style="bright_green",
            header_style="bold bright_green",
        )
        slash_table.add_column("Command", style="bold bright_green")
        slash_table.add_column("Description", style="bold white")
        slash_table.add_column("Usage Example", style="dim green")

        slash_table.add_row("/optimize status", "Inspect GPU optimizer status and activation guide", "/optimize status")
        slash_table.add_row("/optimize run [kernel] [transformation] [model]", "Test transformations via two isolated vte-server instances (defaults to this session's active model)", "/optimize run gemv_q4k")
        slash_table.add_row("/optimize candidates", "List verified kernel optimization candidates with speedup %", "/optimize candidates")
        slash_table.add_row("/optimize apply <id>", "Promote candidate using Confirm Gate (4-digit PIN)", "/optimize apply cand_gemv_q4k_001")
        slash_table.add_row("/optimize rollback, /optimize fallback", "Restore official C++ template from .orig backup", "/optimize rollback")
        slash_table.add_row("/model <name>", "Switch active LLM model dynamically", "/model granite-4.1:3b-q8_0")
        slash_table.add_row("/tokens <number>, /maxtokens", "Set max output generation tokens", "/tokens 2048")
        slash_table.add_row("/ctx <number>, /context", "Set active context window length", "/ctx 8192")
        slash_table.add_row("/egress, /privacy", "Verify 0 B external network egress in real-time", "/egress")
        slash_table.add_row("/verify", "Validate SHA-256 HMAC cryptographic audit log chain", "/verify")
        slash_table.add_row("/log, /logs", "Display Flight Recorder audit trail for the session", "/log")
        slash_table.add_row("/theme <name>", "Switch visual terminal color theme (tokyo-night, dracula, etc.)", "/theme dracula")
        slash_table.add_row("/clear, /cls", "Clear terminal screen and re-render header panel", "/clear")
        slash_table.add_row("/status, /doctor", "Inspect AMD GPU hardware telemetry, VRAM, and Cartographer RAG", "/status")
        slash_table.add_row("/quit, /exit", "Exit interactive chat session", "/quit")

        console.print(slash_table)
        console.print()

        cli_table = Table(
            title="[bold bright_green]2. TERMINAL SUBCOMMANDS[/bold bright_green]",
            border_style="bright_green",
            header_style="bold bright_green",
        )
        cli_table.add_column("Subcommand", style="bold yellow")
        cli_table.add_column("Description", style="bold white")
        cli_table.add_column("Usage Example", style="dim green")

        cli_table.add_row("chat", "Start interactive TUI chat session with GPU warmup", "aetheris chat --theme tokyo-night")
        cli_table.add_row("run", "Execute non-interactive single-shot prompt", 'aetheris run "explain code"')
        cli_table.add_row("optimize", "Manage the GPU kernel optimizer", "aetheris optimize run --kernel gemv_q4k --model llama3.1:8b-instruct-q4_k_m")
        cli_table.add_row("doctor", "Inspect environment health, GPU VRAM, HIP runtime, and egress", "aetheris doctor")
        cli_table.add_row("skills", "Manage and inspect registered skill manifests", "aetheris skills list")
        cli_table.add_row("undo", "Time-Travel: Rollback workspace code to turn N", "aetheris undo --last 1")
        cli_table.add_row("verify", "Verify Flight Recorder log file hash chain integrity", "aetheris verify cli_session")
        cli_table.add_row("log", "Display Flight Recorder audit trail for a session", "aetheris log cli_session")
        cli_table.add_row("export", "Export signed audit bundle (.zip) for a session", "aetheris export cli_session")

        console.print(cli_table)
        console.print()

        panel_opt = Panel(
            "[bold bright_green]⚡ KERNEL OPTIMIZER ACTIVATION INSTRUCTIONS[/bold bright_green]\n\n"
            "[bold white]By default the optimizer is DISABLED to preserve GPU cycles -- it is a manually[/bold white]\n"
            "[bold white]triggered command, not an idle-time background daemon. To enable it:[/bold white]\n\n"
            "   [bold yellow]export AETHERIS_OPTIMIZER_ENABLED=true[/bold yellow]  (Git Bash / Linux / macOS)\n"
            "   [bold yellow]$env:AETHERIS_OPTIMIZER_ENABLED=\"true\"[/bold yellow] (PowerShell)\n\n"
            "[dim green]Then run 'aetheris optimize run' to test transformations against two isolated vte-server[/dim green]\n"
            "[dim green]instances and 'aetheris optimize apply <id>' to promote a validated candidate.[/dim green]",
            border_style="bright_green",
        )
        console.print(panel_opt)
        console.print()

        panel_privacy = Panel(
            "[bold bright_green]✳ BLACKBOX PRIVACY & SECURITY GUARANTEES[/bold bright_green]\n\n"
            "[bold white]1. 100% Local Execution (AMD HIP Engine):[/bold white]\n"
            "   [dim green]All models and tools run natively on your AMD Radeon GPU without cloud APIs.[/dim green]\n\n"
            "[bold white]2. Blackbox Egress Monitor (Zero Telemetry):[/bold white]\n"
            "   [dim green]Continuous socket monitoring guarantees 0 bytes sent to external networks.[/dim green]\n\n"
            "[bold white]3. Flight Recorder Cryptographic Hash-Chain:[/bold white]\n"
            "   [dim green]All tool calls and decisions are recorded in an immutable SHA-256 HMAC structure.[/dim green]",
            border_style="bright_green",
        )
        console.print(panel_privacy)
        console.print("\n[dim]Run 'aetheris <subcommand> --help' for specific subcommand details.[/dim]\n")
    except Exception:
        parser = build_parser()
        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aetheris",
        description="Aetheris CLI — Command line client for Aetheris Studio",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    chat_parser = subparsers.add_parser("chat", help="Start an interactive TUI chat session")
    chat_parser.add_argument("--model", "-m", default="", help="Override model name")
    chat_parser.add_argument("--project", "-p", default="", help="Target project workspace directory")
    chat_parser.add_argument("--resume", "-r", default="", help="Resume specific chat session ID")
    chat_parser.add_argument("--planner", action="store_true", help="Start in Planner mode instead of Builder mode")
    chat_parser.add_argument("--theme", "-t", default="tokyo-night", help="Set color theme")

    run_parser = subparsers.add_parser("run", help="Execute a single-shot prompt non-interactively")
    run_parser.add_argument("prompt", help="Prompt text to execute")
    run_parser.add_argument("--model", "-m", default="", help="Override model name")
    run_parser.add_argument("--project", "-p", default="", help="Target project workspace directory")
    run_parser.add_argument("--planner", action="store_true", help="Use Planner mode instead of Builder mode")
    run_parser.add_argument("--allow-all", action="store_true", help="Bypass all interactive safety confirmations")
    run_parser.add_argument("--allow-read", action="store_true", help="Auto-approve read-only tool calls")
    run_parser.add_argument("--allow-bash", action="store_true", help="Auto-approve non-destructive bash commands")
    run_parser.add_argument("--plan-only", action="store_true", help="Generate execution plan without running write tools")
    run_parser.add_argument("--egress-strict", action="store_true", help="Abort session if external network egress occurs")

    opt_parser = subparsers.add_parser("optimize", help="Manage the GPU kernel optimizer")
    opt_parser.add_argument("action", nargs="?", default="status", choices=["status", "candidates", "run", "apply", "rollback", "fallback"], help="Action to perform")
    opt_parser.add_argument("candidate_id", nargs="?", default="", help="Candidate ID for the apply action")
    opt_parser.add_argument("--kernel", default="gemv_q4k", help="Kernel name for the run action")
    opt_parser.add_argument("--transformation", default="", help="Test only this transformation ID for the run action (default: every not-yet-registered one)")
    opt_parser.add_argument("--model", default="", help="Model to load into both isolated instances for the run action (default: a small fixed reference model). Loads TWO copies of this model at once (official + candidate) -- pick a model your GPU has headroom for twice over.")
    opt_parser.add_argument("--min-speedup", type=float, default=3.0, help="Minimum measured speedup percent required to register a candidate for the run action")
    opt_parser.add_argument("--trials", type=int, default=3, help="Interleaved A/B trial count for the run action")

    subparsers.add_parser("doctor", help="Inspect backend system health, GPU hardware telemetry, VTE engine state, and egress status")

    skills_parser = subparsers.add_parser("skills", help="Manage and search skill manifests")
    skills_sub = skills_parser.add_subparsers(dest="skills_subcommand", help="Skills actions")
    skills_sub.add_parser("list", help="List all available skills")
    skills_search = skills_sub.add_parser("search", help="Search skills by keyword")
    skills_search.add_argument("query", help="Search query string")
    skills_show = skills_sub.add_parser("show", help="Show instructions for a specific skill")
    skills_show.add_argument("name", help="Skill name")
    skills_import = skills_sub.add_parser("import", help="Import skills from URL or file")
    skills_import.add_argument("source", help="Source URL or path")

    undo_parser = subparsers.add_parser("undo", help="Time-Travel: restore the project to before an earlier message")
    undo_parser.add_argument(
        "--session", "-s", default="",
        help="Session ID to roll back (default: this folder's own chat session, same derivation as `aetheris chat`)",
    )
    undo_parser.add_argument(
        "--last", "-n", type=int, default=1,
        help="How many turns back to restore to: 1 undoes the most recent editing turn (default), 2 undoes the last two, and so on",
    )
    undo_parser.add_argument("--project", "-p", default="", help="Project folder to roll back (default: current directory)")
    undo_parser.add_argument("--list", "-l", action="store_true", dest="list_only", help="List restorable checkpoints and exit, changing nothing")
    undo_parser.add_argument("--dry-run", action="store_true", help="Show the exact diff that would be applied, then exit without applying it")
    undo_parser.add_argument("--yes", "-y", action="store_true", help="Skip the interactive confirmation (for scripting)")

    verify_parser = subparsers.add_parser("verify", help="Verify Flight Recorder audit log hash chain")
    verify_parser.add_argument("session_id", help="Session ID or log file path to verify")

    log_parser = subparsers.add_parser("log", help="Display Flight Recorder audit trail")
    log_parser.add_argument("session_id", help="Session ID to view logs for")

    export_parser = subparsers.add_parser("export", help="Export audit bundle ZIP for a session")
    export_parser.add_argument("session_id", help="Session ID to export audit bundle for")

    return parser


def main(args: Optional[List[str]] = None) -> int:
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if not parsed_args.subcommand:
        print_rich_help()
        return 0

    if parsed_args.subcommand == "chat":
        return run_chat_command(
            project_path=parsed_args.project,
            model=parsed_args.model,
            resume_session=parsed_args.resume,
            planner=parsed_args.planner,
            theme=parsed_args.theme,
        )
    elif parsed_args.subcommand == "run":
        # run_one_shot_command's real signature takes project_dir/allow/
        # allow_bash(str)/plan_only -- none of project_path/planner/
        # allow_all/allow_read exist as its parameters, so this call has
        # been raising TypeError unconditionally (confirmed live: `aetheris
        # run` crashed on every invocation before this fix, never
        # exercised by the existing test suite since nothing there called
        # this code path with real argparse-parsed args).
        if parsed_args.allow_all:
            allow_tools = sorted(KNOWN_TOOLS)
        elif parsed_args.allow_read:
            allow_tools = sorted(_READ_ONLY_TOOLS)
        else:
            allow_tools = []
        return run_one_shot_command(
            prompt=parsed_args.prompt,
            project_dir=parsed_args.project,
            model=parsed_args.model,
            allow=",".join(allow_tools),
            allow_bash="true" if (parsed_args.allow_all or parsed_args.allow_bash) else "false",
            plan_only=parsed_args.planner or parsed_args.plan_only,
            egress_strict=parsed_args.egress_strict,
        )
    elif parsed_args.subcommand == "optimize":
        action = getattr(parsed_args, "action", "status")
        cand_id = getattr(parsed_args, "candidate_id", "")
        kernel = getattr(parsed_args, "kernel", "gemv_q4k")
        from core.optimizer import is_optimizer_enabled
        from core.optimizer.registry import CandidateRegistry
        from core.optimizer.sandbox import TemplateSandbox

        if action in ("status", "info"):
            enabled = is_optimizer_enabled()
            sys.stdout.write(f"Optimizer Enabled: {enabled} (AETHERIS_OPTIMIZER_ENABLED={enabled})\n")
            sys.stdout.write(f"Registered Candidates: {len(CandidateRegistry().get_candidates())}\n")
        elif action in ("candidates", "list"):
            cands = CandidateRegistry().get_candidates()
            for c in cands:
                sys.stdout.write(
                    f"{c.get('id')} | kernel={c.get('kernel_name')} | transformation={c.get('transformation_id')} "
                    f"| speedup=+{c.get('speedup_pct', 0.0):.1f}%\n"
                )
        elif action == "run":
            from core.optimizer.isolated_runner import REFERENCE_MODEL
            from core.optimizer.runner import run_optimization
            transformation = getattr(parsed_args, "transformation", "") or None
            model = getattr(parsed_args, "model", "") or REFERENCE_MODEL
            what = f"transformation '{transformation}'" if transformation else "every not-yet-registered transformation"
            sys.stdout.write(f"Running kernel optimizer for '{kernel}' on '{model}' ({what})...\n")
            results = run_optimization(
                kernel, transformation_id=transformation, model_name=model,
                min_speedup_pct=parsed_args.min_speedup, trials=parsed_args.trials,
            )
            if not results:
                sys.stdout.write("Nothing to test (every transformation already registered).\n")
            from core.optimizer.runner import format_result_line
            for r in results:
                _severity, line = format_result_line(r)
                sys.stdout.write(f"  {line}\n")
        elif action == "apply":
            if not cand_id:
                sys.stdout.write("Usage: aetheris optimize apply <candidate_id>\n")
                return 2
            from core.optimizer.runner import apply_candidate
            from aetheris_cli.transport.client import AetherisClient
            ok, message = apply_candidate(cand_id)
            sys.stdout.write(message + "\n")
            if not ok:
                return 1
            try:
                AetherisClient().reload_vte()
                sys.stdout.write("Production vte-server reload requested.\n")
            except Exception as e:
                sys.stdout.write(f"Warning: promoted on disk, but failed to reload the production vte-server: {e}\n")
        elif action in ("rollback", "undo", "fallback"):
            sandbox = TemplateSandbox()
            sandbox.restore_official_from_backup(kernel)
            sys.stdout.write(f"Restored {kernel}.hip.template from .orig backup.\n")
        return 0
    elif parsed_args.subcommand == "doctor":
        return doctor_command()
    elif parsed_args.subcommand == "skills":
        # skills_command's real parameter is `action` (not `subcommand`)
        # and a single `query_or_ref` positional slot shared by search
        # ("query"), show ("name"), and import ("source") -- there is no
        # `skill_name` parameter at all. This call raised TypeError
        # unconditionally before this fix (same class of bug as `run` and
        # `undo` above).
        sub = getattr(parsed_args, "skills_subcommand", "") or "list"
        query_or_ref = {
            "search": getattr(parsed_args, "query", ""),
            "show": getattr(parsed_args, "name", ""),
            "import": getattr(parsed_args, "source", ""),
        }.get(sub, "")
        return skills_command(action=sub, query_or_ref=query_or_ref)
    elif parsed_args.subcommand == "undo":
        # undo_command's real parameter is `last`, not `last_n` -- this
        # call raised TypeError unconditionally before this fix, confirmed
        # live (same class of bug as the `run` subcommand above). Default
        # session_id matches chat.py's own derivation (a hash of the
        # resolved project path) instead of the unrelated literal
        # "cli_session" string, so `aetheris undo` with no --session
        # targets the same session `aetheris chat` used in this folder.
        # Same normalized derivation chat.py uses, so `aetheris undo` in a
        # folder targets the exact session `aetheris chat` created there
        # even if the two spelled the path differently.
        target_dir = parsed_args.project or os.getcwd()
        session_id = parsed_args.session or project_session_id(target_dir)
        return undo_command(
            session_id=session_id,
            last=parsed_args.last,
            dry_run=parsed_args.dry_run,
            list_only=parsed_args.list_only,
            assume_yes=parsed_args.yes,
            project_dir=parsed_args.project or None,
        )
    elif parsed_args.subcommand == "verify":
        return verify_session_command(session_id_or_path=parsed_args.session_id)
    elif parsed_args.subcommand == "log":
        return log_command(session_id=parsed_args.session_id)
    elif parsed_args.subcommand == "export":
        return export_command(session_id=parsed_args.session_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
