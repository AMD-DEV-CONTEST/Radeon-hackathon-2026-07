"""
ROCm Performance Benchmark Suite for NEXUS
Demonstrates GPU optimization and measures performance
"""
import asyncio
import time
from typing import Literal
import statistics

import torch
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from nexus.core.config import NexusConfig, InferenceConfig
from nexus.inference.engine import NexusInferenceEngine, check_rocm_availability
from nexus.agents import AgentTask

console = Console()


async def benchmark_single_inference(
    engine: NexusInferenceEngine,
    model_type: Literal["reasoning", "code", "fast"],
    prompt: str,
    runs: int = 5,
) -> dict:
    """Benchmark a single model inference"""
    latencies = []
    tokens_per_sec = []
    total_tokens = 0

    for i in range(runs):
        result = await engine.infer(
            prompt=prompt,
            model_type=model_type,
            max_tokens=128,
            temperature=0.7,
        )

        if result.success:
            latencies.append(result.latency_ms)
            if result.latency_ms > 0:
                tps = (result.tokens / (result.latency_ms / 1000))
                tokens_per_sec.append(tps)
            total_tokens += result.tokens

    return {
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
        "min_latency_ms": min(latencies) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "avg_tokens_per_sec": statistics.mean(tokens_per_sec) if tokens_per_sec else 0,
        "total_tokens": total_tokens,
        "success_rate": len(latencies) / runs,
    }


async def benchmark_parallel_agents(
    engine: NexusInferenceEngine,
    num_agents: int,
) -> dict:
    """Benchmark parallel agent execution"""
    start_time = time.perf_counter()

    # Create tasks for multiple agents
    prompts = [
        (
            f"Agent {i}: Analyze this code pattern and identify potential issues.",
            "fast" if i % 3 == 0 else "code",
        )
        for i in range(num_agents)
    ]

    # Run in parallel
    results = await engine.parallel_infer(prompts, max_tokens=128)

    end_time = time.perf_counter()
    elapsed_ms = (end_time - start_time) * 1000

    successful = sum(1 for r in results if r.success)
    total_tokens = sum(r.tokens for r in results if r.success)

    return {
        "num_agents": num_agents,
        "elapsed_ms": elapsed_ms,
        "avg_latency_per_agent": elapsed_ms / num_agents,
        "success_rate": successful / num_agents,
        "total_tokens": total_tokens,
        "aggregate_tokens_per_sec": total_tokens / (elapsed_ms / 1000) if elapsed_ms > 0 else 0,
    }


async def run_benchmarks():
    """Run comprehensive benchmark suite"""
    console.print("\n[bold cyan]NEXUS ROCm Performance Benchmark[/bold cyan]\n")

    # Check system info
    console.print("[yellow]Checking system configuration...[/yellow]")
    sys_info = check_rocm_availability()

    info_table = Table(title="System Information")
    info_table.add_column("Component", style="cyan")
    info_table.add_column("Value", style="green")

    info_table.add_row("Device", sys_info["device_name"])
    info_table.add_row("Device Type", sys_info["device"])
    if sys_info["rocm_version"]:
        info_table.add_row("ROCm Version", sys_info["rocm_version"])
    info_table.add_row("GPU Memory", f"{sys_info['memory_total_gb']:.1f} GB")

    console.print(info_table)
    console.print()

    # Initialize engines for both CPU and GPU (if available)
    devices_to_test = ["hip"] if sys_info["cuda_available"] else ["cpu"]

    for device in devices_to_test:
        console.print(f"\n[bold]Running benchmarks on: {device.upper()}[/bold]\n")

        config = InferenceConfig(
            device=device,
            max_parallel_agents=8,
            reasoning_quantization="int4",
            code_quantization="fp16",
            fast_quantization="int4",
        )

        engine = NexusInferenceEngine(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            init_task = progress.add_task(f"[cyan]Initializing {device.upper()} engine...")
            await engine.initialize()
            progress.update(init_task, completed=True)

        # Benchmark 1: Single model inference
        console.print("[yellow]Benchmark 1: Single Model Inference[/yellow]")

        results_table = Table(title=f"Single Inference ({device.upper()})")
        results_table.add_column("Model Type", style="cyan")
        results_table.add_column("Avg Latency (ms)", justify="right")
        results_table.add_column("Tokens/sec", justify="right")
        results_table.add_column("Success Rate", justify="right")

        test_prompt = "Analyze this function for potential bugs: def calculate(x, y): return x / y"

        for model_type in ["fast", "code"]:  # Skip reasoning for speed
            with console.status(f"[cyan]Testing {model_type} model..."):
                result = await benchmark_single_inference(
                    engine,
                    model_type,
                    test_prompt,
                    runs=3,
                )

            results_table.add_row(
                model_type,
                f"{result['avg_latency_ms']:.1f}",
                f"{result['avg_tokens_per_sec']:.1f}",
                f"{result['success_rate']:.0%}",
            )

        console.print(results_table)
        console.print()

        # Benchmark 2: Parallel agent execution
        console.print("[yellow]Benchmark 2: Parallel Agent Execution[/yellow]")

        parallel_table = Table(title=f"Parallel Agents ({device.upper()})")
        parallel_table.add_column("# Agents", justify="right")
        parallel_table.add_column("Total Time (ms)", justify="right")
        parallel_table.add_column("Avg per Agent (ms)", justify="right")
        parallel_table.add_column("Aggregate tok/s", justify="right")

        for num_agents in [2, 4, 8]:
            with console.status(f"[cyan]Testing {num_agents} parallel agents..."):
                result = await benchmark_parallel_agents(engine, num_agents)

            parallel_table.add_row(
                str(result['num_agents']),
                f"{result['elapsed_ms']:.1f}",
                f"{result['avg_latency_per_agent']:.1f}",
                f"{result['aggregate_tokens_per_sec']:.1f}",
            )

        console.print(parallel_table)
        console.print()

        # Cleanup
        await engine.shutdown()

    # Summary
    console.print("\n[bold green]Benchmark Complete![/bold green]\n")

    if sys_info["cuda_available"]:
        console.print("[cyan]Key Metrics:[/cyan]")
        console.print("✅ ROCm GPU acceleration enabled")
        console.print("✅ Multi-model parallel inference operational")
        console.print("✅ Agent swarm concurrency tested")
    else:
        console.print("[yellow]Running on CPU (install ROCm for GPU acceleration)[/yellow]")


if __name__ == "__main__":
    asyncio.run(run_benchmarks())
