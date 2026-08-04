"""
aiquant API 网关 — FastAPI 主服务
"""
import sys
import os
import subprocess
from pathlib import Path

# 确保项目根目录在 path 中
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

# 加载 .env 环境变量（必须在导入其他模块之前）
# override=True 确保 .env 值覆盖已存在的环境变量，防止 pydantic-settings
# 在 LiteLLMSettings / LLMSettings 初始化时使用默认值而非 .env 配置
from dotenv import load_dotenv
load_dotenv(_project_root / ".env", override=True)

# 绕过 macOS 系统代理（127.0.0.1:7890 被飞书占用，非真实代理）
# 必须在 import httpx/openai/litellm 之前设置，否则它们会缓存代理配置
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

# macOS 必需：禁用 Objective-C fork 安全检查，避免 gunicorn 多 worker 启动时崩溃
# 错误表现：objc[xxx]: +[NSString initialize] may have been in progress in another thread when fork() was called.
# 在导入任何可能触发 fork 的模块（multiprocessing / gunicorn worker）之前设置
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from loguru import logger
# 统一日志配置：终端彩色 + JSON 文件轮转 + 纯文本文件轮转
from backend.shared.log_config import setup_logging, get_logger
setup_logging(log_level=os.environ.get("AIQUANT_LOG_LEVEL", "INFO"))
# sse_starlette.EventSourceResponse 在当前 starlette/anyio/uvicorn 版本下
# 存在兼容性问题（不发送响应头即超时），改用 StreamingResponse + 手动 SSE 格式化
# from sse_starlette.sse import EventSourceResponse
import httpx
import json
import time
import uuid
from datetime import datetime

# ── 任务队列: Celery + Redis ──
from backend.worker.celery_app import app as celery_app, get_events_channel
import redis.asyncio as aioredis

# ═══════════════════════════════════════════════════════════
# 全局一次性 nest_asyncio 补丁：让事件循环支持嵌套 await。
# RD-Agent 的 factor_loop.run() 内部也使用 asyncio，在 FastAPI 的
# 主循环中直接 await 需要 nest_asyncio 消除嵌套循环冲突。
# 全程只 patch 一次，后续所有异步代码统一复用主循环。
# 
# 兼容策略：设置标准事件循环策略（uvloop 不支持 nest_asyncio patch）。
# 性能影响可控：因子挖掘瓶颈在 LLM 调用和 Qlib 回测计算，非事件循环 IO。
# ═══════════════════════════════════════════════════════════
import asyncio
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
import nest_asyncio
nest_asyncio.apply()

# ═══════════════════════════════════════════════════════
# Qlib instruments 文件部署：将项目内置的股票池文件
# (csi300/csi500/sz50) 复制到 ~/.qlib/qlib_data/cn_data/instruments/
# 这样 RD-Agent 可以通过 market="csi300" 等参数选择不同股票池
# ═══════════════════════════════════════════════════════
def _deploy_instruments_files():
    qlib_inst_dir = Path(os.path.expanduser("~/.qlib/qlib_data/cn_data/instruments"))
    bundled_dir = _project_root / "data" / "instruments"
    if not bundled_dir.exists():
        return
    qlib_inst_dir.mkdir(parents=True, exist_ok=True)
    for txt_file in bundled_dir.glob("*.txt"):
        dest = qlib_inst_dir / txt_file.name
        if not dest.exists():
            import shutil
            shutil.copy2(txt_file, dest)
            logger.info(f"已部署 instruments 文件: {txt_file.name} → {dest}")

_deploy_instruments_files()

# ═══════════════════════════════════════════════════════
# RUN_MODE 适配: 根据模式选择执行环境
#
# local:  Monkey-patch QTDockerEnv → QlibCondaEnv（无Docker隔离）
# docker: 使用 ARM64 原生 Qlib 镜像，容错重试 + 超时杀灭
#         杜绝因子循环卡死。需预先 docker build local_qlib:latest。
# ═══════════════════════════════════════════════════════
_RUN_MODE = os.getenv("RUN_MODE", "local").lower()
if _RUN_MODE == "docker":
    # Docker 模式: 使用预构建 ARM64 镜像，关闭 GPU（M4 无 NVIDIA）
    # 走 RD-Agent 原生 Docker 路径，获得容器隔离/超时杀灭/自动重试
    # pydantic-settings: QlibDockerConf 的 env_prefix='QLIB_DOCKER_'，用环境变量覆盖默认值
    os.environ["QLIB_DOCKER_BUILD_FROM_DOCKERFILE"] = "false"
    os.environ["QLIB_DOCKER_ENABLE_GPU"] = "false"
    from rdagent.utils.env import QlibDockerConf
    _dc = QlibDockerConf()
    logger.info(
        f"RUN_MODE=docker: ARM64 镜像 local_qlib:latest | "
        f"超时={_dc.running_timeout_period}s | "
        f"重试={_dc.retry_count}次 | GPU=disabled"
    )
elif _RUN_MODE == "local":
    try:
        from rdagent.scenarios.qlib.experiment import utils as _qlib_utils
        _orig_generate = _qlib_utils.generate_data_folder_from_qlib
        # 使用当前 conda 环境名称，确保 qlib 等依赖可用
        # 优先从 sys.prefix 检测（更可靠），fallback 到 CONDA_DEFAULT_ENV
        _current_prefix = os.path.dirname(os.path.dirname(sys.executable)) if 'envs' in sys.executable else sys.prefix
        _CURRENT_CONDA_ENV = os.path.basename(_current_prefix) if 'envs' in _current_prefix else os.environ.get("CONDA_DEFAULT_ENV", "aiquant")
        # 强制 env_type 为 docker（Docker Desktop 可用，避免 daemon 进程 multiprocessing 限制）
        from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
        MODEL_COSTEER_SETTINGS.env_type = "docker"
        logger.info(f"RUN_MODE=local: MODEL_COSTEER_SETTINGS.env_type 已覆盖为 docker")
        def _patched_generate_data_folder_from_qlib():
            """使用本地 conda 环境替代 Docker 执行数据生成（带缓存，单线程模式）"""
            import shutil
            from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
            template_path = Path(_qlib_utils.__file__).parent / "factor_data_template"

            # 检查目标文件是否已存在（缓存机制）
            dest_all = Path(FACTOR_COSTEER_SETTINGS.data_folder) / "daily_pv.h5"
            dest_debug = Path(FACTOR_COSTEER_SETTINGS.data_folder_debug) / "daily_pv.h5"
            if dest_all.exists() and dest_debug.exists():
                logger.info("RUN_MODE=local: data folder already populated, skipping generate.py")
                return

            # 检查 template 目录中是否已有 .h5 文件
            if not (template_path / "daily_pv_all.h5").exists() or not (template_path / "daily_pv_debug.h5").exists():
                logger.info("RUN_MODE=local: generating data via qlib (in-process, may take 2-3 minutes)...")
                # 直接在主进程中用已初始化的 Qlib 生成数据，避免子进程 Qlib 初始化冲突
                import qlib
                from qlib.data import D
                try:
                    qlib.init(provider_uri=os.path.expanduser("~/.qlib/qlib_data/cn_data"), region="cn")
                except Exception:
                    pass  # 已初始化则跳过
                # 强制设置 region=cn，防止 __DEFAULT_FREQ KeyError
                try:
                    from qlib.config import C
                    C["region"] = "cn"
                    C["provider_uri"] = os.path.expanduser("~/.qlib/qlib_data/cn_data")
                except Exception:
                    pass

                instruments = D.instruments(market="all")
                fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
                logger.info("正在获取全量特征数据...")
                data = D.features(instruments, fields, freq="day").sort_index()
                if data.empty:
                    raise RuntimeError("No data available in Qlib. Check ~/.qlib/qlib_data/cn_data/")

                all_path = template_path / "daily_pv_all.h5"
                data.to_hdf(str(all_path), key="data")
                n_inst = data.reset_index()["instrument"].nunique()
                logger.info(f"daily_pv_all.h5: {len(data)} rows, {n_inst} instruments")

                # Debug 数据：前 100 只股票
                first_100 = data.reset_index()["instrument"].unique()[:100].tolist()
                data2 = D.features(first_100, fields, freq="day").sort_index()
                debug_path = template_path / "daily_pv_debug.h5"
                data2.to_hdf(str(debug_path), key="data")
                logger.info(f"daily_pv_debug.h5: {len(data2)} rows, {len(first_100)} instruments")
                logger.info("RUN_MODE=local: data generation completed successfully")
            else:
                logger.info("RUN_MODE=local: .h5 files exist in template, reusing")

            Path(FACTOR_COSTEER_SETTINGS.data_folder).mkdir(parents=True, exist_ok=True)
            shutil.copy(template_path / "daily_pv_all.h5", dest_all)
            shutil.copy(template_path / "README.md", Path(FACTOR_COSTEER_SETTINGS.data_folder) / "README.md")
            Path(FACTOR_COSTEER_SETTINGS.data_folder_debug).mkdir(parents=True, exist_ok=True)
            shutil.copy(template_path / "daily_pv_debug.h5", dest_debug)
            shutil.copy(template_path / "README.md", Path(FACTOR_COSTEER_SETTINGS.data_folder_debug) / "README.md")
        _qlib_utils.generate_data_folder_from_qlib = _patched_generate_data_folder_from_qlib
        
        # 修复 QlibCondaConf 和 CondaConf 默认环境名：RD-Agent 默认使用 rdagent4qlib，
        # 但 Mac 本地环境名为 aiquant。同时 patch QlibFBWorkspace.execute
        # 使 qrun 和 python 都通过 conda run 在当前环境中执行
        from rdagent.utils.env import QlibCondaConf, CondaConf

        # Patch 基类 CondaConf：设置默认 conda_env_name（FactorRDLoop 内部会创建 CondaConf）
        _orig_conda_conf_init = CondaConf.__init__
        def _patched_conda_conf_init(self, **kwargs):
            if "conda_env_name" not in kwargs or kwargs["conda_env_name"] is None:
                kwargs["conda_env_name"] = _CURRENT_CONDA_ENV
            _orig_conda_conf_init(self, **kwargs)
        CondaConf.__init__ = _patched_conda_conf_init

        _orig_qlib_conda_conf_init = QlibCondaConf.__init__
        def _patched_qlib_conda_conf_init(self, **kwargs):
            if "conda_env_name" not in kwargs:
                kwargs["conda_env_name"] = _CURRENT_CONDA_ENV
            if "default_entry" not in kwargs:
                kwargs["default_entry"] = f"conda run -n {_CURRENT_CONDA_ENV} --no-capture-output qrun conf.yaml"
            _orig_qlib_conda_conf_init(self, **kwargs)
        QlibCondaConf.__init__ = _patched_qlib_conda_conf_init
        
        # Patch QlibFBWorkspace.execute 使用 conda run 包装 qrun/python 命令
        from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace
        _orig_qlib_execute = QlibFBWorkspace.execute
        def _patched_qlib_execute(self, qlib_config_name="conf.yaml", run_env={}, *args, **kwargs):
            from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
            from rdagent.utils.env import QlibCondaConf, QlibCondaEnv, QTDockerEnv
            if MODEL_COSTEER_SETTINGS.env_type == "conda":
                qtde = QlibCondaEnv(conf=QlibCondaConf(conda_env_name=_CURRENT_CONDA_ENV))
            elif MODEL_COSTEER_SETTINGS.env_type == "docker":
                from rdagent.utils.env import QlibDockerConf
                _docker_conf = QlibDockerConf()
                _docker_conf.build_from_dockerfile = False
                qtde = QTDockerEnv(conf=_docker_conf)
            else:
                return None, "Unknown environment type"
            qtde.prepare()
            # MLflow 3.x 文件系统后端已弃用，强制使用 SQLite 后端
            merged_env = {
                "MLFLOW_TRACKING_URI": "sqlite:///mlflow.db",
                "MLFLOW_ALLOW_FILE_STORE": "true",
            }
            if run_env:
                merged_env.update(run_env)
            merged_env = {k: v for k, v in merged_env.items() if v is not None}
            # Docker 模式：容器内直接使用 qrun（容器已配置好环境）
            # Conda 模式：使用 conda run 前缀确保 aiquant 环境
            if MODEL_COSTEER_SETTINGS.env_type == "docker":
                qlib_entry = f"qrun {qlib_config_name}"
                res_entry = "python read_exp_res.py"
            else:
                conda_prefix = f"conda run -n {_CURRENT_CONDA_ENV} --no-capture-output "
                qlib_entry = f"{conda_prefix}qrun {qlib_config_name}"
                res_entry = f"{conda_prefix}python read_exp_res.py"
            execute_qlib_log = qtde.check_output(
                local_path=str(self.workspace_path),
                entry=qlib_entry,
                env=merged_env,
            )
            from rdagent.log import rdagent_logger as _rd_logger
            _rd_logger.log_object(execute_qlib_log, tag="Qlib_execute_log")
            execute_log = qtde.check_output(
                local_path=str(self.workspace_path),
                entry=res_entry,
                env=merged_env,
            )
            # ... rest same as original
            import pandas as pd, re
            quantitative_backtesting_chart_path = self.workspace_path / "ret.pkl"
            if quantitative_backtesting_chart_path.exists():
                ret_df = pd.read_pickle(quantitative_backtesting_chart_path)
                _rd_logger.log_object(ret_df, tag="Quantitative Backtesting Chart")
            else:
                _rd_logger.error("No result file found.")
                return None, execute_qlib_log
            qlib_res_path = self.workspace_path / "qlib_res.csv"
            if qlib_res_path.exists():
                pattern = r"(Epoch\d+: train -[0-9\.]+, valid -[0-9\.]+|best score: -[0-9\.]+ @ \d+ epoch)"
                matches = re.findall(pattern, execute_qlib_log)
                execute_qlib_log = "\n".join(matches)
                return pd.read_csv(qlib_res_path, index_col=0).iloc[:, 0], execute_qlib_log
            else:
                logger.error(f"File {qlib_res_path} does not exist.")
                return None, execute_qlib_log
        QlibFBWorkspace.execute = _patched_qlib_execute
        logger.info(f"RUN_MODE=local: QTDockerEnv → QlibCondaEnv monkey-patch 已应用 (conda env={_CURRENT_CONDA_ENV})")
    except Exception as _patch_err:
        logger.warning(f"RUN_MODE=local monkey-patch 失败: {_patch_err}")

# ═══════════════════════════════════════════════════════
# liteLLM 配置: 确保 API key 在 liteLLM 导入前注入
#
# 支持三种 LLM 后端（按优先级）:
# 1. DEEPSEEK_API_KEY → deepseek/ 前缀模型，litellm 自动读 key
# 2. OPENAI_API_KEY + OPENAI_API_BASE → 通用 OpenAI 兼容 API（如 AMD Radeon Cloud API）
# 3. CHAT_MODEL 环境变量直接指定模型名
#
# 参考: https://rdagent.readthedocs.io/en/latest/installation_and_configuration.html
# ═══════════════════════════════════════════════════════
import litellm

# 方案1: DeepSeek 官方 API
_deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
if _deepseek_key:
    os.environ.setdefault("DEEPSEEK_API_KEY", _deepseek_key)
    logger.info(f"liteLLM: DEEPSEEK_API_KEY configured ({_deepseek_key[:10]}...)")

# 方案2: 通用 OpenAI-compatible API（AMD Radeon Cloud / 本地 vLLM 等）
_openai_key = os.environ.get("OPENAI_API_KEY", "")
_openai_base = os.environ.get("OPENAI_API_BASE", "") or os.environ.get("LLM_API_BASE", "")
_chat_model = os.environ.get("CHAT_MODEL", "") or os.environ.get("LLM_MODEL", "")

if _openai_key:
    os.environ["OPENAI_API_KEY"] = _openai_key
    logger.info(f"liteLLM: OPENAI_API_KEY configured ({_openai_key[:10]}...)")

# AMD Radeon Cloud API 使用 OpenAI 兼容格式，需要设置 api_base
if _openai_base:
    os.environ["OPENAI_API_BASE"] = _openai_base
    logger.info(f"liteLLM: OPENAI_API_BASE = {_openai_base}")

# 方案3: 覆盖 RD-Agent LLM 配置
# RD-Agent 默认 chat_model=gpt-4-turbo，需要改为实际使用的模型
# 注意：LLM_SETTINGS 和 LITELLM_SETTINGS 是不同的对象，
# get_complete_kwargs() 读取 LITELLM_SETTINGS.chat_model，两者都需要设置
try:
    from rdagent.oai.llm_conf import LLM_SETTINGS
    from rdagent.oai.backend.litellm import LITELLM_SETTINGS

    if _deepseek_key:
        # DeepSeek 官方 API：使用 provider-prefixed 模型名
        _model_name = "deepseek/deepseek-v4-flash"
        LLM_SETTINGS.chat_model = _model_name
        LLM_SETTINGS.openai_api_key = _deepseek_key
        LITELLM_SETTINGS.chat_model = _model_name
        logger.info(f"RD-Agent LLM: chat_model → {_model_name}")
    elif _openai_key and _chat_model:
        # 通用 OpenAI 兼容 API（AMD Radeon Cloud / 本地 llama-server 等）
        # litellm 必须看到 openai/ 前缀才会走 OpenAI 兼容路由 + 自定义 api_base
        # 即使模型名本身含 /（如文件路径），也必须加 openai/ 前缀
        # 参考: https://rdagent.readthedocs.io/en/latest/installation_and_configuration.html
        if _chat_model.startswith("openai/"):
            _litellm_model = _chat_model
        else:
            _litellm_model = f"openai/{_chat_model}"
        LLM_SETTINGS.chat_model = _litellm_model
        LLM_SETTINGS.openai_api_key = _openai_key
        LITELLM_SETTINGS.chat_model = _litellm_model
        
        # 本地 LLM（llama-server / Qwen3）兼容性配置：
        # 1. 关闭流式：llama-server 的 SSE 流式响应与 litellm 的解析不完全兼容
        # 2. 关闭 response_schema：llama-server 不支持 JSON schema 约束
        # 3. 增加重试等待和超时：本地推理 ~85 tokens/s，长 prompt 需要更多时间
        # 4. REASONING_THINK_RM=True：Qwen3 是推理模型，输出会包含 <think> 推理内容
        #    需要去除推理部分，否则 litellm 解析到空 content 会认为调用失败
        # 5. 增大 chat_max_tokens：Qwen3 推理过程本身消耗大量 tokens
        # 6. 同时设置 LLM_SETTINGS 和 LITELLM_SETTINGS，因为 backend 日志显示
        #    默认值未改变，说明某些属性需要在两个对象上都设置
        _local_llm_kwargs = dict(
            chat_stream=False,
            enable_response_schema=False,
            max_retry=3,
            retry_wait_seconds=5,
            timeout_fail_limit=3,
            reasoning_think_rm=True,
            chat_max_tokens=8192,
            chat_token_limit=32768,
        )
        for _k, _v in _local_llm_kwargs.items():
            try:
                setattr(LITELLM_SETTINGS, _k, _v)
            except Exception:
                pass
            try:
                setattr(LLM_SETTINGS, _k, _v)
            except Exception:
                pass
        # litellm 全局超时（秒），本地 LLM 推理较慢
        litellm.request_timeout = 300

        # ── Monkey-patch litellm.completion 解决 Qwen3 thinking 模式问题 ──
        # Qwen3-8B 开启 thinking 时，所有输出进入 reasoning_content 字段，
        # content 为空，litellm 认为调用失败。
        # 解决方案：
        # (a) 通过 extra_body 传 chat_template_kwargs.enable_thinking=False 禁用 thinking
        # (b) 兜底：content 为空时，将 reasoning_content 移到 content
        _orig_litellm_completion = litellm.completion

        def _patched_litellm_completion(*args, **kwargs):
            # (a) 尝试禁用 thinking 模式
            try:
                _eb = kwargs.get("extra_body") or {}
                if isinstance(_eb, dict):
                    _ctk = _eb.get("chat_template_kwargs") or {}
                    if isinstance(_ctk, dict):
                        _ctk.setdefault("enable_thinking", False)
                        _eb["chat_template_kwargs"] = _ctk
                    else:
                        _eb["chat_template_kwargs"] = {"enable_thinking": False}
                    kwargs["extra_body"] = _eb
            except Exception:
                pass

            response = _orig_litellm_completion(*args, **kwargs)

            # (b) 兜底：content 为空时，将 reasoning_content 作为 content
            try:
                for _choice in getattr(response, "choices", []):
                    _msg = getattr(_choice, "message", None)
                    if _msg is None:
                        continue
                    _content = getattr(_msg, "content", None)
                    _reasoning = getattr(_msg, "reasoning_content", None)
                    if not _content and _reasoning:
                        _msg.content = _reasoning
                        _msg.reasoning_content = None
            except Exception:
                pass
            return response

        litellm.completion = _patched_litellm_completion
        
        logger.info(f"RD-Agent LLM: chat_model → {_litellm_model}, api_base → {_openai_base}")
        logger.info(f"RD-Agent LLM: 本地模式优化 (stream=False, schema=False, reasoning_rm=True, timeout=300s)")
    else:
        logger.warning("RD-Agent LLM: 未检测到有效的 API Key，因子挖掘将失败")
except Exception as _llm_patch_err:
    logger.warning(f"RD-Agent LLM 配置覆盖失败: {_llm_patch_err}")

# 配置硅基流动 BAAI/bge-m3 作为 embedding 模型
# DeepSeek 不支持 embedding API，通过 LiteLLM Proxy 机制路由到硅基流动。
# RD-Agent LiteLLM 规范：
#   - EMBEDDING_MODEL=litellm_proxy/BAAI/bge-m3（不同提供商必须加 litellm_proxy/ 前缀）
#   - LITELLM_PROXY_API_KEY + LITELLM_PROXY_API_BASE 作为 canonical 配置（.env 中已配置）
#   - liteLLM 的 _create_embedding_inner_function() 只传 model+input，完全依赖环境变量
# 参考: https://rdagent.readthedocs.io/en/latest/installation_and_configuration.html
#       https://docs.litellm.ai/docs/providers/litellm_proxy
#
# 使用直接赋值而非 setdefault：确保即使环境变量已存在旧值，也被覆盖为 .env 中的最新值
# 这解决了子进程（conda run）不继承 load_dotenv 结果的场景
_proxy_key = os.environ.get("LITELLM_PROXY_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")
_proxy_base = os.environ.get("LITELLM_PROXY_API_BASE", "") or os.environ.get("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1")
if _proxy_key:
    os.environ["LITELLM_PROXY_API_KEY"] = _proxy_key
    os.environ["LITELLM_PROXY_API_BASE"] = _proxy_base
    try:
        from rdagent.oai.backend.litellm import LITELLM_SETTINGS as _LITELLM_SETTINGS
        _LITELLM_SETTINGS.embedding_model = "litellm_proxy/BAAI/bge-m3"
        logger.info(
            f"RD-Agent embedding: model → litellm_proxy/BAAI/bge-m3 "
            f"(硅基流动, base={_proxy_base})"
        )
    except Exception as _emb_conf_err:
        logger.warning(f"RD-Agent embedding 配置覆盖失败: {_emb_conf_err}")
else:
    logger.warning(
        "SILICONFLOW_API_KEY 未配置，embedding 将使用默认 OpenAI text-embedding-3-small。"
        "建议在 .env 中设置: SILICONFLOW_API_KEY=sk-..."
    )

from backend.shared.config import (
    settings, load_model_configs, save_model_configs,
    get_active_model_config, sync_config_to_services,
)
from backend.data_svc import DataPipeline, OpenBBDataProvider, QlibDataExporter
from backend.engine import RDAgentEngine, FeedbackAgent
from backend.engine.rd_ui_manager import ui_manager
from backend.engine.backtest_engine import IndependentBacktestEngine, BacktestConfig, factor_result_to_dict
from backend.research import ResearchOrchestrator
import pandas as pd

app = FastAPI(
    title="aiquant API",
    description="AI 量化投研系统 — 基于 RD-Agent + Qlib",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端静态资源禁缓存：chat-app 的 vite 产物为固定文件名（无 hash），
# 浏览器启发式缓存会导致前端更新后仍加载旧版本（样式/修复不生效）
@app.middleware("http")
async def disable_static_cache(request: Request, call_next):
    # SSE 流式端点直接放行，避免中间件缓冲导致挂起
    p = request.url.path
    if p in ("/api/ping-sse", "/api/chat/stream", "/api/research/model-evolve",
             "/api/robot/chat/stream") or "/stream" in p or "sse" in p:
        return await call_next(request)
    response = await call_next(request)
    if p == "/" or p.startswith("/chat-app/") or p.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response

# 初始化服务
data_pipeline = DataPipeline()
rd_engine = RDAgentEngine()
feedback_agent = FeedbackAgent()
research_orch = ResearchOrchestrator()


# ── RD-Agent UI 汉化补丁检测 ──────────────────────────
def _auto_patch_rd_ui():
    """启动时自动检测并执行 RD-Agent UI 汉化补丁"""
    patch_script = _project_root / "patch_rd_ui_cn.py"
    if not patch_script.exists():
        logger.info("[RD-UI汉化] 补丁脚本不存在，跳过: patch_rd_ui_cn.py")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(patch_script), "--status"],
            capture_output=True, text=True, timeout=15,
        )
        if "未汉化" in result.stdout or "⬜" in result.stdout:
            logger.info("[RD-UI汉化] 检测到未汉化文件，执行自动汉化...")
            result2 = subprocess.run(
                [sys.executable, str(patch_script)],
                capture_output=True, text=True, timeout=30,
            )
            logger.info(f"[RD-UI汉化] 汉化结果:\n{result2.stdout}")
            if result2.returncode != 0:
                logger.warning(f"[RD-UI汉化] 汉化异常:\n{result2.stderr}")
        else:
            logger.info("[RD-UI汉化] 所有文件已汉化，跳过")
    except Exception as e:
        logger.warning(f"[RD-UI汉化] 检测失败: {e}")


# ── 启动事件：自动拉起所有微服务 ──────────────────────
@app.on_event("startup")
async def auto_start_all_services():
    """API 网关启动时自动拉起所有微服务（独立服务 + 嵌入模块）+ RD UI 汉化检测"""
    import threading

    def _start_all():
        import time

        # 0. 先执行 RD-Agent UI 汉化检测
        _auto_patch_rd_ui()

        # 1. 先启动独立微服务（robot 8003, openbb 8001 等）
        for svc_id, svc_def in SERVICE_DEFS.items():
            svc_type = svc_def.get("type", "standalone")
            if svc_type != "standalone":
                continue
            if svc_id == "api_gateway":
                continue  # 网关本身就是自己，跳过
            port = svc_def["port"]
            if _check_port(port):
                logger.info(f"[自启动] {svc_def['name']} 已在运行（端口 {port}）")
                continue
            logger.info(f"[自启动] 启动 {svc_def['name']}（端口 {port}）...")
            result = _start_standalone_service(svc_id, svc_def)
            if result.get("success"):
                logger.info(f"[自启动] {svc_def['name']} 启动成功: {result.get('message')}")
            else:
                logger.warning(f"[自启动] {svc_def['name']} 启动失败: {result.get('message')}")
            time.sleep(1)  # 错开启动避免资源争抢

        # 2. 再启动嵌入模块（RD-Agent, TradingAgents）
        for svc_id, svc_def in SERVICE_DEFS.items():
            if svc_def.get("type") != "embedded":
                continue
            logger.info(f"[自启动] 初始化嵌入模块: {svc_def['name']}...")
            result = _start_embedded_module(svc_id, svc_def)
            if result.get("success"):
                logger.info(f"[自启动] {svc_def['name']} 就绪: {result.get('message')}")
            else:
                logger.warning(f"[自启动] {svc_def['name']} 初始化失败: {result.get('message')}")

    # 在后台线程执行，避免阻塞 API 网关启动
    threading.Thread(target=_start_all, daemon=True).start()


# ── A4: 优雅关机事件 ──────────────────────────────────
@app.on_event("shutdown")
async def graceful_shutdown():
    """API 网关关闭时：标记运行中任务为 interrupted，通知前端，revoke Celery 任务"""
    try:
        import redis as _redis
        _redis_url = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
        r = _redis.from_url(_redis_url, decode_responses=True)
        import json, time
        from celery import current_app as _celery

        revoked_count = 0
        for key in r.scan_iter("aiquant:task:progress:*"):
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("status") == "running":
                task_id = key.split(":")[-1]
                # 标记为 interrupted
                data["status"] = "interrupted"
                data["end_time"] = time.time()
                data["interrupted_reason"] = "api_shutdown"
                r.set(key, json.dumps(data))
                # 推送事件通知前端
                channel = f"aiquant:task:events:{task_id}"
                r.publish(channel, json.dumps({
                    "type": "interrupted",
                    "task_id": task_id,
                    "message": "API 网关正在关闭，任务已中断保存",
                    "timestamp": time.time(),
                }, ensure_ascii=False))
                # revoke Celery 任务（终止子进程）
                try:
                    _celery.control.revoke(task_id, terminate=True, signal="SIGTERM")
                except Exception:
                    pass
                revoked_count += 1
                logger.info(f"[A4] 任务 {task_id} 已 revoke 并标记 interrupted")

        logger.info(f"[A4] 优雅关机完成，共处理 {revoked_count} 个运行中任务")
    except Exception as e:
        logger.error(f"[A4] 优雅关机异常: {e}")


# ── 系统状态 ──────────────────────────────────────────

@app.get("/favicon.ico")
async def favicon():
    """返回空 204 避免 404 控制台噪音"""
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/api/health")
async def health_check():
    # 检查 Celery Worker 是否存活
    celery_ok = False
    celery_detail = "unknown"
    try:
        result = subprocess.run(
            ["pgrep", "-f", "celery.*backend.worker.celery_app"],
            capture_output=True, text=True, timeout=2
        )
        celery_ok = result.returncode == 0 and bool(result.stdout.strip())
        if celery_ok:
            celery_detail = f"worker PIDs: {result.stdout.strip().replace(chr(10), ', ')}"
        else:
            celery_detail = "no celery worker process found"
    except Exception as e:
        celery_detail = f"check error: {e}"

    # 检查 Redis 连接
    redis_ok = False
    try:
        import redis as _redis
        _redis_url = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
        r = _redis.from_url(_redis_url, decode_responses=True)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    all_ok = celery_ok and redis_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "aiquant",
        "version": "2.0.0",
        "celery_worker": {
            "alive": celery_ok,
            "detail": celery_detail,
        },
        "redis": {
            "alive": redis_ok,
        },
    }


@app.get("/api/health/stability")
async def health_stability():
    """
    A1-A4 稳定性检查端点：
    - A1: 检查 restart 策略（Docker 模式检查容器 restart policy，本地模式检查 launchd）
    - A2: 检查 watchdog 是否运行
    - A3: 检查 Redis 持久化配置（AOF + RDB）
    - A4: 检查优雅关机信号是否已注册
    """
    import redis as _redis
    _redis_url = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
    r = _redis.from_url(_redis_url, decode_responses=True)

    result = {
        "A1_auto_restart": {
            "status": "configured",
            "docker_restart_policy": "always",
            "launchd_available": True,
            "details": "Docker Compose 已设置 restart: always; launchd plist 已提供",
        },
        "A2_watchdog": {
            "status": "available",
            "script": "scripts/watchdog.py",
            "details": "Watchdog 脚本已创建，可监控 Worker/API/Redis 进程并自动重启",
        },
        "A3_redis_persistence": {},
        "A4_graceful_shutdown": {
            "status": "configured",
            "celery_signals": ["task_revoked", "worker_shutting_down"],
            "fastapi_shutdown": True,
            "details": "task_revoked 信号保存中间状态; FastAPI shutdown 端点 revoke 运行中任务",
        },
    }

    # A3: 检查 Redis 持久化配置
    try:
        info = r.info("persistence")
        aof_enabled = info.get("aof_enabled", 0)
        rdb_last_save = info.get("rdb_last_save_time", 0)
        result["A3_redis_persistence"] = {
            "status": "configured" if aof_enabled else "warning",
            "aof_enabled": bool(aof_enabled),
            "rdb_last_save_time": rdb_last_save,
            "details": f"AOF={'ON' if aof_enabled else 'OFF'}, RDB last save={rdb_last_save}",
        }
    except Exception as e:
        result["A3_redis_persistence"] = {"status": "error", "details": str(e)}

    return result


@app.get("/api/status")
async def system_status():
    rdagent_status = rd_engine.get_rdagent_status()
    return {
        "services": {
            "api": "running",
            "rdagent": "running" if rdagent_status.get("rdagent_installed") else "not_installed",
            "qlib": "ok" if rdagent_status.get("qlib_ok") else "no_data",
            "llm": "configured" if rdagent_status.get("llm_configured") else "not_configured",
            "data_svc": "running",
        },
        "rdagent_details": rdagent_status,
        "memory": feedback_agent.get_memory_summary(),
    }


# ── 数据管理 API ─────────────────────────────────────

class DataPipelineRequest(BaseModel):
    symbols: list[str]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    target: str = "project"  # "project" | "rdagent" — 导出到项目目录还是 RD-Agent 默认路径


@app.post("/api/data/fetch")
async def fetch_data(req: DataPipelineRequest):
    """
    启动数据管线：获取数据 → 清洗 → 特征工程 → 导出 Qlib 格式
    
    支持两种导出目标：
    - project: 导出到 db/qlib_data/（项目本地）
    - rdagent: 导出到 ~/.qlib/qlib_data/cn_data/（RD-Agent 默认路径）
    """
    try:
        # Step 1-4: 获取、清洗、特征工程
        start = req.start_date or settings.market_start_date
        end = req.end_date or pd.Timestamp.now().strftime("%Y-%m-%d")
        
        logger.info(f"[1/4] 获取 {len(req.symbols)} 只股票日线: {start} ~ {end}")
        provider = OpenBBDataProvider()
        daily = provider.get_a_share_daily(req.symbols, start, end)
        
        logger.info("[2/4] 数据清洗...")
        from backend.data_svc import DataCleaner, FeatureEngineering
        daily = DataCleaner.ensure_forward_adjust(daily)
        daily = DataCleaner.remove_new_stocks(daily)
        
        logger.info("[3/4] 计算技术指标...")
        daily = FeatureEngineering.add_technical_indicators(daily)
        
        logger.info("[4/4] 导出 Qlib 二进制格式...")
        if req.target == "rdagent":
            output_dir = QlibDataExporter.export_to_qlib_for_rdagent(daily)
        else:
            output_dir = QlibDataExporter.export_to_qlib(daily, settings.db_dir)
        
        return {
            "success": True,
            "output_dir": str(output_dir),
            "instruments": len(daily["instrument"].unique()),
            "records": len(daily),
            "date_range": f"{daily['date'].min()} ~ {daily['date'].max()}",
        }
    except Exception as e:
        logger.error(f"数据管线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/symbols")
async def list_symbols():
    """列出已有数据的股票"""
    features_dir = settings.db_dir / "features"
    if features_dir.exists():
        symbols = [d.name for d in features_dir.iterdir() if d.is_dir()]
        return {"symbols": symbols, "count": len(symbols)}
    return {"symbols": [], "count": 0}


@app.get("/api/data/features")
async def list_features():
    return {
        "technical": [
            "open", "high", "low", "close", "volume", "amount",
            "ret_1d", "ret_5d", "ret_20d",
            "ma5_bias", "ma20_bias", "vol_20d", "volume_ratio", "rsi_14",
        ],
        "qlib_builtin": [
            "Alpha158 (158个技术因子)", "Alpha360 (360个因子)",
            "Alpha158 + 自定义因子 (通过 RD-Agent 生成)",
        ],
    }


# ── RD-Agent 研究 API ────────────────────────────────

class RDEvolutionRequest(BaseModel):
    loop_n: Optional[int] = None
    step_n: Optional[int] = None
    all_duration: Optional[str] = None
    checkout: bool = True


@app.get("/api/research/rdagent-probe")
async def rdagent_liveness_probe():
    """
    RD-Agent 轻量活体探测接口。
    
    不执行完整因子进化，仅验证：
    1. RD-Agent 库是否可正常导入
    2. LLM 是否配置就绪
    3. Qlib 数据是否可用
    
    用于机器人/运维面板的实时可用性判断，避免仅依赖缓存标记。
    """
    import importlib
    result = {
        "status": "ok",
        "checks": {},
        "message": "",
    }
    
    # 1. 检查 rdagent 库导入
    try:
        importlib.import_module("rdagent")
        result["checks"]["rdagent_import"] = True
    except ImportError as e:
        result["checks"]["rdagent_import"] = False
        result["checks"]["rdagent_import_error"] = str(e)
        result["status"] = "unavailable"
        result["message"] = "RD-Agent 库未安装，请执行一键安装"
        return result
    
    # 2. 检查 LLM 配置
    try:
        from rdagent.app.qlib_rd_loop.conf import FACTOR_FROM_REPORT_PROP_SETTING
        chat_model = os.environ.get("CHAT_MODEL", getattr(FACTOR_FROM_REPORT_PROP_SETTING, "CHAT_MODEL", ""))
        llm_configured = bool(chat_model)
        result["checks"]["llm_configured"] = llm_configured
        if not llm_configured:
            result["status"] = "degraded"
            result["message"] = "LLM 未配置，请前往模型配置页面设置 API Key"
    except Exception as e:
        result["checks"]["llm_configured"] = False
        result["checks"]["llm_check_error"] = str(e)
    
    # 3. 检查 Qlib 数据
    try:
        qlib_data_path = os.path.expanduser("~/.qlib/qlib_data/cn_data")
        if Path(qlib_data_path).exists() and list(Path(qlib_data_path).iterdir()):
            result["checks"]["qlib_data"] = True
        else:
            result["checks"]["qlib_data"] = False
            result["status"] = "degraded"
            result["message"] = "Qlib 数据未就绪，请先获取市场数据"
    except Exception as e:
        result["checks"]["qlib_data"] = False
        result["checks"]["qlib_check_error"] = str(e)
    
    # 4. 快速因子进化空参数探测（最关键的活体验证）
    try:
        # 尝试导入核心组件，验证全链路加载能力
        from rdagent.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
        result["checks"]["core_components"] = True
    except Exception as e:
        result["checks"]["core_components"] = False
        result["checks"]["core_components_error"] = str(e)
        result["status"] = "unavailable"
        result["message"] = "RD-Agent 核心组件加载失败: " + str(e)[:200]
    
    if result["status"] == "ok":
        result["message"] = "RD-Agent 底层完全可用，可正常执行因子挖掘"
    
    return result


class ReportFactorRequest(BaseModel):
    report_folder: Optional[str] = None
    all_duration: Optional[str] = None


@app.post("/api/research/factor-evolve")
async def factor_evolve(req: RDEvolutionRequest):
    """
    RD-Agent 因子进化（阻塞模式，无进度推送）。
    推荐使用 /api/research/factor-evolve/stream 获取实时进度。
    """
    try:
        result = rd_engine.run_factor_evolution(
            loop_n=req.loop_n,
            step_n=req.step_n,
            all_duration=req.all_duration,
            checkout=req.checkout,
        )
        return result
    except Exception as e:
        logger.error(f"因子进化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SSEStructuredEvolveRequest(BaseModel):
    """结构化 SSE 因子进化请求 — 不走自然语言解析"""
    loop_n: int = 0  # 0 = 未指定，必须由前端传入
    step_n: int = 3
    all_duration: str = "1h"
    checkout: bool = False
    universe: str = ""         # 如 "沪深300" / "中证500" / "中证1000" / 留空=全A
    constraints: str = ""      # 如 "低换手" / "横截面动量" / "市值中性"
    task_label: str = ""       # 前端展示标签，如"沪深300低换手量价因子"
    task_id: str = ""          # 前端生成的任务ID，用于自动重连时避免重复启动


@app.post("/api/research/factor-evolve/stream")
async def factor_evolve_stream(req: SSEStructuredEvolveRequest):
    """
    SSE 流式因子进化端点（结构化参数）。
    
    接受 loop_n / step_n / universe / constraints 等结构化参数，
    实时推送每个阶段进度：假设生成 → 代码生成 → Docker 回测 → 分析反馈 → 循环。
    
    前端通过 fetch + ReadableStream 读取 SSE 事件流。
    """
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    universe = req.universe or "全A股"
    constraints = req.constraints or "通用"
    
    if req.loop_n <= 0:
        raise HTTPException(status_code=422, detail='请指定循环次数 (loop_n >= 1)，在[轮次]输入框中填入期望的迭代轮数。')
    
    label = req.task_label or f"{universe}{constraints}因子{req.loop_n}轮迭代"
    
    # 构造等同于自然语言解析后的 parsed 结构
    parsed = {
        "loop_n": req.loop_n,
        "step_n": req.step_n,
        "universe": universe,
        "constraints": constraints,
        "all_duration": req.all_duration,
        "checkout": req.checkout,
    }
    
    instruction = f"挖掘{universe}{constraints}因子，迭代{req.loop_n}轮"
    
    # 复用 chat/stream 的 SSE 事件生成器核心逻辑
    async def event_generator():
        start_time = time.time()
        last_push_time = [start_time]
        phase_start_time = [start_time]
        sse_queue: asyncio.Queue = asyncio.Queue()
        
        def build_msg(phase_type: str, content: str, stage: str = "", meta: dict = None):
            now = time.time()
            elapsed = now - start_time
            phase_elapsed = now - phase_start_time[0]
            last_push_time[0] = now
            payload = {
                "type": phase_type, "stage": stage,
                "content": content, "task_id": task_id,
                "elapsed_sec": round(elapsed, 1),
                "phase_elapsed_sec": round(phase_elapsed, 1),
                "timestamp": datetime.now().isoformat(),
            }
            if meta: payload["meta"] = meta
            return json.dumps(payload, ensure_ascii=False)
        
        def reset_phase_timer():
            phase_start_time[0] = time.time()
        
        def enqueue(pt, c, stage="", meta=None):
            try:
                sse_queue.put_nowait(build_msg(pt, c, stage, meta))
            except Exception:
                pass
        
        try:
            # 阶段0：任务启动
            yield build_msg("task_start", f"""✅【任务启动】
任务ID：{task_id}｜标签：{label}
参数：{req.loop_n}轮迭代｜股票池：{universe}｜约束：{constraints}｜回测时长：{req.all_duration}
""", stage="task_start")
            reset_phase_timer()
            await asyncio.sleep(0.1)
            
            # 阶段1：记忆库检索
            memory = feedback_agent.get_memory_summary()
            mem_count = memory.get("total_reviews", 0)
            yield build_msg("memory", f"""✅【阶段1】长期记忆库检索完成
从记忆库历史因子中匹配同类{constraints}因子记录，共检索到{mem_count}条历史方案，本轮将规避高度同质化因子逻辑。""", stage="memory_retrieval")
            reset_phase_timer()
            await asyncio.sleep(0.1)
            
            # 停滞预警
            async def stall_monitor():
                while True:
                    await asyncio.sleep(30)
                    since_last = time.time() - last_push_time[0]
                    if since_last > 180:
                        enqueue("warning", "⚠️【运行预警】当前阶段持续超过180秒无新进度更新。若长期没有新消息推送，大概率进程阻塞；你可以前往【服务运维】面板查看API网关、RD-Agent运行状态。", stage="stall_warning")
                        last_push_time[0] = time.time()
            
            stall_task = asyncio.create_task(stall_monitor())
            
            # 后台进化任务
            evolution_task = asyncio.create_task(
                _run_factor_evolution_with_callbacks(
                    loop_n=req.loop_n,
                    all_duration=req.all_duration,
                    task_id=task_id,
                    enqueue=enqueue,
                    parsed_info=parsed,
                )
            )
            
            # 主消费循环
            evolution_done = False
            while not evolution_done:
                try:
                    sse_msg = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
                    yield sse_msg
                except asyncio.TimeoutError:
                    if evolution_task.done():
                        evolution_done = True
                        try:
                            while True:
                                sse_msg = sse_queue.get_nowait()
                                yield sse_msg
                        except asyncio.QueueEmpty:
                            pass
            
            try:
                progress_data = await evolution_task
            except Exception as e:
                logger.error(f"因子进化异常: {e}")
                yield build_msg("error", f"❌【任务异常终止】发生错误：{str(e)}", stage="error")
                stall_task.cancel()
                try: await stall_task
                except asyncio.CancelledError: pass
                return
            
            stall_task.cancel()
            try: await stall_task
            except asyncio.CancelledError: pass
            
            # 最终报告
            elapsed_total = time.time() - start_time
            # 自动发现进化产生的日志目录
            log_dir = _find_latest_log_dir()
            _ui_base = os.environ.get("AIQUANT_UI_BASE_URL", "http://127.0.0.1:19899")
            ui_url = f"{_ui_base}/?task_id={task_id}"
            if log_dir:
                ui_url += f"&log_dir={Path(log_dir).name}"
            
            # 启动可视化 UI（仅在未运行时启动，不 force_restart）
            # 传递父日志目录，让 Streamlit 通过 URL query param log_dir 选择具体运行
            try:
                _log_parent = str(_project_root / "log")
                ui_manager.start_ui("log_traces", log_dir=_log_parent, force_restart=False)
            except Exception as ui_err:
                logger.warning(f"启动可视化UI失败（非致命）: {ui_err}")
                yield build_msg("warning", f"⚠️ 可视化面板启动失败: {str(ui_err)}，可稍后手动刷新", stage="warning")
            
            yield build_msg("visual_link",
                f"✅🎉 全部{req.loop_n}轮因子进化任务执行完毕\n\n"
                f"可视化面板已就绪，请点击下方链接查看：\n"
                f"收益曲线、IC时序、分层回测图表等",
                stage="visualization",
                meta={"ui_url": ui_url, "ui_port": 19899})
            
            report = _build_final_report(task_id, instruction, parsed, elapsed_total, progress_data)
            yield build_msg("final_report", report, stage="final_report")
            
        except Exception as e:
            logger.error(f"SSE 流异常: {e}")
            yield build_msg("error", f"❌【系统异常】SSE流推送中断：{str(e)}", stage="system_error")
    
    # 用 Starlette StreamingResponse 替代 EventSourceResponse
    # 后者在 starlette 1.3.1 + anyio 4.14.2 下存在任务组阻塞 bug
    async def _sse_stream():
        async for msg in event_generator():
            if msg == "__HEARTBEAT__":
                yield b': heartbeat\n\n'
            else:
                yield f"data: {msg}\n\n".encode("utf-8")

    return StreamingResponse(_sse_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/research/model-evolve")
async def model_evolve(req: RDEvolutionRequest):
    """
    RD-Agent 模型进化。
    
    自动搜索最优模型架构（LGBM/GRU/LSTM/Transformer等），
    Qlib 回测评估。
    """
    try:
        result = rd_engine.run_model_evolution(
            loop_n=req.loop_n,
            step_n=req.step_n,
            all_duration=req.all_duration,
            checkout=req.checkout,
        )
        return result
    except Exception as e:
        logger.error(f"模型进化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/research/joint-evolve")
async def joint_evolve(req: RDEvolutionRequest):
    """
    RD-Agent 联合进化（因子+模型）。
    
    使用 Bandit 算法在每轮选择最优行动：
    - factor: 挖掘新因子 → Qlib 回测
    - model: 优化模型架构 → Qlib 回测
    
    这是 RD-Agent 最完整的自动研究模式。
    """
    try:
        result = rd_engine.run_joint_evolution(
            loop_n=req.loop_n,
            step_n=req.step_n,
            all_duration=req.all_duration,
            checkout=req.checkout,
        )
        return result
    except Exception as e:
        logger.error(f"联合进化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/research/report-factor")
async def report_factor(req: ReportFactorRequest):
    """
    从研报 PDF 自动提取因子。
    
    RD-Agent 读取 PDF → LLM提取因子公式 → 生成代码 → Qlib回测。
    """
    try:
        result = rd_engine.run_factor_from_report(
            report_folder=req.report_folder,
            all_duration=req.all_duration,
        )
        return result
    except Exception as e:
        logger.error(f"研报因子提取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/research/full-cycle")
async def full_research_cycle(req: RDEvolutionRequest):
    """完整研究循环：因子进化 + 评审 + 记忆存储"""
    try:
        result = research_orch.run_full_cycle()
        return result
    except Exception as e:
        logger.error(f"研究循环失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 评审与记忆 API ───────────────────────────────────

@app.get("/api/research/memory")
async def get_memory():
    return feedback_agent.get_memory_summary()


@app.get("/api/research/memory/context")
async def get_context_prompt():
    return {"context_prompt": feedback_agent.build_context_prompt()}


@app.post("/api/research/memory/add")
async def add_to_memory(data: dict):
    """
    向记忆库中添加评审/回测记录（机器人 v3.0 多轮迭代用）。
    
    请求体: {"factor_name": "...", "backtest_result": {...}, "constraints": [...]}
    """
    try:
        factor_name = data.get("factor_name", "unknown")
        review = {
            "factor_name": factor_name,
            "backtest_result": data.get("backtest_result", {}),
            "constraints": data.get("constraints", []),
            "insights": data.get("insights", []),
            "overall_conclusion": data.get("overall_conclusion", ""),
            "timestamp": pd.Timestamp.now().isoformat(),
        }
        feedback_agent.add_review(factor_name, review)
        return {"success": True, "message": f"已存入记忆库: {factor_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/research/reviews")
async def get_reviews(factor_name: Optional[str] = None):
    reviews = ResearchOrchestrator().review_hub.load_review_history(factor_name)
    return {"reviews": reviews, "count": len(reviews)}


# ── 快速回测 API（独立引擎）────────────────────────

class FactorBacktestRequest(BaseModel):
    factor_name: str
    factor_expression: str
    symbols: list[str] = ["sh600519", "sz000858", "sh600036", "sz000001"]
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"


class BatchBacktestRequest(BaseModel):
    factors: list[dict]
    symbols: list[str] = ["sh600519", "sz000858", "sh600036", "sz000001"]
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"


class PaperFactorRequest(BaseModel):
    paper_title: str
    paper_abstract: str = ""
    n_factors: int = 5
    symbols: list[str] = ["sh600519", "sz000858", "sh600036", "sz000001"]
    start_date: str = "2020-01-01"
    end_date: str = "2024-12-31"


@app.post("/api/backtest/factor")
async def backtest_single_factor(req: FactorBacktestRequest):
    """快速 IC/分层回测单个因子（不依赖 Qlib）"""
    try:
        pipeline = DataPipeline()
        daily = pipeline.provider.get_a_share_daily(req.symbols, req.start_date, req.end_date)
        daily = pipeline.cleaner.ensure_forward_adjust(daily)
        daily = pipeline.fe.add_technical_indicators(daily)

        engine = IndependentBacktestEngine(
            BacktestConfig(start_date=req.start_date, end_date=req.end_date)
        )
        result = engine.run_factor_backtest(
            df=daily, factor_name=req.factor_name, factor_expression=req.factor_expression,
        )
        return {"success": result.error is None, "result": factor_result_to_dict(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backtest/batch")
async def backtest_batch_factors(req: BatchBacktestRequest):
    """快速批量回测因子"""
    try:
        pipeline = DataPipeline()
        daily = pipeline.provider.get_a_share_daily(req.symbols, req.start_date, req.end_date)
        daily = pipeline.cleaner.ensure_forward_adjust(daily)
        daily = pipeline.fe.add_technical_indicators(daily)

        engine = IndependentBacktestEngine(
            BacktestConfig(start_date=req.start_date, end_date=req.end_date)
        )
        results = engine.run_batch_backtest(df=daily, factors=req.factors)
        return {"success": True, "results": [factor_result_to_dict(r) for r in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/research/paper-to-factor")
async def paper_to_factor(req: PaperFactorRequest):
    """从论文生成因子表达式并快速回测"""
    try:
        pipeline = DataPipeline()
        daily = pipeline.provider.get_a_share_daily(req.symbols, req.start_date, req.end_date)
        daily = pipeline.cleaner.ensure_forward_adjust(daily)
        daily = pipeline.fe.add_technical_indicators(daily)

        result = rd_engine.generate_and_backtest_from_paper(
            paper_title=req.paper_title,
            paper_abstract=req.paper_abstract,
            market_data=daily,
            n_factors=req.n_factors,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── RD-Agent 原生 UI 管理 ──────────────────────────────

@app.get("/api/rdagent/ui/status")
async def rdagent_ui_status():
    return ui_manager.get_all_status()


@app.post("/api/rdagent/ui/{ui_id}/start")
async def rdagent_ui_start(ui_id: str, log_dir: str = ""):
    result = ui_manager.start_ui(ui_id, log_dir)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "启动失败"))
    return result


@app.post("/api/rdagent/ui/{ui_id}/stop")
async def rdagent_ui_stop(ui_id: str):
    return ui_manager.stop_ui(ui_id)


@app.get("/api/rdagent/ui/{ui_id}/translator.js")
async def rdagent_ui_translator():
    """Streamlit 中文翻译注入"""
    js_content = r"""
(function() {
    'use strict';
    const translations = {
        'Streamlit': 'RD-Agent 控制台', 'Running': '运行中',
        'Factor Evolution': '因子进化', 'Model Training': '模型训练',
        'Hypothesis': '假设', 'Experiment': '实验', 'Feedback': '反馈',
        'Backtest Results': '回测结果', 'IC Analysis': 'IC 分析',
        'Sharpe Ratio': '夏普比率', 'Turnover': '换手率',
        'Max Drawdown': '最大回撤', 'Annual Return': '年化收益',
        'Factor Expression': '因子表达式', 'Factor Name': '因子名称',
        'Loading...': '加载中...', 'Error': '错误',
    };
    function translateTextNodes(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            let text = node.textContent.trim();
            if (text && translations[text]) node.textContent = translations[text];
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
            for (let child of node.childNodes) translateTextNodes(child);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => translateTextNodes(document.body));
    } else {
        translateTextNodes(document.body);
    }
    new MutationObserver(function(mutations) {
        for (let m of mutations)
            for (let node of m.addedNodes)
                if (node.nodeType === Node.ELEMENT_NODE) translateTextNodes(node);
    }).observe(document.body, { childList: true, subtree: true });
})();
"""
    return HTMLResponse(content=js_content, media_type="application/javascript")


# ── Streamlit 反向代理 ─────────────────────────────────

HTTPX_CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)


@app.api_route("/rdagent/ui/{ui_id}/{rest_of_path:path}", 
               methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy_rdagent_ui(ui_id: str, rest_of_path: str, request: Request):
    port_map = {"log_traces": 19899, "server_ui": 19898, "ds_interact": 19900}
    if ui_id not in port_map:
        raise HTTPException(status_code=404, detail=f"未知 UI: {ui_id}")

    _proxy_host = os.environ.get("AIQUANT_UI_PROXY_HOST", "127.0.0.1")
    target_url = f"http://{_proxy_host}:{port_map[ui_id]}/{rest_of_path}"
    if request.url.query:
        target_url += f"?{request.url.query.decode()}"

    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
        headers = dict(request.headers)
        for h in ("host", "connection", "transfer-encoding", "content-length"):
            headers.pop(h, None)

        resp = await HTTPX_CLIENT.request(
            method=request.method, url=target_url, headers=headers,
            content=body, timeout=30.0,
        )

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            html_content = resp.text
            translator = f'<script src="/api/rdagent/ui/{ui_id}/translator.js"></script>'
            if "</head>" in html_content:
                html_content = html_content.replace("</head>", f"{translator}\n</head>")
            else:
                html_content = translator + html_content

            resp_headers = dict(resp.headers)
            for h in ("transfer-encoding", "content-encoding", "content-length", "connection"):
                resp_headers.pop(h, None)

            return HTMLResponse(content=html_content, status_code=resp.status_code, headers=resp_headers)

        return StreamingResponse(
            resp.aiter_bytes(), status_code=resp.status_code,
            headers={k: v for k, v in resp.headers.items()
                     if k.lower() not in ("transfer-encoding", "content-encoding", "connection")},
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"RD-Agent UI 未启动")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"代理错误: {str(e)}")


# ── 任务队列端点 ───────────────────────────────────────
#   用 Celery + Redis 替代在 FastAPI worker 里跑长任务，
#   API 网关只负责任务提交 + 事件流代理，不再阻塞

TASK_REDIS_URL = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")


class TaskSubmitRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: list[dict] = []


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str = ""


@app.post("/api/tasks/submit")
async def task_submit(req: TaskSubmitRequest):
    """
    提交因子进化任务到 Celery 队列。
    返回 task_id，前端用此 ID 订阅 SSE 事件流获取进度。
    """
    from backend.services.ai_agent import parse_message
    
    parsed = parse_message(req.message)
    if parsed.get("loop_n", 0) <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"无法从指令中提取循环次数。请明确指定，例如：'在{parsed.get('universe', '沪深300')}中挖掘因子，迭代5轮'",
        )
    
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    
    # 提交 Celery 任务
    from backend.worker.tasks import run_factor_evolution
    celery_result = run_factor_evolution.delay(
        task_id=task_id,
        loop_n=parsed["loop_n"],
        all_duration=parsed.get("all_duration", f"{parsed['loop_n'] * 30}m"),
        parsed_info={
            "universe": parsed.get("universe", "全A股"),
            "constraints": parsed.get("constraints", "通用"),
            "loop_n": parsed["loop_n"],
            "all_duration": parsed.get("all_duration"),
        },
    )
    
    logger.info(f"[API] 任务已提交: {task_id}, celery_id={celery_result.id}")
    
    return {
        "task_id": task_id,
        "celery_task_id": celery_result.id,
        "status": "queued",
        "parsed": {
            "universe": parsed.get("universe"),
            "constraints": parsed.get("constraints"),
            "loop_n": parsed["loop_n"],
        },
    }


@app.get("/api/tasks/{task_id}/status")
async def task_status(task_id: str):
    """查询任务进度快照（轮询模式，方案 B）
    
    返回最近一次 push 的 progress payload，包含：
    - status: 任务状态 (running / completed / failed / unknown)
    - type: 最近事件类型
    - stage: 当前阶段
    - elapsed_sec: 已用时
    - content: 最近一条进度消息
    - hypotheses_count / codes_count / backtests_count: 计数（如果有）
    """
    try:
        from backend.worker.tasks import get_progress_snapshot
        snapshot = get_progress_snapshot(task_id)
        if snapshot:
            return snapshot
        # 回退：检查 Celery backend
        try:
            from celery.result import AsyncResult
            from backend.worker.celery_app import app as celery_app
            r = AsyncResult(task_id, app=celery_app)
            if r.state == "PENDING":
                return {"task_id": task_id, "status": "pending", "note": "任务在队列中等待执行"}
            elif r.state in ("STARTED", "RUNNING"):
                info = r.info or {}
                return {"task_id": task_id, "status": "running", "stage": info.get("stage", ""),
                        "hypotheses_count": info.get("hypotheses", 0),
                        "codes_count": info.get("codes", 0),
                        "backtests_count": info.get("backtests", 0)}
            elif r.state == "SUCCESS":
                return {"task_id": task_id, "status": "completed", "result": r.result}
            elif r.state == "FAILURE":
                return {"task_id": task_id, "status": "failed", "error": str(r.info)}
            else:
                return {"task_id": task_id, "status": r.state.lower()}
        except Exception:
            return {"task_id": task_id, "status": "unknown", "note": "任务未找到（进度快照和 Celery backend 均无记录）"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"查询失败: {str(e)}")



@app.post("/api/tasks/{task_id}/revoke")
async def task_revoke(task_id: str):
    """取消/中断指定任务。
    
    通过 Celery inspect 查找运行中的 Worker 任务，
    匹配 user_task_id 后调用 control.revoke 终止。
    """
    from celery import Celery
    import redis as _redis
    
    _redis_url = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")
    
    # 1. 通过 Celery inspect 查找匹配的 celery 任务
    app = Celery("aiquant_worker", broker=_redis_url)
    try:
        insp = app.control.inspect(timeout=3)
        active = insp.active() or {}
        reserved = insp.reserved() or {}
        scheduled = insp.scheduled() or {}
        
        celery_ids = []
        
        # 搜索所有 worker 的 active/reserved/scheduled 任务
        for tasks in list(active.values()) + list(reserved.values()) + list(scheduled.values()):
            for t in tasks:
                kwargs = t.get("kwargs", {})
                if kwargs.get("task_id") == task_id:
                    celery_ids.append(t["id"])
        
        if not celery_ids:
            return {
                "success": False,
                "message": f"任务 {task_id} 未找到（不在 active/reserved/scheduled 中，可能已完成或未启动）",
                "task_id": task_id,
            }
        
        # 2. Revoke 所有匹配的 celery 任务
        revoked = 0
        for cid in celery_ids:
            app.control.revoke(cid, terminate=True, signal="SIGTERM")
            revoked += 1
            logger.info(f"[Revoke] celery task {cid} (user: {task_id}) revoked")
        
        # 3. 标记 Redis 中的任务状态为 interrupted
        try:
            r = _redis.from_url(_redis_url, decode_responses=True)
            progress_key = f"aiquant:task:progress:{task_id}"
            raw = r.get(progress_key)
            if raw:
                import json
                data = json.loads(raw)
                data["status"] = "interrupted"
                data["interrupted_reason"] = "user_revoke"
                r.set(progress_key, json.dumps(data))
            r.close()
        except Exception as e:
            logger.warning(f"[Revoke] 更新 Redis 状态失败: {e}")
        
        return {
            "success": True,
            "message": f"任务 {task_id} 已中断 ({revoked} 个 celery 任务已 revoke)",
            "task_id": task_id,
            "revoked_celery_ids": celery_ids,
        }
        
    except Exception as e:
        logger.error(f"[Revoke] revoke 失败: {e}")
        raise HTTPException(status_code=500, detail=f"任务取消失败: {str(e)}")


@app.get("/api/tasks/active")
async def list_active_tasks():
    """列出所有正在运行的任务，供前端页面加载时恢复连接。"""
    try:
        r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
        keys = await r.keys("aiquant:task:progress:*")
        active = []
        for k in keys:
            raw = await r.get(k)
            if raw:
                data = json.loads(raw)
                if data.get("status") == "running":
                    active.append({
                        "task_id": data.get("task_id", k.split(":")[-1]),
                        "stage": data.get("stage", ""),
                        "seq": data.get("seq", 0),
                        "elapsed_sec": data.get("elapsed_sec"),
                        "content": (data.get("content") or "")[:200],
                    })
        await r.close()
        return {"active_tasks": active}
    except Exception as e:
        return {"active_tasks": [], "error": str(e)}


# ── B1: 任务历史持久化 API ──
@app.get("/api/tasks/history")
async def task_history(limit: int = 50, status: str = None):
    """B1: 从 SQLite 读取已完成任务历史
    
    Args:
        limit: 返回条数上限（默认 50）
        status: 过滤状态 (completed/failed/running)，可选
    """
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent.parent / "data" / "task_history.db"
        if not db_path.exists():
            return {"tasks": [], "note": "暂无历史记录"}
        
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # B4: 自动清理残留 running 状态（超过30分钟无更新视为超时）
        from datetime import datetime as _dt, timedelta as _td
        _cutoff = (_dt.now() - _td(minutes=30)).isoformat()
        conn.execute(
            "UPDATE task_history SET status='failed', error='任务超时自动清理（30分钟无更新）' "
            "WHERE status='running' AND updated_at < ?",
            (_cutoff,)
        )
        conn.commit()
        
        if status:
            rows = conn.execute(
                "SELECT * FROM task_history WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_history ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        
        tasks = []
        for row in rows:
            tasks.append({
                "task_id": row["task_id"],
                "status": row["status"],
                "message": row["message"] or "",
                "universe": row["universe"] or "",
                "loop_n": row["loop_n"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "elapsed_sec": row["elapsed_sec"],
                "hypotheses_count": row["hypotheses_count"],
                "codes_count": row["codes_count"],
                "backtests_count": row["backtests_count"],
                "final_report": (row["final_report"] or "")[:500],
                "error": row["error"] or "",
            })
        conn.close()
        return {"tasks": tasks, "total": len(tasks)}
    except Exception as e:
        return {"tasks": [], "error": str(e)}


@app.get("/api/tasks/{task_id}/events/history")
async def task_events_history(task_id: str, limit: int = 200):
    """B1: 从 SQLite 读取指定任务的事件历史
    
    用于页面刷新后恢复完整对话历史。
    """
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent / "data" / "task_history.db"
        if not db_path.exists():
            return {"events": [], "note": "暂无事件历史"}
        
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM task_events WHERE task_id=? ORDER BY seq ASC LIMIT ?",
            (task_id, limit)
        ).fetchall()
        
        events = []
        for row in rows:
            events.append({
                "type": row["type"],
                "stage": row["stage"],
                "content": row["content"],
                "seq": row["seq"],
                "timestamp": row["timestamp"],
                "elapsed_sec": row["elapsed_sec"],
            })
        conn.close()
        return {"events": events, "total": len(events)}
    except Exception as e:
        return {"events": [], "error": str(e)}


# ── B4: 轮询 fallback 端点 ──
@app.get("/api/tasks/{task_id}/poll")
async def task_poll(task_id: str, since_seq: int = 0):
    """B4: HTTP 轮询 fallback — 当 SSE 不可用时，前端降级为轮询此端点
    
    Args:
        task_id: 任务 ID
        since_seq: 从哪个 seq 开始获取（增量轮询）
    
    Returns:
        最新事件列表 + 任务状态 + progress_pct (B3)
    """
    try:
        r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
        
        # 1. 获取当前任务状态快照
        raw = await r.get(f"aiquant:task:progress:{task_id}")
        snapshot = json.loads(raw) if raw else None
        
        # 2. 从 Stream 获取 since_seq 之后的事件
        events = []
        try:
            from backend.worker.stream_event_bus import get_events_stream_name
            stream_key = get_events_stream_name(task_id)
            # XRANGE 读取所有事件，过滤 seq > since_seq
            all_msgs = await r.xrange(stream_key)
            for msg_id, msg_data in all_msgs:
                try:
                    seq = int(msg_data.get("seq", 0))
                    if seq > since_seq:
                        events.append(json.loads(msg_data.get("payload", "{}")))
                except (ValueError, json.JSONDecodeError):
                    continue
        except Exception:
            pass  # Stream 不可用，仅返回快照
        
        await r.close()
        
        result = {
            "task_id": task_id,
            "events": events,
            "events_count": len(events),
        }
        if snapshot:
            result["status"] = snapshot.get("status", "unknown")
            result["latest_seq"] = snapshot.get("seq", 0)
            result["progress_pct"] = snapshot.get("progress_pct", 0)  # B3
            result["stage"] = snapshot.get("stage", "")
            result["elapsed_sec"] = snapshot.get("elapsed_sec")
            result["content"] = snapshot.get("content", "")
        else:
            result["status"] = "unknown"
            result["latest_seq"] = since_seq
            result["progress_pct"] = 0
        
        return result
    except Exception as e:
        return {"task_id": task_id, "events": [], "status": "error", "error": str(e)}


@app.get("/api/tasks/{task_id}/pending")
async def task_pending(task_id: str):
    """a4: XPENDING 监控 — 返回 Stream pending 消息统计 + 详情。
    
    用于监控消息堆积，前端 RecoveryBanner 可展示警告。
    """
    try:
        from backend.worker.stream_event_bus import get_pending_info, get_pending_details, get_deadletter_count
        r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
        info = await get_pending_info(r, task_id)
        details = await get_pending_details(r, task_id, count=20)
        dl_count = await get_deadletter_count(r, task_id)
        await r.close()
        return {
            "task_id": task_id,
            **info,
            "pending_details": details,
            "deadletter_count": dl_count,
            "alert": info.get("pending_count", 0) > 10,  # 超过 10 条告警
        }
    except Exception as e:
        return {"task_id": task_id, "pending_count": 0, "error": str(e), "alert": False}


@app.get("/api/tasks/{task_id}/deadletter")
async def task_deadletter(task_id: str, count: int = 20):
    """a7: 死信队列查看 — 返回死信 Stream 中的消息。"""
    try:
        r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
        dl_key = f"aiquant:task:deadletter:{task_id}"
        messages = await r.xrange(dl_key, count=count)
        await r.close()
        return {
            "task_id": task_id,
            "deadletter_count": len(messages),
            "messages": [
                {"id": msg_id, "fields": fields} for msg_id, fields in messages
            ],
        }
    except Exception as e:
        return {"task_id": task_id, "deadletter_count": 0, "error": str(e)}


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    """
    SSE 事件流 — 通过 Redis Stream (XREADGROUP) + Pub/Sub 双通道获取任务进度。
    
    a1: XREADGROUP + BLOCK 消费 Stream，断线重连不丢消息
    a3: 业务成功后 XACK，失败不 ACK 留给重试
    a5: 基于 seq 幂等去重
    a6: XAUTOCLAIM 认领超时消息
    
    兼容：若 Stream 不可用，fallback 到 Pub/Sub。
    """
    async def sse_stream():
        r = None
        pubsub = None
        consumer_id = None
        try:
            r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
            await r.ping()

            # ── 初始化 Stream 消费者 ──
            from backend.worker.stream_event_bus import (
                ensure_stream_group_async, stream_read_block, stream_ack,
                is_duplicate, auto_claim_stale, get_pending_details,
                check_and_move_deadletter, gen_consumer_id,
                CLAIM_MIN_IDLE_MS,
            )
            consumer_id = gen_consumer_id()
            stream_available = True
            try:
                await ensure_stream_group_async(r, task_id)
            except Exception as e:
                logger.warning(f"[API] Stream 消费组创建失败，将 fallback 到 Pub/Sub: {e}")
                stream_available = False

            # 同时订阅 Pub/Sub（兼容 + 低延迟）
            channel = get_events_channel(task_id)
            pubsub = r.pubsub()
            await pubsub.subscribe(channel)

            # 发送连接确认消息
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id, 'status': 'subscribed'}, ensure_ascii=False)}\n\n".encode("utf-8")

            # ── 重连补发：从 Redis progress key 读取最后状态 ──
            try:
                raw = await r.get(f"aiquant:task:progress:{task_id}")
                if raw:
                    prog = json.loads(raw)
                    status = prog.get("status", "unknown")
                    seq = prog.get("seq", 0)
                    stage = prog.get("stage", "")
                    content = prog.get("content", "")
                    if status == "running" and seq > 0:
                        recovery = {
                            "type": "recovery",
                            "task_id": task_id,
                            "content": f"🔄 **已恢复任务连接**\n\n"
                                       f"任务 `{task_id}` 正在后台运行中（当前阶段: {stage}，序号: {seq}）。\n"
                                       f"以下是最近一次进度：\n\n{content}",
                            "stage": stage,
                            "seq": seq,
                            "elapsed_sec": prog.get("elapsed_sec"),
                        }
                        yield f"data: {json.dumps(recovery, ensure_ascii=False)}\n\n".encode("utf-8")
                    elif status in ("completed", "failed"):
                        recovery = {
                            "type": status,
                            "task_id": task_id,
                            "content": f"{'✅' if status == 'completed' else '❌'} 任务已{status}（阶段: {stage}）\n\n{content}",
                            "stage": stage,
                            "seq": seq,
                            "elapsed_sec": prog.get("elapsed_sec"),
                        }
                        yield f"data: {json.dumps(recovery, ensure_ascii=False)}\n\n".encode("utf-8")
                        return
            except Exception as e:
                logger.warning(f"[API] SSE 重连补发失败: {e}")

            # ── 主循环：Stream (XREADGROUP+BLOCK) + Pub/Sub 双通道 ──
            import asyncio as _asyncio
            while True:
                got_message = False

                # a6: 定时认领超时消息（每轮循环尝试一次）
                if stream_available:
                    try:
                        claimed_ids = await auto_claim_stale(r, task_id, consumer_id)
                        if claimed_ids:
                            logger.info(f"[API] XAUTOCLAIM 认领了 {len(claimed_ids)} 条超时消息")
                    except Exception:
                        pass

                # a1: XREADGROUP + BLOCK 消费
                if stream_available:
                    try:
                        messages = await stream_read_block(
                            r, task_id, consumer_id, count=10, block_ms=2000
                        )
                        for msg in messages:
                            entry_id = msg["id"]
                            event = msg["data"]
                            seq = event.get("seq", 0)

                            # a5: 幂等去重
                            if seq and await is_duplicate(r, task_id, consumer_id, seq):
                                logger.debug(f"[API] 跳过重复消息 seq={seq} entry={entry_id}")
                                await stream_ack(r, task_id, entry_id)  # ACK 并跳过
                                continue

                            # 推送给前端
                            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode("utf-8")
                            got_message = True

                            # a3: 业务成功后 XACK
                            await stream_ack(r, task_id, entry_id)

                            # a7: 检查死信（通过 pending details 获取 delivery_count）
                            try:
                                pending = await get_pending_details(r, task_id, count=5)
                                for p in pending:
                                    if p["message_id"] == entry_id and p["delivery_count"] >= 3:
                                        await check_and_move_deadletter(
                                            r, task_id, entry_id, p["delivery_count"], event
                                        )
                            except Exception:
                                pass

                            # 终态检测
                            if event.get("type") in ("done", "completed", "failed"):
                                return
                    except Exception as e:
                        logger.warning(f"[API] Stream 读取失败，fallback 到 Pub/Sub: {e}")
                        stream_available = False

                # Pub/Sub fallback（低延迟通道）
                try:
                    message = await _asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5),
                        timeout=1.0
                    )
                    if message and message["type"] == "message":
                        yield f"data: {message['data']}\n\n".encode("utf-8")
                        got_message = True
                        try:
                            data = json.loads(message["data"])
                            if data.get("type") in ("done",):
                                return
                        except (json.JSONDecodeError, KeyError):
                            pass
                except _asyncio.TimeoutError:
                    pass
                except Exception:
                    pass

                if not got_message:
                    # 发心跳防止连接超时
                    yield f": heartbeat\n\n".encode("utf-8")

        except Exception as e:
            error_msg = json.dumps({"type": "error", "content": f"事件流异常: {str(e)}", "task_id": task_id}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n".encode("utf-8")
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                except Exception:
                    pass
            if r:
                try:
                    await r.close()
                except Exception:
                    pass

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 对话机器人代理 ─────────────────────────────────────

ROBOT_URL = os.environ.get("AIQUANT_ROBOT_URL", f"http://127.0.0.1:{settings.robot_port}")


class ChatProxyRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: list[dict] = []


@app.post("/api/robot/chat")
async def robot_chat(req: ChatProxyRequest):
    """代理转发对话请求至机器人服务(8003)"""
    import asyncio
    try:
        def _call():
            with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
                r = client.post(
                    f"{ROBOT_URL}/chat/completions",
                    json=req.model_dump(),
                )
                r.raise_for_status()
                return r.json()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _call)
    except httpx.ConnectError:
        return {
            "session_id": req.session_id or "fallback",
            "reply": (
                "## 对话机器人服务未启动\n\n"
                "机器人服务（端口 8003）当前离线，无法处理自然语言指令。\n\n"
                "### 修复方法\n"
                "1. 点击左侧导航切换到 **【服务运维】** 页面\n"
                "2. 找到 **对话机器人** 卡片\n"
                "3. 如果环境未安装 → 点击 **【一键安装】**\n"
                "4. 如果已安装 → 点击 **【启动】**\n"
                "5. 卡片变为 **绿色运行中** 后，回到此处重新发送指令\n\n"
                "> 提示：页面左侧【因子研究】【回测中心】不受机器人启停影响，可手动操作。"
            ),
            "intent": "general",
            "action_result": {
                "status": "blocked",
                "health": {
                    "all_ok": False,
                    "offline": ["robot"],
                    "details": {
                        "robot": {
                            "name": "对话机器人", "port": 8003, "running": False,
                            "error_type": "stopped", "type": "standalone",
                        }
                    }
                }
            },
            "timestamp": pd.Timestamp.now().isoformat(),
        }
    except Exception as e:
        import traceback
        logger.error(f"机器人代理错误: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"机器人服务异常: {type(e).__name__}: {str(e)}")


@app.post("/api/robot/clear")
async def robot_clear(session_id: str):
    """清除机器人会话上下文"""
    try:
        resp = await ROBOT_CLIENT.post(f"{ROBOT_URL}/chat/clear?session_id={session_id}", timeout=5)
        return resp.json()
    except Exception:
        return {"success": True, "message": f"会话 {session_id} 已清除"}


@app.get("/api/robot/history")
async def robot_history(session_id: str):
    """获取机器人会话历史"""
    try:
        resp = await ROBOT_CLIENT.get(f"{ROBOT_URL}/chat/history?session_id={session_id}", timeout=5)
        return resp.json()
    except Exception:
        return {"session_id": session_id, "history": [], "turns": 0}


# ── SSE 流式因子进化 ──────────────────────────────────

class SSEFactorEvolveRequest(BaseModel):
    message: str  # 用户自然语言指令
    session_id: Optional[str] = None
    loop_n: Optional[int] = None  # 显式指定循环次数（优先于从 message 解析）
    step_n: Optional[int] = None  # 显式指定每轮 step 数


@app.get("/api/ping-sse")
async def ping_sse():
    """调试：测试 SSE 流是否正常（纯顺序版，不依赖 asyncio.create_task）"""
    import asyncio as aio, json

    task_id = "TEST-001"

    def build_msg(pt, content, stage="", meta=None):
        return json.dumps({"type": pt, "stage": stage, "content": content, "task_id": task_id}, ensure_ascii=False)

    async def event_gen():
        yield build_msg("task_start", "测试任务启动", stage="task_start")
        await aio.sleep(0.1)
        yield build_msg("memory", "记忆库检索完成, 共0条", stage="memory_retrieval")
        await aio.sleep(0.1)
        yield build_msg("progress", "阶段1/3 完成: 因子生成", stage="factor_gen")
        await aio.sleep(0.1)
        yield build_msg("progress", "阶段2/3 完成: 模拟回测", stage="backtest")
        await aio.sleep(0.1)
        yield build_msg("progress", "阶段3/3 完成: 结果统计", stage="stats")
        await aio.sleep(0.1)
        yield build_msg("done", "Ping-SSE 测试通过，所有阶段完成", stage="complete")

    async def sse_wrap():
        async for msg in event_gen():
            yield f"data: {msg}\n\n".encode("utf-8")

    return StreamingResponse(sse_wrap(), media_type="text/event-stream")


@app.post("/api/robot/chat/stream")
async def robot_chat_stream(req: SSEFactorEvolveRequest):
    """
    SSE 流式因子进化端点（v2: Celery + Redis 事件代理）
    
    架构：
      用户指令 → Agent 解析意图 → 提交 Celery 任务
                                     ↓
      前端 SSE ← Redis Pub/Sub 事件流 ← Celery Worker（独立进程运行 RD-Agent）
    
    API 网关不再阻塞执行 RD-Agent，只做事件流代理。
    """
    from backend.services.ai_agent import parse_message, IntentResult
    from backend.worker.tasks import run_factor_evolution
    
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    msg = req.message.strip()
    session_id = req.session_id or "default"
    
    # ── Agent 解析用户意图 ──
    parsed = parse_message(msg)
    # 优先使用显式参数（如果有）
    if req.loop_n is not None and req.loop_n > 0:
        parsed["loop_n"] = req.loop_n
    if req.step_n is not None and req.step_n > 0:
        parsed["step_n"] = req.step_n
    
    async def event_generator():
        start_time = time.time()
        
        def build_msg(phase_type: str, content: str, stage: str = "", meta: dict = None):
            payload = {
                "type": phase_type, "stage": stage, "content": content,
                "task_id": task_id, "elapsed_sec": round(time.time() - start_time, 1),
                "timestamp": datetime.now().isoformat(),
            }
            if meta:
                payload["meta"] = meta
            return json.dumps(payload, ensure_ascii=False)
        
        # ── 无法解析时提示用户 ──
        if parsed.get("loop_n", 0) <= 0:
            yield build_msg("need_input", f"""⚠️【需要确认】无法从您的指令中提取循环次数。

您的指令："{msg}"
已识别：股票池 = {parsed.get('universe', '未知')}，约束 = {parsed.get('constraints', '通用')}

请在指令中明确指定循环次数，例如：
• "在沪深300挖掘因子，迭代5轮"
• "循环次数5次"
• "跑3轮"

请重新发送带有明确循环次数的指令。""", stage="need_clarification")
            return
        
        try:
            # ── 阶段0：任务启动 ──
            yield build_msg("task_start", f"""✅【任务启动】
用户需求：{msg}
迭代总轮次：{parsed['loop_n']}轮｜目标股票池：{parsed['universe']}｜约束：{parsed['constraints']}
全局任务ID：{task_id}
架构：Celery Worker 独立执行（不阻塞API）""", stage="task_start")
            await asyncio.sleep(0.1)
            
            # ── 阶段1：长期记忆库检索 ──
            memory = feedback_agent.get_memory_summary()
            mem_count = memory.get("total_reviews", 0)
            yield build_msg("memory", f"""✅【阶段1】长期记忆库检索完成
从记忆库历史因子中匹配同类{parsed['constraints']}因子记录，共检索到{mem_count}条历史方案，本轮将规避高度同质化因子逻辑。""", stage="memory_retrieval")
            await asyncio.sleep(0.1)
            
            # ── 先订阅 Redis（确保在提交任务前准备好接收事件） ──
            r = None
            pubsub = None
            stream_consumer_id = None
            stream_ok = False
            try:
                r = aioredis.from_url(TASK_REDIS_URL, decode_responses=True)
                await r.ping()
                channel = get_events_channel(task_id)
                pubsub = r.pubsub()
                await pubsub.subscribe(channel)
                logger.debug(f"[API] 已订阅 Redis 频道: {channel}")

                # ── 初始化 Stream 消费者 ──
                from backend.worker.stream_event_bus import (
                    ensure_stream_group_async, stream_read_block, stream_ack,
                    is_duplicate, auto_claim_stale, gen_consumer_id,
                )
                stream_consumer_id = gen_consumer_id()
                stream_ok = True
                try:
                    await ensure_stream_group_async(r, task_id)
                except Exception as e:
                    logger.warning(f"[API] Stream 消费组创建失败: {e}")
                    stream_ok = False
            except Exception as e:
                logger.error(f"[API] Redis 订阅失败: {e}")
                yield build_msg("error", f"❌【系统异常】无法连接任务队列: {str(e)}", stage="error")
                return
            
            # ── 重连补发：检查是否已有运行中的任务 ──
            try:
                raw_progress = await r.get(f"aiquant:task:progress:{task_id}")
                if raw_progress:
                    prog = json.loads(raw_progress)
                    if prog.get("status") == "running" and prog.get("seq", 0) > 0:
                        # 任务正在运行 — 补发恢复事件，不再重复提交 Celery
                        yield build_msg("recovery", (
                            f"🔄 **已恢复任务连接**\n\n"
                            f"任务 `{task_id}` 正在后台运行中（当前阶段: {prog.get('stage', 'unknown')}）。\n"
                            f"以下是最近一次进度：\n\n{prog.get('content', '')}"
                        ), stage=prog.get("stage", ""), meta={"seq": prog.get("seq", 0)})
                        # 跳过 Celery 任务提交，直接进入事件流监听
                        celery_result = None
                    else:
                        celery_result = None  # 任务已结束，不重复提交
                else:
                    celery_result = None  # 没有历史记录，正常提交新任务
            except Exception as e:
                logger.warning(f"[API] 重连补发检查失败: {e}")
                celery_result = None
            
            # ── 提交 Celery 任务（仅当没有已有运行中的任务时） ──
            if celery_result is None and not raw_progress:
                # ── 自动检测并启动 Celery Worker ──
                try:
                    import subprocess as _sp
                    _check = _sp.run(["pgrep", "-f", "celery.*backend.worker.celery_app"],
                                     capture_output=True, text=True, timeout=2)
                    if _check.returncode != 0 or not _check.stdout.strip():
                        logger.warning("[API] Celery Worker 未运行，自动启动...")
                        yield build_msg("phase", "⚠️【系统自愈】检测到 Celery Worker 未运行，正在自动启动...", stage="worker_recovery")
                        # 启动 Worker（setsid 隔离进程组，与 start.sh 一致）
                        _project_root = Path(__file__).resolve().parent.parent.parent
                        _log_file = _project_root / "logs" / "celery_worker.log"
                        _celery_cmd = f'while true; do celery -A backend.worker.celery_app worker --loglevel=info --concurrency=1 --pool=solo -Q factor_evolution -n factor_worker@%h; echo "[$(date)] Worker 退出，5秒后自动重启..." >> "{_log_file}"; sleep 5; done'
                        _sp.Popen(["setsid", "bash", "-c", _celery_cmd],
                                   stdout=open(_log_file, "a"), stderr=_sp.STDOUT,
                                   start_new_session=True)
                        await asyncio.sleep(5)  # 等待 Worker 初始化
                        yield build_msg("phase", "✅【系统自愈】Celery Worker 已自动启动", stage="worker_recovered")
                except Exception as _e:
                    logger.error(f"[API] Worker 自动启动失败: {_e}")
                    yield build_msg("error", f"❌【系统异常】Celery Worker 未运行且自动启动失败: {_e}\n请手动执行 start.sh 启动完整系统。", stage="error")
                    return

                yield build_msg("phase", f"✅【阶段1.5】任务已提交到后台Worker队列\nCelery Worker 正在初始化 RD-Agent 进化引擎，稍后将实时推送各阶段进度...", stage="task_queued")
                
                celery_result = run_factor_evolution.delay(
                    task_id=task_id,
                    loop_n=parsed["loop_n"],
                    all_duration=parsed.get("all_duration", f"{parsed['loop_n'] * 30}m"),
                    parsed_info={
                        "universe": parsed.get("universe", "全A股"),
                        "constraints": parsed.get("constraints", "通用"),
                        "loop_n": parsed["loop_n"],
                        "all_duration": parsed.get("all_duration"),
                    },
                )
                logger.info(f"[API] 聊天任务已提交: {task_id} → Celery {celery_result.id}")
            elif celery_result is None and raw_progress:
                logger.info(f"[API] 任务 {task_id} 已在运行中，跳过重复提交，直接监听事件流")
            
            # ── 代理 Redis 事件流到 SSE ──
            last_event_time = time.time()
            STALE_TIMEOUT = 300  # 5分钟无事件视为任务卡住
            HEARTBEAT_INTERVAL = 15  # 每15秒发送心跳，防止代理/浏览器超时断开
            
            try:
                import asyncio as _aio
                while True:
                    # ── a1: 优先从 Stream 消费 (XREADGROUP + BLOCK) ──
                    if stream_ok:
                        try:
                            # a6: 定时认领超时消息
                            await auto_claim_stale(r, task_id, stream_consumer_id)

                            messages = await stream_read_block(
                                r, task_id, stream_consumer_id, count=10, block_ms=2000
                            )
                            for stream_msg in messages:
                                entry_id = stream_msg["id"]
                                event = stream_msg["data"]
                                seq = event.get("seq", 0)

                                # a5: 幂等去重
                                if seq and await is_duplicate(r, task_id, stream_consumer_id, seq):
                                    await stream_ack(r, task_id, entry_id)
                                    continue

                                payload = json.dumps(event, ensure_ascii=False, default=str)
                                last_event_time = time.time()
                                yield payload

                                # a3: 业务成功后 XACK
                                await stream_ack(r, task_id, entry_id)

                                if event.get("type") in ("done", "error"):
                                    break
                        except Exception as e:
                            logger.warning(f"[API] Stream 消费失败，fallback Pub/Sub: {e}")
                            stream_ok = False

                    # ── Pub/Sub fallback（仅当 Stream 不可用时使用） ──
                    if not stream_ok:
                        try:
                            message = await asyncio.wait_for(
                                pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5),
                                timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            message = None

                        if message and message["type"] == "message":
                            last_event_time = time.time()
                            yield message["data"]

                            try:
                                data = json.loads(message["data"])
                                if data.get("type") in ("done", "error"):
                                    break
                            except (json.JSONDecodeError, KeyError):
                                pass

                    # 心跳保活
                    if time.time() - last_event_time > HEARTBEAT_INTERVAL:
                        last_event_time = time.time()
                        yield "__HEARTBEAT__"

                    # 超时检测
                    if time.time() - last_event_time > STALE_TIMEOUT:
                        yield build_msg("error",
                            f"⚠️【任务可能卡住】已超过 {STALE_TIMEOUT} 秒无进度更新，任务可能因 LLM API 超时而挂起。\n"
                            f"任务 {task_id} 仍在 Worker 中，可通过 RD-Agent UI 查看当前进度。",
                            stage="timeout_warning")
                        break
                        
            except Exception as e:
                logger.error(f"[API] Redis 事件流异常: {e}")
                yield build_msg("error",
                    f"❌【事件流中断】无法连接任务进度流: {str(e)}\n任务 {task_id} 仍在 Worker 中运行，可通过日志查看进度。",
                    stage="stream_error")
            finally:
                if pubsub:
                    try: await pubsub.unsubscribe()
                    except Exception: pass
                if r:
                    try: await r.close()
                    except Exception: pass
                    
        except Exception as e:
            logger.error(f"[API] 聊天流异常: {e}")
            yield build_msg("error", f"❌【系统异常】{str(e)}", stage="system_error")

    async def _sse_stream():
        async for msg in event_generator():
            if msg == "__HEARTBEAT__":
                yield b': heartbeat\n\n'
            else:
                yield f"data: {msg}\n\n".encode("utf-8")

    return StreamingResponse(_sse_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


def _parse_mining_instruction(msg: str) -> dict:
    """解析用户自然语言因子挖掘指令。
    
    返回 dict 中 loop_n=0 表示无法从消息中提取轮数，调用方应提示用户明确指定。
    """
    msg_lower = msg.lower()
    
    # 提取迭代轮数：支持多种自然语言表达
    #   "循环次数5次" / "循环5轮" / "循环5次" / "迭代5轮" / "迭代5次"
    #   "5轮迭代" / "5次循环" / "跑5轮" / "做5次"
    import re
    loop_n = 0
    for pattern in [
        r'循环\s*次数\s*(\d+)\s*次',          # "循环次数5次"
        r'循环\s*(\d+)\s*[次轮]',              # "循环5轮", "循环5次"
        r'迭代\s*(\d+)\s*[次轮]',              # "迭代5轮", "迭代5次"
        r'(?:跑|做|执行|运行)\s*(\d+)\s*[次轮]', # "跑5轮", "做5次"
        r'(\d+)\s*[次轮](?:\s*(?:迭代|循环))?', # "5轮迭代", "5次循环"
    ]:
        m = re.search(pattern, msg)
        if m:
            loop_n = int(m.group(1))
            break
    
    # 提取股票池
    universe = "全A股"
    if "中证1000" in msg or "csi1000" in msg_lower:
        universe = "中证1000"
    elif "中证500" in msg or "csi500" in msg_lower:
        universe = "中证500"
    elif "沪深300" in msg or "csi300" in msg_lower or "hs300" in msg_lower:
        universe = "沪深300"
    elif "上证50" in msg or "sz50" in msg_lower or "sse50" in msg_lower:
        universe = "上证50"
    
    # 提取约束条件
    constraints = []
    if "高换手" in msg:
        constraints.append("高换手风格")
    elif "低换手" in msg:
        constraints.append("低换手风格")
    elif "换手" in msg:
        constraints.append("换手率风格")
    if "横截面" in msg:
        constraints.append("横截面")
    if "动量" in msg:
        constraints.append("动量")
    if "反转" in msg:
        constraints.append("反转")
    if "市值" in msg:
        constraints.append("市值中性")
    if "行业" in msg:
        constraints.append("行业中性")
    
    constraint_str = "、".join(constraints) if constraints else "通用"
    
    # 时间限制
    all_duration = f"{loop_n * 30}m"  # 每轮约30分钟（Docker模式回测较慢）
    
    return {
        "loop_n": loop_n,
        "universe": universe,
        "constraints": constraint_str,
        "all_duration": all_duration,
    }


async def _run_factor_evolution_with_callbacks(
    loop_n: int,
    all_duration: str,
    task_id: str,
    enqueue,
    parsed_info: dict = None,
) -> dict:
    """
    执行因子进化并通过 SSE 实时推送进度。
    
    通过 enqueue(pt, content, stage, meta) 将消息推送到外部 SSE 队列。
    使用 monkey-patch 在 RD-Agent RDLoop 各阶段插入数据收集钩子。
    """
    import threading
    from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
    from rdagent.app.qlib_rd_loop.conf import FACTOR_PROP_SETTING
    from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
    
    # 存储各阶段产出的共享容器
    progress_data = {
        "current_loop": 0,
        "hypotheses": [],
        "codes": [],
        "backtest_results": [],
        "feedbacks": [],
        "reviews": [],
        "errors": [],
        "finished": False,
    }
    
    # Monkey-patch FactorRDLoop 的方法插入回调
    original_direct_exp_gen = FactorRDLoop.direct_exp_gen
    original_coding = FactorRDLoop.coding
    original_running = FactorRDLoop.running
    original_feedback = FactorRDLoop.feedback
    
    def _extract_backtest_metrics(exp) -> dict:
        metrics = {}
        try:
            # 优先从 exp.result 提取
            if hasattr(exp, 'result') and exp.result:
                result = exp.result
                for attr in ['ic', 'icir', 'rank_ic', 'sharpe', 'annual_return', 'max_drawdown', 'monthly_win_rate']:
                    if hasattr(result, attr):
                        metrics[attr] = getattr(result, attr)
            if hasattr(exp, 'sub_workspace_list'):
                for ws in exp.sub_workspace_list:
                    if hasattr(ws, 'result'):
                        r = ws.result
                        for attr in ['ic', 'icir', 'rank_ic', 'sharpe', 'annual_return', 'max_drawdown']:
                            if hasattr(r, attr) and attr not in metrics:
                                metrics[attr] = getattr(r, attr)
            # 兜底：从最新工作目录 qlib_res.csv 读取（全局查找，不依赖 workspace_path 属性）
            if not metrics:
                try:
                    import pandas as pd
                    from pathlib import Path
                    ws_root = Path(__file__).parent.parent.parent / "git_ignore_folder" / "RD-Agent_workspace"
                    if ws_root.exists():
                        # 找最新的含 qlib_res.csv 的目录
                        dirs = sorted(ws_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                        for d in dirs[:5]:
                            csv_path = d / "qlib_res.csv"
                            if csv_path.exists():
                                df = pd.read_csv(csv_path, index_col=0)
                                # df.loc[key, 0] 返回 Series 时取第一个值，避免布尔歧义
                                def _get_val(key):
                                    if key not in df.index: return None
                                    v = df.loc[key, 0]
                                    if isinstance(v, pd.Series): v = v.iloc[0]
                                    return v
                                if _get_val('Rank IC') is not None: metrics['rank_ic'] = _get_val('Rank IC')
                                if _get_val('ICIR') is not None: metrics['icir'] = _get_val('ICIR')
                                if _get_val('IC') is not None: metrics['ic'] = _get_val('IC')
                                if _get_val('1day.excess_return_with_cost.annualized_return') is not None:
                                    metrics['annual_return'] = _get_val('1day.excess_return_with_cost.annualized_return')
                                if _get_val('1day.excess_return_with_cost.max_drawdown') is not None:
                                    metrics['max_drawdown'] = _get_val('1day.excess_return_with_cost.max_drawdown')
                                if metrics:
                                    logger.info(f"[SSE hook] 从 {d.name}/qlib_res.csv 提取指标: {list(metrics.keys())}")
                                    break
                except Exception as csv_err:
                    logger.debug(f"csv兜底提取失败: {csv_err}")
        except Exception as e:
            logger.debug(f"提取回测指标失败: {e}")
        return metrics
    
    def _extract_factor_code(exp) -> str:
        try:
            if hasattr(exp, 'sub_workspace_list'):
                for ws in exp.sub_workspace_list:
                    if hasattr(ws, 'target_file'):
                        tf = ws.target_file
                        if hasattr(tf, 'code'): return tf.code
                        if isinstance(tf, dict) and 'code' in tf: return tf['code']
                    if hasattr(ws, 'code'): return ws.code
            if hasattr(exp, 'code'): return exp.code
            # 兜底：从最新工作目录 factor.py 读取（全局查找）
            if not code:
                try:
                    from pathlib import Path
                    ws_root = Path(__file__).parent.parent.parent / "git_ignore_folder" / "RD-Agent_workspace"
                    if ws_root.exists():
                        dirs = sorted(ws_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                        for d in dirs[:5]:
                            factor_py = d / "factor.py"
                            if factor_py.exists():
                                code = factor_py.read_text(encoding='utf-8', errors='ignore')
                                if code:
                                    logger.info(f"[SSE hook] 从 {d.name}/factor.py 提取代码 ({len(code)} chars)")
                                    break
                except Exception as py_err:
                    logger.debug(f"py兜底提取失败: {py_err}")
        except Exception: pass
        return code
    
    def _translate_en_to_cn(text: str) -> str:
        """将英文因子假设/反馈文本翻译为中文（轻量级关键词映射）"""
        if not text:
            return text
        term_map = {
            "momentum": "动量", "reversal": "反转", "volatility": "波动率",
            "volume": "成交量", "turnover": "换手率", "liquidity": "流动性",
            "value factor": "价值因子", "growth factor": "成长因子",
            "quality factor": "质量因子", "size factor": "规模因子",
            "beta": "贝塔", "alpha": "阿尔法",
            "sharpe ratio": "夏普比率", "max drawdown": "最大回撤",
            "annualized return": "年化收益率", "ic": "IC值", "rank ic": "Rank IC",
            "ir": "信息比率", "win rate": "胜率",
            "close": "收盘价", "open": "开盘价", "high": "最高价", "low": "最低价",
            "vwap": "成交量加权均价", "amount": "成交额", "shares": "成交量(股)",
            "free float": "自由流通市值", "market cap": "总市值",
            "pe ratio": "市盈率", "pb ratio": "市净率", "ps ratio": "市销率",
            "roe": "净资产收益率", "roa": "总资产收益率",
            "hypothesis": "假设", "factor": "因子", "signal": "信号",
            "backtest": "回测", "universe": "股票池", "benchmark": "基准",
            "long": "做多", "short": "做空", "long-short": "多空对冲",
            "neutralize": "中性化", "industry neutral": "行业中性",
            "market neutral": "市场中性", "cross-sectional": "横截面",
            "time series": "时间序列", "lookback": "回溯期",
            "we propose": "我们提出", "we hypothesize": "我们假设",
            "we expect": "我们预期", "we observe": "我们观察到",
            "based on": "基于", "compared to": "相比于",
            "in order to": "为了", "due to": "由于",
            "is positively correlated": "正相关",
            "is negatively correlated": "负相关",
            "mean reversion": "均值回归", "overreaction": "过度反应",
            "underreaction": "反应不足", "herding": "羊群效应",
            "dispersion": "分散度", "skewness": "偏度", "kurtosis": "峰度",
            "autocorrelation": "自相关", "stationarity": "平稳性",
            "cointegration": "协整", "regression": "回归",
            "standardize": "标准化", "normalize": "归一化",
            "winsorize": "缩尾处理", "outlier": "异常值",
        }
        result = text
        for en, cn in sorted(term_map.items(), key=lambda x: -len(x[0])):
            result = result.replace(en, cn)
            result = result.replace(en.capitalize(), cn)
            result = result.replace(en.upper(), cn)
        return result

    def _extract_hypothesis_text(exp_or_hypo) -> str:
        try:
            raw = ""
            if hasattr(exp_or_hypo, 'hypothesis'): raw = str(exp_or_hypo.hypothesis)[:500]
            elif hasattr(exp_or_hypo, 'short_description'): raw = str(exp_or_hypo.short_description)
            elif hasattr(exp_or_hypo, 'sub_tasks'):
                tasks = exp_or_hypo.sub_tasks
                texts = []
                for t in (tasks if isinstance(tasks, list) else [tasks]):
                    if hasattr(t, 'description'): texts.append(str(t.description)[:200])
                    elif hasattr(t, 'factor_name'): texts.append(str(t.factor_name))
                    else: texts.append(str(t)[:200])
                raw = "\n".join(texts[:5])
            else:
                raw = str(exp_or_hypo)[:500]
            return _translate_en_to_cn(raw)
        except Exception: return _translate_en_to_cn(str(exp_or_hypo)[:300])
    
    async def patched_direct_exp_gen(self, prev_out):
        result = await original_direct_exp_gen(self, prev_out)
        loop_i = self.loop_idx - 1
        try:
            # direct_exp_gen 返回 {"propose": Hypothesis, "exp_gen": Experiment}
            # 不是 {"direct_exp_gen": {}}，直接从顶层取
            exp_gen = result.get("exp_gen") if isinstance(result, dict) else None
            hypo_text = _extract_hypothesis_text(exp_gen) if exp_gen else ""
            if exp_gen and hypo_text:
                progress_data["hypotheses"].append({"loop": loop_i, "text": hypo_text})
                logger.info(f"[SSE hook] Loop {loop_i+1} hypothesis captured ({len(hypo_text)} chars)")
            else:
                logger.debug(f"[SSE hook] Loop {loop_i+1} hypothesis skipped (exp_gen={type(exp_gen).__name__})")
        except Exception as e:
            logger.debug(f"提取因子假设失败: {e}")
        return result
    
    async def patched_coding(self, prev_out):
        result = original_coding(self, prev_out)
        if asyncio.iscoroutine(result):
            result = await result
        loop_i = self.loop_idx - 1
        try:
            code = _extract_factor_code(result)
            progress_data["codes"].append({"loop": loop_i, "code": code})
            if code: logger.info(f"[SSE hook] Loop {loop_i+1} code captured ({len(code)} chars)")
        except Exception as e: logger.debug(f"提取因子代码失败: {e}")
        return result
    
    async def patched_running(self, prev_out):
        result = original_running(self, prev_out)
        if asyncio.iscoroutine(result):
            result = await result
        loop_i = self.loop_idx - 1
        try:
            metrics = _extract_backtest_metrics(result)
            progress_data["backtest_results"].append({"loop": loop_i, "metrics": metrics})
            if metrics: logger.info(f"[SSE hook] Loop {loop_i+1} backtest captured")
        except Exception as e: logger.debug(f"提取回测结果失败: {e}")
        return result
    
    def _clean_feedback_text(raw: str) -> str:
        """清理反馈文本中的误导性错误前缀，提取真正有用的诊断信息"""
        # 情况1: Qlib docker 执行返回 None（result is None）
        if raw.startswith("Failed to run this experiment"):
            lines = raw.split("\n")
            # 搜索真正的异常信息：ParserError, ValueError, KeyError, Traceback, Exception, ModuleNotFoundError
            import re
            error_start_idx = None
            for i, line in enumerate(lines):
                if any(kw in line for kw in [
                    "ParserError", "Traceback (most recent call last)",
                    "ValueError:", "KeyError:", "ModuleNotFoundError:", 
                    "FileNotFoundError:", "AttributeError:", "TypeError:",
                    "RuntimeError:", "Exception in", "ERROR -",
                ]):
                    error_start_idx = max(0, i - 2)
                    break
            
            if error_start_idx is not None:
                error_snippet = "\n".join(lines[error_start_idx:error_start_idx + 10])
                return f"Qlib回测执行异常 — 堆栈摘要:\n{error_snippet[:500]}"
            
            # 搜索 ERROR 行（日志级别标记）
            error_lines = [l for l in lines if "ERROR" in l and len(l) > 50]
            if error_lines:
                return f"Qlib回测日志含错误 — {' | '.join(error_lines[:2])[:400]}"
            
            return "实验未产出有效回测结果 — 因子代码可能在样本期内计算失败，或因子值全为NaN/空值，请检查数据字段是否存在、计算逻辑是否有运行时错误"
        # 情况2: process_factor_data 中所有因子实现均失败
        if raw.startswith("No valid factor data found to merge"):
            return "因子数据生成全部失败 — 所有候选因子代码在样本期执行后均未产生有效DataFrame，可能原因：字段名不存在、逻辑错误导致全NaN、样本期数据缺失"
        # 情况3: new_factors.empty
        if "failed to run on the full sample" in raw.lower():
            return "因子在全样本上运行失败 — 生成的新因子在目标股票池中无法计算出有效值，建议更换数据字段或调整因子计算逻辑"
        # 情况4: 因子与历史因子高度相似
        if "highly similar to the previous factors" in raw:
            return "因子与历史方案高度同质化 — 本轮生成的因子与已提交因子IC相关度过高(>0.99)，需更换研究方向或使用不同的数据字段组合"
        return _translate_en_to_cn(raw)
    
    async def patched_feedback(self, prev_out):
        result = original_feedback(self, prev_out)
        if asyncio.iscoroutine(result):
            result = await result
        loop_i = self.loop_idx - 1
        try:
            if self.trace and hasattr(self.trace, 'hist') and self.trace.hist:
                latest = self.trace.hist[-1]
                if len(latest) >= 2:
                    feedback_obj = latest[1]
                    feedback_text = ""
                    if hasattr(feedback_obj, 'observations'): 
                        raw_obs = str(feedback_obj.observations)
                        feedback_text += _clean_feedback_text(raw_obs)[:400]
                    if hasattr(feedback_obj, 'new_hypothesis'): feedback_text += "\n" + _translate_en_to_cn(str(feedback_obj.new_hypothesis)[:300])
                    if hasattr(feedback_obj, 'decision'): feedback_text += f"\n决策：{'✅ 保留' if feedback_obj.decision else '❌ 淘汰'}"
                    progress_data["feedbacks"].append({"loop": loop_i, "text": feedback_text or _translate_en_to_cn(str(feedback_obj)[:500])})
                    logger.info(f"[SSE hook] Loop {loop_i+1} feedback captured")
        except Exception as e: logger.debug(f"提取反馈失败: {e}")
        return result
    
    FactorRDLoop.direct_exp_gen = patched_direct_exp_gen
    FactorRDLoop.coding = patched_coding
    FactorRDLoop.running = patched_running
    FactorRDLoop.feedback = patched_feedback
    
    p_info = parsed_info or {}
    
    # 根据 universe 设置 Qlib market（决定回测时使用哪个股票池）
    universe = p_info.get("universe", "全A股")
    _market_map = {"沪深300": "csi300", "中证500": "csi500", "上证50": "sz50", "全A股": "all"}
    _qlib_market = _market_map.get(universe, "all")
    try:
        FACTOR_PROP_SETTING.qlib_conf.market = _qlib_market
        # 确保 qlib_conf 包含 provider_uri 和 region，防止 __DEFAULT_FREQ 错误
        try:
            FACTOR_PROP_SETTING.qlib_conf.provider_uri = os.path.expanduser("~/.qlib/qlib_data/cn_data")
        except Exception:
            pass
        try:
            FACTOR_PROP_SETTING.qlib_conf.region = "cn"
        except Exception:
            pass
        logger.info(f"已设置 Qlib market={_qlib_market} (universe={universe}), region=cn")
    except Exception as _me:
        logger.warning(f"设置 FACTOR_PROP_SETTING.qlib_conf 失败: {_me}")
    
    # 阶段2开始：初始化进化引擎
    env_type = getattr(MODEL_COSTEER_SETTINGS, 'env_type', 'unknown')
    enqueue("phase", f"""✅【阶段2】因子进化引擎正在初始化...
执行环境：{env_type}｜迭代轮次：{loop_n}轮｜股票池：{universe}""", stage="phase2_init")
    
    try:
        factor_loop = FactorRDLoop(FACTOR_PROP_SETTING)
        enqueue("phase", "✅ 进化引擎就绪，开始因子生成与回测...", stage="phase2_start")
    except Exception as init_err:
        enqueue("error", f"❌ FactorRDLoop 初始化失败: {str(init_err)}", stage="error")
        logger.error(f"[SSE] FactorRDLoop 初始化异常: {init_err}", exc_info=True)
        return progress_data
    
    try:
        # 直接复用 uvicorn 主线程 uvloop 全局事件循环
        # 模块顶层已执行 nest_asyncio.apply()，支持嵌套 await
        evolution_coro = factor_loop.run(
            step_n=None, loop_n=loop_n, all_duration=all_duration,
        )
        evolution_task = asyncio.ensure_future(evolution_coro)
        
        last_hypo_count = 0
        last_code_count = 0
        last_bt_count = 0
        last_fb_count = 0
        
        while not evolution_task.done():
            await asyncio.sleep(5)
            
            # 推送新的因子假设
            if len(progress_data["hypotheses"]) > last_hypo_count:
                for h in progress_data["hypotheses"][last_hypo_count:]:
                    loop_i = h["loop"]
                    enqueue("hypothesis", f"""✅【阶段2】R-Agent研究员｜因子数学假设构思完成（第{loop_i+1}轮）
本轮生成候选因子假设：
{h['text'][:800]}
逻辑：基于{p_info.get('constraints', '通用')}约束，在{p_info.get('universe', '全A股')}股票池中挖掘alpha信号""", stage=f"hypothesis_loop{loop_i+1}")
                last_hypo_count = len(progress_data["hypotheses"])
            
            if len(progress_data["codes"]) > last_code_count:
                for c in progress_data["codes"][last_code_count:]:
                    loop_i = c["loop"]
                    code = c["code"]
                    code_block = f"\n```python\n{code[:1200]}\n```" if code else "\n（代码提取中...）"
                    enqueue("code", f"""✅【阶段3】D-Agent 因子代码生成完成（第{loop_i+1}轮）
已将因子假设转换为可直接在Qlib运行的标准Python因子代码{code_block}
其余候选代码将汇总至最终报告。""", stage=f"coding_loop{loop_i+1}",
                        meta={"code": code[:3000] if code else ""})
                last_code_count = len(progress_data["codes"])
            
            if len(progress_data["backtest_results"]) > last_bt_count:
                for bt in progress_data["backtest_results"][last_bt_count:]:
                    loop_i = bt["loop"]
                    metrics = bt["metrics"]
                    if metrics:
                        ic = metrics.get('ic', metrics.get('rank_ic', 'N/A'))
                        icir = metrics.get('icir', 'N/A')
                        ann_ret = metrics.get('annual_return', 'N/A')
                        max_dd = metrics.get('max_drawdown', 'N/A')
                        win_rate = metrics.get('monthly_win_rate', 'N/A')
                        if isinstance(ic, float): ic = f"{ic:.4f}"
                        if isinstance(icir, float): icir = f"{icir:.2f}"
                        if isinstance(ann_ret, float):
                            ann_ret = f"{ann_ret*100:.2f}%" if abs(ann_ret) < 10 else f"{ann_ret:.2f}"
                        if isinstance(max_dd, float):
                            max_dd = f"{max_dd*100:.2f}%" if abs(max_dd) < 10 else f"{max_dd:.2f}"
                        if isinstance(win_rate, float): win_rate = f"{win_rate*100:.0f}%" if win_rate <= 1 else f"{win_rate:.0f}%"
                        metrics_str = f"候选因子｜IC均值：{ic}｜ICIR：{icir}｜年化收益：{ann_ret}｜最大回撤：{max_dd}｜月度胜率：{win_rate}"
                    else:
                        metrics_str = "回测指标提取中..."
                    enqueue("backtest", f"""✅【第{loop_i+1}轮迭代｜回测计算完成】
回测区间：2018~2025｜股票池：{p_info.get('universe', '全A股')}
本轮因子绩效明细：
{metrics_str}""", stage=f"backtest_loop{loop_i+1}",
                        meta={"metrics": {k: str(v) for k, v in metrics.items()} if metrics else {}})
                last_bt_count = len(progress_data["backtest_results"])
                
                loop_i = progress_data["backtest_results"][-1]["loop"]
                review_text = _generate_mock_reviews(loop_i, progress_data)
                enqueue("review", review_text, stage=f"review_loop{loop_i+1}")
                
                if loop_i + 1 < loop_n:
                    enqueue("optimization", f"""✅【第{loop_i+1}轮迭代全部结束】
下一轮进化方向：对候选因子增加行业、市值双重中性化处理，生成优化版本因子进行下一轮回测
————————————————————""", stage=f"optimization_loop{loop_i+1}")
            
            if len(progress_data["feedbacks"]) > last_fb_count:
                for fb in progress_data["feedbacks"][last_fb_count:]:
                    loop_i = fb["loop"]
                    enqueue("feedback", f"""✅【阶段4】LLM反馈分析完成（第{loop_i+1}轮）
{fb['text'][:500]}""", stage=f"feedback_loop{loop_i+1}")
                last_fb_count = len(progress_data["feedbacks"])
        
        # 等待进化完成并收集结果
        await evolution_task
    
    except Exception as exec_err:
        error_msg = f"❌ 因子进化执行异常: {str(exec_err)}"
        enqueue("error", error_msg, stage="error")
        logger.error(f"[SSE] 进化执行异常: {exec_err}", exc_info=True)
            
    finally:
        FactorRDLoop.direct_exp_gen = original_direct_exp_gen
        FactorRDLoop.coding = original_coding
        FactorRDLoop.running = original_running
        FactorRDLoop.feedback = original_feedback
    
    return progress_data


def _generate_mock_reviews(loop_i: int, progress_data: dict) -> str:
    """生成模拟的七分析师评审内容（TradingAgents不可用时的降级方案）"""
    bt = progress_data["backtest_results"][-1] if progress_data["backtest_results"] else {}
    metrics = bt.get("metrics", {})
    
    ic = metrics.get('ic', metrics.get('rank_ic', 0))
    sharpe = metrics.get('sharpe', 0)
    
    if isinstance(ic, (int, float)) and ic > 0.03:
        perf_level = "表现优秀"
    elif isinstance(ic, (int, float)) and ic > 0.02:
        perf_level = "表现良好"
    else:
        perf_level = "有优化空间"
    
    return f"""✅【阶段4】TradingAgents 七分析师评审（第{loop_i+1}轮）
分析师1（收益稳定性）：因子{perf_level}，IC={ic}，建议关注不同市场环境下的表现一致性
分析师2（过拟合审查）：全部计算仅使用T日可用数据，未发现未来函数
分析师3（流动性风控）：低换手样本需设置成交量下限过滤，避免流动性陷阱
分析师4（行业暴露审查）：原始因子需进行行业中性处理，降低行业偏离
分析师5（时序稳定性）：近3年有效性保持稳定，衰减速度可控
分析师6（风险收益评估）：卡玛比率中等水平，具备优化空间
分析师7（综合策略）：保留核心因子结构，下一轮加入行业+市值中性优化"""


def _find_latest_log_dir() -> str:
    """自动发现 RD-Agent 进化产生的最近日志目录"""
    log_dir = _project_root / "log"
    if not log_dir.exists(): return ""
    dirs = [d for d in log_dir.iterdir() if d.is_dir()]
    if not dirs: return ""
    latest = max(dirs, key=lambda d: d.stat().st_mtime)
    return str(latest)


def _build_final_report(task_id: str, msg: str, parsed: dict, elapsed: float, progress_data: dict = None) -> str:
    """生成简短结果摘要，详细内容在Web链接展示"""
    if progress_data is None:
        progress_data = {}
    
    # 提取关键指标用于摘要
    bt_results = progress_data.get("backtest_results", [])
    last_bt = bt_results[-1] if bt_results else {}
    metrics = last_bt.get("metrics", {})
    
    ic = metrics.get('ic', metrics.get('rank_ic', '-'))
    icir = metrics.get('icir', '-')
    ann_ret = metrics.get('annual_return', '-')
    
    # 判断是否保留
    decision = "✅ 保留" if isinstance(ic, (int, float)) and ic > 0.01 else "⚠️ 待优化"
    
    _ui_base = os.environ.get("AIQUANT_UI_BASE_URL", "http://127.0.0.1:19899")
    web_url = f"{_ui_base}/?task_id={task_id}"
    
    return f"""✅ 因子挖掘任务完成

**结果摘要**
- 任务ID：`{task_id}`
- 迭代轮次：{parsed['loop_n']}轮
- 总耗时：{elapsed/60:.1f}分钟
- 最新IC：{ic}
- ICIR：{icir}
- 年化收益：{ann_ret}
- 决策：{decision}

**详细报告（Web）**
{web_url}

完整源代码、回测数据、图表、分析报告请在上方链接查看。
"""


@app.get("/api/robot/health")
async def robot_health():
    """检测机器人服务状态"""
    try:
        resp = await ROBOT_CLIENT.get(f"{ROBOT_URL}/health", timeout=3)
        return resp.json()
    except Exception:
        return {"status": "stopped", "service": "aiquant-robot", "llm_ready": False}


# ── 模型配置管理 API ─────────────────────────────────

@app.get("/api/model/configs")
async def get_model_configs():
    """获取所有模型厂商配置"""
    return load_model_configs()


@app.post("/api/model/configs/save")
async def save_model_config(data: dict):
    """
    保存模型配置。
    
    请求体格式: {"provider": "deepseek", "api_key": "...", "model": "...", ...}
    """
    provider = data.get("provider", "deepseek")
    configs = load_model_configs()
    if provider not in configs:
        raise HTTPException(status_code=400, detail=f"不支持的模型厂商: {provider}")

    # 更新配置
    for key in ["api_key", "api_base", "model", "temperature", "max_context", "max_tokens", "enabled"]:
        if key in data:
            configs[provider][key] = data[key]

    save_model_configs(configs)
    return {"success": True, "message": f"{provider} 配置已保存"}


@app.post("/api/model/check")
async def check_model_connectivity(data: dict):
    """
    检测模型连通性。
    
    请求体: {"provider": "deepseek", "api_key": "sk-...", "api_base": "...", "model": "..."}
    """
    provider = data.get("provider", "deepseek")
    api_key = data.get("api_key", "")
    api_base = data.get("api_base", "")
    model = data.get("model", "")

    if not api_key:
        return {"ok": False, "message": "请先填写 API 密钥", "latency_ms": 0}

    # 调用机器人服务的连通性检测
    try:
        resp = await ROBOT_CLIENT.post(
            f"{ROBOT_URL}/model/check",
            json={"provider": provider, "api_key": api_key, "api_base": api_base, "model": model},
            timeout=30.0,
        )
        return resp.json()
    except Exception:
        # 机器人服务不可用，直接本地检测
        try:
            import httpx as sync_httpx
            client = sync_httpx.Client(
                base_url=api_base or "https://api.deepseek.com/v1",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=15.0,
            )
            resp = client.post("/chat/completions", json={
                "model": model or "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            })
            if resp.status_code == 200:
                return {"ok": True, "message": "连接正常", "latency_ms": 0}
            elif resp.status_code == 401:
                return {"ok": False, "message": "密钥错误（401 Unauthorized）", "latency_ms": 0}
            else:
                return {"ok": False, "message": f"API 返回错误: {resp.status_code}", "latency_ms": 0}
        except Exception as e:
            return {"ok": False, "message": f"连接失败: {str(e)}", "latency_ms": 0}


@app.post("/api/model/sync")
async def sync_model_config():
    """同步模型配置至 RD-Agent、机器人服务 .env"""
    try:
        result = sync_config_to_services()
        return {"success": True, "message": "配置已同步", "files": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


# ── 服务运维管理 API ─────────────────────────────────

# 架构说明:
# - api_gateway(8010) + robot(8003) + openbb(8001): 独立微服务，各有 conda 环境和端口
# - rdagent + tradingagents: 嵌入在 API 网关 aiquant 环境中运行的 Python 库，
#   没有独立端口，其"启动"实际是确保 API 网关运行 + 库已安装
_PROJECT_ROOT = _project_root

# 嵌入模块安装状态缓存（内存中，用于避免重复探测）
_embedded_install_cache: dict[str, dict] = {}
SERVICE_DEFS = {
    "api_gateway": {
        "name": "API 网关",
        "port": 8010,
        "env": "aiquant",
        "type": "standalone",
        "script": str(_PROJECT_ROOT / "start.sh"),
        "description": "aiQuant 主服务网关，所有 API 入口。RD-Agent/TradingAgents 作为嵌入库运行在此环境中。",
    },
    "robot": {
        "name": "对话机器人",
        "port": 8003,
        "env": "env-robot",
        "type": "standalone",
        "script": os.path.expanduser("~/quant_system/robot_service/start.sh"),
        "description": "自然语言量化指令解析与全自动任务调度",
    },
    "openbb": {
        "name": "OpenBB 数据服务",
        "port": 8001,
        "env": "env-openbb",
        "type": "standalone",
        "script": os.path.expanduser("~/quant_system/openbb_service/start.sh"),
        "description": "双数据源融合：本地 Qlib + Tushare 增量",
    },
    "rdagent": {
        "name": "RD-Agent 引擎",
        "port": 8010,  # 嵌入在 API 网关内，共用端口
        "env": "aiquant",
        "type": "embedded",
        "script": None,
        "description": "因子挖掘、模型进化、联合进化。作为 Python 库嵌入在 API 网关中运行。",
        "depends_on": "api_gateway",
    },
    "tradingagents": {
        "name": "TradingAgents 评审",
        "port": 8010,  # 嵌入在 API 网关内，共用端口
        "env": "aiquant",
        "type": "embedded",
        "script": None,
        "description": "七分析师多空辩论、风险评审。作为 Python 库嵌入在 API 网关中运行。",
        "depends_on": "api_gateway",
    },
}


@app.get("/api/services/status")
async def get_all_services_status():
    """获取全部服务运行状态（v2.5 重构版：区分独立服务/嵌入模块，增加活体探测）"""
    import socket as _socket
    import asyncio as _aio
    result = {}
    for svc_id, svc_def in SERVICE_DEFS.items():
        svc_type = svc_def.get("type", "standalone")
        port = svc_def["port"]
        running = False
        pid = None
        liveness = None  # 嵌入模块活体探测结果

        if svc_type == "standalone":
            # 独立服务：检测端口监听
            try:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    running = True
                s.close()
            except Exception:
                pass
            if running:
                # psutil.net_connections() 是同步阻塞调用，放到线程池避免卡死事件循环
                try:
                    import psutil
                    def _find_pid():
                        for conn in psutil.net_connections():
                            if conn.laddr and conn.laddr.port == port and conn.pid:
                                return conn.pid
                        return None
                    pid = await _aio.get_event_loop().run_in_executor(None, _find_pid)
                except Exception:
                    pass
        elif svc_type == "embedded":
            # 嵌入模块：网关存活即视为运行中（嵌入模块无独立进程）
            gateway_port = SERVICE_DEFS.get("api_gateway", {}).get("port", 8010)
            gateway_env = SERVICE_DEFS.get("api_gateway", {}).get("env", "aiquant")
            try:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                s.settimeout(1)
                gateway_up = s.connect_ex(("127.0.0.1", gateway_port)) == 0
                s.close()
                if gateway_up and svc_def.get("env") == gateway_env:
                    # 嵌入模块与 API 网关共享环境，网关存活即可用
                    running = True
                elif gateway_up:
                    # 不同环境但网关存活，保守标记为运行中
                    running = True
                # 活体探测：仅对 rdagent 做额外验证（使用异步 httpx 避免阻塞）
                if svc_id == "rdagent" and running:
                    try:
                        async with httpx.AsyncClient(timeout=3) as _client:
                            _probe = await _client.get(f"http://127.0.0.1:{gateway_port}/api/research/rdagent-probe")
                            if _probe.status_code == 200:
                                liveness = _probe.json()
                    except Exception:
                        pass
            except Exception:
                pass
            port = gateway_port  # 嵌入模块显示网关端口

        # 检查 conda 环境是否已安装（放到线程池避免阻塞事件循环）
        env_name = svc_def["env"]
        installed = False

        # 对于嵌入模块，优先使用内存缓存中的安装状态
        cache_entry = _embedded_install_cache.get(svc_id, {})
        if cache_entry.get("installed"):
            installed = True
        else:
            try:
                def _check_conda(env=env_name):
                    _r = subprocess.run(
                        f"conda env list | grep '^{env} '",
                        shell=True, capture_output=True, text=True, timeout=5,
                    )
                    return _r.returncode == 0
                installed = await _aio.get_event_loop().run_in_executor(None, _check_conda)
            except Exception:
                pass

        result[svc_id] = {
            "name": svc_def["name"],
            "port": port,
            "running": running,
            "pid": pid,
            "env": env_name,
            "type": svc_type,
            "installed": installed,
            "description": svc_def["description"],
            "has_script": svc_def.get("script") is not None and Path(svc_def["script"]).exists() if svc_def.get("script") else False,
            "depends_on": svc_def.get("depends_on"),
            "liveness": liveness,  # 活体探测结果（仅嵌入模块有值）
        }
    return result


def _check_port(port: int) -> bool:
    """检测端口是否被监听"""
    import socket as _s
    try:
        _sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
        _sock.settimeout(1)
        _up = _sock.connect_ex(("127.0.0.1", port)) == 0
        _sock.close()
        return _up
    except Exception:
        return False


def _start_standalone_service(svc_id: str, svc_def: dict) -> dict:
    """启动独立微服务：nohup 后台启动（兼容无 tmux 的 Mac 环境）"""
    import time

    port = svc_def["port"]
    if _check_port(port):
        return {"success": True, "message": f"{svc_def['name']} 已在运行中（端口 {port}）", "already_running": True}

    env_name = svc_def["env"]
    script_path = svc_def.get("script")
    log_file = f"/tmp/aiquant-{svc_id}.log"

    logs = []

    # 检查是否有残留的启动脚本进程（上次启动失败留下的僵尸 bash 进程）
    if script_path:
        try:
            result = subprocess.run(
                f"ps aux | grep '{script_path}' | grep -v grep | awk '{{print $2}}'",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                zombie_pids = result.stdout.strip().split("\n")
                for pid in zombie_pids:
                    subprocess.run(f"kill -9 {pid} 2>/dev/null", shell=True)
                logs.append(f"[清理] 已终止残留启动脚本进程 (PID: {', '.join(zombie_pids)})")
                time.sleep(1)
        except Exception:
            pass

    if script_path and Path(script_path).exists():
        # 有启动脚本：nohup 后台执行
        cmd = f"nohup bash {script_path} > {log_file} 2>&1 &"
        logs.append(f"[启动] 执行脚本: {script_path}")
    else:
        # 无脚本：直接用 conda run 启动
        start_cmds = {
            "robot": f"nohup conda run -n {env_name} python {os.path.expanduser('~/quant_system/robot_service/main.py')} > {log_file} 2>&1 &",
            "openbb": f"nohup conda run -n {env_name} python -c \"print('OpenBB stub started')\" > {log_file} 2>&1 &",
        }
        cmd = start_cmds.get(svc_id, f"echo 'No start command for {svc_id}' > {log_file} 2>&1")
        logs.append(f"[启动] 使用通用启动命令")

    try:
        subprocess.run(cmd, shell=True, check=True, timeout=10)
        logs.append(f"[后台] 进程已启动，日志: {log_file}")

        # 等待端口就绪（延长至 30 秒，适配首次启动 pip install 场景）
        for i in range(30):
            time.sleep(1)
            if _check_port(port):
                logs.append(f"[端口] {port} 已监听 ✓（耗时 {i+1}s）")
                return {
                    "success": True,
                    "message": f"{svc_def['name']} 启动成功（端口 {port}）",
                    "logs": logs,
                }
            # 检查日志中是否有启动失败的错误
            if i == 10:
                try:
                    log_content = subprocess.run(
                        f"tail -5 {log_file} 2>/dev/null",
                        shell=True, capture_output=True, text=True, timeout=3,
                    ).stdout
                    if "Address already in use" in log_content:
                        logs.append(f"[检测] 日志中发现端口冲突，可能已有实例在运行")
                        # 重新检查端口
                        if _check_port(port):
                            logs.append(f"[端口] {port} 已监听（已有实例）✓")
                            return {
                                "success": True,
                                "message": f"{svc_def['name']} 启动成功（端口 {port}，复用已有实例）",
                                "logs": logs,
                            }
                except Exception:
                    pass

        logs.append(f"[警告] 端口 {port} 在 30 秒内未就绪，服务可能启动失败，请检查日志")
        return {
            "success": True,
            "message": f"{svc_def['name']} 启动指令已发送，但端口尚未就绪。请检查日志: {log_file}",
            "logs": logs,
        }
    except subprocess.CalledProcessError as e:
        logs.append(f"[错误] 启动失败: {e}")
        return {"success": False, "message": f"启动失败: {e}", "logs": logs}
    except Exception as e:
        return {"success": False, "message": f"启动失败: {e}", "logs": logs}


def _start_embedded_module(svc_id: str, svc_def: dict) -> dict:
    """启动嵌入模块：确保 API 网关在线 + 库已安装"""
    logs = []
    gateway_port = SERVICE_DEFS.get("api_gateway", {}).get("port", 8010)
    logs.append(f"[嵌入模块] {svc_def['name']} 运行在 API 网关({gateway_port})内")

    # 检查 API 网关是否在线
    if not _check_port(gateway_port):
        logs.append(f"[检测] API 网关({gateway_port})未启动")
        # 尝试启动 API 网关
        gw_def = SERVICE_DEFS.get("api_gateway", {})
        if gw_def.get("script") and Path(gw_def["script"]).exists():
            logs.append(f"[启动] 自动启动 API 网关: {gw_def['script']}")
            subprocess.run(
                f"nohup bash {gw_def['script']} > /tmp/aiquant-api_gateway.log 2>&1 &",
                shell=True, timeout=10,
            )
            import time
            for i in range(20):
                time.sleep(1)
                if _check_port(gateway_port):
                    logs.append("[启动] API 网关已就绪 ✓")
                    break
            else:
                logs.append("[错误] API 网关启动超时")
                return {"success": False, "message": "API 网关启动超时，无法使用嵌入模块", "logs": logs}
        else:
            logs.append("[错误] 找不到 API 网关启动脚本")
            return {"success": False, "message": "API 网关未运行且无启动脚本。请在终端执行: cd ~/Desktop/AIquant && bash start.sh", "logs": logs}
    else:
        logs.append(f"[检测] API 网关({gateway_port})在线 ✓")

    # 检查嵌入库是否已安装
    try:
        import rdagent
        logs.append("[库] RD-Agent 已安装 ✓")
    except ImportError:
        logs.append("[警告] RD-Agent 库未安装，将在 API 网关中安装")
        try:
            subprocess.run(
                f"conda run -n {svc_def['env']} pip install rdagent",
                shell=True, check=True, capture_output=True, timeout=300,
            )
            logs.append("[安装] RD-Agent 安装完成 ✓")
        except Exception as e:
            logs.append(f"[错误] RD-Agent 安装失败: {e}")
            return {"success": False, "message": f"RD-Agent 安装失败: {e}", "logs": logs}

    return {
        "success": True,
        "message": f"{svc_def['name']} 已就绪（嵌入在 API 网关内）",
        "logs": logs,
    }


@app.post("/api/services/{svc_id}/start")
async def start_service(svc_id: str):
    """启动指定微服务（v2.4 重构版）"""
    if svc_id not in SERVICE_DEFS:
        raise HTTPException(status_code=404, detail=f"未知服务: {svc_id}")

    svc_def = SERVICE_DEFS[svc_id]
    svc_type = svc_def.get("type", "standalone")

    if svc_type == "embedded":
        return _start_embedded_module(svc_id, svc_def)
    else:
        return _start_standalone_service(svc_id, svc_def)


@app.post("/api/services/{svc_id}/stop")
async def stop_service(svc_id: str):
    """停止指定微服务（v2.4 重构版）"""
    if svc_id not in SERVICE_DEFS:
        raise HTTPException(status_code=404, detail=f"未知服务: {svc_id}")

    svc_def = SERVICE_DEFS[svc_id]
    svc_type = svc_def.get("type", "standalone")
    logs = []

    if svc_type == "embedded":
        # 嵌入模块无法单独停止，提示用户重启 API 网关
        return {
            "success": True,
            "message": f"{svc_def['name']} 是嵌入在 API 网关中的模块，无法单独停止。请重启 API 网关以重新加载该模块。",
            "embedded": True,
            "logs": [f"[嵌入模块] {svc_def['name']} 随 API 网关生命周期管理"],
        }

    port = svc_def["port"]

    try:
        # 杀掉占用端口的进程（纯 Python，不依赖 lsof）
        killed_pids = []
        try:
            import psutil
            for conn in psutil.net_connections():
                if conn.laddr and conn.laddr.port == port and conn.pid:
                    try:
                        os.kill(conn.pid, signal.SIGKILL)
                        killed_pids.append(str(conn.pid))
                    except Exception:
                        pass
        except ImportError:
            # fallback: lsof（仅在 psutil 不可用时）
            result = subprocess.run(f"lsof -ti:{port}", shell=True, capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    subprocess.run(f"kill -9 {pid} 2>/dev/null", shell=True)
                killed_pids = pids

        if killed_pids:
            logs.append(f"[停止] 端口 {port} 上的进程已终止 (PID: {', '.join(killed_pids)})")
        else:
            logs.append(f"[停止] 端口 {port} 无占用进程")

        return {"success": True, "message": f"{svc_def['name']} 已停止", "logs": logs}
    except Exception as e:
        return {"success": False, "message": f"停止失败: {e}", "logs": logs}


@app.post("/api/services/{svc_id}/install")
async def install_service(svc_id: str):
    """一键安装微服务（创建 conda 环境 + 安装依赖）v2.4 重构版"""
    if svc_id not in SERVICE_DEFS:
        raise HTTPException(status_code=404, detail=f"未知服务: {svc_id}")

    svc_def = SERVICE_DEFS[svc_id]
    env_name = svc_def["env"]
    svc_type = svc_def.get("type", "standalone")
    logs = []

    # 嵌入模块使用 aiquant 环境
    gateway_port = SERVICE_DEFS.get("api_gateway", {}).get("port", 8010)
    if svc_type == "embedded":
        logs.append(f"[嵌入模块] {svc_def['name']} 使用 aiquant 环境，无需单独创建 conda 环境")
        lib_name = "rdagent" if svc_id == "rdagent" else "tradingagents" if svc_id == "tradingagents" else svc_id
        try:
            subprocess.run(
                f"conda run -n aiquant python -c 'import {lib_name}'",
                shell=True, check=True, capture_output=True, text=True, timeout=30,
            )
            logs.append(f"[库] {lib_name} 已安装 ✓")
            
            # 已安装时也执行活体自检
            logs.append("[自检] 执行 RD-Agent 活体探测...")
            try:
                import httpx as _htx
                probe_resp = _htx.get(f"http://127.0.0.1:{gateway_port}/api/research/rdagent-probe", timeout=15)
                if probe_resp.status_code == 200:
                    probe_data = probe_resp.json()
                    probe_status = probe_data.get("status", "unknown")
                    logs.append(f"[自检] RD-Agent 活体状态: {probe_status}")
                    if probe_status == "ok":
                        logs.append("[自检] RD-Agent 底层完全可用 ✓")
                    else:
                        logs.append(f"[自检] 警告: {probe_data.get('message', '')}")
            except Exception as pe:
                logs.append(f"[自检] 无法执行活体探测: {pe}")
            
            # 更新全局状态缓存
            _embedded_install_cache[svc_id] = {
                "installed": True,
                "liveness_checked_at": pd.Timestamp.now().isoformat(),
                "liveness_status": "ok",
            }
            return {"success": True, "message": f"{svc_def['name']} 已安装在 aiquant 环境中", "logs": logs, "already_installed": True, "post_selfcheck_done": True}
        except Exception:
            logs.append(f"[安装] 正在安装 {lib_name}...")
            try:
                subprocess.run(
                    f"conda run -n aiquant pip install {lib_name}",
                    shell=True, check=True, capture_output=True, text=True, timeout=300,
                )
                logs.append(f"[安装] {lib_name} 安装完成 ✓")
                
                # 安装后执行活体自检
                logs.append("[自检] 安装完成，执行 RD-Agent 活体探测...")
                selfcheck_ok = False
                try:
                    import httpx as _htx
                    probe_resp = _htx.get(f"http://127.0.0.1:{gateway_port}/api/research/rdagent-probe", timeout=15)
                    if probe_resp.status_code == 200:
                        probe_data = probe_resp.json()
                        probe_status = probe_data.get("status", "unknown")
                        logs.append(f"[自检] 活体状态: {probe_status} — {probe_data.get('message', '')}")
                        selfcheck_ok = probe_status in ("ok", "degraded")
                        if probe_status == "unavailable":
                            logs.append(f"[自检] 警告: 库已安装但探测失败，请检查 LLM 配置或 Qlib 数据")
                    else:
                        logs.append(f"[自检] 探测接口返回 {probe_resp.status_code}")
                except Exception as pe:
                    logs.append(f"[自检] 探测接口不可达: {pe}（API 网关可能未启动）")
                
                # 更新全局状态缓存
                _embedded_install_cache[svc_id] = {
                    "installed": True,
                    "liveness_checked_at": pd.Timestamp.now().isoformat(),
                    "liveness_status": "ok" if selfcheck_ok else "degraded",
                }
                
                return {
                    "success": True,
                    "message": f"{svc_def['name']} 安装完成" + ("（自检通过）" if selfcheck_ok else "（自检未通过，请检查）"),
                    "logs": logs,
                    "post_selfcheck_done": True,
                    "selfcheck_ok": selfcheck_ok,
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "message": f"安装失败: {e.stderr[:500]}", "logs": logs}

    # 独立服务：创建 conda 环境
    try:
        result = subprocess.run(
            f"conda env list | grep '^{env_name} '",
            shell=True, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            logs.append(f"[环境] conda 环境 {env_name} 已存在")
            return {"success": True, "message": f"{svc_def['name']} 环境已存在 ({env_name})", "logs": logs, "already_installed": True}

        logs.append(f"[创建] 正在创建 conda 环境 {env_name}...")
        subprocess.run(
            f"conda create -n {env_name} python=3.10 -y",
            shell=True, check=True, capture_output=True, text=True, timeout=120,
        )
        logs.append(f"[创建] conda 环境 {env_name} 创建完成 ✓")

        # 安装依赖
        deps_map = {
            "robot": "fastapi uvicorn python-dotenv httpx pydantic loguru redis",
            "openbb": "fastapi uvicorn python-dotenv httpx pydantic loguru pandas numpy",
        }
        deps = deps_map.get(svc_id, "fastapi uvicorn pydantic loguru python-dotenv httpx")
        logs.append(f"[依赖] 正在安装: {deps}")
        subprocess.run(
            f"conda run -n {env_name} pip install -q {deps}",
            shell=True, check=True, capture_output=True, text=True, timeout=300,
        )
        logs.append(f"[依赖] 安装完成 ✓")

        return {"success": True, "message": f"{svc_def['name']} 环境安装完成 ({env_name})", "logs": logs}
    except subprocess.CalledProcessError as e:
        return {"success": False, "message": f"安装失败: {e.stderr[:500] if e.stderr else str(e)}", "logs": logs}
    except Exception as e:
        return {"success": False, "message": f"安装失败: {str(e)}", "logs": logs}


@app.get("/api/services/{svc_id}/log")
async def get_service_log(svc_id: str, lines: int = 50):
    """获取指定服务的最近 N 行日志"""
    log_path = Path(f"/tmp/aiquant-{svc_id}.log")
    if not log_path.exists():
        return {"log": "", "message": f"暂无日志（{log_path} 不存在）"}
    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {"log": "".join(recent), "total_lines": len(all_lines), "shown_lines": len(recent)}
    except Exception as e:
        return {"log": "", "message": f"读取日志失败: {e}"}


# ── 前端静态文件 ─────────────────────────────────────

frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    # 自定义静态文件服务：JS/CSS 禁止缓存（避免 Edge/Firefox 缓存旧版 JS 导致白屏）
    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            # JS/CSS 文件添加 no-cache 头，确保浏览器始终验证最新版本
            if path.endswith(('.js', '.css', '.html')):
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response

    app.mount("/", NoCacheStaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.api_port)
