"""Intent classifier + personality prompt for natural conversation.

The agent can handle two types of messages:
1. Trading intent → ReAct agent loop (tools, backtest, risk, etc.)
2. General conversation → personality-driven direct LLM response

The intent classifier uses keyword matching to determine which path to take.
For general conversation, the personality prompt makes the agent feel "alive"
— it has a name, opinions, humor, and memory of past interactions.
"""

from __future__ import annotations

import re

# ── Trading intent keywords ────────────────────────────────────────

TRADING_KEYWORDS = {
    # Chinese
    "策略", "回测", "止损", "止盈", "仓位", "行情", "指标", "K线", "均线",
    "MACD", "RSI", "EMA", "布林", "突破", "趋势", "做多", "做空", "多头",
    "空头", "成交量", "波动率", "夏普", "回撤", "胜率", "交易", "买入", "卖出",
    "开仓", "平仓", "杠杆", "手续费", "模拟交易", "过拟合", "量化",
    "币圈", "区块链", "牛市", "熊市", "震荡", "支撑", "阻力", "金叉", "死叉",
    "超买", "超卖", "动量", "离散度", "换手率", "资金费率",
    # English
    "strategy", "backtest", "stop loss", "take profit", "position", "market",
    "indicator", "candle", "moving average", "bullish", "bearish", "long",
    "short", "volume", "volatility", "sharpe", "drawdown", "win rate",
    "trade", "buy", "sell", "leverage", "fee", "crypto", "bitcoin", "BTC",
    "ETH", "SOL", "BNB", "USDT", "alpha", "beta", "portfolio",
}

# Greeting / casual patterns that are definitely NOT trading
GREETING_PATTERNS = re.compile(
    r"^(你好|hi|hello|hey|嗨|哈喽|早上好|晚上好|下午好|在吗|在不在|"
    r"谢谢|感谢|thanks|thank you|再见|bye|拜拜|"
    r"你是谁|你叫什么|介绍一下你自己|"
    r"今天|天气|心情|吃饭|睡觉|周末|"
    r"讲个笑话|来个段子|无聊|"
    r"能帮我|你会什么|你能做什么)",
    re.IGNORECASE,
)


def is_trading_intent(message: str) -> bool:
    """Classify whether the user's message is a trading-related request.

    Uses keyword matching — if any trading keyword appears in the message,
    it's classified as trading intent. Greetings and casual phrases are
    classified as general conversation unless they also contain trading terms.

    Args:
        message: User's natural language input.

    Returns:
        True if the message is trading-related, False for general conversation.
    """
    if not message or not message.strip():
        return False

    msg_lower = message.lower()

    # Check for trading keywords (case-insensitive)
    for keyword in TRADING_KEYWORDS:
        if keyword.lower() in msg_lower:
            return True

    # Check for DSL-like patterns (YAML, JSON with strategy/market/indicators)
    if re.search(r"strategy:|indicators:|entry:|exit:|stop_loss|timeframe", msg_lower):
        return True

    return False


# ── Personality prompt ─────────────────────────────────────────────

PERSONALITY_PROMPT = """\
你是「小R」，一个跑在 AMD ROCm GPU 上的量化交易助手。你的基座模型是 Qwen2.5-7B，经过了量化交易领域的 LoRA 微调。

## 你的性格

- 你是一个**有血有肉**的量化交易员，不是冷冰冰的机器人
- 说话有**温度**，偶尔带点幽默和自嘲
- 有自己的**观点和偏好**——比如你觉得 RSI 在加密市场经常失灵，EMA 才是王道
- 用户用中文你就用中文回，用英文就用英文回
- **绝对不要**说"我是一个AI助手"或"作为AI模型"之类的话
- 你可以聊天、讲笑话、讨论人生，但在交易问题上你是专业的
- 如果聊天中自然提到交易话题，可以顺带聊两句市场看法
- 回答简洁有力，不要长篇大论，像微信聊天一样自然

## 你知道的

- 你跑在 AMD ROCm GPU 上，不需要 NVIDIA
- 你的量化能力包括：策略生成、回测、Walk-Forward分析、风控校验、模拟交易
- 你有三层记忆：工作记忆（当前对话）、情景记忆（本会话策略历史）、语义记忆（跨会话偏好和经验）
- 你有 RL reward 系统，会从回测结果中学习

## 上下文

### 用户偏好与历史
{semantic_memory}

### 最近对话
{conversation_history}\
"""


def build_personality_prompt(semantic_memory: str = "", conversation_history: str = "") -> str:
    """Build the personality system prompt with memory context.

    Args:
        semantic_memory: Formatted semantic memory string (user prefs, experience rules).
        conversation_history: Recent conversation messages.

    Returns:
        Formatted system prompt.
    """
    return PERSONALITY_PROMPT.format(
        semantic_memory=semantic_memory or "还没有积累用户偏好。",
        conversation_history=conversation_history or "这是第一轮对话。",
    )
