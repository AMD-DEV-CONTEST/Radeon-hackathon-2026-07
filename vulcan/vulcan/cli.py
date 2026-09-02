"""CLI: vulcan index / chat / ask / bench."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import bench as bench_mod
from .agent import Agent
from .config import load
from .llm import LLM
from .rag import Index

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()



def _masked(url: str) -> str:
    """See privacy.mask_endpoint. Kept as a thin alias for the banner."""
    from .privacy import mask_endpoint

    return mask_endpoint(url)


@app.command()
def index(path: Path = typer.Argument(..., exists=True), name: str = "default") -> None:
    """Index a codebase for semantic search."""
    cfg = load()
    idx = Index(cfg, LLM(cfg), name)
    with console.status(f"Indexing {path} ..."):
        n = idx.build(path.resolve())
    console.print(f"[green]Indexed {n} chunks from {path}[/green]")



def show_step(step: dict) -> None:
    """Render one agent step. Shared so `ask` and `chat` show the same thing."""
    if "plan" in step:
        console.print("[cyan]plan[/cyan]")
        for i, part in enumerate(step["plan"], 1):
            console.print(f"[dim]  {i}. {part}[/dim]")
    elif "tool" in step:
        console.print(f"[dim]→ {step['tool']}[/dim]")
    else:
        console.print("[dim]→ final[/dim]")

@app.command()
def ask(question: str, root: Path = Path("."), name: str = "default") -> None:
    """One-shot agent run against an indexed codebase."""
    cfg = load()
    agent = Agent(cfg, root.resolve(), name)

    show = show_step

    answer = agent.run(question, on_step=show)
    console.print(Panel(answer, title="Vulcan", border_style="cyan"))


@app.command()
def chat(root: Path = Path("."), name: str = "default") -> None:
    """Interactive multi-turn session."""
    cfg = load()
    agent = Agent(cfg, root.resolve(), name)
    console.print(f"[cyan]Vulcan[/cyan] on {_masked(cfg.base_url)} · model {cfg.model} · ctrl-d to exit")
    while True:
        try:
            question = console.input("[bold]you>[/bold] ")
        except EOFError:
            break
        if not question.strip():
            continue
        answer = agent.run(question, on_step=show_step)
        console.print(Panel(answer, border_style="cyan"))


@app.command()
def bench(label: str = "local", repeats: int = 3) -> None:
    """Measure TTFT and generation speed on the current backend."""
    cfg = load()
    console.print(f"Benchmarking {cfg.model} at {_masked(cfg.base_url)} ...")
    results = bench_mod.run(cfg, label, repeats)
    for name, run in results["runs"].items():
        console.print(f"  {name:7s} ttft={run['ttft_s_median']}s  speed={run['chunks_per_s_median']} chunks/s")
    console.print(f"[green]Saved bench-results/{label}.json[/green]")


@app.command("bench-concurrency")
def bench_concurrency(label: str = "concurrency", levels: str = "1,2,4,8") -> None:
    """Aggregate throughput as concurrent requests scale."""
    cfg = load()
    parsed = tuple(int(x) for x in levels.split(",") if x.strip())
    results = bench_mod.run_concurrency(cfg, label, parsed)
    for name, run in results["runs"].items():
        console.print(
            f"  {name:15s} agg={run['aggregate_chunks_per_s']} chunks/s  "
            f"per-req={run['per_request_chunks_per_s']}  ttft={run['ttft_s_median']}s"
        )
    console.print(f"[green]Saved bench-results/{label}.json[/green]")


@app.command("bench-prefill")
def bench_prefill(label: str = "prefill", words: str = "128,512,2048,8192") -> None:
    """Time-to-first-token against input length."""
    cfg = load()
    parsed = tuple(int(x) for x in words.split(",") if x.strip())
    results = bench_mod.run_prefill(cfg, label, parsed)
    for name, run in results["runs"].items():
        console.print(f"  {name:15s} ttft={run['ttft_s_median']}s")
    console.print(f"[green]Saved bench-results/{label}.json[/green]")


@app.command("bench-compare")
def bench_compare(baseline: Path, candidate: Path) -> None:
    """Markdown comparison table between two `vulcan bench` result files."""
    console.print(bench_mod.compare(baseline, candidate))


if __name__ == "__main__":
    app()


@app.command("plan-bench")
def plan_bench(
    root: Path = Path("."),
    out: Path = Path("bench-results/planning.json"),
    name: str = "default",
) -> None:
    """Measure whether decomposing a request pays for its extra round trip."""
    from .planbench import sweep

    sweep(root.resolve(), str(out), name)


@app.command("rag-bench")
def rag_bench(
    name: str = "default",
    out: Path = Path("bench-results/retrieval.json"),
) -> None:
    """Sweep the lexical weight and report retrieval top-1 and top-3."""
    from .ragbench import sweep

    sweep(name, str(out))


@app.command("privacy-check")
def privacy_check(
    question: str = "Which module implements the semantic index?",
    root: Path = Path("."),
    name: str = "default",
) -> None:
    """Run a real task and report every host the agent contacted.

    The claim this track rests on is that no token reaches a third party. This
    makes that checkable: it fails if anything outside the configured endpoints
    is contacted.
    """
    from .privacy import check, record_hosts

    cfg = load()
    agent = Agent(cfg, root.resolve(), name)
    with record_hosts() as hosts:
        answer = agent.run(question, on_step=show_step)

    r = check(cfg, hosts)
    table = Table(title="Outbound traffic during one agent run")
    table.add_column("host")
    table.add_column("allowed")
    for h in r["hosts_contacted"]:
        ok = h in r["hosts_allowed"]
        table.add_row(h, "[green]yes[/green]" if ok else "[red]NO[/red]")
    console.print(table)
    console.print(f"[dim]{r['requests']} request(s); allowed endpoints: "
                  f"{', '.join(r['hosts_allowed'])}[/dim]")
    console.print(Panel(answer, border_style="cyan"))

    if r["private"]:
        console.print("[green]No traffic left the configured endpoints.[/green]")
        console.print("[dim]Covers Vulcan's own HTTP. `run_cmd` runs your commands, "
                      "which are not sandboxed.[/dim]")
    else:
        console.print(f"[red]Unexpected hosts: {', '.join(r['unexpected'])}[/red]")
        raise typer.Exit(1)
