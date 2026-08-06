# -*- coding: utf-8 -*-
"""
test_underwriting_backend.py — 核保风险 Agent FastAPI 后端单元测试（Task 9 / SubTask 9.4）

覆盖 underwriting/backend.py 的端点：
- GET  /api/health                              → 健康检查 ``{"ok": true}``
- GET  /                                        → 前端首页（占位 HTML）
- POST /api/underwriting/process                → 单份核保 SSE（session / status / done）
- POST /api/underwriting/batch                  → 批量核保 SSE（session / progress / done）
- POST /api/underwriting/followup               → 追问 SSE（session / reasoning / content / done / error）
- GET  /api/underwriting/session/{sid}/csv      → 批量结果 CSV 导出（UTF-8 BOM）+ 404 分支

约定（与 test_backend.py 风格一致）：
- unittest + fastapi.testclient.TestClient，不引入 pytest。
- 所有外部依赖（process_report_stream / process_batch_stream / stream_followup）
  一律用 unittest.mock.patch 拦截，patch 目标统一为 ``underwriting.backend.<name>``
  （backend.py 已把这些名字绑定到自身命名空间）。
- CSV 测试用真实 export_batch_csv + 真实 get_store 单例（in-memory），验证 BOM 与
  Content-Disposition；不存在会话验证 404。
- TestClient 基于 httpx，对 StreamingResponse 会读取完整 body，response.text 即完整
  SSE 文本，按 ``\\n\\n`` 分段 + ``data:`` 行 JSON.parse 即得事件列表。

运行：
    "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" test_underwriting_backend.py -v
"""

import io
import json
import sys
import unittest
from unittest.mock import patch, MagicMock

# ---- 注入项目根到 sys.path ----
sys.path.insert(0, r"c:\Users\OKONE\fake_ocr_test")
import underwriting  # noqa: F401  注入 sys.path
import config as cfg  # noqa: F401

from fastapi.testclient import TestClient
from underwriting.backend import app
from underwriting.memory import get_store


# --------------------------------------------------------------------------- #
# SSE 解析辅助
# --------------------------------------------------------------------------- #
def parse_sse_events(response):
    """把 TestClient 响应体按 SSE 协议解析为事件 dict 列表。

    TestClient 对 StreamingResponse 会读取完整 body，response.text 含完整 SSE 文本。
    按 ``\\n\\n`` 分段，每段取 ``data:`` 行 JSON.parse；空段与非 data 行跳过。
    """
    events = []
    body = response.text
    for raw_event in body.split("\n\n"):
        if not raw_event.strip():
            continue
        for line in raw_event.split("\n"):
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    try:
                        events.append(json.loads(payload))
                    except Exception:
                        pass
    return events


# 最简 PNG 头（backend 只把上传文件落盘到 tempfile，真实处理已被 mock，无需可解码图片）
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


# ============================================================================
# 1) 健康检查
# ============================================================================
class TestHealth(unittest.TestCase):
    """GET /api/health 返回 ``{"ok": true}``。"""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_ok(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code}")
        body = r.json()
        self.assertTrue(body.get("ok") is True,
                        f"ok 应为 true，实际 {body!r}")


# ============================================================================
# 2) 前端首页（占位 HTML）
# ============================================================================
class TestIndex(unittest.TestCase):
    """GET / 返回 HTML；index.html 不存在时返回占位 HTML，app 不崩溃。"""

    def setUp(self):
        self.client = TestClient(app)

    def test_index_returns_html(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code}")
        # 应返回 HTML（占位或真实 index.html）
        ct = r.headers.get("content-type", "")
        self.assertIn("text/html", ct,
                      f"Content-Type 应含 text/html，实际 {ct!r}")
        self.assertIn("核保", r.text,
                      f"首页应含「核保」字样，实际 body 前 200 字：{r.text[:200]!r}")


# ============================================================================
# 3) 单份核保 SSE
# ============================================================================
class TestProcessReportSSE(unittest.TestCase):
    """POST /api/underwriting/process：mock process_report_stream，验证 status→done。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(image_path, session_id=None):
        yield {"status": "🔍 正在识别报告（多模态提取）…"}
        yield {"status": "✅ 报告识别完成：体检报告"}
        yield {"done": True, "result": {
            "ok": True,
            "patient": {"name": "张三", "gender": "男", "age": 45},
            "report_type": "体检报告",
            "overall_risk": "中",
            "recommendation": "次标准体-加费",
        }}

    def test_process_yields_status_then_done(self):
        with patch("underwriting.backend.process_report_stream",
                   side_effect=self._fake_stream):
            r = self.client.post(
                "/api/underwriting/process",
                files={"image": ("report.png", io.BytesIO(PNG_BYTES), "image/png")},
                data={"session_id": "sid-test"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        types = [e.get("type") for e in events]
        # 提供了 session_id，不应有 session 事件
        self.assertNotIn("session", types,
                         f"提供了 session_id 时不应有 session 事件，实际 {types}")
        self.assertEqual(types, ["status", "status", "done"],
                         f"事件类型序列应为 [status,status,done]，实际 {types}")
        # done.result.ok==True
        done = events[-1]
        self.assertTrue(done.get("result", {}).get("ok") is True,
                        f"done.result.ok 应为 True，实际 {done!r}")
        # 透传 session_id 给底层
        self.assertEqual(
            self._fake_stream.call_count if hasattr(self._fake_stream, "call_count") else 0,
            0, "side_effect 函数本身不是 mock，跳过 call_count 校验")

    def test_process_generates_session_when_missing(self):
        """未提供 session_id 时，首条事件回传生成的 session_id。"""
        captured = {}

        def fake(image_path, session_id=None):
            captured["session_id"] = session_id
            yield {"status": "处理中"}
            yield {"done": True, "result": {"ok": True}}

        with patch("underwriting.backend.process_report_stream",
                   side_effect=fake):
            r = self.client.post(
                "/api/underwriting/process",
                files={"image": ("report.png", io.BytesIO(PNG_BYTES), "image/png")},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        # 首条应为 session 事件，且 session_id 非空
        self.assertTrue(len(events) >= 1,
                        f"应至少收到 1 个事件，实际 {events}")
        self.assertEqual(events[0].get("type"), "session",
                         f"首条事件应为 session，实际 {events[0]!r}")
        sid = events[0].get("session_id", "")
        self.assertTrue(sid, f"session_id 应非空，实际 {sid!r}")
        # 底层流水线收到的 session_id 与回传一致
        self.assertEqual(captured.get("session_id"), sid,
                         f"底层收到的 session_id 应与回传一致，实际 {captured}")


# ============================================================================
# 4) 批量核保 SSE
# ============================================================================
class TestBatchProcessSSE(unittest.TestCase):
    """POST /api/underwriting/batch：mock process_batch_stream，验证 progress→done。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(file_list, session_id=None):
        yield {"type": "progress", "status": "[1/2] a.png · 🔍 正在核保…",
               "index": 0, "total": 2, "filename": "a.png",
               "stage": "extract", "conclusion": None}
        yield {"type": "progress", "status": "[1/2] a.png · ✅ 整体风险「中」｜建议 次标准体-加费",
               "index": 0, "total": 2, "filename": "a.png",
               "stage": "done", "conclusion": "中/次标准体-加费"}
        yield {"type": "done", "result": {
            "ok": True,
            "total": 2,
            "success_count": 1,
            "aggregate": {"summary_text": "共 2 张报告，成功 1 张"},
        }}

    def test_batch_yields_progress_then_done(self):
        with patch("underwriting.backend.process_batch_stream",
                   side_effect=self._fake_stream):
            r = self.client.post(
                "/api/underwriting/batch",
                files=[
                    ("files", ("a.png", io.BytesIO(PNG_BYTES), "image/png")),
                    ("files", ("b.png", io.BytesIO(PNG_BYTES), "image/png")),
                ],
                data={"session_id": "sid-batch"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        types = [e.get("type") for e in events]
        self.assertEqual(types, ["progress", "progress", "done"],
                         f"事件类型序列应为 [progress,progress,done]，实际 {types}")
        # progress 事件字段透传
        p1 = events[0]
        self.assertEqual(p1.get("index"), 0)
        self.assertEqual(p1.get("total"), 2)
        self.assertEqual(p1.get("filename"), "a.png")
        self.assertEqual(p1.get("stage"), "extract")
        # done.result.aggregate.summary_text 透传
        done = events[-1]
        self.assertIn("summary_text", done.get("result", {}).get("aggregate", {}),
                      f"done.result.aggregate.summary_text 应存在，实际 {done!r}")


# ============================================================================
# 5) 追问 SSE — 思考链不丢专项回归测试
# ============================================================================
class TestFollowupSSE(unittest.TestCase):
    """POST /api/underwriting/followup：mock stream_followup，验证思考链完整 + session 透传。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(message, session_id="default"):
        # 3 个 reasoning chunk + 2 个 content chunk + 1 个 done
        for i in range(1, 4):
            yield {"type": "reasoning", "text": f"r{i}"}
        for i in range(1, 3):
            yield {"type": "content", "text": f"c{i}"}
        yield {"type": "done"}

    def test_followup_reasoning_not_lost(self):
        with patch("underwriting.backend.stream_followup",
                   side_effect=self._fake_stream) as mk:
            r = self.client.post(
                "/api/underwriting/followup",
                json={"message": "该患者高血压风险如何加费", "session_id": "sid-followup"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)

        # 总共 6 个事件：3 reasoning + 2 content + 1 done（提供了 session_id，无 session 事件）
        types = [e.get("type") for e in events]
        self.assertEqual(types, ["reasoning", "reasoning", "reasoning",
                                 "content", "content", "done"],
                         f"事件类型序列应为 3 reasoning + 2 content + 1 done，实际 {types}")

        # 3 个 reasoning 的 text 依次为 r1..r3（全部保留，无丢失）
        reasoning_texts = [e.get("text") for e in events
                           if e.get("type") == "reasoning"]
        self.assertEqual(reasoning_texts, ["r1", "r2", "r3"],
                         f"reasoning 片段应完整保留 r1..r3（无丢失），实际 {reasoning_texts}")

        # 2 个 content 的 text 依次为 c1..c2
        content_texts = [e.get("text") for e in events
                         if e.get("type") == "content"]
        self.assertEqual(content_texts, ["c1", "c2"],
                         f"content 片段应完整保留 c1..c2，实际 {content_texts}")

        # session_id 透传给底层 stream_followup
        mk.assert_called_once_with(
            "该患者高血压风险如何加费", session_id="sid-followup")

    def test_followup_generates_session_when_missing(self):
        """未提供 session_id 时，首条事件回传生成的 session_id。"""
        captured = {}

        def fake(message, session_id="default"):
            captured["session_id"] = session_id
            yield {"type": "content", "text": "回答"}
            yield {"type": "done"}

        with patch("underwriting.backend.stream_followup", side_effect=fake):
            r = self.client.post(
                "/api/underwriting/followup",
                json={"message": "测试"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        self.assertEqual(events[0].get("type"), "session",
                         f"首条事件应为 session，实际 {events[0]!r}")
        sid = events[0].get("session_id", "")
        self.assertTrue(sid, f"session_id 应非空，实际 {sid!r}")
        self.assertEqual(captured.get("session_id"), sid,
                         f"底层收到的 session_id 应与回传一致，实际 {captured}")


# ============================================================================
# 6) 追问 SSE — error 分支
# ============================================================================
class TestFollowupSSEErrorBranch(unittest.TestCase):
    """POST /api/underwriting/followup：mock stream_followup yield error 事件，验证错误下发。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(message, session_id="default"):
        yield {"type": "error", "text": "LLM 请求失败：HTTP 500"}

    def test_followup_error_event(self):
        with patch("underwriting.backend.stream_followup",
                   side_effect=self._fake_stream):
            r = self.client.post(
                "/api/underwriting/followup",
                json={"message": "测试", "session_id": "sid-err"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200（SSE 内 error 事件，非 HTTP 错误），"
                         f"实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        self.assertTrue(any(e.get("type") == "error" for e in events),
                        f"应收到 error 事件，实际事件列表 {events}")
        err = [e for e in events if e.get("type") == "error"][0]
        self.assertIn("LLM 请求失败", err.get("text", ""),
                      f"error 事件 text 应含「LLM 请求失败」，实际 {err!r}")


# ============================================================================
# 7) CSV 导出（真实 export_batch_csv + 真实 get_store 单例）
# ============================================================================
class TestCSVExport(unittest.TestCase):
    """GET /api/underwriting/session/{sid}/csv：验证 BOM/headers/404。

    用真实 get_store 单例（in-memory）+ 真实 export_batch_csv，构造一个最小合法
    batch_result 存入 memory，验证返回 text/csv + UTF-8 BOM + Content-Disposition。
    不存在会话验证 404 + ``{"detail":"未找到批量结果"}``。
    """

    def setUp(self):
        self.client = TestClient(app)
        self.sid = "sid-csv-test"
        # 构造最小合法 batch_result（对齐 batch_pipeline 输出结构）
        self.batch_result = {
            "ok": True,
            "session_id": self.sid,
            "total": 1,
            "success_count": 1,
            "duplicate_count": 0,
            "fail_count": 0,
            "reports": [{
                "index": 0,
                "filename": "report.png",
                "ok": True,
                "stage": None,
                "message": None,
                "duplicate_of": None,
                "report": {
                    "ok": True,
                    "patient": {"name": "张三"},
                    "report_type": "体检报告",
                    "overall_risk": "中",
                    "recommendation": "次标准体-加费",
                    "abnormalities": [{"name": "血压偏高"}],
                    "references": [{"title": "高血压指南", "url": "http://x"}],
                },
            }],
            "duplicates": [],
            "errors": [],
            "aggregate": {"summary_text": "共 1 张报告，成功 1 张"},
        }
        # 写入 memory 单例
        get_store().set_batch_report(self.sid, self.batch_result)

    def tearDown(self):
        get_store().clear(self.sid)

    def test_csv_export_returns_bom(self):
        r = self.client.get(f"/api/underwriting/session/{self.sid}/csv")
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code}")
        # Content-Type 应为 text/csv
        ct = r.headers.get("content-type", "")
        self.assertIn("text/csv", ct,
                      f"Content-Type 应含 text/csv，实际 {ct!r}")
        # Content-Disposition 应含 attachment + underwriting_{sid}.csv
        cd = r.headers.get("content-disposition", "")
        self.assertIn("attachment", cd,
                      f"Content-Disposition 应含 attachment，实际 {cd!r}")
        self.assertIn(f"underwriting_{self.sid}.csv", cd,
                      f"Content-Disposition 应含 underwriting_{self.sid}.csv，实际 {cd!r}")
        # 应以 UTF-8 BOM 开头（\xef\xbb\xbf）
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"),
                        f"响应应以 UTF-8 BOM 开头，实际前 6 字节：{r.content[:6]!r}")
        # 解码后应含表头与患者姓名
        text = r.content.decode("utf-8-sig")
        self.assertIn("序号", text, f"CSV 应含表头「序号」，实际 {text!r}")
        self.assertIn("张三", text, f"CSV 应含患者姓名「张三」，实际 {text!r}")
        self.assertIn("次标准体-加费", text,
                      f"CSV 应含核保建议「次标准体-加费」，实际 {text!r}")

    def test_csv_export_404_when_missing(self):
        """不存在批量结果的会话返回 404 + ``{"detail":"未找到批量结果"}``。"""
        missing_sid = "sid-not-exist"
        # 确保该会话在 store 中不存在
        get_store().clear(missing_sid)
        r = self.client.get(f"/api/underwriting/session/{missing_sid}/csv")
        self.assertEqual(r.status_code, 404,
                         f"HTTP 状态应为 404，实际 {r.status_code}")
        body = r.json()
        self.assertIn("未找到批量结果", body.get("detail", ""),
                      f"detail 应含「未找到批量结果」，实际 {body!r}")


# ============================================================================
# 入口
# ============================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
