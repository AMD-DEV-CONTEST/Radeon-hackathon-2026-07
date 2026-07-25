#!/usr/bin/env python3
"""
生成管理层摘要报告（GPU 推理环节）。

用法:
    python scripts/generate_report.py [选项]

选项:
    --demo          使用演示模式（生成更丰富的报告，无需 LLM 服务）
    --input PATH    指定分析结果路径（默认 data/output/analysis_result.json）

环境变量:
    LLM_BASE_URL: LLM 服务地址（默认 http://localhost:8000/v1）
    LLM_MODEL: 模型名称（默认 meta-llama/Llama-3.1-8B-Instruct）
"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import load_config, InventoryDocAgent
from src.report_generator import ReportGenerator
from rich.console import Console
from rich.markdown import Markdown

console = Console()


def main():
    # 解析参数
    demo_mode = "--demo" in sys.argv
    result_path = "data/output/analysis_result.json"

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--input" and i < len(sys.argv) - 1:
            result_path = sys.argv[i + 1]

    if not Path(result_path).exists():
        console.print(f"[red]错误: 文件不存在 {result_path}[/red]")
        console.print("请先运行 python run_full_workflow.py 生成分析结果。")
        sys.exit(1)

    # 输出路径
    output_path = "data/output/管理层摘要报告.md"

    console.print(f"[bold]读取分析结果:[/bold] {result_path}")
    console.print(f"[bold]输出报告:[/bold] {output_path}")
    if demo_mode:
        console.print("[bold]模式:[/bold] 演示模式（无需 LLM 服务）")
    console.print()

    # 加载分析结果
    import json
    with open(result_path, "r", encoding="utf-8") as f:
        analysis_result = json.load(f)

    # 生成报告
    config = load_config()
    generator = ReportGenerator(config)

    if demo_mode:
        console.print("[yellow]正在生成演示报告...[/yellow]")
        report = generator.generate_report(analysis_result, demo_mode=True)
    else:
        console.print("[yellow]正在使用本地 LLM 生成报告...[/yellow]")
        report = generator.generate_report(analysis_result)

    # 保存报告
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report, encoding="utf-8")

    # 显示结果
    console.print()
    console.rule("[bold green]管理层摘要报告[/bold green]")
    console.print(Markdown(report))
    console.print()
    console.print(f"[green]✓ 报告已保存到 {output_path}[/green]")


if __name__ == "__main__":
    main()
