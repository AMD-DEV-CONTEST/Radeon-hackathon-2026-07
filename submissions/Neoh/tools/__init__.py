"""工具注册包。

导入此包时会自动注册所有内置工具到 registry。
新增工具模块时，在此处添加一行 import 即可。
"""

# 导入即触发各工具模块顶层的 register_tool() 调用
from . import file_tools  # noqa: F401
from . import shell_tools  # noqa: F401
from . import system_tools  # noqa: F401
from . import code_tools  # noqa: F401
from . import hardware_tools  # noqa: F401  硬件研发工具集（Verilog/Testbench 生成）

from .registry import registry, ToolDefinition  # noqa: F401

__all__ = ["registry", "ToolDefinition"]
