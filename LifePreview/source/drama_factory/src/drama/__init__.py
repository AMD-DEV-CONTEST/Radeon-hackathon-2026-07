"""AI Drama Factory — 小说→竖屏短剧 全自动多agent流水线。

核心模块：
  - schemas        : 全流程数据资产(JSON)的数据结构定义
  - llm_client     : 分层模型路由(本地/远端API, 按任务复杂度选型)
  - comfy_client   : ComfyUI HTTP/WebSocket 客户端
  - orchestrator   : 状态机 + 任务队列 的流水线编排器
  - agents.*       : 12 个流水线 agent
"""

__version__ = "0.1.0"
