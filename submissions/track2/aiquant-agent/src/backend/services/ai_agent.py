"""
AI 量化助手 Agent
================
- 意图识别：解析用户自然语言指令，判断是因子挖掘/回测/咨询/闲聊
- 参数提取：从指令中提取 stock universe、循环轮数、约束条件
- 路由分发：返回结构化意图对象，供 API 网关决定执行路径
"""

import re
import json
import os
from typing import Optional
from loguru import logger

# ── 意图类型 ──
INTENT_FACTOR_MINING = "factor_mining"   # 因子挖掘
INTENT_BACKTEST = "backtest"              # 回测分析
INTENT_INQUIRY = "inquiry"                # 咨询问答
INTENT_CHITCHAT = "chitchat"             # 闲聊


class IntentResult:
    """意图解析结果"""
    def __init__(
        self,
        intent: str,
        confidence: float = 0.0,
        loop_n: int = 0,
        universe: str = "全A股",
        constraints: str = "通用",
        all_duration: str = "15m",
        raw_message: str = "",
        needs_clarification: bool = False,
        clarification_hint: str = "",
    ):
        self.intent = intent
        self.confidence = confidence
        self.loop_n = loop_n
        self.universe = universe
        self.constraints = constraints
        self.all_duration = all_duration
        self.raw_message = raw_message
        self.needs_clarification = needs_clarification
        self.clarification_hint = clarification_hint
    
    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "loop_n": self.loop_n,
            "universe": self.universe,
            "constraints": self.constraints,
            "all_duration": self.all_duration,
            "raw_message": self.raw_message,
            "needs_clarification": self.needs_clarification,
            "clarification_hint": self.clarification_hint,
        }


class QuantAIAgent:
    """
    AI 量化助手 Agent。
    
    采用两层策略：
    1. 规则层：快速正则匹配（低延迟，覆盖 80% 常见指令）
    2. LLM 层：当规则无法确定时，调用 LLM 进行语义理解（备选，需配置 API key）
    
    始终返回 IntentResult，确保前端能收到结构化响应。
    """
    
    # ── 意图关键词 ──
    MINING_KEYWORDS = [
        "挖掘", "因子", "因子挖掘", "生成因子", "挖因子", "挖一个",
        "alpha", "因子进化", "量化因子", "选股因子", "因子策略",
        "帮我挖", "帮我生成", "帮我跑", "跑因子",
    ]
    
    BACKTEST_KEYWORDS = [
        "回测", "回溯", "backtest", "绩效", "收益率", "净值曲线",
        "最大回撤", "夏普", "Sharpe", "calmar",
    ]
    
    INQUIRY_KEYWORDS = [
        "是什么", "怎么用", "什么是", "如何", "为什么", "怎样",
        "怎么", "怎么样", "什么意思", "介绍一下", "说明",
    ]
    
    # ── 股池映射 ──
    UNIVERSE_PATTERNS = [
        (r"(?:中证\s*1000|中证1000|csi\s*1000|CSI\s*1000)", "中证1000"),
        (r"(?:中证\s*500|中证500|csi\s*500|CSI\s*500)", "中证500"),
        (r"(?:沪深\s*300|沪深300|csi\s*300|CSI\s*300|hs\s*300|HS\s*300|hs300)", "沪深300"),
        (r"(?:上证\s*50|上证50|sz50|SZ50)", "上证50"),
        (r"(?:创业板|创业板指)", "创业板指"),
        (r"(?:科创\s*50|科创50)", "科创50"),
        (r"(?:全\s*A\s*股|全部A股|全市场|全部股票)", "全A股"),
    ]
    
    # ── 约束条件映射（从具体到通用排列，避免重叠匹配） ──
    CONSTRAINT_PATTERNS = [
        (r"高\s*换手|高换手率", "高换手风格"),
        (r"低\s*换手|低换手率", "低换手风格"),
        (r"横截面", "横截面"),
        (r"动量", "动量风格"),
        (r"反转", "反转风格"),
        (r"市值\s*中性|市值中性", "市值中性"),
        (r"行业\s*中性|行业中性", "行业中性"),
        (r"低\s*波动|低波", "低波动"),
        (r"质量", "质量因子"),
        (r"成长", "成长因子"),
        (r"价值", "价值因子"),
    ]
    
    # ── 迭代轮数模式 ──
    LOOP_PATTERNS = [
        r"循环\s*次数\s*(\d+)\s*次",
        r"循环\s*(\d+)\s*[次轮]",
        r"迭代\s*(\d+)\s*[次轮]",
        r"(?:跑|做|执行|运行)\s*(\d+)\s*[次轮]",
        r"(\d+)\s*[次轮](?:\s*(?:迭代|循环))?",
    ]
    
    def __init__(self, llm_api_key: Optional[str] = None, llm_base_url: Optional[str] = None,
                 llm_model: Optional[str] = None):
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
    
    def parse(self, message: str) -> IntentResult:
        """
        解析用户消息，返回意图结果。
        
        Args:
            message: 用户输入的自然语言指令
            
        Returns:
            IntentResult: 结构化意图结果
        """
        message = message.strip()
        if not message:
            return IntentResult(
                intent=INTENT_CHITCHAT,
                confidence=0.0,
                raw_message=message,
                needs_clarification=True,
                clarification_hint="请输入您的量化研究需求，例如：在沪深300中挖掘低换手因子，迭代5轮",
            )
        
        msg_lower = message.lower()
        
        # ── 第一层：规则匹配 ──
        result = self._rule_based_parse(message, msg_lower)
        if result.confidence >= 0.6:
            return result
        
        # ── 第二层：LLM 语义理解 ──
        # TODO: 当配置了 LLM key 时，调用 LLM 进行深层语义理解
        # 目前降级为规则兜底 + 提示
        
        logger.debug(f"[Agent] 规则匹配低置信度({result.confidence})，消息: {message[:100]}")
        return result
    
    def _rule_based_parse(self, message: str, msg_lower: str) -> IntentResult:
        """规则层快速解析"""
        raw = message
        
        # 1. 判断意图类别
        intent = INTENT_CHITCHAT
        confidence = 0.2
        
        mining_score = sum(1 for kw in self.MINING_KEYWORDS if kw in message or kw.lower() in msg_lower)
        backtest_score = sum(1 for kw in self.BACKTEST_KEYWORDS if kw in message or kw.lower() in msg_lower)
        inquiry_score = sum(1 for kw in self.INQUIRY_KEYWORDS if kw in message or kw.lower() in msg_lower)
        
        if mining_score > 0 and backtest_score > 0:
            # 同时有挖掘和回测关键词 — 先挖掘
            intent = INTENT_FACTOR_MINING
            confidence = 0.7
        elif mining_score > 0:
            intent = INTENT_FACTOR_MINING
            confidence = 0.8
        elif backtest_score > 0:
            intent = INTENT_BACKTEST
            confidence = 0.7
        elif inquiry_score > 0:
            intent = INTENT_INQUIRY
            confidence = 0.6
        
        # 2. 如果意图不是因子挖掘，直接返回
        if intent != INTENT_FACTOR_MINING:
            return IntentResult(
                intent=intent,
                confidence=confidence,
                raw_message=raw,
            )
        
        # 3. 因子挖掘：提取参数
        universe = "全A股"
        for pattern, name in self.UNIVERSE_PATTERNS:
            if re.search(pattern, message):
                universe = name
                confidence = max(confidence, 0.85)
                break
        
        constraints_parts = []
        for pattern, name in self.CONSTRAINT_PATTERNS:
            if re.search(pattern, message):
                constraints_parts.append(name)
        constraints = "、".join(constraints_parts) if constraints_parts else "通用"
        if constraints_parts:
            confidence = max(confidence, 0.85)
        
        loop_n = 0
        for pattern in self.LOOP_PATTERNS:
            m = re.search(pattern, message)
            if m:
                loop_n = int(m.group(1))
                confidence = max(confidence, 0.9)
                break
        
        all_duration = f"{max(loop_n, 1) * 15}m"
        
        needs_clarification = loop_n <= 0
        clarification_hint = ""
        if needs_clarification:
            clarification_hint = (
                f"无法从您的指令中提取循环次数。请指定迭代轮数，例如：\n"
                f"• \"在{universe}挖掘因子，迭代5轮\"\n"
                f"• \"循环次数5次\"\n"
                f"• \"跑3轮\""
            )
        
        return IntentResult(
            intent=intent,
            confidence=confidence,
            loop_n=loop_n,
            universe=universe,
            constraints=constraints,
            all_duration=all_duration,
            raw_message=raw,
            needs_clarification=needs_clarification,
            clarification_hint=clarification_hint,
        )
    
    def parse_to_legacy(self, message: str) -> dict:
        """
        兼容旧版 _parse_mining_instruction 的返回格式。
        返回 dict: {loop_n, universe, constraints, all_duration}
        """
        result = self.parse(message)
        return {
            "loop_n": result.loop_n,
            "universe": result.universe,
            "constraints": result.constraints,
            "all_duration": result.all_duration,
            "intent": result.intent,
            "confidence": result.confidence,
        }


# ── 全局单例 ──
_agent_instance: Optional[QuantAIAgent] = None


def get_agent() -> QuantAIAgent:
    """获取全局 AI Agent 实例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = QuantAIAgent(
            llm_api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"),
            llm_base_url=os.environ.get("OPENAI_API_BASE") or os.environ.get("DEEPSEEK_API_BASE"),
            llm_model=os.environ.get("LLM_MODEL"),
        )
    return _agent_instance


def parse_message(message: str) -> dict:
    """快捷方法：解析用户消息"""
    return get_agent().parse_to_legacy(message)
