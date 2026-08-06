# -*- coding: utf-8 -*-
"""
agent 包 — 智能理赔 Agent 编排层。

- pipeline.py  确定性端到端理赔流水线（OCR→查验→逐项RAG→决策），金额可复核
- memory.py    会话记忆（按 session_id 隔离，存上一张发票的提取与决策结果）
- agent.py     LangChain 1.x Agent（工具调用 + 多轮追问 + 记忆）
"""

import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
