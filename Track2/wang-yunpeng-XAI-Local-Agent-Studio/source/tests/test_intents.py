"""P0-2: 意图分类自动化回归测试。

测试 core/kernel/intents.py 的 classify_intent 函数：
- code 类意图
- research 类意图
- general 类意图
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import unittest
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import Optional

# 构造 IntentRouter 的 mock 结果类型，避免真实导入复杂依赖
@dataclass
class MockIRResult:
    intent: "MockIntent"
    confidence: float
    rationale: str


@dataclass
class MockIntent:
    value: str


class TestIntentClassification(unittest.TestCase):
    """测试 classify_intent 的意图分类能力。"""

    def _make_mock_engine(self, ir_intent: str = "general", ir_confidence: float = 0.3):
        """构造一个 mock engine，其 intent_router.classify 返回指定结果。

        当 ir_confidence >= 0.5 且 ir_intent != 'general' 时走 IntentRouter 路径；
        否则走内置关键词规则。
        """
        engine = MagicMock()
        mock_ir = MagicMock()
        mock_ir.classify.return_value = MockIRResult(
            intent=MockIntent(value=ir_intent),
            confidence=ir_confidence,
            rationale="mock",
        )
        engine.intent_router = mock_ir
        return engine

    # ---- code 类意图 ----

    def test_code_intent_via_keywords(self):
        """code 类：'帮我写一个 Python 函数实现快速排序' → code_dev。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="general", ir_confidence=0.3)
        intent = classify_intent(engine, "帮我写一个 Python 函数实现快速排序")
        self.assertEqual(intent.type, "code_dev")

    def test_code_intent_via_router(self):
        """code 类：IntentRouter 高置信度返回 code_dev。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="code_dev", ir_confidence=0.85)
        intent = classify_intent(engine, "生成一个 API 接口")
        self.assertEqual(intent.type, "code_dev")

    # ---- research 类意图 ----

    def test_research_intent_via_keywords(self):
        """research 类：'帮我分析一下微服务架构的优缺点' → research。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="general", ir_confidence=0.3)
        intent = classify_intent(engine, "帮我分析一下微服务架构的优缺点")
        self.assertEqual(intent.type, "research")

    def test_research_intent_via_router(self):
        """research 类：IntentRouter 高置信度返回 research。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="research", ir_confidence=0.80)
        intent = classify_intent(engine, "调研最新的 AI 趋势")
        self.assertEqual(intent.type, "research")

    # ---- general 类意图 ----

    def test_general_intent_no_keyword_match(self):
        """general 类：无关键词匹配 → general。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="general", ir_confidence=0.3)
        intent = classify_intent(engine, "今天天气不错")
        self.assertEqual(intent.type, "general")

    def test_general_intent_router_low_confidence(self):
        """general 类：IntentRouter low confidence + 无关键词 → general。"""
        from core.kernel.intents import classify_intent

        engine = self._make_mock_engine(ir_intent="some_unknown", ir_confidence=0.45)
        intent = classify_intent(engine, "随便聊聊")
        self.assertEqual(intent.type, "general")


if __name__ == "__main__":
    unittest.main()
