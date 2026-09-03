"""AutoFlow CLI 入口 (Typer)。

命令一览:
  autoflow create  <自然语言>   --url <url>   创建流程 (录制+编译+注册)
  autoflow run     <task_id|自然语言>         执行流程 (零模型 replay)
  autoflow list                           列出所有流程
  autoflow inspect <task_id>               查看流程详情
  autoflow repair <task_id>                修复失败的流程
  autoflow stats  <task_id>                查看执行统计

MVP 阶段: create 的"录制"默认用 Playwright Web 后端 + MockPlanner
(未配置 LLM API key 时)，适合无网络环境演示完整链路。
"""

from __future__ import annotations

import sys
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from autoflow.capture.web import WebBackend
from autoflow.compiler import BundleCompiler
from autoflow.config import get_settings
from autoflow.models import Recording
from autoflow.planner import create_planner
from autoflow.registry import SkillRegistry
from autoflow.repair import RepairAgent
from autoflow.replay import ReplayEngine

app = typer.Typer(help="AutoFlow Compiler - 自然语言驱动 -> 确定性自动化系统 (MVP)")
console = Console()


@app.command()
def create(
    task: str = typer.Argument(..., help="自然语言任务描述"),
    url: str = typer.Option("", "--url", help="目标 Web 应用 URL"),
    task_name: str = typer.Option("", "--name", help="任务名称 (默认自动生成)"),
    mock: bool = typer.Option(False, "--mock", help="使用 mock planner (无需 API key)"),
    headless: bool = typer.Option(False, "--headless", help="无头模式运行浏览器"),
) -> None:
    """首次执行并录制，编译为 Bundle，注册到技能库。"""
    settings = get_settings()
    planner = create_planner(mock=mock)

    console.print(f"[bold]▶ 规划任务:[/bold] {task}")
    context = {"app_name": task_name or "web-app", "backend": "web", "url": url}
    plan = planner.plan(task, context=context)
    console.print(f"[green]✓ 已生成任务计划:[/green] {plan.task_id} ({len(plan.steps)} 步)")

    # 录制
    recording = Recording(
        recording_id=f"rec_{plan.task_id}",
        app_name=context["app_name"],
        backend="mock" if mock else "web",
        metadata={"url": url},
    )
    from autoflow.capture.agent import ComputerUseAgent

    backend = _make_backend(mock=mock, url=url, headless=headless)
    agent = ComputerUseAgent(backend=backend, recording=recording)
    console.print("[bold]▶ 开始首次执行 (录制)...[/bold]")
    plan = agent.execute(plan, params={})
    console.print("[green]✓ 执行完成，已录制动作序列[/green]")

    # 编译
    compiler = BundleCompiler()
    bundle = compiler.compile(recording, plan, version=1)
    console.print(f"[green]✓ 编译 Bundle (v1):[/green] {len(bundle.steps)} 步")

    # 注册
    registry = SkillRegistry()
    registry.register(bundle, tags=[task_name])
    console.print(f"[bold green]✓ 已注册技能: {bundle.task_id}[/bold green]")
    console.print(f"  下次执行: autoflow run '{bundle.task_id}' --param note_content=值")


@app.command()
def run(
    task: str = typer.Argument(..., help="task_id 或自然语言描述"),
    param: list[str] = typer.Option([], "--param", help="参数注入, 如 --param note_content=复查"),
    url: str = typer.Option("", "--url", help="目标 URL (覆盖 Bundle 中的配置)"),
    headless: bool = typer.Option(False, "--headless", help="无头模式"),
) -> None:
    """执行已编译的 Bundle (零模型调用)。"""
    registry = SkillRegistry()

    # 解析参数
    params: dict[str, Any] = {}
    for p in param:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k] = v

    # 查找 bundle
    bundle = registry.get(task)
    if bundle is None:
        matches = registry.find(task)
        if not matches:
            console.print(f"[red]✗ 未找到任务 '{task}'[/red]")
            raise typer.Exit(1)
        best = matches[0]
        console.print(f"[yellow]→ 语义匹配: {best['goal']} (task_id={best['task_id']})[/yellow]")
        bundle = registry.get(best["task_id"])

    run_url = url or bundle.metadata.get("environment_fingerprint", {}).get("url", "")
    backend_type = bundle.metadata.get("backend", "web")

    console.print(f"[bold]▶ 执行任务:[/bold] {bundle.goal} (v{bundle.version}, backend={backend_type})")
    backend = _make_backend(mock=(backend_type == "mock"), url=run_url, headless=headless)
    engine = ReplayEngine(backend=backend)
    result = engine.replay(bundle, params=params)

    registry.record_run(bundle.task_id, result.status)

    _print_run_result(result)
    if result.status != "success":
        console.print(f"\n[red]运行失败，可使用: autoflow repair '{bundle.task_id}'[/red]")
        raise typer.Exit(1)


@app.command()
def list_skills() -> None:
    """列出所有已注册技能。"""
    registry = SkillRegistry()
    entries = registry.list_all()
    if not entries:
        console.print("[yellow]技能库为空。先用 autoflow create 创建一个流程。[/yellow]")
        return
    table = Table(title="AutoFlow 技能库")
    table.add_column("task_id")
    table.add_column("目标")
    table.add_column("版本")
    table.add_column("执行次数")
    table.add_column("成功率")
    for e in entries:
        st = e.get("executions", {})
        count = st.get("count", 0)
        rate = f"{st.get('success', 0)/max(count,1):.0%}"
        table.add_row(e["task_id"], e["goal"], str(e["latest_version"]), str(count), rate)
    console.print(table)


@app.command()
def inspect(task_id: str = typer.Argument(...)) -> None:
    """查看任务详情与各版本。"""
    registry = SkillRegistry()
    bundle = registry.get(task_id)
    if not bundle:
        console.print(f"[red]✗ 未找到任务 '{task_id}'[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]任务:[/bold] {bundle.goal} (v{bundle.version})")
    console.print(f"[bold]参数:[/bold] {bundle.parameters}")
    table = Table(title="步骤")
    table.add_column("index")
    table.add_column("action")
    table.add_column("描述")
    table.add_column("risk")
    table.add_column("ladder")
    for s in bundle.steps:
        ladder = ", ".join(e.value for e in s.resolution_ladder)
        table.add_row(str(s.index), s.action.get("type", ""), s.description, str(s.risk.get("level")), ladder)
    console.print(table)
    versions = registry.get_versions(task_id)
    console.print(f"[bold]版本历史:[/bold] {[v['version'] for v in versions]}")


@app.command()
def repair(task_id: str = typer.Argument(...)) -> None:
    """诊断并修复失败的任务 (生成 vN+1 Bundle)。"""
    registry = SkillRegistry()
    bundle = registry.get(task_id)
    if not bundle:
        console.print(f"[red]✗ 未找到任务 '{task_id}'[/red]")
        raise typer.Exit(1)

    # 构造 halt 报告 (MVP 简化: 针对定位失败)
    failed_step = next(
        (s.index for s in bundle.steps if s.risk.get("level") == "high"),
        bundle.steps[-1].index if bundle.steps else 0,
    )
    halt_report = {
        "task_id": bundle.task_id,
        "goal": bundle.goal,
        "failed_step": failed_step,
        "reason": "元素定位失败 (模拟 halt，用于演示 repair 链路)",
        "evidence_used": "structural",
        "current_screen": None,
    }

    agent = RepairAgent()
    console.print("[bold]▶ AI 诊断中...[/bold]")
    plan = agent.diagnose(halt_report, bundle)
    console.print(f"[green]✓ 诊断:[/green] {plan.get('root_cause')}")
    console.print(f"[green]✓ 策略:[/green] {plan.get('strategy')}")

    new_bundle = agent.apply(bundle, plan)
    registry.register(new_bundle)
    console.print(f"[bold green]✓ 已生成修复版 v{new_bundle.version}: {new_bundle.task_id}[/bold green]")


@app.command()
def stats(task_id: str = typer.Argument(...)) -> None:
    """查看执行统计与成本对比。"""
    registry = SkillRegistry()
    s = registry.stats(task_id)
    console.print(f"[bold]任务 {task_id} 统计:[/bold]")
    table = Table()
    table.add_column("指标")
    table.add_column("值")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)


def _print_run_result(result: Any) -> None:
    table = Table(title=f"运行结果: {result.status}")
    table.add_column("step")
    table.add_column("状态")
    table.add_column("证据")
    table.add_column("耗时(ms)")
    for s in result.steps:
        ev = s.evidence_used.value if s.evidence_used else "-"
        table.add_row(str(s.index), s.status, ev, str(s.duration_ms))
    console.print(table)
    if result.status == "success":
        console.print("[bold green]✓ 执行成功 (零模型调用)[/bold green]")
    else:
        console.print(f"[red]✗ 执行失败: {result.halt_report.get('reason') if result.halt_report else 'unknown'}[/red]")
    console.print(f"Receipt: {result.receipt}")


def _make_backend(mock: bool, url: str = "", headless: bool = False) -> Any:
    """根据模式创建录制/执行后端。

    - mock: 使用内存 MockBackend (无需浏览器，适合演示/测试)
    - 其他: 使用 Playwright WebBackend (需安装 playwright + chromium)
    """
    if mock:
        from autoflow.capture.mock import MockBackend

        return MockBackend()
    return WebBackend(url=url, headless=headless)


def main() -> None:
    app()


if __name__ == "__main__":
    app()
