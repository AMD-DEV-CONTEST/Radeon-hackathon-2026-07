"""
Tools — 供应链业务工具集。
支持 ERP 查询、回写、邮件通知、文件读取、数据校验。
"""

from langchain_core.tools import tool


@tool
def erp_lookup(item_code: str) -> str:
    """查询 ERP 系统中物料编码的库存和价格信息。"""
    # 模拟 ERP 查询（实际部署时对接真实 ERP API）
    mock_data = {
        "MAT-001": {"name": "螺丝钉M6", "stock": 10000, "unit_price": 0.5},
        "MAT-002": {"name": "垫片M6", "stock": 5000, "unit_price": 0.3},
        "MAT-003": {"name": "法兰盘DN50", "stock": 500, "unit_price": 45.0},
    }
    info = mock_data.get(item_code)
    if info:
        return f"物料 {item_code}: {info['name']}, 库存 {info['stock']}, 单价 ¥{info['unit_price']}"
    return f"物料 {item_code} 未在 ERP 中找到"


@tool
def erp_writeback(data: str) -> str:
    """将校验通过的入库数据写回 ERP 系统。"""
    # 模拟 ERP 回写
    return f"入库数据已成功写入 ERP: {data[:200]}"


@tool
def email_notify(recipient: str, subject: str, body: str) -> str:
    """发送邮件通知（用于异常单据审批提醒）。"""
    # 模拟邮件发送
    return f"邮件已发送给 {recipient}: {subject}"


@tool
def file_reader(file_path: str) -> str:
    """读取本地文件内容。"""
    from pathlib import Path
    path = Path(file_path)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return f"文件不存在: {file_path}"


@tool
def validator(data: str, rules: str) -> str:
    """校验数据是否符合业务规则。"""
    # 基础校验逻辑
    issues = []
    if not data or data.strip() == "":
        issues.append("数据为空")
    if "error" in data.lower():
        issues.append("数据包含错误标记")

    if issues:
        return f"校验失败: {'; '.join(issues)}"
    return "校验通过"


TOOL_REGISTRY = {
    "erp_lookup": erp_lookup,
    "erp_writeback": erp_writeback,
    "email_notify": email_notify,
    "file_reader": file_reader,
    "validator": validator,
}


def get_tools(enabled: list[str]) -> list:
    """根据配置返回启用的工具列表。"""
    return [TOOL_REGISTRY[name] for name in enabled if name in TOOL_REGISTRY]
