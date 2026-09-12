"""
RD-Agent Python API 适配器

直接调用 RD-Agent 的核心 RDLoop 进行：
- fin_factor: 因子挖掘 + Qlib 回测
- fin_model: 模型进化 + Qlib 回测  
- fin_quant: 因子+模型联合进化
- fin_factor_report: 从研报 PDF 提取因子

RD-Agent 的完整研究循环:
  propose(LLM) → exp_gen(LLM) → coding(CoSTEER) → running(Qlib回测) → feedback(LLM) → 循环
"""
import asyncio
import os
from pathlib import Path
from typing import Optional
from loguru import logger

from backend.shared.config import settings


import threading as _threading
_ADAPTER_LOCK = _threading.Lock()


class RDAgentAdapter:
    """
    RD-Agent 适配器 — 封装 RD-Agent 的 Python API。
    
    RD-Agent 提供四种研究模式：
    1. fin_factor   — 纯因子挖掘（Hypothesis → Code → Qlib回测 → Feedback）
    2. fin_model    — 纯模型进化（模型架构搜索 + Qlib回测）
    3. fin_quant    — 联合进化（Bandit算法选择每轮做因子还是模型）
    4. fin_factor_report — 从研报 PDF 提取因子
    """

    def __init__(self):
        self._configure_rdagent_llm()
        self._status_cache: Optional[dict] = None
        self._check_environment()
        # 在后台线程中预热状态缓存，避免首次 API 请求阻塞事件循环
        _threading.Thread(target=self._prewarm_cache, daemon=True).start()

    def _prewarm_cache(self):
        """后台预热：带锁，避免主线程同时调用时 Qlib 双初始化死锁"""
        try:
            self.check_status()
        except Exception:
            pass

    @staticmethod
    def _configure_rdagent_llm():
        """配置 RD-Agent LLM（均衡 API 进程和 Celery Worker 的行为）"""
        import os as _os
        from dotenv import load_dotenv as _load_dotenv
        _env_file = _os.path.join(_os.path.dirname(__file__), "..", "..", ".env")
        if _os.path.exists(_env_file):
            _load_dotenv(_env_file, override=True)
        _deepseek_key = _os.environ.get("DEEPSEEK_API_KEY", "")
        if _deepseek_key:
            try:
                from rdagent.oai.llm_conf import LLM_SETTINGS as _LLM_SETTINGS
                _LLM_SETTINGS.chat_model = "deepseek/deepseek-v4-flash"
                _LLM_SETTINGS.openai_api_key = _deepseek_key
            except Exception:
                pass
            _proxy_key = _os.environ.get("LITELLM_PROXY_API_KEY", "") or _os.environ.get("SILICONFLOW_API_KEY", "")
            if _proxy_key:
                _os.environ["LITELLM_PROXY_API_KEY"] = _proxy_key
                _os.environ.setdefault("LITELLM_PROXY_API_BASE", _os.environ.get("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1"))
                try:
                    from rdagent.oai.backend.litellm import LITELLM_SETTINGS as _LITELLM_SETTINGS
                    _LITELLM_SETTINGS.embedding_model = "litellm_proxy/BAAI/bge-m3"
                except Exception:
                    pass
        else:
            # 本地 LLM（llama-server / Qwen3）配置
            _openai_key = _os.environ.get("OPENAI_API_KEY", "") or _os.environ.get("LLM_API_KEY", "")
            _openai_base = _os.environ.get("OPENAI_API_BASE", "") or _os.environ.get("LLM_API_BASE", "")
            _chat_model = _os.environ.get("CHAT_MODEL", "") or _os.environ.get("LLM_MODEL", "")
            if _openai_key and _chat_model:
                if not _chat_model.startswith("openai/"):
                    _chat_model = f"openai/{_chat_model}"
                try:
                    from rdagent.oai.llm_conf import LLM_SETTINGS as _LLM_SETTINGS
                    from rdagent.oai.backend.litellm import LITELLM_SETTINGS as _LITELLM_SETTINGS
                    _LLM_SETTINGS.chat_model = _chat_model
                    _LLM_SETTINGS.openai_api_key = _openai_key
                    _LITELLM_SETTINGS.chat_model = _chat_model
                    # 本地 LLM 兼容性配置
                    for _k, _v in dict(
                        chat_stream=False,
                        enable_response_schema=False,
                        max_retry=3,
                        retry_wait_seconds=5,
                        timeout_fail_limit=3,
                        reasoning_think_rm=True,
                        chat_max_tokens=8192,
                        chat_token_limit=32768,
                    ).items():
                        try:
                            setattr(_LITELLM_SETTINGS, _k, _v)
                        except Exception:
                            pass
                        try:
                            setattr(_LLM_SETTINGS, _k, _v)
                        except Exception:
                            pass
                    # 全局超时
                    import litellm as _litellm
                    _litellm.request_timeout = 300
                except Exception as _e:
                    logger.warning(f"本地 LLM 配置失败: {_e}")

    @staticmethod
    def _check_environment():
        """检查 RD-Agent 运行环境"""
        try:
            import rdagent
            logger.info(f"RD-Agent 可用")
        except ImportError:
            raise RuntimeError(
                "RD-Agent 未安装。请运行: pip install rdagent\n"
                "注意: RD-Agent 需要 Qlib 数据和 LLM API Key。"
            )

        # 检查 Qlib 数据
        qlib_data = os.path.expanduser("~/.qlib/qlib_data/cn_data")
        if not Path(qlib_data).exists():
            logger.warning(
                f"Qlib 数据目录不存在: {qlib_data}\n"
                f"请先通过数据管线获取数据并导出到该路径。"
            )
        else:
            logger.info(f"Qlib 数据目录: {qlib_data}")

    # ── 因子挖掘 ──────────────────────────────────────

    def _extract_factors_from_workspace(self, factor_loop) -> list:
        """从 RD-Agent workspace 提取生成的因子代码和回测结果"""
        import json as _json
        import glob

        factors = []
        try:
            # 获取 workspace 路径
            workspace_dir = os.path.expanduser(
                os.environ.get("RD_AGENT_WORKSPACE", "~/RD-Agent_workspace")
            )
            # 也检查项目内的 workspace
            alt_workspace = os.path.expanduser(
                os.path.join(os.path.dirname(__file__), "..", "..", "git_ignore_folder", "RD-Agent_workspace")
            )

            for ws_dir in [alt_workspace, workspace_dir]:
                if not os.path.isdir(ws_dir):
                    continue

                # 查找所有 factor.py 文件（每个因子一个目录）
                factor_files = sorted(glob.glob(os.path.join(ws_dir, "*", "factor.py")), reverse=True)
                for fp in factor_files[:20]:  # 最多取最近 20 个
                    factor_id = os.path.basename(os.path.dirname(fp))
                    try:
                        code = open(fp, "r").read()
                    except Exception:
                        code = ""

                    # 提取因子名称
                    factor_name = "unknown"
                    for line in code.split("\n"):
                        if "def calculate_" in line:
                            factor_name = line.split("def calculate_")[1].split("(")[0].strip()
                            break

                    # 查找同目录下的回测结果
                    backtest_results = {}
                    result_dir = os.path.dirname(fp)
                    for json_file in glob.glob(os.path.join(result_dir, "*.json")):
                        try:
                            data = _json.load(open(json_file))
                            if isinstance(data, dict):
                                # 递归查找 IC / Sharpe / return 等指标
                                for key in ["IC", "ICIR", "Sharpe", "annualized_return", "max_drawdown"]:
                                    val = self._find_key_recursive(data, key)
                                    if val is not None:
                                        backtest_results[key] = val
                        except Exception:
                            pass

                    factors.append({
                        "factor_id": factor_id,
                        "name": factor_name,
                        "code": code[:500],  # 截断到 500 字符
                        "backtest": backtest_results if backtest_results else None,
                    })

                if factors:
                    break  # 找到因子就不检查下一个目录

            logger.info(f"从 workspace 提取了 {len(factors)} 个因子")
        except Exception as e:
            logger.warning(f"提取因子失败: {e}")

        return factors

    @staticmethod
    def _find_key_recursive(d, target_key, depth=0):
        """递归查找 dict 中的指定 key"""
        if depth > 5 or not isinstance(d, dict):
            return None
        if target_key in d:
            return d[target_key]
        for v in d.values():
            if isinstance(v, dict):
                result = RDAgentAdapter._find_key_recursive(v, target_key, depth + 1)
                if result is not None:
                    return result
        return None

    def run_factor_evolution(
        self,
        step_n: Optional[int] = None,
        loop_n: Optional[int] = None,
        all_duration: Optional[str] = None,
        checkout: bool = True,
        path: Optional[str] = None,
    ) -> dict:
        """
        启动 RD-Agent 因子进化循环。
        
        RD-Agent 会自动：
        1. HypothesisGen (LLM): 生成因子假设
        2. Hypothesis2Experiment (LLM): 将假设转为可执行的实验
        3. FactorCoSTEER (CoSTEER): 生成因子实现代码
        4. FactorRunner: 运行代码 → 合并因子数据 → Qlib 回测
        5. Experiment2Feedback (LLM): 分析回测结果 → 生成反馈
        
        Args:
            step_n: 执行的 step 数（None = 全部 steps）
            loop_n: 执行的 loop 数（None = evolving_n）
            all_duration: 运行时长限制，如 "1h" / "30m"
            checkout: 是否从 checkpoint 恢复
            path: 已有 session 路径（用于断点续跑）
        
        Returns:
            {"success": bool, "output": str, "log_dir": str, "factors": list, "report_url": str}
        """
        from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
        from rdagent.app.qlib_rd_loop.conf import FACTOR_PROP_SETTING

        logger.info("=== RD-Agent 因子进化启动 ===")
        logger.info(f"配置: evolving_n={FACTOR_PROP_SETTING.evolving_n}")

        if path is None:
            factor_loop = FactorRDLoop(FACTOR_PROP_SETTING)
        else:
            factor_loop = FactorRDLoop.load(path, checkout=checkout)

        try:
            # 复用主线程 uvloop 全局事件循环，模块顶层 nest_asyncio 已 patch
            loop = asyncio.get_event_loop()
            loop.run_until_complete(factor_loop.run(
                step_n=step_n, loop_n=loop_n, all_duration=all_duration,
            ))
            logger.info("因子进化完成")

            # 从 workspace 提取因子代码和回测结果
            factors = self._extract_factors_from_workspace(factor_loop)
            log_dir = str(factor_loop.logger.log_dir if hasattr(factor_loop, 'logger') else "")

            return {
                "success": True,
                "output": f"因子进化完成，共生成 {len(factors)} 个因子",
                "log_dir": log_dir,
                "factors": factors,
                "report_url": f"/api/research/factor-report?log_dir={log_dir}" if log_dir else None,
            }
        except Exception as e:
            logger.error(f"因子进化失败: {e}")
            return {"success": False, "output": str(e)}

    # ── 模型进化 ──────────────────────────────────────

    def run_model_evolution(
        self,
        step_n: Optional[int] = None,
        loop_n: Optional[int] = None,
        all_duration: Optional[str] = None,
        checkout: bool = True,
        path: Optional[str] = None,
    ) -> dict:
        """
        启动 RD-Agent 模型进化循环。
        
        自动搜索最优模型架构（LGBM/GRU/LSTM/Transformer 等），
        通过 Qlib 回测评估模型表现。
        """
        from rdagent.app.qlib_rd_loop.model import ModelRDLoop
        from rdagent.app.qlib_rd_loop.conf import MODEL_PROP_SETTING

        logger.info("=== RD-Agent 模型进化启动 ===")
        logger.info(f"配置: evolving_n={MODEL_PROP_SETTING.evolving_n}")

        if path is None:
            model_loop = ModelRDLoop(MODEL_PROP_SETTING)
        else:
            model_loop = ModelRDLoop.load(path, checkout=checkout)

        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(model_loop.run(
                step_n=step_n, loop_n=loop_n, all_duration=all_duration,
            ))
            logger.info("模型进化完成")
            return {
                "success": True,
                "output": "模型进化完成",
            }
        except Exception as e:
            logger.error(f"模型进化失败: {e}")
            return {"success": False, "output": str(e)}

    # ── 联合进化（因子+模型）────────────────────────

    def run_joint_evolution(
        self,
        step_n: Optional[int] = None,
        loop_n: Optional[int] = None,
        all_duration: Optional[str] = None,
        checkout: bool = True,
        path: Optional[str] = None,
    ) -> dict:
        """
        启动 RD-Agent 联合进化循环（因子+模型）。
        
        使用 Bandit 算法在每轮自动选择：
        - 做因子挖掘（发现新 alpha）
        - 做模型优化（提升模型拟合能力）
        
        这是 RD-Agent 最强大的模式。
        """
        from rdagent.app.qlib_rd_loop.quant import QuantRDLoop
        from rdagent.app.qlib_rd_loop.conf import QUANT_PROP_SETTING

        logger.info("=== RD-Agent 联合进化启动（因子+模型）===")
        logger.info(f"配置: evolving_n={QUANT_PROP_SETTING.evolving_n}")
        logger.info(f"Action selection: {QUANT_PROP_SETTING.action_selection}")

        if path is None:
            quant_loop = QuantRDLoop(QUANT_PROP_SETTING)
        else:
            quant_loop = QuantRDLoop.load(path, checkout=checkout)

        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(quant_loop.run(
                step_n=step_n, loop_n=loop_n, all_duration=all_duration,
            ))
            logger.info("联合进化完成")
            return {
                "success": True,
                "output": "联合进化完成",
            }
        except Exception as e:
            logger.error(f"联合进化失败: {e}")
            return {"success": False, "output": str(e)}

    # ── 从研报提取因子 ──────────────────────────────

    def run_factor_from_report(
        self,
        report_folder: Optional[str] = None,
        all_duration: Optional[str] = None,
        checkout: bool = True,
        path: Optional[str] = None,
    ) -> dict:
        """
        从研报 PDF 中自动提取因子。
        
        RD-Agent 会：
        1. 读取 PDF 研报
        2. LLM 提取因子描述和公式
        3. 生成因子实现代码
        4. Qlib 回测验证
        
        Args:
            report_folder: 包含 PDF 研报的文件夹路径
        """
        from rdagent.app.qlib_rd_loop.factor_from_report import FactorReportLoop

        logger.info("=== RD-Agent 研报因子提取启动 ===")

        if path is None and report_folder is None:
            report_loop = FactorReportLoop()
        elif path is not None:
            report_loop = FactorReportLoop.load(path, checkout=checkout)
        else:
            report_loop = FactorReportLoop(report_folder=report_folder)

        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(report_loop.run(all_duration=all_duration))
            logger.info("研报因子提取完成")
            return {
                "success": True,
                "output": "研报因子提取完成",
            }
        except Exception as e:
            logger.error(f"研报因子提取失败: {e}")
            return {"success": False, "output": str(e)}

    # ── 状态检查（带线程锁，防止 Qlib 双初始化死锁） ──────────────

    def check_status(self) -> dict:
        """检查 RD-Agent 运行环境状态（缓存结果，避免每次请求阻塞事件循环）"""
        if self._status_cache is not None:
            return self._status_cache

        with _ADAPTER_LOCK:
            # 二次检查：锁持有期间缓存可能已被后台线程写入
            if self._status_cache is not None:
                return self._status_cache

            qlib_data = os.path.expanduser("~/.qlib/qlib_data/cn_data")
            qlib_data_exists = Path(qlib_data).exists()

            # 检查 Qlib 能否初始化（仅在缓存未命中时执行一次）
            qlib_ok = False
            if qlib_data_exists:
                try:
                    import qlib
                    qlib.init(provider_uri=qlib_data, region="cn")
                    from qlib.data import D
                    instruments = D.instruments(market="all")
                    D.list_instruments(instruments)
                    qlib_ok = True
                except Exception as e:
                    logger.warning(f"Qlib 初始化失败: {e}")

            # 检查 LLM 配置
            from rdagent.oai.llm_conf import LLM_SETTINGS
            llm_configured = bool(
                LLM_SETTINGS.openai_api_key
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
            )

            # 识别 LLM provider
            chat_model = LLM_SETTINGS.chat_model
            if "deepseek" in str(chat_model).lower():
                llm_provider = "deepseek"
            elif LLM_SETTINGS.chat_openai_base_url:
                llm_provider = "custom"
            else:
                llm_provider = "openai"

            self._status_cache = {
                "rdagent_installed": True,
                "qlib_data_exists": qlib_data_exists,
                "qlib_data_path": qlib_data,
                "qlib_ok": qlib_ok,
                "llm_configured": llm_configured,
                "llm_model": chat_model,
                "llm_backend": LLM_SETTINGS.backend,
                "llm_provider": llm_provider,
                "llm_base_url": LLM_SETTINGS.chat_openai_base_url or os.environ.get("OPENAI_API_BASE", ""),
            }

        return self._status_cache
