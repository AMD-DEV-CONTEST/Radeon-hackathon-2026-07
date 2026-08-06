# -*- coding: utf-8 -*-
"""
underwriting 包 — 核保风险 Agent（独立项目，复用根 config.py 的 LLM 端点）。

模块组织（对齐 spec.md）：
- config.py            导入根 cfg + 核保专属常量（风险等级/核保建议/风险色块）
- memory.py            会话记忆（单份/批量报告，按 session_id 隔离）
- tools/               4 个业务工具（report_extract / abnormality / risk / medical_search）
- pipeline.py          单份核保流水线（确定性顺序，流式）
- batch_pipeline.py    批量核保（并发 + 持久化 + CSV 导出）
- agent.py             核保 Agent + stream_followup（流式追问）
- backend.py           FastAPI 后端（端口 8002）
- static/              原生前端（HTML + Tailwind）

sys.path 注入确保 ``import config as cfg`` 在任意启动方式下均可用
（参考 agent/__init__.py 的模式）。
"""

import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
