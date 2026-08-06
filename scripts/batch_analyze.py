"""Batch analysis for high-volume scanning.

Prototype: CPU-parallel + GPU-sequential pipeline.
Run: python scripts/batch_analyze.py <directory> [--workers 4] [--output json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()


def collect_files(path: Path) -> list[Path]:
    """Collect supported code files."""
    extensions = {".c", ".h", ".py"}
    if path.is_file():
        return [path] if path.suffix in extensions else []
    files = []
    for ext in extensions:
        files.extend(path.rglob(f"*{ext}"))
    return [f for f in files if f.is_file()]


def agent1_static(filepath: Path) -> dict:
    """Agent 1: Static analysis (CPU-only, parallelizable)."""
    from agents.static_analyzer import StaticAnalyzer
    from core.models import CodeFile, Language

    lang_map = {".c": Language.C, ".h": Language.C, ".py": Language.PYTHON}
    code_file = CodeFile.from_path(filepath)
    analyzer = StaticAnalyzer()
    findings = analyzer.analyze(code_file)
    return {"file": str(filepath), "findings": findings, "count": len(findings)}


# Shared LLM client (singleton for GPU efficiency)
_llm_client = None

def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        from core.llm_client import LLMClient
        _llm_client = LLMClient()
    return _llm_client


def agent23_gpu(filepath: Path, static_findings: list) -> dict:
    """Agent 2+3: Semantic + Verification (GPU, sequential)."""
    try:
        from agents.semantic_analyzer import SemanticAnalyzer
        from agents.deep_verifier import DeepVerifier
        from core.models import CodeFile

        llm = _get_llm_client()
        code_file = CodeFile.from_path(filepath)

        # Agent 2: Semantic analysis (signature: analyze(code_file, existing_risks))
        semantic = SemanticAnalyzer(llm_client=llm)
        semantic_results = semantic.analyze(code_file, static_findings)

        # Agent 3: Deep verification (signature: verify_batch(files, risks))
        verifier = DeepVerifier(llm_client=llm)
        verified = verifier.verify_batch([code_file], semantic_results)

        return {"file": str(filepath), "verified": verified, "count": len(verified)}
    except Exception as e:
        console.print(f"[yellow]GPU analysis failed for {filepath}: {e}[/]")
        return {"file": str(filepath), "verified": [], "count": 0, "error": str(e)}


def agent4_report(result: dict) -> dict:
    """Agent 4: Report generation (CPU-only, parallelizable)."""
    # Simplified — just format the result
    return result


def batch_analyze(directory: str, max_workers: int = 4) -> list[dict]:
    """4-phase batch pipeline: CPU → GPU → GPU → CPU."""
    path = Path(directory)
    files = collect_files(path)

    if not files:
        console.print(f"[yellow]No supported files found in {directory}[/]")
        return []

    console.print(f"[cyan]Found {len(files)} files to analyze[/]")

    results = []
    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        # Phase 1: Agent 1 (CPU) — parallel
        task1 = progress.add_task("Phase 1: Static analysis (CPU parallel)...", total=len(files))
        static_results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(agent1_static, f): f for f in files}
            for future in as_completed(futures):
                filepath = futures[future]
                try:
                    result = future.result()
                    static_results[str(filepath)] = result
                except Exception as e:
                    console.print(f"[red]Static analysis failed for {filepath}: {e}[/]")
                    static_results[str(filepath)] = {"file": str(filepath), "findings": [], "count": 0}
                progress.advance(task1)

        # Phase 2+3: Agent 2+3 (GPU) — sequential
        task2 = progress.add_task("Phase 2+3: Semantic + Verification (GPU sequential)...", total=len(files))
        gpu_results = []
        for filepath_str, static_result in static_results.items():
            filepath = Path(filepath_str)
            gpu_result = agent23_gpu(filepath, static_result["findings"])
            gpu_results.append(gpu_result)
            progress.advance(task2)

        # Phase 4: Agent 4 (CPU) — parallel reports
        task3 = progress.add_task("Phase 4: Report generation (CPU parallel)...", total=len(gpu_results))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(agent4_report, r): r for r in gpu_results}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    console.print(f"[red]Report generation failed: {e}[/]")
                progress.advance(task3)

    elapsed = time.time() - start_time
    total_risks = sum(r.get("count", 0) for r in results)

    console.print(f"\n[green]Analysis complete![/]")
    console.print(f"  Files analyzed: {len(files)}")
    console.print(f"  Total risks: {total_risks}")
    console.print(f"  Total time: {elapsed:.1f}s ({elapsed/len(files):.1f}s per file)")
    console.print(f"  Workers: {max_workers}")

    return results


def main():
    parser = argparse.ArgumentParser(description="CodeRisk Agent - Batch Analysis")
    parser.add_argument("directory", help="Directory to analyze")
    parser.add_argument("--workers", type=int, default=4, help="CPU parallel workers (default: 4)")
    parser.add_argument("--output", default="terminal", choices=["terminal", "json"],
                        help="Output format (default: terminal)")
    args = parser.parse_args()

    results = batch_analyze(args.directory, max_workers=args.workers)

    if args.output == "json":
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
