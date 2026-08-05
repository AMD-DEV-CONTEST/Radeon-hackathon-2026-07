"""
Demo Script — 演示 Agent 核心功能的脚本。
用于录制 3-5 分钟演示视频时的自动化流程。
"""

import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def demo_step1_load_files():
    """演示 Step 1: 多文件加载。"""
    console.rule("[bold green]Step 1: 多格式文件加载")
    console.print("支持 CSV / XLSX / TXT 混合格式...\n")

    table = Table(title="已加载文件")
    table.add_column("文件名", style="cyan")
    table.add_column("类型", style="green")
    table.add_column("行数", justify="right")

    files = [
        ("01_库存快照_20190425.csv", "CSV", "1,858"),
        ("02_库存快照_20190428.xlsx", "XLSX", "1,500"),
        ("03_扫描日志_20190422.txt", "TXT", "344"),
        ("04_盘点表_5月.xlsx", "XLSX (11 sheets)", "528 SKU"),
        ("05_库位主数据.xlsx", "XLSX", "304"),
        ("06_商品主数据.xlsx", "XLSX", "528"),
        ("08_入库明细_4月.xlsx", "XLSX", "129"),
        ("09_4月出库记录_市配.xlsx", "XLSX", "50"),
    ]

    for f in files:
        table.add_row(*f)

    console.print(table)
    time.sleep(1)


def demo_step2_noise_detection():
    """演示 Step 2: 噪音识别。"""
    console.rule("[bold green]Step 2: 智能噪音识别")

    console.print("[bold]扫描日志噪音检测:[/bold]")
    console.print("  总记录: 344 条")
    console.print("  NOISE 干扰: [red]68 条[/red] (型号以 NOISE- 开头)")
    console.print("  真实操作: [green]276 条[/green]\n")

    console.print("[bold]噪音文件识别:[/bold]")
    console.print("  ❌ 07_库存月报: 品类汇总粒度，月度口径不匹配")
    console.print("  ❌ 10_历史库存: 含 200+ 条 TEST/异常记录\n")

    time.sleep(1)


def demo_step3_baseline():
    """演示 Step 3: 基准选择。"""
    console.rule("[bold green]Step 3: 基准选择三维论证")

    table = Table(title="基准选择对比")
    table.add_column("维度", style="cyan")
    table.add_column("01_库存快照", style="red")
    table.add_column("02_库存快照", style="green")

    rows = [
        ("编码体系", "货号编码 (12位数字)", "型号编码 (K-xxx)"),
        ("时间点", "2019-04-25", "2019-04-28"),
        ("数据粒度", "批次×库位 (1,858行)", "型号×库位 (1,500行)"),
    ]

    for r in rows:
        table.add_row(*r)

    console.print(table)
    console.print("\n[bold green]→ 选定 02 作为比对基准[/bold green]\n")
    time.sleep(1)


def demo_step7_correlation():
    """演示 Step 7: 日志关联分析。"""
    console.rule("[bold green]Step 7: 日志关联三分类")

    table = Table(title="扫描日志关联分析")
    table.add_column("关联类别", style="cyan")
    table.add_column("SKU 数", justify="right")
    table.add_column("差异金额 (元)", justify="right")

    rows = [
        ("完全可解释", "14", "-14,160.78"),
        ("部分可解释", "21", "-350,068.19"),
        ("无日志关联", "[red]124[/red]", "[red]-625,672.00[/red]"),
    ]

    for r in rows:
        table.add_row(*r)

    console.print(table)
    console.print("\n[dim]124 个 SKU 无日志关联，需优先现场实物复核[/dim]\n")
    time.sleep(1)


def main():
    console.print(Panel.fit(
        "[bold]InventoryDoc Agent 功能演示[/bold]\n"
        "基于 AMD Radeon GPU + ROCm 的库存盘点差异智能分析",
        border_style="green",
    ))
    console.print()

    demo_step1_load_files()
    demo_step2_noise_detection()
    demo_step3_baseline()
    demo_step7_correlation()

    console.rule("[bold green]演示完成")
    console.print("\n完整演示请运行: python3 -m src.agent")
    console.print("然后在浏览器中访问 http://localhost:7860\n")


if __name__ == "__main__":
    main()
