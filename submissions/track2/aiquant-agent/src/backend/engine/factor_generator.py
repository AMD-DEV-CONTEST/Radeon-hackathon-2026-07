"""
LLM 驱动的因子生成器

支持:
1. 从论文摘要/标题自动提取因子表达式
2. 基于市场状态生成候选因子
3. 多 provider 支持（OpenAI / 本地模型 / 兼容 API）

不需要 RD-Agent，直接用 LLM API 生成因子表达式
"""
import json
import re
from typing import Optional
from loguru import logger

from backend.shared.config import settings


class LLMFactorGenerator:
    """
    使用 LLM 从论文/描述中生成因子表达式
    支持 OpenAI 兼容 API
    """

    # 因子表达式可用的列名
    AVAILABLE_COLUMNS = [
        "open", "high", "low", "close", "volume", "amount",
        "ret_1d", "ret_5d", "ret_20d",
        "ma5_bias", "ma20_bias", "vol_20d", "volume_ratio", "rsi_14",
    ]

    # 可用函数
    AVAILABLE_FUNCTIONS = [
        "rolling_mean(series, window)",
        "rolling_std(series, window)",
        "rolling_corr(series1, series2, window)",
        "shift(series, n)",
        "rank(series)",
        "log(x)", "abs(x)", "sqrt(x)",
    ]

    def __init__(self, api_key: str = None, api_base: str = None, model: str = None):
        self.api_key = api_key or settings.llm_api_key
        self.api_base = api_base or settings.llm_api_base
        self.model = model or settings.llm_model

    def generate_from_paper(
        self,
        paper_title: str,
        paper_abstract: str = "",
        n_factors: int = 3,
    ) -> list[dict]:
        """
        从论文生成因子表达式

        Args:
            paper_title: 论文标题
            paper_abstract: 论文摘要
            n_factors: 生成因子数量

        Returns:
            [{"name": "...", "expression": "...", "description": "..."}, ...]
        """
        prompt = self._build_paper_prompt(paper_title, paper_abstract, n_factors)
        factors = self._call_llm(prompt, n_factors)

        # 验证因子表达式
        validated = []
        for f in factors:
            expr = f.get("expression", "")
            if self._validate_expression(expr):
                validated.append(f)
            else:
                logger.warning(f"因子表达式验证失败: {expr}")

        if not validated:
            # fallback: 用启发式规则生成
            logger.warning("LLM 生成失败，使用启发式因子")
            return self._heuristic_factors(paper_title, paper_abstract, n_factors)

        return validated

    def generate_from_market_state(
        self,
        market_state: str,
        n_factors: int = 5,
    ) -> list[dict]:
        """
        根据市场状态生成候选因子

        Args:
            market_state: 市场状态描述（如 "震荡市" / "牛市" / "熊市"）
            n_factors: 数量
        """
        prompt = self._build_market_prompt(market_state, n_factors)
        return self._call_llm(prompt, n_factors)

    def generate_batch(
        self,
        descriptions: list[str],
        n_per_desc: int = 2,
    ) -> list[dict]:
        """批量生成因子"""
        all_factors = []
        for desc in descriptions:
            factors = self.generate_from_paper(desc, "", n_per_desc)
            all_factors.extend(factors)
        return all_factors

    # ── Prompt 构建 ─────────────────────────────────────

    def _build_paper_prompt(
        self, title: str, abstract: str, n: int
    ) -> str:
        return f"""你是一个量化因子研究专家。请根据以下论文，提取或推导出可量化的A股因子表达式。

论文标题: {title}
论文摘要: {abstract if abstract else '（无摘要）'}

可用的数据列:
{', '.join(self.AVAILABLE_COLUMNS)}

可用的函数:
{chr(10).join(f'- {fn}' for fn in self.AVAILABLE_FUNCTIONS)}

表达式规则:
- 使用 pandas/numpy 风格表达式
- 对于滚动计算，使用 rolling_mean(col, window), rolling_std(col, window) 等
- 对于滞后值，列名加 _lagN 后缀（如 close_lag5 表示5日前收盘价）
- rank(x) 返回截面排名（0~1之间的百分位）
- 结果必须是可以逐行计算的数值

请生成 {n} 个因子，用 JSON 数组格式返回：
[
  {{
    "name": "因子英文简称",
    "expression": "因子计算表达式",
    "description": "因子逻辑说明（中文）"
  }}
]

只返回 JSON，不要其他内容。"""

    def _build_market_prompt(self, market_state: str, n: int) -> str:
        return f"""你是一个量化因子研究专家。当前A股市场处于"{market_state}"状态。

请设计适合该市场环境的因子表达式。

可用的数据列:
{', '.join(self.AVAILABLE_COLUMNS)}

可用函数: rolling_mean, rolling_std, rolling_corr, shift, rank, log, abs, sqrt
滞后值使用 _lagN 后缀（如 ret_5d_lag5）

请生成 {n} 个因子，JSON数组格式返回。只返回JSON。"""

    # ── LLM 调用 ────────────────────────────────────────

    def _call_llm(self, prompt: str, n_factors: int) -> list[dict]:
        """
        调用 LLM API
        支持 OpenAI 兼容接口
        """
        # 检查 API Key
        if not self.api_key or self.api_key == "your_api_key_here":
            logger.warning("未配置 LLM API Key，使用启发式因子生成")
            return self._heuristic_factors(prompt, "", n_factors)

        try:
            import requests

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是量化因子研究专家。只返回JSON，不要其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            }

            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            content = data["choices"][0]["message"]["content"]

            # 提取 JSON
            factors = self._extract_json(content)
            if factors:
                logger.info(f"LLM 生成 {len(factors)} 个因子")
                return factors
            else:
                logger.warning("LLM 返回无法解析，使用启发式")
                return self._heuristic_factors(prompt, "", n_factors)

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return self._heuristic_factors(prompt, "", n_factors)

    def _extract_json(self, text: str) -> Optional[list]:
        """从 LLM 返回中提取 JSON 数组"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 块
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取 [...] 块
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    # ── 表达式验证 ──────────────────────────────────────

    def _validate_expression(self, expr: str) -> bool:
        """验证因子表达式是否安全且可执行"""
        if not expr or len(expr) < 3:
            return False

        # 禁止危险操作
        forbidden = ["__", "import", "exec", "eval", "open(", "os.", "sys.", "subprocess"]
        for word in forbidden:
            if word in expr:
                return False

        # 检查是否引用了已知列或函数
        known_tokens = set(self.AVAILABLE_COLUMNS + [
            "rolling_mean", "rolling_std", "rolling_sum", "rolling_corr",
            "shift", "rank", "log", "abs", "sqrt", "np",
        ])

        # 简单检查：表达式应该包含括号或运算符
        has_operation = any(op in expr for op in ["(", ")", "+", "-", "*", "/", ">", "<"])
        return has_operation

    # ── 启发式因子生成（无需 LLM）──────────────────────

    def _heuristic_factors(
        self, title: str = "", abstract: str = "", n: int = 3
    ) -> list[dict]:
        """
        基于论文关键词的启发式因子生成
        不需要 LLM，根据标题/摘要中的关键词匹配合适的因子模板
        """
        text = (title + " " + abstract).lower()

        templates = []

        # 动量相关
        if any(w in text for w in ["momentum", "动量", "trend", "趋势"]):
            templates.extend([
                {
                    "name": "momentum_20d",
                    "expression": "ret_20d",
                    "description": "20日动量因子：过去20日收益率",
                },
                {
                    "name": "ma_crossover",
                    "expression": "ma5_bias - ma20_bias",
                    "description": "均线交叉因子：5日均线偏离与20日均线偏离之差",
                },
            ])

        # 反转相关
        if any(w in text for w in ["reversal", "反转", "contrarian", "逆向", "mean_reversion", "均值回归"]):
            templates.extend([
                {
                    "name": "short_term_reversal",
                    "expression": "-ret_5d",
                    "description": "短期反转因子：过去5日收益率的反向",
                },
                {
                    "name": "rsi_reversal",
                    "expression": "100 - rsi_14",
                    "description": "RSI反转因子：RSI超卖区域反向",
                },
            ])

        # 波动率相关
        if any(w in text for w in ["volatility", "波动", "vol", "risk", "风险"]):
            templates.extend([
                {
                    "name": "low_volatility",
                    "expression": "-vol_20d",
                    "description": "低波动因子：20日波动率的反向",
                },
                {
                    "name": "vol_adjusted_momentum",
                    "expression": "ret_20d / (vol_20d + 0.0001)",
                    "description": "波动率调整动量：20日收益除以波动率",
                },
            ])

        # 成交量相关
        if any(w in text for w in ["volume", "量", "liquidity", "流动性", "turnover"]):
            templates.extend([
                {
                    "name": "volume_price_trend",
                    "expression": "rolling_corr(close, volume, 20)",
                    "description": "量价相关性：收盘价与成交量的20日滚动相关性",
                },
                {
                    "name": "abnormal_volume",
                    "expression": "volume_ratio - 1",
                    "description": "异常成交量：当日成交量相对20日均量的偏离",
                },
            ])

        # 价值/基本面相关
        if any(w in text for w in ["value", "价值", "fundamental", "基本面", "pe", "pb", "roe", "eps"]):
            templates.extend([
                {
                    "name": "value_momentum_combo",
                    "expression": "-ret_20d * 0.5 + rank(close) * 0.5",
                    "description": "价值动量混合：反转加低估值偏好",
                },
                {
                    "name": "quality_trend",
                    "expression": "ma5_bias * volume_ratio",
                    "description": "质量趋势：均线偏离乘以量比",
                },
            ])

        # 情绪/行为金融
        if any(w in text for w in ["sentiment", "情绪", "behavior", "行为", "investor", "投资者"]):
            templates.extend([
                {
                    "name": "overreaction",
                    "expression": "-(ret_5d - ret_20d)",
                    "description": "过度反应因子：短期与中期收益差异的反向",
                },
                {
                    "name": "disposition_effect",
                    "expression": "rolling_corr(close, volume, 10) * -ret_5d",
                    "description": "处置效应因子：量价相关与短期反转结合",
                },
            ])

        # 如果没有任何匹配，使用通用因子
        if not templates:
            templates = [
                {
                    "name": "momentum_reversal_20d",
                    "expression": "-rank(ret_20d)",
                    "description": "20日动量反转因子",
                },
                {
                    "name": "volume_price_divergence",
                    "expression": "rolling_corr(volume, close, 20) * rank(ret_5d)",
                    "description": "量价背离因子：量价相关乘以5日收益排名",
                },
                {
                    "name": "volatility_breakout",
                    "expression": "volume_ratio * abs(ret_5d) / (vol_20d + 0.0001)",
                    "description": "波动突破因子：量比乘绝对收益除以波动率",
                },
                {
                    "name": "trend_strength",
                    "expression": "ma5_bias * (1 + ret_20d)",
                    "description": "趋势强度：均线偏离乘以趋势方向",
                },
                {
                    "name": "liquidity_premium",
                    "expression": "-rank(volume_ratio)",
                    "description": "流动性溢价因子：低换手率股票偏好",
                },
            ]

        return templates[:n]
