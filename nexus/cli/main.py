"""
NEXUS CLI - Command-line interface for the Causal Reality Agent Swarm
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from rich import print as rprint

from nexus.core.config import NexusConfig
from nexus.core.orchestrator import Orchestrator
from nexus.inference.engine import check_rocm_availability

app = typer.Typer(
    name="nexus",
    help="NEXUS - The Causal Reality Agent Swarm",
    add_completion=False,
)
console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def init(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Project path (defaults to current directory)",
    ),
):
    """Initialize NEXUS in a project directory"""
    project_path = path or Path.cwd()

    console.print(Panel.fit(
        "[bold cyan]NEXUS Initialization[/bold cyan]",
        subtitle=f"Project: {project_path}",
    ))

    # Create .nexus directory
    nexus_dir = project_path / ".nexus"
    nexus_dir.mkdir(exist_ok=True)

    # Create subdirectories
    (nexus_dir / "models").mkdir(exist_ok=True)
    (nexus_dir / "cache").mkdir(exist_ok=True)
    (nexus_dir / "logs").mkdir(exist_ok=True)

    # Create default config
    config_file = nexus_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text("""# NEXUS Configuration
inference:
  device: hip  # hip=ROCm, cuda=NVIDIA, cpu=fallback
  reasoning_quantization: int4
  code_quantization: fp16
  fast_quantization: int4

agents:
  max_agents: 8
  enable_temporal_analyst: true
  enable_code_archaeologist: true
  enable_fix_simulator: true
""")

    console.print("✅ NEXUS initialized successfully!")
    console.print(f"📁 Config directory: {nexus_dir}")
    console.print("\n[yellow]Next steps:[/yellow]")
    console.print("1. Run 'nexus check' to verify ROCm setup")
    console.print("2. Run 'nexus debug \"your problem\"' to start debugging")


@app.command()
def check(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Check system configuration and ROCm availability"""
    setup_logging(verbose)

    console.print(Panel.fit("[bold cyan]NEXUS System Check[/bold cyan]"))

    # Check ROCm
    with console.status("[cyan]Checking GPU availability..."):
        info = check_rocm_availability()

    # Display results
    table = Table(title="System Information", show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details")

    # Device
    if info["cuda_available"]:
        device_status = "✅ Available"
        device_details = f"{info['device_name']} ({info['device_count']} device(s))"
    else:
        device_status = "⚠️  Not Available"
        device_details = "Falling back to CPU"

    table.add_row("GPU Device", device_status, device_details)

    # ROCm
    if info["rocm_version"]:
        rocm_status = "✅ Installed"
        rocm_details = f"Version {info['rocm_version']}"
    else:
        rocm_status = "⚠️  Not Detected"
        rocm_details = "Install ROCm for GPU acceleration"

    table.add_row("ROCm", rocm_status, rocm_details)

    # Memory
    if info["memory_total_gb"] > 0:
        memory_status = "✅ Available"
        memory_details = (
            f"{info['memory_available_gb']:.1f}GB / "
            f"{info['memory_total_gb']:.1f}GB"
        )
        table.add_row("GPU Memory", memory_status, memory_details)

    console.print(table)

    # Recommendations
    if not info["cuda_available"]:
        console.print("\n[yellow]⚠️  Recommendations:[/yellow]")
        console.print("- Install ROCm 6.2+ for GPU acceleration")
        console.print("- NEXUS will run on CPU (slower)")


@app.command()
def debug(
    problem: str = typer.Argument(..., help="Problem description"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Debug a problem using the NEXUS agent swarm
    """
    setup_logging(verbose)

    console.print(Panel.fit(
        f"[bold cyan]NEXUS Debug Session[/bold cyan]\n\n{problem}",
    ))

    async def run_debug():
        # Initialize orchestrator
        config = NexusConfig()
        orchestrator = Orchestrator(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Initialize
            init_task = progress.add_task("[cyan]Initializing NEXUS...", total=None)
            await orchestrator.initialize()
            progress.update(init_task, completed=True)
            progress.remove_task(init_task)

            # Run debug workflow
            debug_task = progress.add_task("[cyan]Running agent swarm...", total=None)
            result = await orchestrator.debug_problem(problem)
            progress.update(debug_task, completed=True)
            progress.remove_task(debug_task)

        # Display results
        console.print("\n" + "=" * 70)
        console.print("\n[bold green]NEXUS Analysis Complete[/bold green]\n")

        # Temporal analysis
        if result.get("temporal_analysis"):
            ta = result["temporal_analysis"]
            console.print("[bold]🕐 Temporal Analysis:[/bold]")
            console.print(f"  Root causes found: {ta.get('root_causes_found', 0)}")
            console.print(f"  Causal path length: {ta.get('causal_path_length', 0)}")

            if ta.get("root_cause_nodes"):
                console.print("\n  [yellow]Root Causes:[/yellow]")
                for rc in ta["root_cause_nodes"][:2]:
                    console.print(f"  - {rc['type']}: {rc['data'].get('description', rc['id'])}")
            console.print()

        # Fix simulations
        if result.get("fix_simulations"):
            fs = result["fix_simulations"]
            sims = fs.get("simulations", [])

            console.print("[bold]🔧 Fix Simulations:[/bold]")
            for i, sim in enumerate(sims[:3], 1):
                console.print(
                    f"  {i}. {sim['fix_description'][:80]}"
                    f" (confidence: {sim['confidence_score']:.0%}, "
                    f"risk: {sim['risk_level']})"
                )
            console.print()

        # Recommendation
        if result.get("recommendation"):
            console.print(Panel(
                result["recommendation"],
                title="[bold]💡 Recommendation[/bold]",
                border_style="green",
            ))

        # Performance
        perf = result.get("performance", {})
        console.print(f"\n[dim]⚡ Total execution time: {perf.get('total_latency_ms', 0):.0f}ms[/dim]")

        # Shutdown
        await orchestrator.shutdown()

    # Run async
    asyncio.run(run_debug())


@app.command()
def status():
    """Show NEXUS status and statistics"""
    console.print(Panel.fit("[bold cyan]NEXUS Status[/bold cyan]"))

    nexus_dir = Path.cwd() / ".nexus"
    if not nexus_dir.exists():
        console.print("[yellow]NEXUS not initialized in this directory.[/yellow]")
        console.print("Run 'nexus init' to initialize.")
        return

    # Check if models are downloaded
    models_dir = nexus_dir / "models"
    model_count = len(list(models_dir.glob("*"))) if models_dir.exists() else 0

    console.print(f"📁 NEXUS directory: {nexus_dir}")
    console.print(f"🤖 Models cached: {model_count}")
    console.print(f"✅ Status: Ready")


@app.command()
def version():
    """Show NEXUS version"""
    from nexus import __version__
    console.print(f"NEXUS version {__version__}")
    console.print("Built for AMD Radeon GPUs with ROCm")


if __name__ == "__main__":
    app()
