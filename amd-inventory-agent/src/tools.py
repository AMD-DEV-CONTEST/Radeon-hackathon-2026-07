"""
Tools — Agent 可调用的工具集。
支持 Excel 读写、统计计算、差异分析、报告生成。
"""

from pathlib import Path
from langchain_core.tools import tool
import pandas as pd
import numpy as np


@tool
def read_excel_file(file_path: str, sheet_name: str = None) -> str:
    """读取 Excel 文件，返回数据概览。"""
    try:
        path = Path(file_path)
        if not path.exists():
            return f"文件不存在: {file_path}"

        xls = pd.ExcelFile(file_path)
        sheets = xls.sheet_names

        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path, sheet_name=sheets[0])

        return (
            f"文件: {path.name}\n"
            f"Sheet 列表: {sheets}\n"
            f"当前 Sheet: {sheet_name or sheets[0]}\n"
            f"行数: {len(df)}, 列数: {len(df.columns)}\n"
            f"列名: {list(df.columns)}\n"
            f"前 5 行:\n{df.head().to_string()}"
        )
    except Exception as e:
        return f"读取失败: {e}"


@tool
def read_csv_file(file_path: str, encoding: str = "utf-8-sig") -> str:
    """读取 CSV 文件，自动处理 BOM 头。"""
    try:
        df = pd.read_csv(file_path, encoding=encoding)
        path = Path(file_path)
        return (
            f"文件: {path.name}\n"
            f"行数: {len(df)}, 列数: {len(df.columns)}\n"
            f"列名: {list(df.columns)}\n"
            f"前 5 行:\n{df.head().to_string()}"
        )
    except Exception as e:
        return f"读取失败: {e}"


@tool
def read_txt_file(file_path: str, sep: str = "\t") -> str:
    """读取 TXT/TSV 文件。"""
    try:
        df = pd.read_csv(file_path, sep=sep)
        path = Path(file_path)
        return (
            f"文件: {path.name}\n"
            f"行数: {len(df)}, 列数: {len(df.columns)}\n"
            f"列名: {list(df.columns)}\n"
            f"前 5 行:\n{df.head().to_string()}"
        )
    except Exception as e:
        return f"读取失败: {e}"


@tool
def calculate_variance(system_qty: int, recount_qty: int, cost_price: float) -> dict:
    """计算单个 SKU 的差异。"""
    variance = recount_qty - system_qty
    variance_amount = variance * cost_price
    return {
        "variance_qty": variance,
        "variance_amount": round(variance_amount, 2),
        "direction": "盘亏" if variance < 0 else ("盘盈" if variance > 0 else "一致"),
    }


@tool
def calculate_category_summary(df: pd.DataFrame) -> str:
    """按品类汇总差异。"""
    if "品类" not in df.columns or "差异数量" not in df.columns:
        return "缺少必要列（品类/差异数量）"

    summary = df.groupby("品类").agg(
        SKU数量=("型号", "count"),
        系统库存总计=("系统库存数", "sum"),
        复盘总计=("复盘数", "sum"),
        差异总计=("差异数量", "sum"),
        差异金额总计=("差异金额", "sum"),
    ).reset_index()

    summary["差异率"] = (summary["差异总计"].abs() / summary["系统库存总计"] * 100).round(1)
    summary = summary.sort_values("差异率", ascending=False)

    return summary.to_string(index=False)


@tool
def generate_excel_output(data: dict, output_path: str) -> str:
    """生成盘点差异明细表 Excel。"""
    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            if "summary" in data:
                data["summary"].to_excel(writer, sheet_name="差异汇总", index=False)
            if "loss_detail" in data:
                data["loss_detail"].to_excel(writer, sheet_name="盘亏明细", index=False)
            if "gain_detail" in data:
                data["gain_detail"].to_excel(writer, sheet_name="盘盈明细", index=False)
            if "correction" in data:
                data["correction"].to_excel(writer, sheet_name="初盘纠错记录", index=False)

        return f"Excel 已生成: {output_path}"
    except Exception as e:
        return f"生成失败: {e}"


@tool
def generate_quality_report(checks: list[dict]) -> str:
    """生成质量校验报告。"""
    passed = sum(1 for c in checks if c.get("passed", False))
    total = len(checks)

    report = f"质量校验: {passed}/{total} 通过\n\n"
    for i, check in enumerate(checks, 1):
        status = "✅" if check.get("passed", False) else "❌"
        report += f"{status} {i}. {check.get('name', '未知')}: {check.get('detail', '')}\n"

    return report


def get_tools(enabled: list[str] = None) -> list:
    """返回所有可用工具。"""
    all_tools = [
        read_excel_file,
        read_csv_file,
        read_txt_file,
        calculate_variance,
        calculate_category_summary,
        generate_excel_output,
        generate_quality_report,
    ]
    if enabled:
        return [t for t in all_tools if t.name in enabled]
    return all_tools
