"""
NEXUS Setup Script
Handles initial setup, model downloads, and ROCm verification
"""
import subprocess
import sys
from pathlib import Path

import torch
from rich.console import Console
from rich.prompt import Confirm
from rich.progress import Progress

console = Console()


def check_python_version():
    """Check Python version"""
    console.print("[cyan]Checking Python version...[/cyan]")
    if sys.version_info < (3, 11):
        console.print(f"[red]Error: Python 3.11+ required (you have {sys.version})[/red]")
        sys.exit(1)
    console.print(f"[green]✓ Python {sys.version.split()[0]}[/green]")


def check_rocm():
    """Check if ROCm is available"""
    console.print("\n[cyan]Checking ROCm/GPU availability...[/cyan]")

    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        console.print(f"[green]✓ GPU detected: {device_name}[/green]")

        if hasattr(torch.version, "hip"):
            console.print(f"[green]✓ ROCm version: {torch.version.hip}[/green]")
            return True
        else:
            console.print("[yellow]⚠ ROCm not detected (CUDA GPU found)[/yellow]")
            return False
    else:
        console.print("[yellow]⚠ No GPU detected - will run on CPU[/yellow]")
        console.print("\n[yellow]For optimal performance, install:[/yellow]")
        console.print("  - AMD Radeon GPU (RDNA2 or RDNA3)")
        console.print("  - ROCm 6.2+")
        console.print("  - PyTorch with ROCm support")
        return False


def install_dependencies():
    """Install Python dependencies"""
    console.print("\n[cyan]Installing dependencies...[/cyan]")

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            check=True,
            capture_output=True,
        )
        console.print("[green]✓ Dependencies installed[/green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]✗ Installation failed: {e}[/red]")
        return False


def create_directories():
    """Create necessary directories"""
    console.print("\n[cyan]Creating directories...[/cyan]")

    dirs = [
        Path(".nexus"),
        Path(".nexus/models"),
        Path(".nexus/cache"),
        Path(".nexus/logs"),
    ]

    for dir_path in dirs:
        dir_path.mkdir(parents=True, exist_ok=True)

    console.print("[green]✓ Directories created[/green]")


def setup_env_file():
    """Create .env file if it doesn't exist"""
    console.print("\n[cyan]Setting up environment...[/cyan]")

    env_file = Path(".env")
    if env_file.exists():
        console.print("[yellow]⚠ .env file already exists, skipping[/yellow]")
        return

    env_content = """# NEXUS Configuration

# Inference device (hip=ROCm, cuda=NVIDIA, cpu=fallback)
NEXUS_INFERENCE_DEVICE=hip

# Model quantization (int4, int8, fp16, fp32)
NEXUS_INFERENCE_REASONING_QUANTIZATION=int4
NEXUS_INFERENCE_CODE_QUANTIZATION=fp16
NEXUS_INFERENCE_FAST_QUANTIZATION=int4

# Performance
NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=8
NEXUS_INFERENCE_USE_FLASH_ATTENTION=true

# Logging
NEXUS_LOG_LEVEL=INFO
"""

    env_file.write_text(env_content)
    console.print("[green]✓ .env file created[/green]")


def main():
    """Main setup routine"""
    console.print("\n[bold cyan]NEXUS Setup[/bold cyan]")
    console.print("Causal Reality Agent Swarm for AMD Radeon GPUs\n")

    # Check Python
    check_python_version()

    # Check ROCm
    has_rocm = check_rocm()

    # Ask to continue
    if not has_rocm:
        if not Confirm.ask("\n[yellow]ROCm not detected. Continue with CPU?[/yellow]"):
            console.print("[red]Setup cancelled[/red]")
            return

    # Install dependencies
    if not install_dependencies():
        console.print("\n[red]Setup failed at dependency installation[/red]")
        return

    # Create directories
    create_directories()

    # Setup environment
    setup_env_file()

    # Done
    console.print("\n[bold green]✓ Setup complete![/bold green]\n")
    console.print("[cyan]Next steps:[/cyan]")
    console.print("1. Run 'python scripts/benchmark_rocm.py' to test performance")
    console.print("2. Run 'python examples/demo_time_travel_debug.py' for a demo")
    console.print("3. Use 'nexus debug \"your problem\"' to start debugging")

    console.print("\n[dim]Note: First run will download models (~20GB) - be patient![/dim]\n")


if __name__ == "__main__":
    main()
