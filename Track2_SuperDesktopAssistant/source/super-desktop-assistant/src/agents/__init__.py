"""Agent 层初始化 —— 注册所有执行 Agent 到 DAG 执行器。"""

# 导入各 Agent 模块，触发 register_agent 装饰器注册
from . import vision as _vision      # noqa: F401
from . import speech as _speech      # noqa: F401
from . import image_gen as _image_gen  # noqa: F401
from . import llm_agent as _llm_agent  # noqa: F401
