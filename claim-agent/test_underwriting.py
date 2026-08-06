# -*- coding: utf-8 -*-
"""
test_underwriting.py — 核保风险 Agent 综合集成测试（Task 11 / SubTask 11.1 + 11.2）

定位与已有测试的分工（避免重复）：
- test_underwriting_agent.py（Task 7，28 用例）：聚焦 stream_followup 的 SSE 解析、
  三级回退分支选择、_format_report_context/_format_batch_context 纯函数。
- test_underwriting_backend.py（Task 9，10 用例）：聚焦 FastAPI 端点（TestClient）+
  SSE 透传 + CSV 导出，所有底层 stream 均被 mock。
- **本文件（test_underwriting.py）**：聚焦**集成链路**——
  1. 单份流水线把 4 个工具（extract/abnormality/risk/medical_search）按确定性顺序
     串起来，验证事件序列 + 报告结构 + 建议映射 + 报告卡渲染（mock 4 个工具函数，
     走真实 pipeline.process_report_stream）。
  2. 批量核保把 N 张图通过 batch_pipeline 串起来（mock process_report 单份入口），
     验证 progress→done 事件序列 + 聚合统计 + CSV BOM（走真实 batch_pipeline）。
  3. **搜索集成（真实联网，核心）**：调用 search_medical(["高血压"])，验证返回
     references 非空、每项含必要字段、url 去重正确；联网失败则 skip 不阻塞。
  4. 流式追问集成（mock SSE）：验证 stream_followup 事件序列 reasoning/content/done
     + 三级回退（set_last_report 后走单份分支，通过捕获 body 验证）。
  5. 端到端配置与导入：验证 underwriting 包所有模块可导入、config 关键常量存在。
  6. 浏览器端到端验证占位（SubTask 11.2）：skip 标记 + 顶部手动验证步骤说明。

手动浏览器端到端验证步骤（SubTask 11.2，LLM 端点 localhost:8000 经 SSH 隧道指向
AMD Radeon + ROCm 上的 Qwen3.6-27B 时执行）：
  1. 启动后端：
       $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
       & "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" -m underwriting.backend
     确认控制台输出「Uvicorn running on http://0.0.0.0:8002」。
  2. 浏览器打开 http://localhost:8002 ，应看到「核保风险 Agent」单份/批量两 Tab。
  3. 单份 Tab：上传一张病历/体检报告图片（如 fapiao.jpg 同目录的体检报告样例），
     点击「开始核保」。观察：
       - 阶段进度区逐条追加「🔍 正在识别报告… ✅ 报告识别完成… 🔬 异常… ⚠️ 风险…
         🔎 联网检索… 📝 生成报告」。
       - 思考过程折叠区逐字追加（若该阶段调用 LLM）。
       - 报告卡区出现：风险色块（绿/黄/红）+ 核保建议 + 报告摘要 + 异常明细表 +
         风险明细表 + 医学参考引用列表（含标题/来源/链接）。
  4. 批量 Tab：选择多张图片（含一张重复、一张不可识别），点击「批量核保」。观察：
       - 进度区逐张追加 [i/N] filename · 阶段，重复张标注「⚠️ 重复报告」，失败张
         标注「❌ 处理失败」。
       - 完成后出现汇总卡（成功/重复/失败计数 + 风险分布 + 建议分布）+ CSV 下载按钮。
       - 点击 CSV 下载，文件以 UTF-8 BOM 开头，Excel 打开中文不乱码。
  5. 追问：在报告卡下方输入「该患者高血压风险如何加费」并提交。观察：
       - 思考过程区逐字追加 reasoning（灰色），正文区逐字追加 content（黑色）。
       - 思考链完整不断（不会「说一半断」），最后出现「✅ 回答完成」。
  6. 健康检查：浏览器或 curl 访问 http://localhost:8002/api/health ，应返回
     {"ok": true}。

运行：
    $env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
    & "C:\\Users\\OKONE\\anaconda3\\envs\\deepseekocr\\python.exe" -m unittest test_underwriting -v
"""

import csv
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch

# ---- 注入项目根到 sys.path（与 test_underwriting_agent.py / test_underwriting_backend.py 一致）----
sys.path.insert(0, r"c:\Users\OKONE\fake_ocr_test")

import underwriting  # noqa: F401  注入 sys.path（确保 import config 可用）
import config as cfg  # noqa: F401
from underwriting import config as uwcfg
from underwriting.pipeline import (
    process_report_stream,
    process_report,
    format_report_card,
    format_report_text,
)
from underwriting.batch_pipeline import (
    process_batch_stream,
    process_batch,
    export_batch_csv,
    list_images,
)
from underwriting.agent import stream_followup
from underwriting.memory import get_store
from underwriting.tools.medical_search_tool import search_medical


BASE = os.path.dirname(os.path.abspath(__file__))
FAPIAO = os.path.join(BASE, "fapiao.jpg")


# ============================================================================
# 辅助：构造 mock 工具返回值（供单份流水线集成测试用）
# ============================================================================

def _mock_extract_result():
    """构造 report_extract_tool.extract_report 的 mock 返回值（体检报告，含异常）。"""
    return {
        "report_type": "体检报告",
        "patient": {"name": "张三", "gender": "男", "age": 55},
        "exam_date": "2026-06-15",
        "items": [
            {"name": "收缩压", "value": "165", "unit": "mmHg",
             "reference_range": "90-140", "abnormal": True},
            {"name": "总胆固醇", "value": "6.8", "unit": "mmol/L",
             "reference_range": "<5.2", "abnormal": True},
            {"name": "空腹血糖", "value": "5.4", "unit": "mmol/L",
             "reference_range": "3.9-6.1", "abnormal": False},
        ],
        "diagnoses": ["高血压"],
        "summary": "本次体检发现血压偏高、血脂异常，建议复查并随访。",
    }


def _mock_abnormality_result():
    """构造 abnormality_tool.detect_abnormalities 的 mock 返回值。"""
    return {
        "abnormalities": [
            {"name": "收缩压偏高", "type": "检验越界", "severity_hint": "中",
             "evidence": "收缩压 165 mmHg（参考范围 90-140）",
             "detail": "收缩压超出参考上限，提示高血压可能"},
            {"name": "总胆固醇偏高", "type": "检验越界", "severity_hint": "轻",
             "evidence": "总胆固醇 6.8 mmol/L（参考范围 <5.2）",
             "detail": "总胆固醇升高，提示高脂血症"},
            {"name": "高血压", "type": "诊断", "severity_hint": "中",
             "evidence": "诊断：高血压",
             "detail": "临床诊断高血压，核保需重点关注"},
        ],
        "note": "",
    }


def _mock_risk_result():
    """构造 risk_tool.assess_risk 的 mock 返回值（整体风险「中」）。"""
    return {
        "risks": [
            {"name": "高血压", "risk_level": "中",
             "risk_factors": ["收缩压偏高", "年龄>50"],
             "evidence": "收缩压 165 mmHg",
             "reasoning": "患者收缩压持续偏高，结合年龄因素，心血管事件风险升高"},
            {"name": "高脂血症", "risk_level": "低",
             "risk_factors": ["总胆固醇偏高"],
             "evidence": "总胆固醇 6.8 mmol/L",
             "reasoning": "血脂升高但无合并症，短期风险较低"},
        ],
        "overall_risk": "中",
        "overall_reasoning": "存在高血压等中等风险因素，整体风险中等",
    }


def _mock_search_result():
    """构造 medical_search_tool.search_medical 的 mock 返回值（双端并用结果）。"""
    return {
        "references": [
            {"disease": "高血压", "title": "中国高血压防治指南 2024",
             "url": "https://example.com/htn-guideline",
             "snippet": "高血压核保风险评估要点...", "source": "exa"},
            {"disease": "高血压", "title": "高血压与心血管风险研究",
             "url": "https://example.com/htn-research",
             "snippet": "高血压长期管理...", "source": "health"},
            {"disease": "高脂血症", "title": "血脂异常管理专家共识",
             "url": "https://example.com/lipid-consensus",
             "snippet": "血脂异常与心血管风险...", "source": "academic"},
        ],
        "warnings": [],
        "errors": [],
    }


# ============================================================================
# SubTask 11.1 - 1) 单份流水线集成（mock 4 个工具函数，走真实 pipeline）
# ============================================================================

class TestSinglePipelineIntegration(unittest.TestCase):
    """单份核保流水线集成：mock 4 个工具函数，验证 process_report_stream 全链路。

    覆盖：
    - 事件序列：多个 status → done，done.result.ok=True。
    - 报告结构：patient/report_type/exam_date/summary/abnormalities/risks/references/
      recommendation/recommendation_reason/overall_risk 均存在。
    - recommendation 映射：overall_risk=中 → 次标准体-加费（沿用 config 映射）。
    - format_report_card 非空且含关键信息（风险色块 / 异常表 / 引用列表）。
    - 会话记忆写入：set_last_report 被调用。
    """

    def _patch_all_tools(self):
        """一次性 patch 4 个工具函数，返回 patcher 上下文管理器列表（用于 __exit__）。"""
        patchers = [
            patch("underwriting.pipeline.extract_report", return_value=_mock_extract_result()),
            patch("underwriting.pipeline.detect_abnormalities", return_value=_mock_abnormality_result()),
            patch("underwriting.pipeline.assess_risk", return_value=_mock_risk_result()),
            patch("underwriting.pipeline.search_medical", return_value=_mock_search_result()),
        ]
        for p in patchers:
            p.start()
        return patchers

    def _unpatch_all(self, patchers):
        for p in patchers:
            p.stop()

    def test_event_sequence_status_then_done(self):
        """事件序列：多个 status 进度 → 最后一个为 done，done.result.ok=True。"""
        sid = "test-int-single-seq"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            events = list(process_report_stream("/tmp/report.jpg", session_id=sid))
        finally:
            self._unpatch_all(patchers)
            get_store().clear(sid)

        self.assertTrue(events, "事件列表不应为空")
        # 最后一个应为 done
        self.assertEqual(events[-1].get("done"), True,
                         f"最后一个事件应为 done=True，实际 {events[-1]!r}")
        # done 之前应有多个 status
        status_events = [e for e in events if "status" in e]
        self.assertGreater(len(status_events), 3,
                           f"应有多个 status 进度事件（至少 4 阶段），实际 {len(status_events)}")
        # done.result.ok=True
        result = events[-1].get("result", {})
        self.assertTrue(result.get("ok") is True,
                        f"done.result.ok 应为 True，实际 {result!r}")

    def test_report_structure_complete(self):
        """报告结构完整：所有 spec 要求字段均存在。"""
        sid = "test-int-single-struct"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            result = process_report("/tmp/report.jpg", session_id=sid)
        finally:
            self._unpatch_all(patchers)
            get_store().clear(sid)

        self.assertTrue(result.get("ok") is True, "报告 ok 应为 True")
        # spec.md「核保报告生成」要求的全部字段
        required_keys = [
            "patient", "report_type", "exam_date", "summary",
            "abnormalities", "risks", "references",
            "recommendation", "recommendation_reason", "overall_risk",
        ]
        for k in required_keys:
            self.assertIn(k, result, f"报告应含字段「{k}」（spec 要求），实际字段 {list(result.keys())}")

        # 关键字段值校验
        self.assertEqual(result["report_type"], "体检报告")
        self.assertEqual(result["patient"]["name"], "张三")
        self.assertEqual(result["overall_risk"], "中")
        self.assertEqual(len(result["abnormalities"]), 3, "应有 3 项异常（mock）")
        self.assertEqual(len(result["risks"]), 2, "应有 2 项风险（mock）")
        self.assertGreaterEqual(len(result["references"]), 1, "应至少 1 条医学引用（mock）")

    def test_recommendation_mapping_medium_risk(self):
        """overall_risk=中 → recommendation=次标准体-加费（沿用 config.RISK_TO_RECOMMENDATION_DEFAULT）。"""
        sid = "test-int-single-rec"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            result = process_report("/tmp/report.jpg", session_id=sid)
        finally:
            self._unpatch_all(patchers)
            get_store().clear(sid)

        # config 映射：中 → 次标准体-加费
        expected = uwcfg.RISK_TO_RECOMMENDATION_DEFAULT.get(uwcfg.RISK_LEVEL_MEDIUM)
        self.assertEqual(result["overall_risk"], uwcfg.RISK_LEVEL_MEDIUM)
        self.assertEqual(result["recommendation"], expected,
                         f"overall_risk=中 应映射到「{expected}」，实际「{result['recommendation']}」")
        # 建议应在合法枚举内
        self.assertIn(result["recommendation"], uwcfg.RECOMMENDATIONS,
                      "recommendation 应在合法枚举内")
        # 建议理由非空
        self.assertTrue(result["recommendation_reason"],
                        "recommendation_reason 不应为空")

    def test_format_report_card_nonempty(self):
        """format_report_card 返回非空 HTML，含风险色块 / 异常表 / 引用列表关键标记。"""
        sid = "test-int-single-card"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            result = process_report("/tmp/report.jpg", session_id=sid)
        finally:
            self._unpatch_all(patchers)
            get_store().clear(sid)

        card_html = format_report_card(result)
        self.assertIsInstance(card_html, str)
        self.assertTrue(card_html, "报告卡 HTML 不应为空")
        # 整体风险 + 核保建议
        self.assertIn("整体风险", card_html, "报告卡应含「整体风险」")
        self.assertIn("核保建议", card_html, "报告卡应含「核保建议」")
        self.assertIn("次标准体-加费", card_html, "报告卡应含核保建议文案")
        # 异常明细表
        self.assertIn("异常明细", card_html, "报告卡应含「异常明细」段")
        self.assertIn("收缩压偏高", card_html, "报告卡应含异常项名称")
        # 风险明细表
        self.assertIn("风险明细", card_html, "报告卡应含「风险明细」段")
        self.assertIn("高血压", card_html, "报告卡应含风险项名称")
        # 医学参考引用列表
        self.assertIn("医学参考引用", card_html, "报告卡应含「医学参考引用」段")
        self.assertIn("中国高血压防治指南", card_html, "报告卡应含引用标题")

    def test_format_report_text_nonempty(self):
        """format_report_text 返回非空中文摘要文本。"""
        sid = "test-int-single-text"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            result = process_report("/tmp/report.jpg", session_id=sid)
        finally:
            self._unpatch_all(patchers)
            get_store().clear(sid)

        text = format_report_text(result)
        self.assertIsInstance(text, str)
        self.assertTrue(text, "报告文本不应为空")
        self.assertIn("报告类型", text)
        self.assertIn("整体风险等级", text)
        self.assertIn("核保建议", text)

    def test_memory_written_after_process(self):
        """process_report 后会话记忆 set_last_report 被调用（get_last_report 命中）。"""
        sid = "test-int-single-mem"
        get_store().clear(sid)
        patchers = self._patch_all_tools()
        try:
            process_report("/tmp/report.jpg", session_id=sid)
        finally:
            self._unpatch_all(patchers)

        try:
            stored = get_store().get_last_report(sid)
            self.assertIsNotNone(stored, "会话记忆应已写入单份报告")
            self.assertTrue(stored.get("ok") is True, "记忆中的报告 ok 应为 True")
            self.assertEqual(stored.get("report_type"), "体检报告")
        finally:
            get_store().clear(sid)

    def test_extract_failure_isolates_report(self):
        """extract 返回 error → 流水线隔离该报告，done.result.ok=False，stage=extract。"""
        sid = "test-int-single-fail"
        get_store().clear(sid)
        with patch("underwriting.pipeline.extract_report",
                   return_value={"error": "图片无法识别"}):
            events = list(process_report_stream("/tmp/bad.jpg", session_id=sid))
        try:
            # 应只有一个 done 事件（extract 失败立即 return，不继续后续阶段）
            done_events = [e for e in events if e.get("done")]
            self.assertEqual(len(done_events), 1, "应只 yield 一个 done 事件")
            result = done_events[0]["result"]
            self.assertTrue(result.get("ok") is False, "失败报告 ok 应为 False")
            self.assertEqual(result.get("stage"), "extract", "失败 stage 应为 extract")
            self.assertIn("图片无法识别", result.get("message", ""))
        finally:
            get_store().clear(sid)


# ============================================================================
# SubTask 11.1 - 2) 批量核保集成（mock process_report，走真实 batch_pipeline）
# ============================================================================

class TestBatchPipelineIntegration(unittest.TestCase):
    """批量核保集成：mock process_report 单份入口，验证 process_batch_stream 全链路。

    覆盖：
    - 事件序列：逐张 progress → done，done.result.ok=True。
    - 聚合统计：success_count/duplicate_count/fail_count/total 与输入一致。
    - CSV BOM：export_batch_csv 以 UTF-8 BOM 开头，表头与数据行数正确。
    - 重复检测：同图两次（mock 一致）→ 第二张 duplicate_of=0。
    - 失败隔离：mock 一张失败 → 不崩批，fail_count=1。
    """

    @staticmethod
    def _fake_process_report_success(image_path, session_id=None):
        """mock process_report：成功返回报告。

        患者姓名从 image_path basename 派生（report_0.png → 患者_0），确保不同图
        返回不同 patient+exam_date，避免触发 batch_pipeline 的 patient+date 回退去重
        （让所有图都计入 success_count）。
        """
        basename = os.path.basename(image_path or "")
        # 从文件名提取索引（report_0.png → "0"），派生唯一患者名
        idx = ""
        if "_" in basename:
            stem = basename.rsplit(".", 1)[0]
            parts = stem.split("_")
            if len(parts) >= 2:
                idx = parts[-1]
        patient_name = f"患者_{idx}" if idx else "默认患者"
        return {
            "ok": True,
            "image_path": image_path,
            "patient": {"name": patient_name, "gender": "男", "age": 55},
            "report_type": "体检报告",
            "exam_date": f"2026-06-{15 + (int(idx) if idx.isdigit() else 0):02d}",
            "summary": "血压偏高",
            "abnormalities": [{"name": "收缩压偏高", "type": "检验越界",
                               "severity_hint": "中", "evidence": "165 mmHg",
                               "detail": ""}],
            "risks": [{"name": "高血压", "risk_level": "中",
                       "risk_factors": ["收缩压偏高"], "evidence": "165 mmHg",
                       "reasoning": "心血管风险升高"}],
            "overall_risk": "中",
            "overall_reasoning": "整体风险中等",
            "references": [],
            "recommendation": "次标准体-加费",
            "recommendation_reason": "整体风险中等，建议加费承保。",
        }

    def _make_temp_images(self, count=3):
        """创建 count 个临时图片文件，返回路径列表。

        每个文件写入**不同**内容（含索引字节），确保文件内容 md5 哈希各不相同，
        避免触发 batch_pipeline 的文件哈希去重（让所有图都走到 process_report）。
        """
        import tempfile
        folder = tempfile.mkdtemp(prefix="uw_batch_test_")
        paths = []
        for i in range(count):
            p = os.path.join(folder, f"report_{i}.png")
            # 内容含索引字节 i，保证各文件哈希不同
            with open(p, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + bytes([i]) * 16)
            paths.append(p)
        return paths, folder

    def test_batch_event_sequence_progress_then_done(self):
        """批量事件序列：逐张 progress → done，done.result.ok=True。"""
        paths, folder = self._make_temp_images(count=2)
        try:
            with patch("underwriting.batch_pipeline.process_report",
                       side_effect=self._fake_process_report_success):
                events = list(process_batch_stream(paths, session_id="test-int-batch-seq"))
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

        progress_events = [e for e in events if e.get("type") == "progress"]
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertGreater(len(progress_events), 0, "应有 progress 事件")
        self.assertEqual(len(done_events), 1, "应只 yield 一个 done 事件")
        result = done_events[0]["result"]
        self.assertTrue(result.get("ok") is True, "批量结果 ok 应为 True")
        self.assertEqual(result["total"], 2, "total 应为 2")

    def test_batch_aggregate_stats_success(self):
        """3 张图全部成功 → success_count=3，duplicate_count=0，fail_count=0。"""
        paths, folder = self._make_temp_images(count=3)
        try:
            with patch("underwriting.batch_pipeline.process_report",
                       side_effect=self._fake_process_report_success):
                result = process_batch(paths, session_id="test-int-batch-agg")
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

        self.assertTrue(result.get("ok") is True)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["fail_count"], 0)
        # aggregate 含 summary_text / 风险分布 / 建议分布
        agg = result["aggregate"]
        self.assertIn("summary_text", agg, "aggregate 应含 summary_text")
        self.assertIn("overall_risk_distribution", agg, "aggregate 应含 overall_risk_distribution")
        self.assertIn("recommendation_distribution", agg, "aggregate 应含 recommendation_distribution")
        # 3 张全部「中」风险 + 「次标准体-加费」建议
        self.assertEqual(agg["overall_risk_distribution"][uwcfg.RISK_LEVEL_MEDIUM], 3)
        self.assertEqual(agg["recommendation_distribution"][uwcfg.RECOMMENDATION_SUBSTANDARD_EXTRA_PREMIUM], 3)

    def test_batch_duplicate_detection_by_file_hash(self):
        """同一张图传两次 → 第二张 duplicate_of=0（按文件内容 md5 哈希去重）。"""
        import shutil
        import tempfile
        folder = tempfile.mkdtemp(prefix="uw_batch_dup_")
        try:
            p1 = os.path.join(folder, "a.png")
            p2 = os.path.join(folder, "b.png")  # 不同文件名，相同内容
            content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
            with open(p1, "wb") as f:
                f.write(content)
            with open(p2, "wb") as f:
                f.write(content)
            with patch("underwriting.batch_pipeline.process_report",
                       side_effect=self._fake_process_report_success):
                result = process_batch([p1, p2], session_id="test-int-batch-dup")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["duplicate_count"], 1, "应有 1 张重复")
        self.assertEqual(result["success_count"], 1, "成功数应为 1（重复不计成功）")
        # 重复报告标注 duplicate_of=0
        dups = [r for r in result["reports"] if r.get("duplicate_of") is not None]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["duplicate_of"], 0)

    def test_batch_failure_isolation(self):
        """1 张成功 + 1 张失败（mock process_report 抛异常）→ 不崩批，fail_count=1。"""
        paths, folder = self._make_temp_images(count=2)
        try:
            def fake_with_failure(image_path, session_id=None):
                if "report_1" in image_path:
                    raise RuntimeError("VLM 不可达")
                return self._fake_process_report_success(image_path, session_id)
            with patch("underwriting.batch_pipeline.process_report",
                       side_effect=fake_with_failure):
                result = process_batch(paths, session_id="test-int-batch-fail")
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

        self.assertTrue(result.get("ok") is True, "单张失败不应崩批，ok 仍为 True")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["fail_count"], 1)
        self.assertEqual(len(result["errors"]), 1, "errors 应记录 1 条")
        # 失败报告在 reports 中 ok=False
        failed = [r for r in result["reports"] if not r.get("ok")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["stage"], "process")

    def test_batch_csv_export_has_bom(self):
        """export_batch_csv 以 UTF-8 BOM 开头，表头与数据行数正确。"""
        paths, folder = self._make_temp_images(count=2)
        try:
            with patch("underwriting.batch_pipeline.process_report",
                       side_effect=self._fake_process_report_success):
                result = process_batch(paths, session_id="test-int-batch-csv")
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)

        csv_text = export_batch_csv(result)
        # UTF-8 BOM
        self.assertTrue(csv_text.startswith("\ufeff"), "CSV 应以 UTF-8 BOM 开头")
        # 去掉 BOM 后解析
        text = csv_text[1:] if csv_text.startswith("\ufeff") else csv_text
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(rows), 3, "应为 1 表头 + 2 数据行 = 3 行")
        # 表头首列「序号」
        self.assertEqual(rows[0][0], "序号")
        self.assertIn("核保建议", rows[0], "表头应含「核保建议」列")
        # 数据行含核保建议文案
        self.assertIn("次标准体-加费", rows[1][5],
                      f"数据行核保建议列应为「次标准体-加费」，实际 {rows[1][5]!r}")

    def test_batch_empty_list_returns_ok(self):
        """空列表 → ok=True，total=0，不崩。"""
        result = process_batch([], session_id="test-int-batch-empty")
        self.assertTrue(result.get("ok") is True)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["reports"], [])


# ============================================================================
# SubTask 11.1 - 3) 搜索集成（真实联网，核心）—— 联网失败则 skip 不阻塞
# ============================================================================

class TestMedicalSearchIntegration(unittest.TestCase):
    """医学检索真实联网集成测试（核心）。

    调用 search_medical(["高血压"])，验证：
    - 返回结构含 references / warnings / errors 三字段。
    - references 非空（双端并用，至少一端应返回结果）。
    - 每条 reference 含必要字段（disease/title/url/snippet/source）。
    - url 去重正确（非空 url 集合大小 == references 中非空 url 计数）。
    - source 取值合法（exa / health / academic）。

    联网失败（两端皆不可达）则 skipTest，不阻塞测试通过。
    """

    def test_search_medical_hypertension_real_network(self):
        """真实联网：search_medical(["高血压"]) 返回非空 references 且字段完整。"""
        try:
            result = search_medical(["高血压"])
        except Exception as e:
            self.skipTest(f"search_medical 调用抛异常（联网不可用），跳过：{e}")
            return

        # 结构校验
        self.assertIsInstance(result, dict)
        self.assertIn("references", result)
        self.assertIn("warnings", result)
        self.assertIn("errors", result)

        references = result["references"]
        # 联网失败兜底：两端皆失败 → references 为空 + errors 非空，skip
        if not references:
            err_msgs = "; ".join(e.get("error", "") for e in result["errors"])
            self.skipTest(
                f"双端联网检索均未返回结果（Exa + anysearch 都失败），跳过。errors: {err_msgs}"
            )

        # references 非空：每条字段完整
        self.assertGreater(len(references), 0, "references 应非空（双端并用）")
        valid_sources = {"exa", "health", "academic"}
        for i, ref in enumerate(references):
            self.assertIsInstance(ref, dict, f"reference #{i} 应为 dict")
            # 必要字段（url 可为空，但字段必须存在）
            for field in ("disease", "title", "url", "snippet", "source"):
                self.assertIn(field, ref,
                              f"reference #{i} 应含字段「{field}」，实际字段 {list(ref.keys())}")
            # source 取值合法
            self.assertIn(ref["source"], valid_sources,
                          f"reference #{i} source 应为 exa/health/academic，实际 {ref['source']!r}")
            # disease 应为查询词「高血压」（或合并后含高血压）
            self.assertTrue(
                "高血压" in ref.get("disease", "") or ref.get("disease"),
                f"reference #{i} disease 应非空且关联查询词，实际 {ref.get('disease')!r}"
            )

        # url 去重正确：非空 url 集合大小 == references 中非空 url 计数
        non_empty_urls = [r["url"] for r in references if r.get("url")]
        if non_empty_urls:
            unique_urls = set(non_empty_urls)
            # _merge_and_dedup 保证同 url 只保留一条；空 url 不去重全部保留
            self.assertEqual(len(non_empty_urls), len(unique_urls),
                             f"非空 url 应已去重：总数 {len(non_empty_urls)} 应等于唯一数 "
                             f"{len(unique_urls)}")

    def test_search_medical_empty_diseases_returns_empty(self):
        """空 diseases 列表 → 返回空 references（不调网络）。"""
        result = search_medical([])
        self.assertEqual(result["references"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["errors"], [])


# ============================================================================
# SubTask 11.1 - 4) 流式追问集成（mock SSE）+ 三级回退（set_last_report 走单份分支）
# ============================================================================

class _FakeSSEResponse:
    """模拟 urlopen 返回的 SSE 响应：按行迭代返回 bytes。"""

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
        self.captured_body = req.data
        return _FakeSSEResponse(self._lines)


def _sse_line(delta: dict) -> bytes:
    """构造一行 SSE data: payload。"""
    return b'data: ' + json.dumps({"choices": [{"delta": delta}]}).encode("utf-8") + b'\n\n'


class TestStreamFollowupIntegration(unittest.TestCase):
    """流式追问集成：mock SSE，验证事件序列 + 三级回退（set_last_report 后走单份分支）。

    与 test_underwriting_agent.py 的区别：本类聚焦「集成链路」——
    - 通过 set_last_report 注入记忆后，验证 stream_followup 走单份分支（捕获 body
      解析 system_content），并产出完整 reasoning/content/done 事件序列。
    - 验证 set_last_report → stream_followup → get_last_report 的端到端记忆链路。
    """

    def test_followup_event_sequence_after_set_last_report(self):
        """set_last_report 后 stream_followup 产出 reasoning/content/done 完整序列。"""
        sid = "test-int-followup-seq"
        get_store().clear(sid)
        # 注入单份报告记忆（走二级回退分支）
        get_store().set_last_report(sid, {
            "ok": True,
            "patient": {"name": "张三", "gender": "男", "age": 55},
            "report_type": "体检报告",
            "overall_risk": "中",
            "recommendation": "次标准体-加费",
            "abnormalities": [{"name": "收缩压偏高", "type": "检验越界",
                                "severity_hint": "中", "evidence": "165 mmHg",
                                "detail": ""}],
            "risks": [{"name": "高血压", "risk_level": "中",
                       "risk_factors": [], "evidence": "", "reasoning": ""}],
            "references": [],
        })
        try:
            lines = [
                _sse_line({"reasoning_content": "分析该患者高血压风险"}),
                _sse_line({"content": "建议加费承保"}),
                b'data: [DONE]\n\n',
            ]
            cap = _CapturingUropen(lines)
            with patch("urllib.request.urlopen", side_effect=cap):
                events = list(stream_followup("该患者高血压风险如何加费", session_id=sid))

            # 事件序列：reasoning → content → done
            types = [e["type"] for e in events]
            self.assertEqual(types, ["reasoning", "content", "done"],
                             f"事件序列应为 [reasoning, content, done]，实际 {types}")
            # reasoning 与 content 拼接正确
            reasoning_text = "".join(e["text"] for e in events if e["type"] == "reasoning")
            content_text = "".join(e["text"] for e in events if e["type"] == "content")
            self.assertEqual(reasoning_text, "分析该患者高血压风险")
            self.assertEqual(content_text, "建议加费承保")
            # done 是最后一个且唯一
            self.assertEqual(events[-1]["type"], "done")
            self.assertEqual(sum(1 for e in events if e["type"] == "done"), 1)
        finally:
            get_store().clear(sid)

    def test_followup_tier2_single_report_branch_taken(self):
        """set_last_report 后 stream_followup 走单份分支（system_content 含报告上下文）。"""
        sid = "test-int-followup-tier2"
        get_store().clear(sid)
        # 注入单份报告记忆
        get_store().set_last_report(sid, {
            "ok": True,
            "patient": {"name": "李四", "gender": "女", "age": 42},
            "report_type": "病历",
            "exam_date": "2026-07-01",
            "overall_risk": "低",
            "recommendation": "标准体",
            "abnormalities": [],
            "risks": [],
            "references": [],
        })
        try:
            lines = [
                _sse_line({"content": "ok"}),
                b'data: [DONE]\n\n',
            ]
            cap = _CapturingUropen(lines)
            with patch("urllib.request.urlopen", side_effect=cap):
                list(stream_followup("问题", session_id=sid))

            # 捕获 body，解析 system_content（messages[0].content）
            self.assertIsNotNone(cap.captured_body, "应捕获到 POST body")
            body_obj = json.loads(cap.captured_body.decode("utf-8"))
            messages = body_obj.get("messages", [])
            self.assertGreaterEqual(len(messages), 2, "messages 至少含 system + user")
            system_content = messages[0].get("content", "")
            # 走单份分支：system_content 含「已完成核保的报告」+ 患者信息
            self.assertIn("已完成核保的报告", system_content, "应走单份分支")
            self.assertIn("李四", system_content, "system_content 应含患者姓名")
            self.assertIn("标准体", system_content, "system_content 应含核保建议")
            # 不应走批量分支
            self.assertNotIn("批量报告", system_content, "不应走批量分支")
        finally:
            get_store().clear(sid)

    def test_followup_tier3_generic_when_no_memory(self):
        """无记忆时走通用分支（system_content 为通用提示词）。"""
        sid = "test-int-followup-tier3"
        get_store().clear(sid)
        try:
            lines = [
                _sse_line({"content": "通用回答"}),
                b'data: [DONE]\n\n',
            ]
            cap = _CapturingUropen(lines)
            with patch("urllib.request.urlopen", side_effect=cap):
                events = list(stream_followup("问题", session_id=sid))

            body_obj = json.loads(cap.captured_body.decode("utf-8"))
            system_content = body_obj["messages"][0]["content"]
            self.assertEqual(
                system_content,
                "你是智能核保风险助手，用简洁中文回答用户问题。",
                "无记忆时应走通用提示词",
            )
            # 事件序列仍完整
            self.assertEqual(events[-1]["type"], "done")
        finally:
            get_store().clear(sid)

    def test_followup_error_branch_http_error(self):
        """urlopen 抛 HTTPError → yield error 事件，不 yield done。"""
        sid = "test-int-followup-err"
        get_store().clear(sid)
        try:
            with patch("urllib.request.urlopen",
                       side_effect=urllib.error.HTTPError("url", 500, "err", {}, None)):
                events = list(stream_followup("x", session_id=sid))
            err_events = [e for e in events if e["type"] == "error"]
            self.assertEqual(len(err_events), 1, "应只 yield 一个 error 事件")
            self.assertIn("HTTP 500", err_events[0]["text"])
            self.assertFalse(any(e["type"] == "done" for e in events),
                             "HTTPError 分支不应 yield done")
        finally:
            get_store().clear(sid)


# ============================================================================
# SubTask 11.1 - 5) 端到端配置与导入
# ============================================================================

class TestConfigAndImportsIntegration(unittest.TestCase):
    """端到端配置与导入：验证 underwriting 包所有模块可导入、config 关键常量存在。"""

    def test_underwriting_package_imports(self):
        """underwriting 包所有核心模块均可导入（不抛异常）。"""
        # 已在文件顶部导入，这里再次显式 import 验证
        import underwriting
        import underwriting.config
        import underwriting.memory
        import underwriting.pipeline
        import underwriting.batch_pipeline
        import underwriting.agent
        import underwriting.backend  # noqa: F401
        import underwriting.tools.report_extract_tool  # noqa: F401
        import underwriting.tools.abnormality_tool  # noqa: F401
        import underwriting.tools.risk_tool  # noqa: F401
        import underwriting.tools.medical_search_tool  # noqa: F401
        # tools/search 两个 vendor
        import tools.search.web_search  # noqa: F401
        import tools.search.anysearch_cli  # noqa: F401
        # 全部导入成功即通过
        self.assertTrue(True)

    def test_config_key_constants_exist(self):
        """underwriting.config 关键常量均存在且类型/值合理。"""
        # 风险等级枚举
        self.assertEqual(uwcfg.RISK_LEVEL_LOW, "低")
        self.assertEqual(uwcfg.RISK_LEVEL_MEDIUM, "中")
        self.assertEqual(uwcfg.RISK_LEVEL_HIGH, "高")
        self.assertEqual(len(uwcfg.RISK_LEVELS), 3)

        # 核保建议枚举（5 项）
        self.assertEqual(len(uwcfg.RECOMMENDATIONS), 5)
        for rec in ("标准体", "次标准体-加费", "次标准体-除外", "延期", "拒保"):
            self.assertIn(rec, uwcfg.RECOMMENDATIONS,
                          f"核保建议枚举应含「{rec}」")

        # 风险→建议默认映射
        self.assertEqual(uwcfg.RISK_TO_RECOMMENDATION_DEFAULT[uwcfg.RISK_LEVEL_LOW], "标准体")
        self.assertEqual(uwcfg.RISK_TO_RECOMMENDATION_DEFAULT[uwcfg.RISK_LEVEL_MEDIUM], "次标准体-加费")
        self.assertEqual(uwcfg.RISK_TO_RECOMMENDATION_DEFAULT[uwcfg.RISK_LEVEL_HIGH], "拒保")

        # 风险色块映射
        self.assertEqual(uwcfg.RISK_COLOR_MAP[uwcfg.RISK_LEVEL_LOW], "green")
        self.assertEqual(uwcfg.RISK_COLOR_MAP[uwcfg.RISK_LEVEL_MEDIUM], "yellow")
        self.assertEqual(uwcfg.RISK_COLOR_MAP[uwcfg.RISK_LEVEL_HIGH], "red")

    def test_root_config_underwriting_section_exists(self):
        """根 config.py「八、核保 Agent」配置段关键常量存在。"""
        # 端口
        self.assertEqual(cfg.UNDERWRITING_PORT, 8002)
        # 双搜索后端
        self.assertEqual(cfg.EXA_MCP_URL, "https://mcp.exa.ai/mcp")
        self.assertGreaterEqual(cfg.EXA_NUM_RESULTS, 1)
        self.assertGreater(cfg.EXA_TIMEOUT, 0)
        # anysearch
        self.assertTrue(cfg.ANYSEARCH_CLI_PATH.endswith("anysearch_cli.py"))
        self.assertTrue(os.path.isfile(cfg.ANYSEARCH_CLI_PATH),
                        f"ANYSEARCH_CLI_PATH 应指向存在的文件，实际 {cfg.ANYSEARCH_CLI_PATH}")
        # 并发上限
        self.assertGreaterEqual(cfg.SEARCH_MAX_WORKERS, 1)
        self.assertGreaterEqual(cfg.UNDERWRITING_BATCH_MAX_WORKERS, 1)
        # 持久化
        self.assertTrue(cfg.UNDERWRITING_PERSIST_DIR)
        self.assertIsInstance(cfg.UNDERWRITING_PERSIST_ENABLED, bool)

    def test_llm_endpoint_constants_propagated(self):
        """underwriting.config 透出根 cfg 的 LLM 端点常量（MODEL_BASE_URL/MODEL_URL/MODEL_ID）。"""
        self.assertTrue(uwcfg.MODEL_BASE_URL, "MODEL_BASE_URL 不应为空")
        self.assertTrue(uwcfg.MODEL_URL, "MODEL_URL 不应为空")
        self.assertTrue(uwcfg.MODEL_ID, "MODEL_ID 不应为空")
        # underwriting.config 与根 cfg 应一致
        self.assertEqual(uwcfg.MODEL_BASE_URL, cfg.MODEL_BASE_URL)
        self.assertEqual(uwcfg.MODEL_URL, cfg.MODEL_URL)
        self.assertEqual(uwcfg.MODEL_ID, cfg.MODEL_ID)

    def test_pipeline_and_batch_functions_callable(self):
        """pipeline / batch_pipeline / agent 的核心函数可调用（签名存在）。"""
        self.assertTrue(callable(process_report_stream))
        self.assertTrue(callable(process_report))
        self.assertTrue(callable(format_report_card))
        self.assertTrue(callable(format_report_text))
        self.assertTrue(callable(process_batch_stream))
        self.assertTrue(callable(process_batch))
        self.assertTrue(callable(export_batch_csv))
        self.assertTrue(callable(list_images))
        self.assertTrue(callable(stream_followup))
        self.assertTrue(callable(search_medical))


# ============================================================================
# SubTask 11.2 - 浏览器端到端验证占位（skip）
# ============================================================================

@unittest.skip("需 LLM 端点可用 + 浏览器手动验证（见文件顶部手动验证步骤）")
class TestBrowserEndToEndManual(unittest.TestCase):
    """浏览器端到端验证（手动）。

    LLM 端点 localhost:8000 当前未连（SSH 隧道未运行），无法做真实多模态端到端。
    待 LLM 端点可用时，按文件顶部「手动浏览器端到端验证步骤」执行：
      1. 启动 python -m underwriting.backend（端口 8002）
      2. 浏览器打开 http://localhost:8002
      3. 单份 Tab 上传病历/体检报告图片，观察阶段进度 + 报告卡
      4. 批量 Tab 上传多张图（含重复/失败），观察进度 + 汇总卡 + CSV 下载
      5. 追问：输入问题，观察思考链逐字追加 + 正文
      6. 健康检查：GET /api/health 返回 {"ok": true}
    """

    def test_single_report_browser_e2e(self):
        """单份核保浏览器端到端（需手动执行）。"""
        pass

    def test_batch_report_browser_e2e(self):
        """批量核保浏览器端到端（需手动执行）。"""
        pass

    def test_followup_browser_e2e(self):
        """追问浏览器端到端（需手动执行）。"""
        pass


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
