# -*- coding: utf-8 -*-
"""
test_stream.py — stream_followup 流式追问与 format_batch_card 明细展开单元测试

覆盖范围（Spec: stream-thinking-and-item-detail，Task 5 测试与验证）：
- TestStreamFollowupMocked：用 unittest.mock.patch("urllib.request.urlopen", ...) mock SSE
  流式响应，验证 agent.stream_followup 正确分离 reasoning_content / content 并按序 yield，
  以及 error 分支（HTTPError）与 done 结束事件。全 mock，不依赖后端。
- TestFormatBatchCardItems：从 app 导入 format_batch_card 纯函数，构造含 1 张成功发票 +
  1 张重复发票的 batch_result，断言 HTML 含药品子表（"└ 药品明细"）且重复发票不展开。
  若 gradio 未装导致 import 失败则整类 skip。

运行：
    python test_stream.py
或：
    $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; \
    & "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" "test_stream.py"
"""

import unittest
import urllib.error
from unittest.mock import patch

import agent  # noqa: F401  注入 sys.path
from agent.agent import stream_followup

# app.py 顶部 import gradio，若未装 gradio 则 format_batch_card 无法导入，
# TestFormatBatchCardItems 整类在 setUpClass 跳过。
try:
    from app import format_batch_card
except Exception as _e:  # noqa: F841  pragma: no cover
    format_batch_card = None


# ============================================================================
# 1) stream_followup mock SSE 流式测试（不依赖后端）
# ============================================================================
class TestStreamFollowupMocked(unittest.TestCase):
    """mock urllib.request.urlopen 返回构造的 SSE 流，验证 stream_followup 行为。"""

    class _FakeResponse:
        """模拟 urlopen 返回的响应对象：按行迭代返回 bytes。"""

        def __init__(self, lines):
            self._lines = lines

        def __iter__(self):
            return iter(self._lines)

    def test_reasoning_then_content_then_done(self):
        """reasoning 片段先于 content 片段，拼接正确，最后 yield done。"""
        lines = [
            b'data: {"choices":[{"delta":{"reasoning_content":"Let me think"}}]}\n\n',
            b'data: {"choices":[{"delta":{"reasoning_content":" carefully"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"The answer"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" is 42"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen",
                   return_value=self._FakeResponse(lines)) as m:
            events = list(stream_followup("test question", session_id="test-stream"))

        # urlopen 应被调用一次（session_id=test-stream 无会话记忆，走通用 prompt，
        # 仍会调 urlopen）
        self.assertTrue(m.called, "urlopen 应被调用（被 mock）")

        # 拼接 reasoning 与 content
        reasoning_text = "".join(e["text"] for e in events if e["type"] == "reasoning")
        content_text = "".join(e["text"] for e in events if e["type"] == "content")
        self.assertEqual(reasoning_text, "Let me think carefully",
                         f"reasoning 拼接应为 'Let me think carefully'，实际 {reasoning_text!r}")
        self.assertEqual(content_text, "The answer is 42",
                         f"content 拼接应为 'The answer is 42'，实际 {content_text!r}")

        # 最后一个事件应为 done
        self.assertTrue(events, "事件列表不应为空")
        self.assertEqual(events[-1]["type"], "done",
                         f"最后一个事件 type 应为 'done'，实际 {events[-1]!r}")

        # 事件顺序：所有 reasoning 片段应先于所有 content 片段
        first_content_idx = next(
            (i for i, e in enumerate(events) if e["type"] == "content"), None)
        last_reasoning_idx = max(
            (i for i, e in enumerate(events) if e["type"] == "reasoning"), default=-1)
        self.assertIsNotNone(first_content_idx, "应至少有一个 content 事件")
        self.assertGreater(first_content_idx, last_reasoning_idx,
                           "reasoning 片段应先于 content 片段")

        # done 应是唯一且在最后
        self.assertEqual(sum(1 for e in events if e["type"] == "done"), 1,
                         "应只有一个 done 事件")

    def test_error_branch_http_error(self):
        """urlopen 抛 HTTPError → yield 一个 error 事件。"""
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError("url", 500, "err", {}, None)):
            events = list(stream_followup("x", session_id="t"))
        self.assertTrue(any(e["type"] == "error" for e in events),
                        f"应 yield 一个 error 事件，实际事件 {events!r}")
        # error 事件应含 text 字段（非空）
        err_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(err_events), 1, "应只有一个 error 事件")
        self.assertTrue(err_events[0].get("text"), "error 事件 text 不应为空")
        # HTTPError 时不应有 done 事件（异常分支 return，不执行到 yield done）
        self.assertFalse(any(e["type"] == "done" for e in events),
                         "HTTPError 分支不应 yield done")


# ============================================================================
# 2) format_batch_card 药品明细子表展开测试（纯函数，不依赖后端）
# ============================================================================
class TestFormatBatchCardItems(unittest.TestCase):
    """format_batch_card 在成功发票行下展开药品明细子表，重复发票不展开。"""

    @classmethod
    def setUpClass(cls):
        if format_batch_card is None:
            raise unittest.SkipTest("app 模块导入失败（如 gradio 未装），跳过 format_batch_card 测试")

    def _build_batch_result(self):
        """构造 1 张成功发票 + 1 张重复发票的 batch_result。"""
        inv_ok = {
            "index": 0, "filename": "a.jpg", "ok": True, "duplicate_of": None,
            "extract": {"fphm": "001", "code": "100"},
            "decision": {
                "conclusion": "部分通过",
                "total_amount": 100, "total_reimbursable": 70,
                "total_medical_insurance": 70, "total_commercial": 0,
                "items": [
                    {"name": "阿莫西林", "amount": 50, "category": "甲类",
                     "medical_reimbursable": 35, "commercial_reimbursable": 0,
                     "reason": "甲类全额纳入"},
                    {"name": "布洛芬", "amount": 50, "category": "乙类",
                     "medical_reimbursable": 35, "commercial_reimbursable": 0,
                     "reason": "乙类先行自付"},
                ],
            },
        }
        inv_dup = {
            "index": 1, "filename": "b.jpg", "ok": True, "duplicate_of": 0,
            "extract": {"fphm": "001", "code": "100"},
            "decision": None,
        }
        aggregate = {
            "conclusion": "部分通过",
            "total_invoices": 2, "success_count": 1, "failed_count": 0,
            "duplicate_count": 1,
            "total_amount": 100, "total_medical_insurance": 70,
            "total_commercial": 0, "total_reimbursable": 70,
            "cap_applied": False, "medical_after_cap": 70,
            "annual_cap": 0, "cap_note": "",
        }
        batch = {
            "ok": True, "session_id": "t", "created_at": "",
            "invoices": [inv_ok, inv_dup],
            "aggregate": aggregate, "errors": [], "duplicates": [],
        }
        return batch

    def test_items_expanded_for_success_invoice(self):
        """成功且非重复发票行下方应展开药品明细子表，含药品名与理由。"""
        batch = self._build_batch_result()
        html = format_batch_card(batch)

        # 药品名存在
        self.assertIn("阿莫西林", html, "HTML 应包含药品名「阿莫西林」")
        self.assertIn("布洛芬", html, "HTML 应包含药品名「布洛芬」")
        # 子表标题存在
        self.assertIn("└ 药品明细", html, "HTML 应包含子表标题「└ 药品明细」")
        # 理由列存在（任一即可）
        self.assertTrue("甲类全额纳入" in html or "乙类先行自付" in html,
                        "HTML 应包含至少一个药品的理由文本")

    def test_items_not_expanded_for_duplicate_invoice(self):
        """重复发票（duplicate_of 非 None）不应展开药品明细子表。"""
        batch = self._build_batch_result()
        html = format_batch_card(batch)

        # 只有成功发票展开子表，重复发票不展开 → 子表标题只出现 1 次
        self.assertEqual(html.count("└ 药品明细"), 1,
                         f"应只有 1 个药品明细子表（成功发票展开、重复发票不展开），"
                         f"实际出现 {html.count('└ 药品明细')} 次")
        # 重复发票应在主明细表中以「重复」标注
        self.assertIn("重复", html, "重复发票应在主明细表结论列标注「重复」")


if __name__ == "__main__":
    unittest.main(verbosity=2)
