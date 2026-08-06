"""
Warden CLI — command-line entry points.

Usage:
    warden check "Is this input malicious?"
    warden scan-diff --file changes.patch
    warden interactive --policy policies/default.yaml
    warden stats
    warden audit --last 24h
"""

from __future__ import annotations

import argparse
import sys
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from warden.config import WardenConfig, Decision
from warden.tiers.tier0_regex import Tier0RegexChecker
from warden.routing.router import ThrottleRouter

console = Console()
logger = logging.getLogger(__name__)


def create_router(config: WardenConfig) -> ThrottleRouter:
    """Create a router with available components."""
    tier0 = Tier0RegexChecker()

    # Tier 1 and Tier 2 are optional — router degrades gracefully
    tier1 = None
    tier2 = None

    try:
        from warden.tiers.tier1_classifier import Tier1Classifier
        tier1 = Tier1Classifier(config.model)
        tier1.load()
    except Exception as e:
        logger.info(f"Tier 1 not available: {e}")

    try:
        from warden.tiers.tier2_llm import Tier2LLM
        if config.model.llm_model_path:
            tier2 = Tier2LLM(config.model)
            tier2.load()
    except Exception as e:
        logger.info(f"Tier 2 not available: {e}")

    return ThrottleRouter(
        tier0=tier0,
        tier1=tier1,
        tier2=tier2,
        config=config.routing,
    )


def cmd_check(args):
    """Check a single input for injection/threats."""
    config = WardenConfig.from_env()
    router = create_router(config)

    result = router.route(args.text)

    # Display result
    color = {"allow": "green", "block": "red", "flag": "yellow"}.get(result.decision.value, "white")
    icon = {"allow": "✅", "block": "🚫", "flag": "⚠️"}.get(result.decision.value, "❓")

    console.print(Panel(
        f"{icon} Decision: [bold {color}]{result.decision.value.upper()}[/]\n"
        f"Confidence: {result.confidence:.2f}\n"
        f"Tier reached: {result.tier_reached}\n"
        f"Latency: {result.total_latency_ms:.1f}ms\n"
        f"Explanation: {result.explanation}",
        title="[bold]Warden Security Check[/]",
        border_style=color,
    ))


def cmd_stats(args):
    """Show routing statistics."""
    config = WardenConfig.from_env()
    router = create_router(config)
    stats = router.get_stats()

    table = Table(title="Routing Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    for key, value in stats.items():
        if key.endswith("_pct"):
            table.add_row(key, f"{value:.1f}%")
        else:
            table.add_row(key, str(value))

    console.print(table)


def cmd_ui(args):
    """Launch the Gradio dashboard."""
    config = WardenConfig.from_env()
    router = create_router(config)
    
    from warden.camel.interpreter import CaMeLInterpreter
    from warden.guards.diff_guard import DiffGuard
    from warden.guards.policy import PolicyEngine
    from warden.memory.audit_log import AuditLog
    from warden.orchestrator import WardenOrchestrator
    
    audit = AuditLog("warden_audit.db")
    audit.initialize()
    
    policy = PolicyEngine()
    diff_guard = DiffGuard()
    
    # We pass the router's tier2 model directly to camel if available
    camel = CaMeLInterpreter(llm=router.tier2, policy=policy)
    
    orchestrator = WardenOrchestrator(
        router=router,
        camel=camel,
        diff_guard=diff_guard,
        policy=policy,
        audit=audit
    )
    
    from ui.dashboard import build_dashboard
    app = build_dashboard(orchestrator)
    console.print("[bold green]Starting Warden Dashboard...[/]")
    app.launch(server_name="0.0.0.0", server_port=7860, share=True)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="warden",
        description="Warden - Adaptive security guard for AI coding agents",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # check command
    check_parser = subparsers.add_parser("check", help="Check input for threats")
    check_parser.add_argument("text", help="Text to check")
    check_parser.set_defaults(func=cmd_check)

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show routing statistics")
    # ui command
    ui_parser = subparsers.add_parser("ui", help="Launch the Gradio dashboard")
    ui_parser.set_defaults(func=cmd_ui)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
