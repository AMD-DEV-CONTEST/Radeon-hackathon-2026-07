# -*- coding: utf-8 -*-
"""
underwriting/config.py — 核保 Agent 专属配置

设计对齐 spec.md「集中配置」：根 config.py 已新增「八、核保 Agent」配置段
（端口、双搜索后端、批量参数、持久化），本模块负责：
1. 透出根 cfg 的 LLM 端点相关常量，方便后续模块引用（不必每次 import config）；
2. 定义核保专属领域常量：风险等级枚举、核保建议枚举、风险色块映射。

不在本模块重新读取环境变量；所有环境变量统一在根 config.py 用 `_env` 模式读取。
"""

import config as cfg

# ----------------------------------------------------------------------------
# 透出根 cfg 的 LLM 端点常量（后续工具/流水线/Agent 直接 from underwriting.config import *）
# ----------------------------------------------------------------------------
MODEL_BASE_URL = cfg.MODEL_BASE_URL
MODEL_URL = cfg.MODEL_URL
MODEL_ID = cfg.MODEL_ID
MODEL_API_KEY = cfg.MODEL_API_KEY
LLM_TEMPERATURE = cfg.LLM_TEMPERATURE
LLM_MAX_TOKENS = cfg.LLM_MAX_TOKENS
LLM_TIMEOUT = cfg.LLM_TIMEOUT
IMAGE_MAX_WIDTH = cfg.IMAGE_MAX_WIDTH
IMAGE_EXTS = cfg.IMAGE_EXTS
BASE_DIR = cfg.BASE_DIR
DATA_DIR = cfg.DATA_DIR

# ----------------------------------------------------------------------------
# 核保后端与搜索后端（透出根 cfg 第八段）
# ----------------------------------------------------------------------------
UNDERWRITING_PORT = cfg.UNDERWRITING_PORT
EXA_MCP_URL = cfg.EXA_MCP_URL
EXA_NUM_RESULTS = cfg.EXA_NUM_RESULTS
EXA_TIMEOUT = cfg.EXA_TIMEOUT
ANYSEARCH_API_KEY = cfg.ANYSEARCH_API_KEY
ANYSEARCH_CLI_PATH = cfg.ANYSEARCH_CLI_PATH
SEARCH_MAX_WORKERS = cfg.SEARCH_MAX_WORKERS
UNDERWRITING_BATCH_MAX_WORKERS = cfg.UNDERWRITING_BATCH_MAX_WORKERS
UNDERWRITING_PERSIST_DIR = cfg.UNDERWRITING_PERSIST_DIR
UNDERWRITING_PERSIST_ENABLED = cfg.UNDERWRITING_PERSIST_ENABLED

# ----------------------------------------------------------------------------
# 核保领域枚举与映射
# ----------------------------------------------------------------------------

# Risk level enums (Low / Medium / High)
RISK_LEVEL_LOW = "Low"
RISK_LEVEL_MEDIUM = "Medium"
RISK_LEVEL_HIGH = "High"
RISK_LEVELS = (RISK_LEVEL_LOW, RISK_LEVEL_MEDIUM, RISK_LEVEL_HIGH)

# Underwriting recommendation enums
RECOMMENDATION_STANDARD = "Standard"
RECOMMENDATION_SUBSTANDARD_EXTRA_PREMIUM = "Substandard - Extra Premium"
RECOMMENDATION_SUBSTANDARD_EXCLUSION = "Substandard - Exclusion"
RECOMMENDATION_POSTPONE = "Postpone"
RECOMMENDATION_DECLINE = "Decline"
RECOMMENDATIONS = (
    RECOMMENDATION_STANDARD,
    RECOMMENDATION_SUBSTANDARD_EXTRA_PREMIUM,
    RECOMMENDATION_SUBSTANDARD_EXCLUSION,
    RECOMMENDATION_POSTPONE,
    RECOMMENDATION_DECLINE,
)

# 风险色块映射：低=绿 / 中=黄 / 高=红（前端结论卡用，对应 Tailwind 色系）。
RISK_COLOR_MAP = {
    RISK_LEVEL_LOW: "green",
    RISK_LEVEL_MEDIUM: "yellow",
    RISK_LEVEL_HIGH: "red",
}

# 风险等级到核保建议的默认映射（仅作工具内部参考；最终建议以 risk_tool / 报告生成为准）
RISK_TO_RECOMMENDATION_DEFAULT = {
    RISK_LEVEL_LOW: RECOMMENDATION_STANDARD,
    RISK_LEVEL_MEDIUM: RECOMMENDATION_SUBSTANDARD_EXTRA_PREMIUM,
    RISK_LEVEL_HIGH: RECOMMENDATION_DECLINE,
}

# ----------------------------------------------------------------------------
# PDF 处理参数（核保专属，透出给 pdf_loader / report_extract_tool）
# ----------------------------------------------------------------------------
# 用 getattr 兜底：即便根 config.py 暂未加这几项也不报错（集中配置 + 容错）。
PDF_IMAGE_DPI = int(getattr(cfg, "PDF_IMAGE_DPI", 150))          # 页面渲染 DPI
PDF_MAX_PAGES = int(getattr(cfg, "PDF_MAX_PAGES", 20))           # 单 PDF 最大处理页数
PDF_TEXT_MIN_CHARS = int(getattr(cfg, "PDF_TEXT_MIN_CHARS", 50))  # 文本路径阈值

# 文档扩展名：图片 + PDF（独立于发票 Agent 的 IMAGE_EXTS，避免污染发票批处理）
# 核保侧的批量扫描、单份上传均按 DOCUMENT_EXTS 筛选。
DOCUMENT_EXTS = tuple(cfg.IMAGE_EXTS) + (".pdf",)
