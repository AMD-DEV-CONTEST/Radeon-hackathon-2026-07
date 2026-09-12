"""
aiquant 引擎服务 — 核心量化研究循环

整合:
1. RD-Agent Python API（因子挖掘 + 模型进化 + 联合进化 + Qlib回测）
2. 独立回测引擎（快速 IC/分层回测，不依赖 Qlib）
3. LLM 因子生成器（论文→因子表达式）
4. Feedback-Agent 长期记忆
"""
import json
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger

from backend.shared.config import settings
from backend.engine.rd_agent_adapter import RDAgentAdapter
from backend.engine.backtest_engine import (
    IndependentBacktestEngine,
    BacktestConfig,
    factor_result_to_dict,
)
from backend.engine.factor_generator import LLMFactorGenerator


class RDAgentEngine:
    """
    量化因子引擎
    
    双引擎架构：
    - 主引擎: RD-Agent（完整研究循环 + Qlib 回测）
    - 辅助引擎: IndependentBacktestEngine（快速验证，不依赖 LLM）
    """

    def __init__(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="aiquant_"))
        self.backtest_engine = IndependentBacktestEngine(
            BacktestConfig(
                start_date=settings.backtest_start,
                end_date=settings.backtest_end,
            )
        )
        self.factor_generator = LLMFactorGenerator()
        
        # 尝试初始化 RD-Agent 适配器
        try:
            self.rd_adapter = RDAgentAdapter()
            self._use_rdagent = True
        except (ImportError, RuntimeError) as e:
            logger.warning(f"RD-Agent 不可用: {e}，将使用独立引擎")
            self.rd_adapter = None
            self._use_rdagent = False

        status = "RD-Agent" if self._use_rdagent else "独立引擎"
        logger.info(f"引擎初始化: {status}")

    # ── 因子进化 ──────────────────────────────────────

    def run_factor_evolution(
        self,
        loop_n: int = None,
        step_n: int = None,
        all_duration: str = None,
        checkout: bool = True,
    ) -> dict:
        """
        执行因子进化循环。
        
        优先使用 RD-Agent（完整 Qlib 回测），不可用时使用独立引擎。
        
        RD-Agent 自动流程：
        LLM生成假设 → CoSTEER写代码 → 运行代码 → 合并因子 → Qlib LGBM回测 → LLM分析反馈
        
        Args:
            loop_n: loop 数量（None = 使用默认 evolving_n）
            step_n: step 数量
            all_duration: 运行时长限制 "1h" / "30m"
            checkout: 是否从 checkpoint 恢复
        """
        if self._use_rdagent:
            logger.info("使用 RD-Agent 执行因子进化")
            return self.rd_adapter.run_factor_evolution(
                loop_n=loop_n,
                step_n=step_n,
                all_duration=all_duration,
                checkout=checkout,
            )

        # Fallback: 独立引擎
        logger.info("RD-Agent 不可用，使用独立引擎")
        return self._run_independent_evolution()

    def _run_independent_evolution(self) -> dict:
        """独立因子进化（LLM生成 + 简单IC回测）"""
        factors = self.factor_generator._heuristic_factors(n=10)
        return {
            "success": True,
            "output": "独立引擎生成启发式因子（请配置 LLM API Key 和 Qlib 数据以使用 RD-Agent 完整流程）",
            "workspace": str(self.workspace),
            "factors": factors,
            "engine": "independent",
        }

    # ── 模型进化 ──────────────────────────────────────

    def run_model_evolution(
        self,
        loop_n: int = None,
        step_n: int = None,
        all_duration: str = None,
        checkout: bool = True,
    ) -> dict:
        """
        执行模型进化循环。
        
        RD-Agent 自动搜索最优模型架构（LGBM/GRU/LSTM/Transformer 等），
        在 Qlib 上回测评估。
        """
        if self._use_rdagent:
            return self.rd_adapter.run_model_evolution(
                loop_n=loop_n,
                step_n=step_n,
                all_duration=all_duration,
                checkout=checkout,
            )
        return {
            "success": False,
            "output": "模型进化需要 RD-Agent。请安装 rdagent 并配置 Qlib 数据。",
        }

    # ── 联合进化（因子+模型）────────────────────────

    def run_joint_evolution(
        self,
        loop_n: int = None,
        step_n: int = None,
        all_duration: str = None,
        checkout: bool = True,
    ) -> dict:
        """
        执行联合进化（因子+模型）。
        
        RD-Agent 使用 Bandit 算法在每轮选择最优行动：
        - factor: 挖掘新因子
        - model: 优化模型架构
        
        这是 RD-Agent 最完整的模式。
        """
        if self._use_rdagent:
            return self.rd_adapter.run_joint_evolution(
                loop_n=loop_n,
                step_n=step_n,
                all_duration=all_duration,
                checkout=checkout,
            )
        return {
            "success": False,
            "output": "联合进化需要 RD-Agent。请安装 rdagent 并配置 Qlib 数据。",
        }

    # ── 研报因子提取 ──────────────────────────────────

    def run_factor_from_report(
        self,
        report_folder: str = None,
        all_duration: str = None,
    ) -> dict:
        """从研报 PDF 提取因子"""
        if self._use_rdagent:
            return self.rd_adapter.run_factor_from_report(
                report_folder=report_folder,
                all_duration=all_duration,
            )
        return {
            "success": False,
            "output": "研报因子提取需要 RD-Agent。",
        }

    # ── 论文因子生成 + 快速回测 ────────────────────────

    def generate_and_backtest_from_paper(
        self,
        paper_title: str,
        paper_abstract: str = "",
        market_data: "pd.DataFrame" = None,
        n_factors: int = 5,
    ) -> dict:
        """从论文生成因子表达式并快速回测（使用独立引擎）"""
        logger.info(f"从论文生成因子: {paper_title[:50]}...")

        factors = self.factor_generator.generate_from_paper(
            paper_title, paper_abstract, n_factors
        )

        if market_data is None or market_data.empty:
            return {
                "success": True,
                "paper_title": paper_title,
                "factors": factors,
                "backtest_results": [],
                "engine": "llm_only",
                "message": "因子已生成。要使用 Qlib 完整回测，请先通过数据管线获取数据并启动 RD-Agent。",
            }

        results = self.backtest_engine.run_batch_backtest(
            df=market_data, factors=factors, forward_period=1
        )
        backtest_dicts = [factor_result_to_dict(r) for r in results]
        valid = [d for d in backtest_dicts if d.get("error") is None]
        valid.sort(key=lambda d: d.get("sharpe", 0), reverse=True)

        return {
            "success": True,
            "paper_title": paper_title,
            "factors": factors,
            "backtest_results": valid,
            "best_factor": valid[0] if valid else None,
            "engine": "independent",
        }

    # ── RD-Agent 状态 ──────────────────────────────────

    def get_rdagent_status(self) -> dict:
        """获取 RD-Agent 环境状态"""
        if self.rd_adapter:
            return self.rd_adapter.check_status()
        return {
            "rdagent_installed": False,
            "qlib_data_exists": False,
            "llm_configured": False,
        }


class FeedbackAgent:
    """
    增强版 Feedback-Agent
    在原生反馈逻辑基础上，接入 TradingAgents 评审结果
    存入长期记忆库，在下一轮 R-Agent 构思因子时注入 Prompt
    """

    def __init__(self):
        self.memory_dir = settings.memory_dir
        self.memory_file = self.memory_dir / "long_term_memory.json"
        self._init_memory()

    def _init_memory(self):
        if not self.memory_file.exists():
            initial = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "review_history": [],
                "factor_performance": {},
                "constraints": [],
                "insights": [],
            }
            with open(self.memory_file, "w") as f:
                json.dump(initial, f, ensure_ascii=False, indent=2)

    def load_memory(self) -> dict:
        with open(self.memory_file, "r") as f:
            return json.load(f)

    def save_memory(self, memory: dict):
        with open(self.memory_file, "w") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)

    def add_review(self, factor_name: str, review: dict):
        memory = self.load_memory()
        review["timestamp"] = review.get("timestamp", datetime.now().isoformat())
        memory["review_history"].append(review)

        if "backtest_result" in review:
            memory["factor_performance"][factor_name] = review["backtest_result"]
        if "constraints" in review:
            memory["constraints"].extend(review["constraints"])
            memory["constraints"] = list(set(memory["constraints"]))
        if "insights" in review:
            memory["insights"].extend(review["insights"])
            memory["insights"] = list(set(memory["insights"]))

        self.save_memory(memory)
        logger.info(f"评审结果已存入长期记忆: {factor_name}")

    def build_context_prompt(self) -> str:
        memory = self.load_memory()
        prompt_parts = ["## 历史因子评审经验（请在设计新因子时参考）\n"]

        if memory["factor_performance"]:
            prompt_parts.append("### 历史因子表现")
            for name, perf in list(memory["factor_performance"].items())[-10:]:
                ic = perf.get("ic", "N/A")
                sharpe = perf.get("sharpe", "N/A")
                prompt_parts.append(f"- {name}: IC={ic}, Sharpe={sharpe}")

        if memory["constraints"]:
            prompt_parts.append("\n### 设计约束")
            for c in memory["constraints"][-20:]:
                prompt_parts.append(f"- {c}")

        if memory["insights"]:
            prompt_parts.append("\n### 关键洞察")
            for i in memory["insights"][-15:]:
                prompt_parts.append(f"- {i}")

        recent = memory["review_history"][-5:]
        if recent:
            prompt_parts.append("\n### 最近评审结论")
            for r in recent:
                prompt_parts.append(
                    f"- [{r.get('factor_name', 'N/A')}]: {r.get('overall_conclusion', 'N/A')[:200]}"
                )

        return "\n".join(prompt_parts)

    def get_memory_summary(self) -> dict:
        memory = self.load_memory()
        return {
            "total_reviews": len(memory["review_history"]),
            "tracked_factors": len(memory["factor_performance"]),
            "active_constraints": len(memory["constraints"]),
            "accumulated_insights": len(memory["insights"]),
            "recent_reviews": memory["review_history"][-3:],
        }
