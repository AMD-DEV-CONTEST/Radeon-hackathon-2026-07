"""
TradingAgents 评审桥接器

将 RD-Agent-Q 的 R-Agent 因子构思结果发送给 TradingAgents 做交叉评审，
评审结果回传给 Feedback-Agent 存入长期记忆。
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger

from backend.shared.config import settings


class TradingAgentsReviewHub:
    """
    TradingAgents 评审中心
    接收因子逻辑，调度多分析师交叉评审，输出中文评审结论
    """

    def __init__(self):
        self.output_dir = Path(settings.memory_dir) / "reviews"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def review_factor(
        self,
        factor_name: str,
        factor_expression: str,
        factor_description: str,
        backtest_result: dict,
        stock_context: dict = None,
    ) -> dict:
        """
        对单个因子发起交叉评审

        Args:
            factor_name: 因子名称
            factor_expression: 因子数学表达式
            factor_description: R-Agent 的因子构思描述
            backtest_result: Qlib 回测结果
            stock_context: 股票池/市场上下文

        Returns:
            评审结论 dict
        """
        logger.info(f"启动 TradingAgents 评审: {factor_name}")

        # 构建评审请求
        review_input = self._build_review_input(
            factor_name,
            factor_expression,
            factor_description,
            backtest_result,
            stock_context,
        )

        # 调用 TradingAgents 多 Agent 评审
        try:
            review_result = self._call_tradingagents_review(review_input)
        except Exception as e:
            logger.warning(f"TradingAgents 调用失败，使用模拟评审: {e}")
            review_result = self._mock_review(review_input)

        # 保存评审结果
        self._save_review(factor_name, review_result)

        return review_result

    def _build_review_input(
        self,
        factor_name: str,
        factor_expression: str,
        factor_description: str,
        backtest_result: dict,
        stock_context: dict = None,
    ) -> dict:
        """构建 TradingAgents 评审输入"""
        return {
            "task": "factor_review",
            "factor": {
                "name": factor_name,
                "expression": factor_expression,
                "description": factor_description,
            },
            "backtest": backtest_result,
            "context": stock_context or {
                "market": "A_share",
                "benchmark": settings.market_benchmark,
                "period": f"{settings.backtest_start} ~ {settings.backtest_end}",
            },
            "review_agents": [
                "fundamentals_analyst",   # 基本面分析师
                "macro_analyst",          # 宏观分析师
                "risk_manager",           # 风控分析师
            ],
            "timestamp": datetime.now().isoformat(),
        }

    def _call_tradingagents_review(self, review_input: dict) -> dict:
        """
        调用 TradingAgents 进行评审
        通过 Python API 直接调用，兼容 v0.7.0 新 API
        """
        try:
            from tradingagents import TradingAgentsGraph, TradingAgentsConfig

            config = TradingAgentsConfig()
            config.llm_provider = settings.llm_provider
            config.deep_think_llm = settings.llm_model
            config.quick_think_llm = settings.llm_model

            # 构建评审 prompt
            review_prompt = self._build_review_prompt(review_input)

            ta = TradingAgentsGraph(debug=False, config=config)

            # 使用 TradingAgents 的分析能力
            # 对 A 股标的进行评审（使用 benchmark 作为标的）
            benchmark = review_input["context"].get("benchmark", "000300.SS")
            trade_date = review_input["context"].get("period", "2024-01-01").split(" ~ ")[0]

            _, decision = ta.propagate(benchmark, trade_date)

            return self._parse_tradingagents_output(decision, review_input)

        except ImportError:
            raise RuntimeError("TradingAgents 未安装")

    def _build_review_prompt(self, review_input: dict) -> str:
        """构建给 TradingAgents 的评审 prompt"""
        factor = review_input["factor"]
        backtest = review_input["backtest"]

        prompt = f"""
请作为量化因子评审团队，对以下因子进行交叉评审：

## 因子信息
- 名称: {factor['name']}
- 表达式: {factor['expression']}
- 逻辑描述: {factor['description']}

## 回测结果
- IC: {backtest.get('ic', 'N/A')}
- ICIR: {backtest.get('icir', 'N/A')}
- Rank IC: {backtest.get('rank_ic', 'N/A')}
- Sharpe: {backtest.get('sharpe', 'N/A')}
- 最大回撤: {backtest.get('max_drawdown', 'N/A')}
- 换手率: {backtest.get('turnover', 'N/A')}

## 评审要求
请各位分析师从以下角度给出评审意见（中文）：

1. **基本面分析师**: 该因子是否符合A股基本面逻辑？因子逻辑是否合理？
2. **宏观分析师**: 该因子在牛市、熊市、震荡市环境下的有效性如何？是否具有长期稳定性？
3. **风控分析师**: 是否存在换手过高、行业偏离、市值偏离等问题？

请给出综合结论和改进建议。
"""
        return prompt

    def _parse_tradingagents_output(self, raw_output, review_input: dict) -> dict:
        """解析 TradingAgents 输出为结构化评审"""
        output_str = str(raw_output) if raw_output else ""

        # 尝试从中提取各分析师的结论
        return {
            "factor_name": review_input["factor"]["name"],
            "reviews": {
                "fundamentals_analyst": self._extract_section(output_str, "基本面"),
                "macro_analyst": self._extract_section(output_str, "宏观"),
                "risk_analyst": self._extract_section(output_str, "风控"),
            },
            "overall_conclusion": self._extract_section(output_str, "综合结论") or output_str[:500],
            "raw_output": output_str,
            "timestamp": datetime.now().isoformat(),
        }

    def _extract_section(self, text: str, keyword: str) -> str:
        """从文本中提取特定分析师的结论段落"""
        # 简单关键词匹配提取
        for line in text.split("\n"):
            if keyword in line:
                return line.strip()
        return f"（{keyword}评审结论待提取）"

    def _mock_review(self, review_input: dict) -> dict:
        """
        当 TradingAgents 不可用时，生成模拟评审
        基于因子表达式和回测结果做启发式判断
        """
        factor = review_input["factor"]
        backtest = review_input["backtest"]

        ic = backtest.get("ic", 0)
        sharpe = backtest.get("sharpe", 0)
        turnover = backtest.get("turnover", 0.5)
        expression = factor.get("expression", "")

        # 启发式评审逻辑
        reviews = {}

        # 基本面评审
        if "roe" in expression.lower() or "profit" in expression.lower():
            reviews["fundamentals_analyst"] = (
                f"因子 {factor['name']} 基于基本面指标，逻辑清晰。"
                "基本面因子在A股市场通常具有较好的稳定性，建议关注财报披露时点避免未来函数。"
                "该因子与价值投资理念一致，适合中长期配置。"
            )
        elif "momentum" in expression.lower() or "ret" in expression.lower():
            reviews["fundamentals_analyst"] = (
                f"因子 {factor['name']} 基于价格动量，属于技术类因子。"
                "A股市场存在明显的动量/反转效应，但需注意该因子的逻辑支撑较弱，"
                "可能面临风格切换风险。建议结合基本面因子使用。"
            )
        else:
            reviews["fundamentals_analyst"] = (
                f"因子 {factor['name']} 属于量化挖掘因子，逻辑基础需进一步验证。"
                "建议在实盘前补充经济直觉解释。"
            )

        # 宏观评审
        if abs(ic) > 0.03:
            reviews["macro_analyst"] = (
                f"IC={ic} 表现较好，因子在不同市场环境下可能具有区分度。"
                "建议分牛熊周期单独测试，确认因子并非仅在特定市场状态有效。"
                "若牛熊IC方向一致且显著，则因子具有长期配置价值。"
            )
        else:
            reviews["macro_analyst"] = (
                f"IC={ic} 偏低，因子区分度有限。"
                "建议检查是否在特定宏观环境下（如流动性宽松期）表现更好，"
                "考虑添加宏观择时条件。"
            )

        # 风控评审
        risk_issues = []
        if turnover > 1.0:
            risk_issues.append("换手率过高，实盘交易成本将显著侵蚀收益")
        if turnover < 0.1:
            risk_issues.append("换手率过低，因子可能捕捉的是长期风格暴露而非alpha")
        if abs(sharpe) < 0.5:
            risk_issues.append("Sharpe比率偏低，风险调整后收益不足")

        if risk_issues:
            reviews["risk_analyst"] = (
                f"风控评审发现问题：{'；'.join(risk_issues)}。"
                "建议优化因子组合以降低单一因子风险暴露。"
            )
        else:
            reviews["risk_analyst"] = (
                f"因子 {factor['name']} 风控指标在可接受范围内。"
                "建议定期监控换手率和行业偏离度。"
            )

        overall = (
            f"综合评审：因子 {factor['name']} "
            f"(IC={ic}, Sharpe={sharpe}) "
            f"整体{'表现良好，可考虑提交' if sharpe > 0.8 else '建议进一步优化'}。"
        )

        return {
            "factor_name": factor["name"],
            "reviews": reviews,
            "overall_conclusion": overall,
            "constraints": [
                f"换手率需控制在1.0以内（当前{review_input.get('backtest', {}).get('turnover', 'N/A')}）",
            ],
            "insights": [
                f"因子{factor['name']}在{review_input['context'].get('period', '')}期间IC={ic}",
            ],
            "timestamp": datetime.now().isoformat(),
            "source": "mock",
        }

    def _save_review(self, factor_name: str, review: dict):
        """保存评审结果到文件"""
        filepath = self.output_dir / f"{factor_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filepath, "w") as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
        logger.info(f"评审结果已保存: {filepath}")

    def load_review_history(self, factor_name: str = None) -> list:
        """加载历史评审记录"""
        reviews = []
        for f in sorted(self.output_dir.glob("*.json"), reverse=True):
            if factor_name and factor_name not in f.name:
                continue
            with open(f, "r") as fh:
                reviews.append(json.load(fh))
        return reviews


class ResearchOrchestrator:
    """
    研究协调器 — 串联 RD-Agent-Q → TradingAgents → Feedback-Agent 完整循环
    """

    def __init__(self):
        from backend.engine import RDAgentEngine, FeedbackAgent
        self.rd_engine = RDAgentEngine()
        self.review_hub = TradingAgentsReviewHub()
        self.feedback_agent = FeedbackAgent()

    def run_full_cycle(
        self,
        symbols: list[str] = None,
        max_rounds: int = 5,
    ) -> dict:
        """
        执行完整研究循环：
        1. RD-Agent-Q 因子进化
        2. 对每个新因子调用 TradingAgents 评审
        3. 评审结果存入 Feedback-Agent 长期记忆
        4. 更新上下文约束，准备下一轮
        """
        symbols = symbols or ["sh600000", "sh600519", "sz000001", "sz000858"]

        logger.info("=== 启动完整研究循环 ===")

        # Step 1: RD-Agent-Q 因子挖掘
        logger.info("[1/3] RD-Agent-Q 因子进化...")
        factor_result = self.rd_engine.run_factor_evolution(
            qlib_data_path=str(settings.db_dir),
            max_rounds=max_rounds,
        )

        # Step 2: TradingAgents 交叉评审
        logger.info("[2/3] TradingAgents 交叉评审...")
        factors = factor_result.get("factors", [])
        all_reviews = []

        for factor in factors:
            review = self.review_hub.review_factor(
                factor_name=factor.get("name", "unknown"),
                factor_expression=factor.get("expression", ""),
                factor_description=factor.get("description", ""),
                backtest_result={
                    "ic": factor.get("ic", 0),
                    "icir": factor.get("icir", 0),
                    "sharpe": factor.get("sharpe", 0),
                    "turnover": factor.get("turnover", 0.5),
                },
                stock_context={
                    "market": "A_share",
                    "symbols": symbols,
                    "benchmark": settings.market_benchmark,
                },
            )
            all_reviews.append(review)

            # Step 3: 存入长期记忆
            logger.info(f"[3/3] 评审结果存入记忆: {factor.get('name')}")
            self.feedback_agent.add_review(
                factor_name=factor.get("name", "unknown"),
                review=review,
            )

        # 获取更新后的上下文约束
        context_prompt = self.feedback_agent.build_context_prompt()

        return {
            "success": factor_result.get("success", False),
            "factors_found": len(factors),
            "reviews_completed": len(all_reviews),
            "reviews": all_reviews,
            "context_prompt": context_prompt,
            "memory_summary": self.feedback_agent.get_memory_summary(),
        }
