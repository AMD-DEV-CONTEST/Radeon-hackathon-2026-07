# -*- coding: utf-8 -*-
"""
rag 包 — 药品目录检索增强（RAG）。

导入时统一完成两件事：
1. 将项目根目录加入 sys.path，保证 `import config` 可用（无论从何处运行）。
2. 在导入 sentence-transformers / huggingface_hub 之前设置 HF_ENDPOINT，
   使 embedding 模型下载走国内镜像（见 config.HF_ENDPOINT）。
"""

import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config as _cfg  # noqa: E402

# 必须在任何 huggingface_hub / sentence_transformers 导入之前设置才生效
if _cfg.HF_ENDPOINT and not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = _cfg.HF_ENDPOINT
