# -*- coding: utf-8 -*-
"""
config.py — 智能发票理赔 Agent 系统集中配置

所有端点、模型标识、路径、RAG 阈值与理赔规则参数在此统一维护，
供 tools / rag / agent / app 各模块引用，避免散落硬编码。

设计原则（见《设计文档.md》第 2.3 / 3.4 节）：
- Agent 层只认「OpenAI 兼容端点」，不感知底层是 CUDA 还是 ROCm；
  迁移到 AMD Radeon + ROCm 时只需改 MODEL_BASE_URL 指向新后端。
- 环境变量可覆盖默认值，便于开发期 CUDA 与部署期 ROCm 切换。
"""

import os

# ----------------------------------------------------------------------------
# 一、路径
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DRUG_CATALOG_PATH = os.path.join(DATA_DIR, "drug_catalog.json")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
CHROMA_COLLECTION = "drug_catalog"


def _env(key: str, default: str) -> str:
    """读取环境变量，未设置则用默认值。"""
    return os.environ.get(key, default)


# ----------------------------------------------------------------------------
# 二、大模型推理后端（OpenAI 兼容端点）
# ----------------------------------------------------------------------------
# 实际后端：本地 vLLM OpenAI 兼容服务（vllm/vllm-openai:v0.25.1），监听 0.0.0.0:8080，
# 模型名 /model，max-model-len 100000，speculative tokens=2 (MTP)。
# 实测支持 chat_template_kwargs.enable_thinking=False（与 llama.cpp 行为一致）。
# 备选：远程 AMD ROCm llama.cpp，用 SSH 隧道 ssh -N -L 8000:localhost:8080 -p 31059 root@...，
# 或 Cloudflare Tunnel 公网端点（设 MODEL_BASE_URL 环境变量覆盖，临时 URL 重启会变）。
# Agent 层只认「OpenAI 兼容端点」，与底层 CUDA/ROCm 及 vLLM/llama.cpp 均解耦。
MODEL_HOST = _env("MODEL_HOST", "127.0.0.1")
MODEL_PORT = _env("MODEL_PORT", "8080")
MODEL_BASE_URL = _env("MODEL_BASE_URL", f"http://{MODEL_HOST}:{MODEL_PORT}/v1")
MODEL_URL = f"{MODEL_BASE_URL}/chat/completions"
MODEL_ID = _env("MODEL_ID", "/workspace/models/Qwen3.6-27B-UD-Q8_K_XL.gguf")
MODEL_API_KEY = _env("MODEL_API_KEY", "EMPTY")  # 本地服务无需真实 key

# 推理参数
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(_env("LLM_MAX_TOKENS", "8192"))
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "600"))

# ----------------------------------------------------------------------------
# 三、官方发票查验接口（外部辅助工具，非核心推理）
# ----------------------------------------------------------------------------
VERIFY_URL = _env("VERIFY_URL", "https://inv-veri.com/check")
VERIFY_CHANNEL = _env("VERIFY_CHANNEL", "yd")
VERIFY_TIMEOUT = int(_env("VERIFY_TIMEOUT", "30"))
# 响应可能的编码，按序尝试解码
VERIFY_ENCODINGS = ("utf-8", "gbk", "gb18030")

# ----------------------------------------------------------------------------
# 四、Embedding 与向量库（RAG）
# ----------------------------------------------------------------------------
# 本地 embedding，不调用远程 API；底层 torch 可走 ROCm 或 CPU。
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = _env("EMBEDDING_DEVICE", "cpu")  # "cuda" / "cpu"（ROCm 亦以 "cuda" 标识）
# HuggingFace 镜像端点（国内加速下载 embedding 模型）；置空则用官方源。
HF_ENDPOINT = _env("HF_ENDPOINT", "https://hf-mirror.com")
# bge 系列检索型 embedding 的查询前缀（拼在 query 前可提升召回；文档侧不加）
BGE_QUERY_PREFIX = _env("BGE_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章：")

# 检索参数
RAG_TOP_K = int(_env("RAG_TOP_K", "3"))
RAG_SCORE_THRESHOLD = float(_env("RAG_SCORE_THRESHOLD", "0.6"))  # 低于此且非商保创新药 → 目录外

# 混合检索（BM25 关键字 + 向量语义，RRF 融合）
RAG_HYBRID = _env("RAG_HYBRID", "true").lower() == "true"   # 是否启用 BM25+向量混合
RAG_BM25_TOP_K = int(_env("RAG_BM25_TOP_K", "10"))          # BM25 召回数
RAG_VECTOR_TOP_K = int(_env("RAG_VECTOR_TOP_K", "10"))      # 向量召回数
RAG_FUSION_K = int(_env("RAG_FUSION_K", "8"))               # RRF 融合后候选数（默认 8）
RAG_RRF_K = int(_env("RAG_RRF_K", "60"))                    # RRF 常数 k

# 重排序（CrossEncoder reranker）
RAG_RERANK = _env("RAG_RERANK", "true").lower() == "true"   # 是否启用 rerank
RAG_RERANK_MODEL = _env("RAG_RERANK_MODEL", "BAAI/bge-reranker-base")
RAG_RERANK_DEVICE = _env("RAG_RERANK_DEVICE", "cpu")        # reranker 设备（"cuda"/"cpu"）

# ----------------------------------------------------------------------------
# 五、理赔规则默认参数（因统筹地区/保单而异，可被目录条目覆盖）
# ----------------------------------------------------------------------------
# 统筹报销比例默认值（目录条目缺省时兜底）
DEFAULT_REIMBURSE_RATIO = float(_env("DEFAULT_REIMBURSE_RATIO", "0.7"))
# 商保创新药 / 商保约定目录的默认报销比例
DEFAULT_COMMERCIAL_RATIO = float(_env("DEFAULT_COMMERCIAL_RATIO", "1.0"))
# 乙类先行自付（自付二）默认比例，目录条目缺省时兜底
DEFAULT_SELF_PAY_2 = float(_env("DEFAULT_SELF_PAY_2", "0.1"))

# ----------------------------------------------------------------------------
# 六、前端与会话
# ----------------------------------------------------------------------------
APP_HOST = _env("APP_HOST", "192.168.31.250")
APP_PORT = int(_env("APP_PORT", "7860"))
APP_SHARE = _env("APP_SHARE", "true").lower() == "true"

# 图片预处理：超过此宽度则等比压缩后再编码 base64（降低视觉编码耗时）
IMAGE_MAX_WIDTH = int(_env("IMAGE_MAX_WIDTH", "1600"))

# ----------------------------------------------------------------------------
# 七、批量处理
# ----------------------------------------------------------------------------
# 批量并发数：控制批量发票处理时的并发线程/协程数，避免压垮本地 VLM；
# 建议取 2~4，默认 1（串行处理）。从环境变量读取需 int 转换。
BATCH_MAX_WORKERS = int(_env("BATCH_MAX_WORKERS", "1"))
# 年度封顶线：累计可报销金额上限；0 表示不启用封顶。默认 0.0。
ANNUAL_CAP = float(_env("ANNUAL_CAP", "0.0"))
# 批量结果持久化目录：默认位于 DATA_DIR 下的 batch_results 子目录。
BATCH_PERSIST_DIR = _env("BATCH_PERSIST_DIR", os.path.join(DATA_DIR, "batch_results"))
# 是否启用批量结果持久化：默认 True，按 "true"/"false" 解析（参考 APP_SHARE 写法）。
BATCH_PERSIST_ENABLED = _env("BATCH_PERSIST_ENABLED", "true").lower() == "true"
# 支持的图片扩展名元组：批量扫描目录时按此过滤图片文件；
# 元组类型不支持环境变量覆盖，直接定义为常量。
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# ----------------------------------------------------------------------------
# 八、核保 Agent（独立项目，复用根 config 的 LLM 端点与多模态调用模式）
# ----------------------------------------------------------------------------
# 核保后端独立端口：避开理赔 8001 / Gradio 7860 / VLM 8000。
UNDERWRITING_PORT = int(_env("UNDERWRITING_PORT", "8002"))

# Exa 神经语义搜索后端（免费稳定，医学查询召回准确率高）
EXA_MCP_URL = _env("EXA_MCP_URL", "https://mcp.exa.ai/mcp")
EXA_NUM_RESULTS = int(_env("EXA_NUM_RESULTS", "5"))
EXA_TIMEOUT = int(_env("EXA_TIMEOUT", "30"))

# anysearch 后端：默认匿名免费，ANYSEARCH_API_KEY 可选提额；空则匿名调用。
ANYSEARCH_API_KEY = _env("ANYSEARCH_API_KEY", "")
ANYSEARCH_CLI_PATH = _env("ANYSEARCH_CLI_PATH", os.path.join(BASE_DIR, "tools", "search", "anysearch_cli.py"))

# 双端并发线程池上限：控制 Exa + anysearch 同时调用时的并发线程数。
SEARCH_MAX_WORKERS = int(_env("SEARCH_MAX_WORKERS", "4"))

# 批量核保并发数：默认 1（串行），避免压垮本地 VLM。
UNDERWRITING_BATCH_MAX_WORKERS = int(_env("UNDERWRITING_BATCH_MAX_WORKERS", "1"))

# 核保结果持久化目录与开关
UNDERWRITING_PERSIST_DIR = _env("UNDERWRITING_PERSIST_DIR", os.path.join(DATA_DIR, "underwriting_results"))
UNDERWRITING_PERSIST_ENABLED = _env("UNDERWRITING_PERSIST_ENABLED", "true").lower() == "true"

# PDF 处理参数（underwriting/tools/pdf_loader.py 使用）
# PDF_IMAGE_DPI：页面渲染 DPI，150 对医学报告文本清晰度与视觉编码耗时较均衡
PDF_IMAGE_DPI = int(_env("PDF_IMAGE_DPI", "150"))
# PDF_MAX_PAGES：单 PDF 最大处理页数，超出截断，避免超长 PDF 压垮本地 VLM
PDF_MAX_PAGES = int(_env("PDF_MAX_PAGES", "20"))
# PDF_TEXT_MIN_CHARS：文本路径阈值；提取文本去空白后少于此字符数视为扫描件，走转图回退
PDF_TEXT_MIN_CHARS = int(_env("PDF_TEXT_MIN_CHARS", "50"))

# ----------------------------------------------------------------------------
# 九、鉴权与日志脱敏（demo 最小化）
# ----------------------------------------------------------------------------
# AUTH_DISABLED：一键禁用全部鉴权（回退开关）。答辩前若 JWT 出问题，
# 设环境变量 AUTH_DISABLED=true 重启即可放行所有业务接口，业务照常演示。
AUTH_DISABLED = _env("AUTH_DISABLED", "false").lower() == "true"
# 单一账号（demo），生产应换数据库 + bcrypt。密码支持环境变量覆盖。
AUTH_USERNAME = _env("AUTH_USERNAME", "admin")
AUTH_PASSWORD = _env("AUTH_PASSWORD", "claim123")
# 密码哈希 salt（sha256 用），固定值，生产应每用户独立 salt。
AUTH_PASSWORD_SALT = _env("AUTH_PASSWORD_SALT", "claim-agent-2026")
# JWT 签名密钥；两个后端共用同一密钥，故 8001/8002 token 互通（统一鉴权）。
AUTH_SECRET_KEY = _env("AUTH_SECRET_KEY", "claim-agent-demo-secret-CHANGE-ME")
# Token 有效期（小时），demo 取 12 小时。
AUTH_TOKEN_EXPIRE_HOURS = int(_env("AUTH_TOKEN_EXPIRE_HOURS", "12"))
