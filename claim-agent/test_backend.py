# -*- coding: utf-8 -*-
"""
test_backend.py — 智能理赔 Agent FastAPI 后端单元测试（Task 10）

覆盖 backend/main.py 的 5 个 /api/* 端点：
- GET  /api/health                  → 健康检查
- POST /api/invoice/process         → 单张发票 SSE（status / done）
- POST /api/batch/process           → 批量发票 SSE（status / done）
- POST /api/followup                → 追问 SSE（reasoning / content / done / error）
- GET  /api/session/{sid}/csv       → 批量结果 CSV 导出（UTF-8 BOM）

约定：
- 用 unittest + fastapi.testclient.TestClient（与项目现有 test_batch.py / test_stream.py
  风格一致，不引入 pytest）。
- 所有外部依赖（agent.pipeline.process_invoice_stream / agent.batch_pipeline.
  process_batch_stream / agent.agent.stream_followup / agent.memory.get_store /
  tools.export_tool.export_batch_csv）一律用 unittest.mock.patch 拦截，patch 目标
  统一为 `backend.main.<name>`（main.py 已把这些名字绑定到自身命名空间）。
- TestClient 基于 httpx，对 StreamingResponse 会读取完整 body，response.text 即完整
  SSE 文本，按 "\n\n" 分段 + "data:" 行 JSON.parse 即得事件列表。

运行：
    "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" test_backend.py -v
"""

import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# ---- 注入项目根到 sys.path，再 import 项目内模块（与 backend/main.py 顶部一致）----
sys.path.insert(0, r"c:\Users\OKONE\fake_ocr_test")
import agent  # noqa: F401  注入 sys.path
import config as cfg  # noqa: F401

from fastapi.testclient import TestClient
from backend.main import app


# --------------------------------------------------------------------------- #
# SSE 解析辅助
# --------------------------------------------------------------------------- #
def parse_sse_events(response):
    """把 TestClient 响应体按 SSE 协议解析为事件 dict 列表。

    TestClient 对 StreamingResponse 会读取完整 body，response.text 含完整 SSE 文本。
    按 "\\n\\n" 分段，每段取 `data:` 行 JSON.parse；空段与非 data 行跳过。
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
class TestBackendHealth(unittest.TestCase):
    """GET /api/health 返回 ok 状态与服务名。"""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_ok(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "ok",
                         f"status 应为 'ok'，实际 {body!r}")
        self.assertEqual(body.get("service"), "claim-agent-backend",
                         f"service 应为 'claim-agent-backend'，实际 {body!r}")


# ============================================================================
# 2) 单张发票处理 SSE
# ============================================================================
class TestInvoiceProcessSSE(unittest.TestCase):
    """POST /api/invoice/process：mock process_invoice_stream，验证 status→done 序列。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(*args, **kwargs):
        yield {"status": "🔍 正在识别…"}
        yield {"status": "✅ 识别完成"}
        yield {"done": True,
               "result": {"ok": True,
                          "extract": {"fphm": "12345"},
                          "decision": {"conclusion": "全额通过"}}}

    def test_invoice_process_yields_status_then_done(self):
        with patch("backend.main.process_invoice_stream",
                   side_effect=self._fake_stream):
            r = self.client.post(
                "/api/invoice/process",
                files={"image": ("test.png", io.BytesIO(PNG_BYTES), "image/png")},
                data={"do_verify": "false", "session_id": "testsid"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        types = [e.get("type") for e in events]
        self.assertEqual(types, ["status", "status", "done"],
                         f"事件类型序列应为 [status,status,done]，实际 {types}")
        # 第一个 status 含「识别」
        self.assertIn("识别", events[0].get("text", ""),
                      f"首个 status 的 text 应含「识别」，实际 {events[0]!r}")
        # done 事件 result.ok==True
        done = events[-1]
        self.assertTrue(done.get("result", {}).get("ok") is True,
                        f"done.result.ok 应为 True，实际 {done!r}")


# ============================================================================
# 3) 批量发票处理 SSE
# ============================================================================
class TestBatchProcessSSE(unittest.TestCase):
    """POST /api/batch/process：mock process_batch_stream，验证 status→done 序列。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(*args, **kwargs):
        yield {"status": "批量处理中"}
        yield {"done": True,
               "result": {"ok": True,
                          "aggregate": {"conclusion": "全部通过",
                                        "summary_text": "批量完成"},
                          "invoices": []}}

    def test_batch_process_yields_status_then_done(self):
        with patch("backend.main.process_batch_stream",
                   side_effect=self._fake_stream):
            r = self.client.post(
                "/api/batch/process",
                files=[
                    ("files", ("a.png", io.BytesIO(PNG_BYTES), "image/png")),
                    ("files", ("b.png", io.BytesIO(PNG_BYTES), "image/png")),
                ],
                data={"do_verify": "false", "session_id": "testsid"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        types = [e.get("type") for e in events]
        self.assertEqual(types, ["status", "done"],
                         f"事件类型序列应为 [status,done]，实际 {types}")
        done = events[-1]
        agg = done.get("result", {}).get("aggregate", {})
        self.assertEqual(agg.get("conclusion"), "全部通过",
                         f"done.result.aggregate.conclusion 应为「全部通过」，实际 {agg!r}")


# ============================================================================
# 4) 追问 SSE — 思考链不丢专项回归测试
# ============================================================================
class TestFollowupSSE(unittest.TestCase):
    """POST /api/followup：mock stream_followup，验证思考链每个 chunk 都到达前端。

    专项意义：用户痛点「思考链会断」的回归测试——必须验证 5 个 reasoning chunk
    全部按序到达，无丢失、无合并。
    """

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(*args, **kwargs):
        # 5 个 reasoning chunk + 3 个 content chunk + 1 个 done
        for i in range(1, 6):
            yield {"type": "reasoning", "text": f"r{i}"}
        for i in range(1, 4):
            yield {"type": "content", "text": f"c{i}"}
        yield {"type": "done"}

    def test_followup_reasoning_not_lost(self):
        with patch("backend.main.stream_followup", side_effect=self._fake_stream):
            r = self.client.post(
                "/api/followup",
                json={"message": "测试", "session_id": "testsid"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200，实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)

        # 总共 9 个事件：5 reasoning + 3 content + 1 done
        self.assertEqual(len(events), 9,
                         f"应收到 9 个事件（5 reasoning + 3 content + 1 done），"
                         f"实际 {len(events)}: {events}")

        # 事件类型按序排列
        types = [e.get("type") for e in events]
        self.assertEqual(
            types,
            ["reasoning"] * 5 + ["content"] * 3 + ["done"],
            f"事件类型序列应为 5 reasoning + 3 content + 1 done，实际 {types}")

        # 5 个 reasoning 的 text 依次为 r1..r5（全部保留，无丢失）
        reasoning_texts = [e.get("text") for e in events
                           if e.get("type") == "reasoning"]
        self.assertEqual(
            reasoning_texts,
            [f"r{i}" for i in range(1, 6)],
            f"reasoning 片段应完整保留 r1..r5（无丢失），实际 {reasoning_texts}")

        # 3 个 content 的 text 依次为 c1..c3
        content_texts = [e.get("text") for e in events
                         if e.get("type") == "content"]
        self.assertEqual(
            content_texts,
            [f"c{i}" for i in range(1, 4)],
            f"content 片段应完整保留 c1..c3，实际 {content_texts}")

        # 最后一个是 done
        self.assertEqual(events[-1].get("type"), "done",
                         f"最后一个事件应为 done，实际 {events[-1]!r}")


# ============================================================================
# 5) 追问 SSE — error 分支
# ============================================================================
class TestFollowupSSEErrorBranch(unittest.TestCase):
    """POST /api/followup：mock stream_followup yield error 事件，验证错误下发。"""

    def setUp(self):
        self.client = TestClient(app)

    @staticmethod
    def _fake_stream(*args, **kwargs):
        yield {"type": "error", "text": "LLM 异常"}

    def test_followup_error_event(self):
        with patch("backend.main.stream_followup", side_effect=self._fake_stream):
            r = self.client.post(
                "/api/followup",
                json={"message": "测试", "session_id": "testsid"},
            )
        self.assertEqual(r.status_code, 200,
                         f"HTTP 状态应为 200（SSE 内 error 事件，非 HTTP 错误），"
                         f"实际 {r.status_code} body={r.text!r}")
        events = parse_sse_events(r)
        self.assertTrue(any(e.get("type") == "error" for e in events),
                        f"应收到 error 事件，实际事件列表 {events}")
        err = [e for e in events if e.get("type") == "error"][0]
        self.assertIn("LLM 异常", err.get("text", ""),
                      f"error 事件 text 应含「LLM 异常」，实际 {err!r}")


# ============================================================================
# 6) CSV 导出
# ============================================================================
class TestCSVExport(unittest.TestCase):
    """GET /api/session/{sid}/csv：mock get_store + export_batch_csv，验证 BOM/headers/404。

    后端实现：调用 export_batch_csv(batch) 拿到带 UTF-8 BOM 的 CSV 字符串，直接
    encode("utf-8") 作为 Response content 返回，无需落盘临时文件（BOM 由
    export_batch_csv 自身写入）。
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_csv_export_success(self):
        store = MagicMock()
        store.get_batch_claim.return_value = {
            "ok": True,
            "invoices": [{"filename": "test.png"}],
        }
        csv_str = "\ufeff序号,文件名\n1,test.png\n"
        with patch("backend.main.get_store", return_value=store), \
                patch("backend.main.export_batch_csv", return_value=csv_str):
            r = self.client.get("/api/session/testsid/csv")

        self.assertEqual(r.status_code, 200,
                         f"CSV 导出应返回 200，实际 {r.status_code} body={r.text!r}")
        self.assertIn("text/csv", r.headers.get("content-type", ""),
                      f"content-type 应含 text/csv，实际 {r.headers.get('content-type')!r}")
        cd = r.headers.get("content-disposition", "")
        self.assertIn("attachment; filename=batch_testsid.csv", cd,
                      f"content-disposition 应含 attachment; filename=batch_testsid.csv，"
                      f"实际 {cd!r}")
        # 响应 bytes 以 UTF-8 BOM 开头
        self.assertTrue(
            r.content.startswith(b"\xef\xbb\xbf"),
            f"响应应以 UTF-8 BOM (\\xef\\xbb\\xbf) 开头，实际前 6 字节: {r.content[:6]!r}")

    def test_csv_export_not_found(self):
        store = MagicMock()
        store.get_batch_claim.return_value = None
        with patch("backend.main.get_store", return_value=store):
            r = self.client.get("/api/session/unknown/csv")
        self.assertEqual(r.status_code, 404,
                         f"未找到会话应返回 404，实际 {r.status_code} body={r.text!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
