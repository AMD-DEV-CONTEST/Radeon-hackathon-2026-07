import logging
from typing import Dict, Any, Callable, Optional
from tools.registry import registry
from .audit import audit_logger

logger = logging.getLogger(__name__)


# 默认审批回调：CLI 模式下用 input() 询问
def default_approval_callback(tool_name: str, arguments: Dict[str, Any], description: str = "") -> bool:
    """默认审批回调（CLI 模式）。

    Args:
        tool_name: 工具名称
        arguments: 工具参数
        description: 步骤描述

    Returns:
        True 表示用户批准，False 表示拒绝
    """
    print("\n" + "=" * 50)
    print("⚠️  高危操作审批")
    print(f"工具: {tool_name}")
    print(f"参数: {arguments}")
    if description:
        print(f"说明: {description}")
    print("=" * 50)
    while True:
        choice = input("是否批准执行？(y/n): ").strip().lower()
        if choice in ("y", "yes"):
            return True
        elif choice in ("n", "no"):
            return False
        else:
            print("请输入 y 或 n")


class Executor:
    """步骤执行器，支持 Human-in-the-loop 高危操作审批。"""

    def __init__(self, approval_callback: Optional[Callable] = None):
        """
        Args:
            approval_callback: 审批回调函数，签名 (tool_name, arguments, description) -> bool
                              为 None 时使用默认 CLI input() 回调
        """
        self.approval_callback = approval_callback or default_approval_callback

    def execute(self, step: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = step.get("tool")

        # 无工具调用的步骤：直接返回描述
        if tool_name is None or tool_name == "None" or tool_name == "null":
            return {
                "success": True,
                "output": f"执行步骤: {step.get('description', '')}",
                "step": step.get("step"),
            }

        # 检查工具是否存在
        try:
            tool_def = registry.get_tool(tool_name)
        except ValueError as e:
            return {
                "success": False,
                "error": f"工具未注册: {tool_name}",
                "step": step.get("step"),
                "tool": tool_name,
            }

        arguments = step.get("arguments", {})
        description = step.get("description", "")

        # ---- Human-in-the-loop 审批 ----
        if tool_def.requires_approval:
            logger.info(f"Step {step.get('step')}: 工具 {tool_name} 需要审批")
            try:
                approved = self.approval_callback(tool_name, arguments, description)
            except Exception as e:
                logger.error(f"审批回调异常: {e}")
                approved = False

            # 记录审批决策
            audit_logger.log_approval(
                tool_name=tool_name,
                arguments=arguments,
                approved=approved,
                step=step.get("step"),
            )

            if not approved:
                logger.warning(f"Step {step.get('step')}: 用户拒绝执行 {tool_name}")
                return {
                    "success": False,
                    "skipped": True,
                    "output": f"用户拒绝执行高危操作: {tool_name}",
                    "step": step.get("step"),
                    "tool": tool_name,
                }

        # ---- 执行工具 ----
        try:
            result = registry.call_tool(tool_name, **arguments)
            # 记录工具调用
            audit_logger.log_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                success=result.get("success", True),
                output=result,
                step=step.get("step"),
            )
            return {
                "success": result.get("success", True),
                "output": result,
                "step": step.get("step"),
                "tool": tool_name,
            }
        except Exception as e:
            logger.error(f"Execution failed for step {step.get('step')}: {str(e)}")
            audit_logger.log_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                output={"error": str(e)},
                step=step.get("step"),
            )
            return {
                "success": False,
                "error": str(e),
                "step": step.get("step"),
                "tool": tool_name,
            }
