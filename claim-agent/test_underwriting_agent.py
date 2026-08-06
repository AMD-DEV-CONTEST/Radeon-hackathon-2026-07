# -*- coding: utf-8 -*-
"""
test_underwriting_agent.py — 核保 Agent 流式追问单元测试（Task 7.3）

覆盖范围（对齐 spec.md「核保 Agent 与流式追问」与 Task 7 验证清单）：
- TestFormatReportContext：单份报告上下文格式化（不依赖 LLM），构造 mock report
  （含患者/风险/异常/引用），断言 _format_report_context 返回非空文本且含关键信息。
- TestFormatBatchContext：批量上下文格式化（不依赖 LLM），构造 mock batch（含
  成功/重复/失败三类），断言 _format_batch_context 含逐张明细。
- TestStreamFollowupThreeTierFallback：三级回退分支选择（不依赖 LLM 成功），
  monkey-patch urllib.request.urlopen 捕获 body，验证 system_content 走对应分支。
- TestStreamFollowupMockedSSE：mock SSE 流（reasoning_content + content + [DONE]），
  验证 yield 事件序列为 [reasoning..., content..., done]，以及 HTTPError 分支。
- TestStreamFollowupEndpointUnreachable：真实调用（不 mock），验证 LLM 不可达时
  yield error 事件且生成器正常结束（不抛异常）。

运行：
    python test_underwriting_agent.py
或：
    $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"; \
    & "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" "test_underwriting_agent.py"
"""

import json
import unittest
import urllib.error
from unittest.mock import patch

import sys
sys.path.insert(0, r"c:\Users\OKONE\fake_ocr_test")

import underwriting  # noqa: F401  注入 sys.path
from underwriting.agent import (
    stream_followup,
    answer_followup,
    _format_report_context,
    _format_batch_context,
)
from underwriting.memory import get_store


# ============================================================================
# 辅助：构造 mock 数据
# ============================================================================

def _build_mock_report():
    """构造一份完整的 mock 核保报告（含患者/风险/异常/引用）。"""
    return {
        "ok": True,
        "image_path": "/tmp/report.jpg",
        "patient": {"name": "张三", "gender": "男", "age": 55},
        "report_type": "体检报告",
        "exam_date": "2026-06-15",
        "summary": "本次体检发现血压偏高、血脂异常，建议复查并随访。",
        "abnormalities": [
            {
                "name": "收缩压偏高",
                "type": "检验越界",
                "severity_hint": "中",
                "evidence": "收缩压 165 mmHg（参考范围 90-140）",
                "detail": "收缩压超出参考上限，提示高血压可能",
            },
            {
                "name": "总胆固醇偏高",
                "type": "检验越界",
                "severity_hint": "轻",
                "evidence": "总胆固醇 6.8 mmol/L（参考范围 <5.2）",
                "detail": "总胆固醇升高，提示高脂血症",
            },
        ],
        "risks": [
            {
                "name": "高血压",
                "risk_level": "中",
                "risk_factors": ["收缩压偏高", "年龄>50"],
                "evidence": "收缩压 165 mmHg",
                "reasoning": "患者收缩压持续偏高，结合年龄因素，心血管事件风险升高",
            },
            {
                "name": "高脂血症",
                "risk_level": "低",
                "risk_factors": ["总胆固醇偏高"],
                "evidence": "总胆固醇 6.8 mmol/L",
                "reasoning": "血脂升高但无合并症，短期风险较低",
            },
        ],
        "overall_risk": "中",
        "overall_reasoning": "存在高血压等中等风险因素，整体风险中等",
        "references": [
            {
                "disease": "高血压",
                "title": "中国高血压防治指南 2024",
                "url": "https://example.com/htn-guideline",
                "snippet": "高血压核保风险评估要点...",
                "source": "exa",
            },
            {
                "disease": "高脂血症",
                "title": "血脂异常管理专家共识",
                "url": "https://example.com/lipid-consensus",
                "snippet": "血脂异常与心血管风险...",
                "source": "anysearch-health",
            },
        ],
        "search_warnings": [],
        "search_errors": [],
        "recommendation": "次标准体-加费",
        "recommendation_reason": "整体风险中等，存在高血压等中风险因素，建议加费承保。",
        "extract": {},
    }


def _build_mock_batch():
    """构造一份 mock 批量核保结果（含成功/重复/失败三类）。"""
    return {
        "ok": True,
        "session_id": "test-batch",
        "created_at": "2026-07-25T10:00:00",
        "reports": [
            {
                "index": 0,
                "filename": "report_a.jpg",
                "ok": True,
                "duplicate_of": None,
                "patient": {"name": "张三", "gender": "男", "age": 55},
                "report_type": "体检报告",
                "overall_risk": "中",
                "recommendation": "次标准体-加费",
            },
            {
                "index": 1,
                "filename": "report_b.jpg",
                "ok": True,
                "duplicate_of": 0,
                "patient": {"name": "张三", "gender": "男", "age": 55},
                "report_type": "体检报告",
                "overall_risk": "中",
                "recommendation": "次标准体-加费",
            },
            {
                "index": 2,
                "filename": "report_c.jpg",
                "ok": False,
                "duplicate_of": None,
                "stage": "extract",
                "message": "图片无法识别",
            },
            {
                "index": 3,
                "filename": "report_d.jpg",
                "ok": True,
                "duplicate_of": None,
                "patient": {"name": "李四", "gender": "女", "age": 42},
                "report_type": "病历",
                "overall_risk": "低",
                "recommendation": "标准体",
            },
        ],
        "aggregate": {
            "summary_text": "本次批量核保共 4 份报告：成功 2 份，重复 1 份，失败 1 份。",
            "total_reports": 4,
            "success_count": 2,
            "failed_count": 1,
            "duplicate_count": 1,
        },
        "errors": [{"filename": "report_c.jpg", "stage": "extract", "message": "图片无法识别"}],
        "duplicates": [{"filename": "report_b.jpg", "duplicate_of": 0}],
    }


# ============================================================================
# 1) 上下文格式化测试（不依赖 LLM）
# ============================================================================

class TestFormatReportContext(unittest.TestCase):
    """_format_report_context 把结构化报告压缩成文本，含关键信息。"""

    def test_returns_nonempty_text_with_key_info(self):
        report = _build_mock_report()
        text = _format_report_context(report)
        self.assertIsInstance(text, str)
        self.assertTrue(text, "格式化结果不应为空")

        # 患者信息
        self.assertIn("张三", text, "应包含患者姓名")
        self.assertIn("男", text, "应包含患者性别")
        self.assertIn("55", text, "应包含患者年龄")

        # 报告类型与检查日期
        self.assertIn("体检报告", text, "应包含报告类型")
        self.assertIn("2026-06-15", text, "应包含检查日期")

        # 整体风险与核保建议
        self.assertIn("中", text, "应包含整体风险等级")
        self.assertIn("次标准体-加费", text, "应包含核保建议")
        self.assertIn("建议加费承保", text, "应包含建议理由")

        # 异常明细
        self.assertIn("收缩压偏高", text, "应包含异常项名称")
        self.assertIn("检验越界", text, "应包含异常类型")
        self.assertIn("165 mmHg", text, "应包含异常依据")

        # 风险明细
        self.assertIn("高血压", text, "应包含风险项名称")
        self.assertIn("心血管事件风险升高", text, "应包含风险理由")

        # 医学引用摘要
        self.assertIn("中国高血压防治指南", text, "应包含医学引用标题")
        self.assertIn("exa", text, "应包含引用来源")

    def test_empty_report_returns_empty(self):
        self.assertEqual(_format_report_context(None), "")
        self.assertEqual(_format_report_context({}), "")

    def test_minimal_report_no_crash(self):
        """字段缺失时不崩溃，能拼出基本行。"""
        text = _format_report_context({"ok": True, "report_type": "病历"})
        self.assertIn("病历", text)

    def test_no_abnormalities_marked(self):
        """无异常时应标注「未见明显异常」。"""
        report = _build_mock_report()
        report["abnormalities"] = []
        text = _format_report_context(report)
        self.assertIn("未见明显异常", text)

    def test_search_unavailable_note(self):
        """有 search_errors 且无 references 时应追加检索不可用提示。"""
        report = _build_mock_report()
        report["references"] = []
        report["search_errors"] = ["exa timeout"]
        text = _format_report_context(report)
        self.assertIn("联网检索暂不可用", text)


class TestFormatBatchContext(unittest.TestCase):
    """_format_batch_context 含逐张明细（成功/重复/失败三类）。"""

    def test_returns_nonempty_text_with_per_report_details(self):
        batch = _build_mock_batch()
        text = _format_batch_context(batch)
        self.assertIsInstance(text, str)
        self.assertTrue(text, "格式化结果不应为空")

        # 汇总
        self.assertIn("批量核保汇总", text, "应包含汇总标题")
        self.assertIn("成功 2 份", text, "应包含成功计数")

        # 成功报告明细
        self.assertIn("report_a.jpg", text, "应包含成功报告文件名")
        self.assertIn("张三", text, "应包含成功报告患者")
        self.assertIn("次标准体-加费", text, "应包含成功报告核保建议")
        self.assertIn("report_d.jpg", text, "应包含第二份成功报告")
        self.assertIn("李四", text, "应包含第二份成功报告患者")
        self.assertIn("标准体", text, "应包含标准体建议")

        # 重复报告
        self.assertIn("report_b.jpg", text, "应包含重复报告文件名")
        self.assertIn("重复", text, "应标注重复")
        self.assertIn("第 1 份相同", text, "应标注重复目标")

        # 失败报告
        self.assertIn("report_c.jpg", text, "应包含失败报告文件名")
        self.assertIn("处理失败", text, "应标注失败")
        self.assertIn("图片无法识别", text, "应包含失败原因")

        # 计数行
        self.assertIn("失败 1 份", text, "应包含失败计数行")
        self.assertIn("重复 1 份", text, "应包含重复计数行")

    def test_empty_batch_returns_empty(self):
        self.assertEqual(_format_batch_context(None), "")
        self.assertEqual(_format_batch_context({}), "")

    def test_aggregate_without_summary_text_uses_counts(self):
        """aggregate 无 summary_text 时，从计数字段拼汇总行。"""
        batch = _build_mock_batch()
        batch["aggregate"] = {
            "total_reports": 3, "success_count": 2,
            "failed_count": 1, "duplicate_count": 0,
        }
        text = _format_batch_context(batch)
        self.assertIn("共 3 份报告", text)
        self.assertIn("成功 2", text)

    def test_no_crash_on_malformed_reports(self):
        """reports 含非 dict 元素时不崩溃。"""
        batch = {
            "ok": True,
            "reports": ["not a dict", {"filename": "x.jpg", "ok": True, "duplicate_of": None}],
            "aggregate": {"summary_text": "汇总"},
        }
        text = _format_batch_context(batch)
        self.assertIn("汇总", text)
        self.assertIn("x.jpg", text)


# ============================================================================
# 2) mock SSE 流式响应辅助
# ============================================================================

class _FakeResponse:
    """模拟 urlopen 返回的响应对象：按行迭代返回 bytes。"""

    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _CapturingUropen:
    """捕获传给 urlopen 的 Request（含 body），并返回 FakeResponse。

    用于三级回退测试：通过解析 captured_body 中的 messages[0].content 来判断
    system_content 走了哪个分支。
    """

    def __init__(self, lines):
        self._lines = lines
        self.captured_req = None
        self.captured_body = None

    def __call__(self, req, timeout=None):
        self.captured_req = req
        self.captured_body = req.data  # bytes
        return _FakeResponse(self._lines)


def _sse_line(delta: dict) -> bytes:
    """构造一行 SSE data: payload。"""
    return b'data: ' + json.dumps({"choices": [{"delta": delta}]}).encode("utf-8") + b'\n\n'


# ============================================================================
# 3) 三级回退分支测试（不依赖 LLM 成功，用 mock SSE + 捕获 body）
# ============================================================================

class TestStreamFollowupThreeTierFallback(unittest.TestCase):
    """三级回退：批量记忆 → 单份记忆 → 通用提示词。

    通过 _CapturingUropen 捕获 POST body，解析 messages[0].content（system_content）
    判断走了哪个分支。每个用例独立 session_id 避免记忆污染。
    """

    def _run_and_capture_system_content(self, session_id):
        """运行 stream_followup，消费完事件，返回捕获到的 system_content。"""
        lines = [
            _sse_line({"content": "ok"}),
            b'data: [DONE]\n\n',
        ]
        cap = _CapturingUropen(lines)
        with patch("urllib.request.urlopen", side_effect=cap):
            list(stream_followup("test", session_id=session_id))
        self.assertIsNotNone(cap.captured_body, "应捕获到 POST body")
        body_obj = json.loads(cap.captured_body.decode("utf-8"))
        messages = body_obj.get("messages", [])
        self.assertGreaterEqual(len(messages), 2, "messages 至少含 system + user")
        return messages[0].get("content", "")

    def test_tier1_batch_memory(self):
        """有批量记忆（ok=True）→ system_content 含批量上下文。"""
        sid = "test-tier1-batch"
        get_store().clear(sid)
        get_store().set_batch_report(sid, _build_mock_batch())
        try:
            system_content = self._run_and_capture_system_content(sid)
            self.assertIn("批量报告", system_content, "应走批量分支，含「批量报告」字样")
            self.assertIn("report_a.jpg", system_content, "system_content 应含批量明细")
            self.assertIn("张三", system_content, "system_content 应含批量患者信息")
        finally:
            get_store().clear(sid)

    def test_tier2_single_report_when_no_batch(self):
        """无批量记忆、有单份记忆（ok=True）→ system_content 含单份上下文。"""
        sid = "test-tier2-single"
        get_store().clear(sid)
        get_store().set_last_report(sid, _build_mock_report())
        try:
            system_content = self._run_and_capture_system_content(sid)
            self.assertIn("已完成核保的报告", system_content, "应走单份分支")
            self.assertIn("张三", system_content, "system_content 应含患者信息")
            self.assertIn("收缩压偏高", system_content, "system_content 应含异常明细")
            self.assertIn("次标准体-加费", system_content, "system_content 应含核保建议")
            # 不应含批量明细
            self.assertNotIn("批量报告", system_content, "不应走批量分支")
        finally:
            get_store().clear(sid)

    def test_tier3_generic_when_no_memory(self):
        """无任何记忆 → system_content 为通用提示词。"""
        sid = "test-tier3-generic"
        get_store().clear(sid)
        try:
            system_content = self._run_and_capture_system_content(sid)
            self.assertEqual(
                system_content,
                "你是智能核保风险助手，用简洁中文回答用户问题。",
                "无记忆时应走通用提示词",
            )
        finally:
            get_store().clear(sid)

    def test_tier1_skipped_when_batch_not_ok(self):
        """批量记忆存在但 ok=False → 跳过批量，走单份/通用。"""
        sid = "test-tier1-skip-not-ok"
        get_store().clear(sid)
        bad_batch = _build_mock_batch()
        bad_batch["ok"] = False
        get_store().set_batch_report(sid, bad_batch)
        try:
            system_content = self._run_and_capture_system_content(sid)
            self.assertEqual(
                system_content,
                "你是智能核保风险助手，用简洁中文回答用户问题。",
                "batch.ok=False 时应跳过批量走通用",
            )
        finally:
            get_store().clear(sid)

    def test_tier2_skipped_when_report_not_ok(self):
        """单份记忆存在但 ok=False → 跳过单份，走通用。"""
        sid = "test-tier2-skip-not-ok"
        get_store().clear(sid)
        bad_report = _build_mock_report()
        bad_report["ok"] = False
        get_store().set_last_report(sid, bad_report)
        try:
            system_content = self._run_and_capture_system_content(sid)
            self.assertEqual(
                system_content,
                "你是智能核保风险助手，用简洁中文回答用户问题。",
                "report.ok=False 时应跳过单份走通用",
            )
        finally:
            get_store().clear(sid)


# ============================================================================
# 4) 流式事件序列测试（mock SSE）
# ============================================================================

class TestStreamFollowupMockedSSE(unittest.TestCase):
    """mock urllib.request.urlopen 返回构造的 SSE 流，验证事件序列。"""

    def test_reasoning_then_content_then_done(self):
        """reasoning 片段先于 content 片段，拼接正确，最后 yield done。"""
        sid = "test-sse-sequence"
        get_store().clear(sid)
        lines = [
            _sse_line({"reasoning_content": "Let me think"}),
            _sse_line({"reasoning_content": " carefully"}),
            _sse_line({"content": "The answer"}),
            _sse_line({"content": " is 42"}),
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen",
                   return_value=_FakeResponse(lines)) as m:
            events = list(stream_followup("test question", session_id=sid))

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

    def test_event_types_are_exactly_reasoning_content_done(self):
        """事件类型集合应只含 reasoning/content/done（无其他类型）。"""
        sid = "test-sse-types"
        get_store().clear(sid)
        lines = [
            _sse_line({"reasoning_content": "thinking"}),
            _sse_line({"content": "answer"}),
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen", return_value=_FakeResponse(lines)):
            events = list(stream_followup("q", session_id=sid))
        types = {e["type"] for e in events}
        self.assertEqual(types, {"reasoning", "content", "done"},
                         f"事件类型集合应为 {{reasoning, content, done}}，实际 {types}")

    def test_event_sequence_exact_order(self):
        """验证完整事件序列：[reasoning, reasoning, content, content, done]。"""
        sid = "test-sse-order"
        get_store().clear(sid)
        lines = [
            _sse_line({"reasoning_content": "r1"}),
            _sse_line({"reasoning_content": "r2"}),
            _sse_line({"content": "c1"}),
            _sse_line({"content": "c2"}),
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen", return_value=_FakeResponse(lines)):
            events = list(stream_followup("q", session_id=sid))

        expected = [
            {"type": "reasoning", "text": "r1"},
            {"type": "reasoning", "text": "r2"},
            {"type": "content", "text": "c1"},
            {"type": "content", "text": "c2"},
            {"type": "done"},
        ]
        self.assertEqual(events, expected,
                         f"事件序列应与预期完全一致，实际 {events}")

    def test_only_content_no_reasoning(self):
        """无 reasoning_content 时只 yield content + done。"""
        sid = "test-sse-content-only"
        get_store().clear(sid)
        lines = [
            _sse_line({"content": "hello"}),
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen", return_value=_FakeResponse(lines)):
            events = list(stream_followup("q", session_id=sid))
        types = [e["type"] for e in events]
        self.assertEqual(types, ["content", "done"],
                         f"无 reasoning 时应为 [content, done]，实际 {types}")

    def test_empty_stream_yields_done(self):
        """空 SSE 流（无 data 行）应直接 yield done。"""
        sid = "test-sse-empty"
        get_store().clear(sid)
        lines = [b'\n', b': comment\n', b'\n']
        with patch("urllib.request.urlopen", return_value=_FakeResponse(lines)):
            events = list(stream_followup("q", session_id=sid))
        self.assertEqual(events, [{"type": "done"}],
                         f"空流应只 yield done，实际 {events}")

    def test_error_branch_http_error(self):
        """urlopen 抛 HTTPError → yield 一个 error 事件，且不 yield done。"""
        sid = "test-sse-http-error"
        get_store().clear(sid)
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError("url", 500, "err", {}, None)):
            events = list(stream_followup("x", session_id=sid))
        self.assertTrue(any(e["type"] == "error" for e in events),
                        f"应 yield 一个 error 事件，实际事件 {events!r}")
        err_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(err_events), 1, "应只有一个 error 事件")
        self.assertTrue(err_events[0].get("text"), "error 事件 text 不应为空")
        self.assertIn("HTTP 500", err_events[0]["text"], "error text 应含 HTTP 状态码")
        # HTTPError 时不应有 done 事件（异常分支 return，不执行到 yield done）
        self.assertFalse(any(e["type"] == "done" for e in events),
                         "HTTPError 分支不应 yield done")

    def test_error_branch_generic_exception(self):
        """urlopen 抛通用异常 → yield error 事件，含「LLM 流式调用异常」。"""
        sid = "test-sse-generic-error"
        get_store().clear(sid)
        with patch("urllib.request.urlopen",
                   side_effect=ConnectionRefusedError("connection refused")):
            events = list(stream_followup("x", session_id=sid))
        err_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(err_events), 1, "应只有一个 error 事件")
        self.assertIn("LLM 流式调用异常", err_events[0]["text"],
                      "error text 应含「LLM 流式调用异常」前缀")
        self.assertIn("connection refused", err_events[0]["text"],
                      "error text 应含原始异常信息")

    def test_malformed_sse_lines_skipped(self):
        """非 JSON 的 data 行应被跳过，不崩溃。"""
        sid = "test-sse-malformed"
        get_store().clear(sid)
        lines = [
            b'data: not json\n\n',
            _sse_line({"content": "good"}),
            b'data: {bad json\n\n',
            b'data: {"choices": []}\n\n',  # 无 delta，跳过
            b'data: [DONE]\n\n',
        ]
        with patch("urllib.request.urlopen", return_value=_FakeResponse(lines)):
            events = list(stream_followup("q", session_id=sid))
        content_text = "".join(e["text"] for e in events if e["type"] == "content")
        self.assertEqual(content_text, "good", "应只产出有效 content")
        self.assertEqual(events[-1]["type"], "done")


# ============================================================================
# 5) 端点未连兜底测试（真实调用，不 mock）
# ============================================================================

class TestStreamFollowupEndpointUnreachable(unittest.TestCase):
    """真实调用 stream_followup（不 mock），验证 LLM 不可达时的兜底行为。

    LLM 端点 localhost:8000 当前未连，预期 urlopen 抛连接异常 → yield error 事件，
    生成器正常结束（不抛异常到调用方）。
    """

    def test_yields_error_when_endpoint_down(self):
        sid = "test-endpoint-down"
        get_store().clear(sid)
        try:
            events = list(stream_followup("高血压如何加费", session_id=sid))
        except Exception as e:
            self.fail(f"stream_followup 在端点未连时不应抛异常到调用方，实际抛出：{e!r}")

        self.assertTrue(events, "应至少 yield 一个事件")
        # 应有 error 事件
        err_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(err_events), 1,
                         f"应 yield 一个 error 事件，实际 {events!r}")
        err_text = err_events[0].get("text", "")
        self.assertTrue(err_text, "error 事件 text 不应为空")
        # error text 应为两种格式之一
        self.assertTrue(
            err_text.startswith("LLM 流式调用异常") or err_text.startswith("LLM 请求失败"),
            f"error text 应以「LLM 流式调用异常」或「LLM 请求失败」开头，实际 {err_text!r}"
        )
        # 不应有 done 事件（异常分支 return，不执行到 yield done）
        self.assertFalse(any(e["type"] == "done" for e in events),
                         "异常分支不应 yield done")


# ============================================================================
# 6) answer_followup 同步版本测试（mock LLM）
# ============================================================================

class TestAnswerFollowupSync(unittest.TestCase):
    """answer_followup 同步版本：三级回退 + LLM 降级保护。"""

    def test_tier1_batch_uses_llm_invoke(self):
        """有批量记忆时调用 build_llm().invoke，返回 content。"""
        sid = "test-sync-tier1"
        get_store().clear(sid)
        get_store().set_batch_report(sid, _build_mock_batch())

        class _FakeResp:
            content = "这是基于批量结果的回答"

        fake_llm = type("FakeLLM", (), {"invoke": lambda self, p: _FakeResp()})()
        try:
            with patch("underwriting.agent.build_llm", return_value=fake_llm) as m:
                result = answer_followup("问题", session_id=sid)
            self.assertTrue(m.called, "build_llm 应被调用")
            self.assertEqual(result, "这是基于批量结果的回答")
        finally:
            get_store().clear(sid)

    def test_tier2_single_report_uses_llm_invoke(self):
        """无批量、有单份记忆时调用 build_llm().invoke。"""
        sid = "test-sync-tier2"
        get_store().clear(sid)
        get_store().set_last_report(sid, _build_mock_report())

        class _FakeResp:
            content = "这是基于单份报告的回答"

        fake_llm = type("FakeLLM", (), {"invoke": lambda self, p: _FakeResp()})()
        try:
            with patch("underwriting.agent.build_llm", return_value=fake_llm):
                result = answer_followup("问题", session_id=sid)
            self.assertEqual(result, "这是基于单份报告的回答")
        finally:
            get_store().clear(sid)

    def test_tier3_generic_uses_llm_invoke(self):
        """无记忆时走通用提示词，仍调用 build_llm().invoke。"""
        sid = "test-sync-tier3"
        get_store().clear(sid)

        class _FakeResp:
            content = "通用回答"

        fake_llm = type("FakeLLM", (), {"invoke": lambda self, p: _FakeResp()})()
        try:
            with patch("underwriting.agent.build_llm", return_value=fake_llm) as m:
                result = answer_followup("问题", session_id=sid)
            self.assertTrue(m.called, "build_llm 应被调用")
            self.assertEqual(result, "通用回答")
        finally:
            get_store().clear(sid)

    def test_llm_invoke_exception_returns_degraded_text(self):
        """LLM invoke 抛异常时返回降级提示文本，不抛异常。"""
        sid = "test-sync-llm-error"
        get_store().clear(sid)

        class _BoomLLM:
            def invoke(self, p):
                raise RuntimeError("llm down")

        try:
            with patch("underwriting.agent.build_llm", return_value=_BoomLLM()):
                result = answer_followup("问题", session_id=sid)
            self.assertIn("LLM 调用失败", result)
            self.assertIn("llm down", result)
        finally:
            get_store().clear(sid)

    def test_llm_unavailable_returns_degraded_text(self):
        """build_llm 返回 None（langchain_openai 不可用）时返回降级提示。"""
        sid = "test-sync-no-llm"
        get_store().clear(sid)
        try:
            with patch("underwriting.agent.build_llm", return_value=None):
                result = answer_followup("问题", session_id=sid)
            self.assertIn("LLM 未就绪", result)
        finally:
            get_store().clear(sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
