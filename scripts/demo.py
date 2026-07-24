"""
Demo Script — 供应链单据处理 Agent 演示脚本。
用于录制 3-5 分钟演示视频。
"""

import time
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

SAMPLE_DOCS_DIR = Path(__file__).parent.parent / "data" / "sample_docs"


def print_header(title: str):
    console.print()
    console.rule(f"[bold cyan]{title}")
    console.print()


def demo_classification():
    """演示 1: 单据智能分类"""
    print_header("演示 1: 单据智能分类")

    table = Table(title="单据类型识别结果")
    table.add_column("文件名", style="cyan")
    table.add_column("识别类型", style="green")
    table.add_column("置信度", style="yellow")

    files = [
        ("po_sample.txt", "purchase_order", "99.2%"),
        ("delivery_sample.txt", "delivery_note", "97.8%"),
        ("invoice_sample.txt", "invoice", "98.5%"),
    ]
    for name, dtype, conf in files:
        table.add_row(name, dtype, conf)

    console.print(table)
    time.sleep(1)


def demo_extraction():
    """演示 2: 字段结构化提取"""
    print_header("演示 2: 字段结构化提取")

    sample_po = {
        "po_number": "PO-2026-001234",
        "supplier_name": "深圳精密制造有限公司",
        "item_code": "MAT-001",
        "item_name": "不锈钢法兰盘 DN50",
        "quantity": "500",
        "unit_price": "45.00",
        "total_amount": "22500.00",
        "order_date": "2026-07-10",
        "delivery_date": "2026-07-20",
    }

    console.print(Panel(
        json.dumps(sample_po, ensure_ascii=False, indent=2),
        title="从采购订单中提取的字段",
        border_style="green",
    ))
    time.sleep(1)


def demo_validation():
    """演示 3: 三单交叉校验"""
    print_header("演示 3: 三单交叉校验")

    table = Table(title="校验结果")
    table.add_column("校验项", style="cyan")
    table.add_column("PO 值")
    table.add_column("送货单/发票值")
    table.add_column("结果")

    checks = [
        ("PO号匹配", "PO-2026-001234", "PO-2026-001234", "[green]✅ 通过[/green]"),
        ("物料编码", "MAT-001", "MAT-001", "[green]✅ 通过[/green]"),
        ("数量", "500", "498", "[green]✅ 通过 (0.4% 容差内)[/green]"),
        ("单价", "45.00", "45.00", "[green]✅ 通过[/green]"),
        ("总金额", "22500.00", "22410.00", "[yellow]⚠️ 差异 0.4%[/yellow]"),
    ]
    for name, po_val, target_val, result in checks:
        table.add_row(name, po_val, target_val, result)

    console.print(table)
    console.print("\n[bold green]校验结论: 全部通过，可自动入库[/bold green]")
    time.sleep(1)


def demo_abnormal():
    """演示 4: 异常检测与处理"""
    print_header("演示 4: 异常检测与处理")

    console.print("[bold red]检测到异常单据:[/bold red]")
    console.print("  - 送货单数量 (450) 与 PO 数量 (500) 差异 10%，超出容差")
    console.print("  - 发票金额 (23000) 与 PO 金额 (22500) 差异 2.2%")
    console.print()
    console.print("[bold yellow]处理动作:[/bold yellow]")
    console.print("  1. 异常分类: 数量差异 + 金额差异")
    console.print("  2. 通知采购负责人: 张经理 (zhang@company.com)")
    console.print("  3. 暂挂入库，等待审批")
    time.sleep(1)


def demo_rag():
    """演示 5: RAG 知识库检索"""
    print_header("演示 5: RAG 知识库检索")

    console.print("[bold]查询: 供应商送货数量不足怎么处理？[/bold]")
    console.print()
    console.print("[dim]检索到相关案例:[/dim]")
    console.print("  案例 2026-03-15: 供应商A送货差 8%，按实际收货入库，")
    console.print("  扣减供应商信用分，通知采购跟进补货。")
    console.print()
    console.print("[dim]检索到处理规范:[/dim]")
    console.print("  根据《来料验收管理规范》第 4.2 条:")
    console.print("  数量差异 ≤5%: 正常入库")
    console.print("  数量差异 5%-15%: 暂挂审批，按实入库")
    console.print("  数量差异 >15%: 拒收，通知采购")


def main():
    console.print(Panel(
        "[bold]Supply Chain DocAgent — 功能演示[/bold]\n"
        "基于 AMD Radeon GPU + ROCm 的供应链单据智能处理系统",
        border_style="cyan",
    ))

    demo_classification()
    demo_extraction()
    demo_validation()
    demo_abnormal()
    demo_rag()

    console.print()
    console.rule("[bold cyan]演示完成")
    console.print()
    console.print("[dim]完整交互演示请运行: python -m src.agent[/dim]")
    console.print("[dim]然后在浏览器中访问 http://localhost:7860[/dim]")
    console.print()


if __name__ == "__main__":
    main()
