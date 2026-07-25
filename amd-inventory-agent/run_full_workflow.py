"""
运行完整的 10 步 Agent 工作流。
使用真实科勒供应链数据测试。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.agent import InventoryDocAgent, load_config
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def main():
    console.print(Panel.fit(
        "[bold]InventoryDoc Agent — 完整 10 步工作流[/bold]\n"
        "数据: 科勒供应链 5 月循环盘点",
        border_style="green",
    ))

    # 加载配置
    config = load_config()
    agent = InventoryDocAgent(config)

    # 运行工作流
    input_dir = "data/input"
    output_dir = "data/output"

    console.print(f"\n[bold]输入目录:[/bold] {input_dir}")
    console.print(f"[bold]输出目录:[/bold] {output_dir}\n")

    result = agent.run_workflow(input_dir, output_dir)

    # 打印每步结果
    console.rule("[bold green]Step 1: 加载所有文件")
    step1 = result.get("Step 1: 加载所有文件", {})
    console.print(f"已加载: {step1.get('total_files', 0)} 个文件")
    for f in step1.get("loaded", []):
        console.print(f"  ✓ {f}")

    console.rule("[bold green]Step 2: 识别噪音数据")
    step2 = result.get("Step 2: 识别噪音数据", {})
    noise_log = step2.get("scan_log_noise", {})
    console.print(f"扫描日志 NOISE: {noise_log.get('noise_count', 0)} 条")
    console.print(f"真实操作: {noise_log.get('real_count', 0)} 条")
    noise_files = step2.get("noise_files", [])
    console.print(f"噪音文件: {len(noise_files)} 个")
    for f in noise_files:
        console.print(f"  ❌ {f}")

    console.rule("[bold green]Step 3: 选定比对基准")
    step3 = result.get("Step 3: 选定比对基准", {})
    console.print(f"选定基准: {step3.get('selected', '未选定')}")
    console.print(f"理由: {step3.get('reason', '')}")
    if "three_dimension_analysis" in step3:
        tda = step3["three_dimension_analysis"]
        console.print(f"三维论证: 编码={tda.get('编码体系')}, 粒度={tda.get('数据粒度')}")

    console.rule("[bold green]Step 4: 清洗扫描日志")
    step4 = result.get("Step 4: 清洗扫描日志", {})
    console.print(f"总记录: {step4.get('total_records', 0)}")
    console.print(f"排除 NOISE: {step4.get('noise_removed', 0)} 条")
    console.print(f"真实操作: {step4.get('real_records', 0)} 条")
    console.print(f"窗口期 (4/25-4/28): {step4.get('window_records', 0)} 条")
    ops = step4.get("operations", {}).get("operation_types", {})
    if ops:
        console.print(f"操作分布: {ops}")

    console.rule("[bold green]Step 5: 加载盘点结果")
    step5 = result.get("Step 5: 加载盘点结果", {})
    console.print(f"SKU 总数: {step5.get('total_sku', 0)}")
    console.print(f"系统库存总计: {step5.get('system_total', 0)}")
    console.print(f"复盘总计: {step5.get('recount_total', 0)}")
    console.print(f"净差异: {step5.get('net_variance', 0)}")
    console.print(f"差异率: {step5.get('variance_rate', 0)}%")
    console.print(f"盘亏: {step5.get('loss_count', 0)} 个 | 盘盈: {step5.get('gain_count', 0)} 个 | 一致: {step5.get('consistent_count', 0)} 个")
    console.print(f"初盘纠错: {step5.get('correction_count', 0)} 个")

    console.rule("[bold green]Step 6: 计算差异金额")
    step6 = result.get("Step 6: 计算差异金额", {})
    console.print(f"盘亏金额: {step6.get('total_loss_amount', 0):,.2f} 元")
    console.print(f"盘盈金额: {step6.get('total_gain_amount', 0):,.2f} 元")
    console.print(f"净差异金额: {step6.get('net_variance_amount', 0):,.2f} 元")
    console.print(f"缺失成本 SKU: {step6.get('missing_cost_count', 0)} 个")

    console.rule("[bold green]Step 7: 日志关联分析")
    step7 = result.get("Step 7: 日志关联分析", {})
    if isinstance(step7, dict) and "error" not in step7:
        table = Table(title="日志关联三分类")
        table.add_column("关联类别", style="cyan")
        table.add_column("SKU 数", justify="right")
        table.add_column("差异金额 (元)", justify="right")
        for cat in ["完全可解释", "部分可解释", "无日志关联"]:
            if cat in step7:
                info = step7[cat]
                table.add_row(cat, str(info["count"]), f"{info['amount']:,.2f}")
        console.print(table)
    else:
        console.print(f"结果: {step7}")

    console.rule("[bold green]Step 8: 库位状态校验")
    step8 = result.get("Step 8: 库位状态校验", {})
    if "status_distribution" in step8:
        dist = step8["status_distribution"]
        console.print(f"库位状态分布: 启用={dist.get('启用', 0)}, 已停用={dist.get('已停用', 0)}, 维修中={dist.get('维修中', 0)}")
        console.print(f"异常库位 SKU: {step8.get('abnormal_count', 0)} 个")

    console.rule("[bold green]Step 9: 品类维度分析")
    step9 = result.get("Step 9: 品类维度分析", {})
    if "categories" in step9:
        table = Table(title="品类差异分析")
        table.add_column("品类", style="cyan")
        table.add_column("SKU 数", justify="right")
        table.add_column("系统库存", justify="right")
        table.add_column("差异率", justify="right")
        for cat in step9["categories"]:
            name = cat.get("品类", "")
            rate = cat.get("差异率", 0)
            style = "red" if rate > 10 else ("yellow" if rate > 5 else "")
            table.add_row(
                name,
                str(cat.get("SKU数量", 0)),
                str(cat.get("系统库存总计", 0)),
                f"[{style}]{rate}%[/{style}]" if style else f"{rate}%",
            )
        console.print(table)

    anomalies = step9.get("anomaly_categories", [])
    if anomalies:
        console.print("\n[bold red]异常品类:[/bold red]")
        for a in anomalies:
            console.print(f"  ⚠️ {a['品类']}: {a['差异率']}% ({a['严重程度']})")

    console.rule("[bold green]Step 10: 生成交付物")
    step10 = result.get("Step 10: 生成交付物", {})
    console.print(f"Excel: {step10.get('xlsx_path', '未生成')}")
    console.print(f"报告: {step10.get('md_path', '未生成')}")

    # 质量校验
    console.rule("[bold green]质量校验 (7 条 must_check_points)")
    checks = result.get("quality_checks", [])
    passed = sum(1 for c in checks if c.get("passed", False))
    console.print(f"通过: {passed}/{len(checks)}\n")
    for i, check in enumerate(checks, 1):
        status = "[green]✅[/green]" if check.get("passed") else "[red]❌[/red]"
        console.print(f"{status} {i}. {check.get('name', '')} ({check.get('importance', '')})")
        console.print(f"   {check.get('detail', '')}\n")

    # 显示生成的报告内容
    md_path = step10.get("md_path")
    if md_path and Path(md_path).exists():
        console.rule("[bold green]生成的分析报告")
        report_content = Path(md_path).read_text(encoding="utf-8")
        console.print(Markdown(report_content[:3000]))

    console.print(Panel.fit(
        "[bold green]工作流执行完成！[/bold green]\n"
        f"输出目录: {output_dir}",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
