# -*- coding: utf-8 -*-
"""
tools 包 — 智能理赔 Agent 的工具集（LangChain 1.x @tool）。

四个工具（对齐《设计文档.md》第五章）：
- invoice_ocr_tool     发票多模态提取（字段 + 药品明细 items）
- invoice_verify_tool  官方发票真伪查验（外部辅助工具）
- drug_catalog_rag_tool 药品目录语义检索（本地 RAG）
- claim_decision_tool  理赔规则确定性计算（纯 Python）

设计约定：每个工具都拆成「可独立单测的核心函数」+「@tool 薄封装」，
便于 M3 单测与 M4 Agent 编排两种调用方式。
"""

import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
