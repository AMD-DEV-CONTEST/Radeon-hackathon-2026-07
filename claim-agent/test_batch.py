# -*- coding: utf-8 -*-
"""
test_batch.py — 批量发票处理单元测试（Task 8）

覆盖：
- decide_batch_core：跨发票聚合决策（部分通过/全部通过/全部拒赔/失败/重复/空/封顶线）
- list_images：目录扫描与文件列表筛选、按 basename 排序
- export_batch_csv：CSV 导出（UTF-8 BOM/表头/行数/重复与失败标注）
- process_batch：错误隔离（缺失图片不崩批、空列表边界）
- 集成测试：真实 VLM 后端跑两张样例发票与重复检测（后端不可达时整类 skip）

运行：python test_batch.py
说明：集成测试类在 setUpClass 探测 http://localhost:8000/v1/models，不可达则整类 skip，
      不让 CI 因后端不可达而失败。
"""

import os
import csv
import io
import json
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

import agent  # noqa: F401  注入 sys.path
from tools.decision_tool import decide_batch_core
from agent.batch_pipeline import list_images, process_batch, process_batch_stream  # noqa: F401
from tools.export_tool import export_batch_csv
from agent.memory import get_store

BASE = os.path.dirname(os.path.abspath(__file__))
FAPIAO = os.path.join(BASE, "fapiao.jpg")
FAPIAO2 = os.path.join(BASE, "fapiao2.jpg")


def _make_invoice(index, filename, ok=True, duplicate_of=None, fphm="123", code="100.00",
                  conclusion="部分通过", total_amount=100.0, total_reimbursable=70.0,
                  total_medical_insurance=70.0, total_commercial=0.0, stage=None, message=None):
    """构造单张 invoice 结果 dict（对齐 process_batch_stream 输出结构）。

    失败（ok=False）或重复（duplicate_of 非 None）的发票 decision 置 None，
    与真实流水线一致：失败/重复发票不会跑 decide_claim_core。
    """
    return {
        "index": index, "filename": filename, "image_path": f"/tmp/{filename}", "ok": ok,
        "stage": stage, "message": message, "duplicate_of": duplicate_of,
        "extract": {"fphm": fphm, "date": "20240101", "code": code},
        "verify": None,
        "decision": (None if not ok or duplicate_of is not None else
                     {"conclusion": conclusion, "total_amount": total_amount,
                      "total_reimbursable": total_reimbursable,
                      "total_medical_insurance": total_medical_insurance,
                      "total_commercial": total_commercial, "items": [], "summary_text": ""}),
    }


# ============================================================================
# 1) decide_batch_core 纯单元测试（不依赖后端）
# ============================================================================
class TestDecideBatchCore(unittest.TestCase):
    """decide_batch_core 跨发票聚合决策纯单元测试。"""

    def test_partial_batch(self):
        """2 张成功（一全额通过+一部分通过）→ 整体部分通过，可报为两者之和。"""
        inv0 = _make_invoice(0, "a.jpg", conclusion="全额通过", total_reimbursable=100.0,
                             total_medical_insurance=100.0, total_commercial=0.0, code="100.00")
        inv1 = _make_invoice(1, "b.jpg", conclusion="部分通过", total_reimbursable=70.0,
                             total_medical_insurance=70.0, total_commercial=0.0, code="100.00")
        agg = decide_batch_core([inv0, inv1])
        self.assertEqual(agg["conclusion"], "部分通过", "一全一部分 → 整体应为部分通过")
        self.assertEqual(agg["success_count"], 2, "成功数应为 2")
        self.assertEqual(agg["failed_count"], 0, "失败数应为 0")
        self.assertTrue(abs(agg["total_reimbursable"] - 170.0) < 0.01,
                        f"可报合计应为 100+70=170，实际 {agg['total_reimbursable']}")

    def test_all_pass(self):
        """2 张全额通过 → 整体全部通过。"""
        inv0 = _make_invoice(0, "a.jpg", conclusion="全额通过", total_reimbursable=100.0,
                             total_medical_insurance=100.0)
        inv1 = _make_invoice(1, "b.jpg", conclusion="全额通过", total_reimbursable=100.0,
                             total_medical_insurance=100.0)
        agg = decide_batch_core([inv0, inv1])
        self.assertEqual(agg["conclusion"], "全部通过", "两张均全额通过 → 整体应全部通过")

    def test_all_reject(self):
        """2 张拒赔 → 整体全部拒赔，可报为 0。"""
        inv0 = _make_invoice(0, "a.jpg", conclusion="拒赔", total_reimbursable=0.0,
                             total_medical_insurance=0.0, total_commercial=0.0)
        inv1 = _make_invoice(1, "b.jpg", conclusion="拒赔", total_reimbursable=0.0,
                             total_medical_insurance=0.0, total_commercial=0.0)
        agg = decide_batch_core([inv0, inv1])
        self.assertEqual(agg["conclusion"], "全部拒赔", "两张均拒赔 → 整体应全部拒赔")
        self.assertTrue(abs(agg["total_reimbursable"] - 0.0) < 0.01,
                        f"全部拒赔可报应为 0，实际 {agg['total_reimbursable']}")

    def test_failed_invoice_not_in_totals(self):
        """1 张成功 + 1 张失败：失败发票金额不计入 total_amount。"""
        inv0 = _make_invoice(0, "a.jpg", conclusion="部分通过", total_reimbursable=70.0,
                             total_medical_insurance=70.0, code="100.00")
        inv1 = _make_invoice(1, "b.jpg", ok=False, stage="ocr", message="识别失败", code="200.00")
        agg = decide_batch_core([inv0, inv1])
        self.assertEqual(agg["failed_count"], 1, "失败数应为 1")
        self.assertEqual(agg["total_invoices"], 2, "总张数应为 2")
        self.assertTrue(abs(agg["total_amount"] - 100.0) < 0.01,
                        f"失败发票价税合计不应计入总额，应为 100，实际 {agg['total_amount']}")

    def test_duplicate_not_in_totals(self):
        """1 张成功 + 1 张重复：重复发票不计入可报，success_count 不含重复。"""
        inv0 = _make_invoice(0, "a.jpg", conclusion="部分通过", total_reimbursable=70.0,
                             total_medical_insurance=70.0, fphm="A001", code="100.00")
        inv1 = _make_invoice(1, "b.jpg", ok=True, duplicate_of=0, fphm="A001", code="100.00")
        agg = decide_batch_core([inv0, inv1])
        self.assertEqual(agg["duplicate_count"], 1, "重复数应为 1")
        self.assertEqual(agg["success_count"], 1, "成功数应为 1（重复不计成功）")
        self.assertTrue(abs(agg["total_reimbursable"] - 70.0) < 0.01,
                        f"重复发票不应计入可报，应为 70，实际 {agg['total_reimbursable']}")

    def test_empty(self):
        """空列表 → total_invoices=0，全部拒赔，可报为 0。"""
        agg = decide_batch_core([])
        self.assertEqual(agg["total_invoices"], 0, "空列表 total_invoices 应为 0")
        self.assertEqual(agg["conclusion"], "全部拒赔", "空列表结论应为全部拒赔")
        self.assertTrue(abs(agg["total_reimbursable"] - 0.0) < 0.01,
                        f"空列表可报应为 0，实际 {agg['total_reimbursable']}")

    def test_annual_cap(self):
        """mock ANNUAL_CAP=50，医保可报 100 → 触发封顶，medical_after_cap=50，可报=50+商保。"""
        with patch("tools.decision_tool.cfg.ANNUAL_CAP", 50.0):
            inv = _make_invoice(0, "cap.jpg", conclusion="部分通过",
                                total_medical_insurance=100.0, total_commercial=10.0,
                                total_reimbursable=110.0, code="100.00")
            agg = decide_batch_core([inv])
        self.assertTrue(agg["cap_applied"] is True,
                        "医保可报 100 超过封顶 50，应触发封顶 cap_applied=True")
        self.assertTrue(abs(agg["medical_after_cap"] - 50.0) < 0.01,
                        f"封顶后医保应为 50，实际 {agg['medical_after_cap']}")
        self.assertTrue(abs(agg["total_reimbursable"] - 60.0) < 0.01,
                        f"封顶后总可报应为 60（医保 50 + 商保 10），实际 {agg['total_reimbursable']}")


# ============================================================================
# 2) list_images 目录扫描与文件列表筛选（不依赖后端）
# ============================================================================
class TestListImages(unittest.TestCase):
    """list_images 顶层扫描、扩展名过滤、按 basename 排序。"""

    def test_folder_filter_and_sort(self):
        """文件夹扫描：仅顶层图片，按 basename 排序，不含 .txt 与子目录内文件。"""
        with tempfile.TemporaryDirectory() as folder:
            for name in ["b.jpg", "a.png", "notes.txt"]:
                with open(os.path.join(folder, name), "w") as f:
                    f.write("")
            sub = os.path.join(folder, "sub")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, "c.jpg"), "w") as f:
                f.write("")
            result = list_images(folder)
            names = [os.path.basename(p) for p in result]
            self.assertEqual(len(result), 2, "应只列出顶层图片文件（不含 .txt 与子目录内文件）")
            self.assertEqual(names, ["a.png", "b.jpg"], "应按 basename 排序，a.png 在前")

    def test_file_list_input(self):
        """文件列表入参：保留存在的图片，过滤非图片与不存在文件。"""
        with tempfile.TemporaryDirectory() as folder:
            a_png = os.path.join(folder, "a.png")
            notes_txt = os.path.join(folder, "notes.txt")
            with open(a_png, "w") as f:
                f.write("")
            with open(notes_txt, "w") as f:
                f.write("")
            nonexistent = os.path.join(folder, "nope.jpg")
            result = list_images([a_png, notes_txt, nonexistent])
            names = [os.path.basename(p) for p in result]
            self.assertEqual(names, ["a.png"], "应只保留存在的图片文件，过滤 .txt 与不存在文件")

    def test_empty_folder(self):
        """空目录 → 空列表。"""
        with tempfile.TemporaryDirectory() as folder:
            result = list_images(folder)
            self.assertEqual(result, [], "空目录应返回空列表")

    def test_nonexistent(self):
        """不存在的路径 → 空列表（静默跳过，不抛异常）。"""
        result = list_images("/no/such/path")
        self.assertEqual(result, [], "不存在的路径应返回空列表")


# ============================================================================
# 3) export_batch_csv CSV 导出（不依赖后端，用合成 batch_result）
# ============================================================================
class TestExportCsv(unittest.TestCase):
    """export_batch_csv 导出：BOM、表头、行数、重复/失败标注。"""

    def test_csv_header_and_rows(self):
        """CSV 含 BOM、表头、4 行数据，重复/失败行标注正确。"""
        invoices = [
            _make_invoice(0, "a.jpg", conclusion="部分通过", total_reimbursable=70.0,
                          total_medical_insurance=70.0, code="100.00"),
            _make_invoice(1, "b.jpg", conclusion="全额通过", total_reimbursable=100.0,
                          total_medical_insurance=100.0, code="100.00"),
            _make_invoice(2, "c.jpg", ok=True, duplicate_of=0, fphm="123", code="100.00"),
            _make_invoice(3, "d.jpg", ok=False, stage="ocr", message="识别失败", code="0.00"),
        ]
        batch_result = {
            "ok": True, "session_id": "test", "created_at": "2026-07-18T00:00:00",
            "invoices": invoices, "aggregate": {}, "errors": [], "duplicates": [],
        }
        csv_text = export_batch_csv(batch_result)

        # UTF-8 BOM
        self.assertTrue(csv_text.startswith("\ufeff"), "CSV 应以 UTF-8 BOM 开头")

        # 去掉 BOM 后用 csv.reader 解析
        text = csv_text[1:] if csv_text.startswith("\ufeff") else csv_text
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(rows), 5, "应为 1 表头 + 4 数据行 = 5 行")

        # 表头
        self.assertEqual(rows[0][0], "序号", "表头首列应为「序号」")
        self.assertIn("结论", rows[0], "表头应含「结论」列")
        self.assertIn("备注", rows[0], "表头应含「备注」列")

        # 重复行（第 3 行数据，rows[3]）；结论列 index=8，备注列 index=9
        dup_row = rows[3]
        self.assertEqual(dup_row[8], "重复", "重复行结论列应为「重复」")
        self.assertIn("重复", dup_row[9], "重复行备注应含「重复」")

        # 失败行（第 4 行数据，rows[4]）
        fail_row = rows[4]
        self.assertTrue(fail_row[8].startswith("失败"),
                        f"失败行结论应以「失败」开头，实际 {fail_row[8]}")


# ============================================================================
# 4) process_batch 错误隔离（不依赖后端：extract_invoice 对不存在文件直接返回 error）
# ============================================================================
class TestProcessBatchErrorIsolation(unittest.TestCase):
    """process_batch 单张异常隔离与空列表边界。"""

    def test_missing_image_isolated(self):
        """缺失图片不崩批：ok=True，errors=1，failed_count=1，invoices 中 1 个 ok=False。"""
        batch_result = process_batch(["/no/such/fapiao.jpg"], do_verify=False)
        self.assertTrue(batch_result.get("ok") is True, "批量流程应返回 ok=True（不因单张失败而崩）")
        self.assertEqual(len(batch_result.get("errors", [])), 1, "应记录 1 个错误")
        agg = batch_result["aggregate"]
        self.assertEqual(agg["failed_count"], 1, "聚合计数 failed_count 应为 1")
        self.assertEqual(agg["total_invoices"], 1, "聚合计数 total_invoices 应为 1")
        failed = [inv for inv in batch_result["invoices"] if not inv.get("ok")]
        self.assertEqual(len(failed), 1, "invoices 中应有且仅有 1 个 ok=False 的元素")

    def test_empty_list(self):
        """空列表：ok=True，invoices 为空，total_invoices=0。"""
        batch_result = process_batch([], do_verify=False)
        self.assertTrue(batch_result.get("ok") is True, "空列表应返回 ok=True")
        self.assertEqual(batch_result.get("invoices"), [], "空列表 invoices 应为空")
        self.assertEqual(batch_result["aggregate"]["total_invoices"], 0,
                         "空列表 total_invoices 应为 0")


# ============================================================================
# 5) 集成测试（需 VLM 后端可达；不可达则整类 skip）
# ============================================================================
class TestBatchIntegration(unittest.TestCase):
    """真实 VLM 后端集成测试：两张样例发票聚合与重复检测。

    setUpClass 探测 http://localhost:8000/v1/models，不可达则跳过整类，
    不让 CI 因后端不可达而失败。
    """

    @classmethod
    def setUpClass(cls):
        try:
            urllib.request.urlopen("http://localhost:8000/v1/models", timeout=5)
        except Exception:
            raise unittest.SkipTest("VLM 后端不可达，跳过集成测试")

    def test_two_invoices_aggregate(self):
        """两张样例发票：聚合可报 = 各成功非重复发票可报之和，会话记忆已写入。"""
        batch_result = process_batch([FAPIAO, FAPIAO2], do_verify=False, session_id="test-batch")
        self.assertTrue(batch_result.get("ok") is True, "批量处理应返回 ok=True")
        invoices = batch_result.get("invoices", [])
        self.assertEqual(len(invoices), 2, "应处理 2 张发票")
        expected = sum(inv["decision"]["total_reimbursable"] for inv in invoices
                       if inv.get("ok") and inv.get("duplicate_of") is None)
        agg = batch_result["aggregate"]
        self.assertTrue(abs(agg["total_reimbursable"] - expected) < 0.01,
                        f"聚合可报 {agg['total_reimbursable']} 应等于各成功非重复发票可报之和 {expected}")
        self.assertIn(agg["conclusion"], {"全部通过", "部分通过", "全部拒赔"},
                      "整体结论应为合法值（全部通过/部分通过/全部拒赔）")
        self.assertEqual(agg["total_invoices"], 2, "total_invoices 应为 2")
        stored = get_store().get_batch_claim("test-batch")
        self.assertIsNotNone(stored, "会话记忆应已写入批量结果（session_id=test-batch）")
        self.assertTrue(stored.get("ok") is True, "会话记忆中的批量结果 ok 应为 True")

    def test_duplicate_detection(self):
        """同一张图两次（真实 VLM）：若两次 OCR 返回一致 fphm+code，则第二张判为重复。

        VLM 对发票号某位数字的识别存在偶发不确定性，本用例在 VLM 一致时验证重复
        被识别；若本次运行 VLM 返回了不同的 fphm/code（未触发去重），则 skip 而非
        fail——重复检测的确定性逻辑由 TestBatchDuplicateMocked 覆盖。
        """
        batch_result = process_batch([FAPIAO, FAPIAO], do_verify=False, session_id="test-dup")
        invoices = batch_result.get("invoices", [])
        dups = [inv for inv in invoices if inv.get("duplicate_of") is not None]
        if len(dups) == 0:
            # VLM 两次识别 fphm/code 不一致，未触发去重——属环境不确定性，跳过
            self.skipTest("VLM 两次 OCR 的 fphm/code 不一致，未触发去重（确定性逻辑见 TestBatchDuplicateMocked）")
        self.assertEqual(len(dups), 1, "应有 1 张重复发票被识别")
        self.assertEqual(dups[0]["duplicate_of"], 0,
                         "重复发票 duplicate_of 应指向首张索引 0")
        agg = batch_result["aggregate"]
        self.assertEqual(agg["duplicate_count"], 1, "duplicate_count 应为 1")
        self.assertEqual(agg["success_count"], 1, "success_count 应为 1")
        # 与单独跑一张比较 total_reimbursable：重复发票未计入可报
        single = process_batch([FAPIAO], do_verify=False)
        self.assertTrue(
            abs(agg["total_reimbursable"] - single["aggregate"]["total_reimbursable"]) < 0.01,
            f"重复发票未计入：批量可报 {agg['total_reimbursable']} 应等于单张可报 "
            f"{single['aggregate']['total_reimbursable']}")


# ============================================================================
# 6) 重复检测确定性测试（mock OCR，避免 VLM 不确定性导致 flaky）
# ============================================================================
class TestBatchDuplicateMocked(unittest.TestCase):
    """重复检测确定性测试。

    VLM 对发票号某位数字的识别在不同运行间存在不确定性（如 0389... vs 0380...），
    会导致真实「同图重复」集成测试偶发失败。本类用 mock 固定 extract_invoice 的
    返回，使两次 OCR 结果完全一致，从而确定性验证 process_batch_stream 的重复
    检测逻辑（seen 集合、duplicate_of 标记、重复不计入聚合理赔金额）。
    仅依赖本地 RAG（_enrich_item），不需要 VLM 后端。
    """

    def test_duplicate_detection_mocked(self):
        """同一张图两次（mock OCR 一致）：第二张标记 duplicate_of=0，重复不计入可报。"""
        fixed_extract = {
            "fpdm": "11060126", "fphm": "0380074352", "date": "20260508", "code": "139.40",
            "items": [{"name": "测试药品", "spec": "", "amount": "1", "priceSum": 100.0}],
        }
        fixed_decision = {
            "conclusion": "部分通过", "verified": True, "total_amount": 139.40,
            "total_reimbursable": 70.0, "total_medical_insurance": 70.0,
            "total_commercial": 0.0, "items": [], "summary_text": "测试决策",
        }

        def fake_extract(path):
            return dict(fixed_extract)

        def fake_decide(verified, items):
            return dict(fixed_decision)

        with patch("agent.batch_pipeline.extract_invoice", side_effect=fake_extract), \
             patch("agent.batch_pipeline.decide_claim_core", side_effect=fake_decide):
            batch_result = process_batch([FAPIAO, FAPIAO], do_verify=False, session_id="test-dup-mock")
            single = process_batch([FAPIAO], do_verify=False, session_id="test-dup-mock-single")

        invoices = batch_result.get("invoices", [])
        dups = [inv for inv in invoices if inv.get("duplicate_of") is not None]
        self.assertEqual(len(dups), 1, "应有 1 张重复发票被识别")
        self.assertEqual(dups[0]["duplicate_of"], 0,
                         "重复发票 duplicate_of 应指向首张索引 0")
        agg = batch_result["aggregate"]
        self.assertEqual(agg["duplicate_count"], 1, "duplicate_count 应为 1")
        self.assertEqual(agg["success_count"], 1, "success_count 应为 1")
        self.assertEqual(agg["total_invoices"], 2, "total_invoices 应为 2")
        # 重复发票未计入可报：批量可报(70) 应等于单张可报(70)
        self.assertTrue(
            abs(agg["total_reimbursable"] - single["aggregate"]["total_reimbursable"]) < 0.01,
            f"重复发票未计入：批量可报 {agg['total_reimbursable']} 应等于单张可报 "
            f"{single['aggregate']['total_reimbursable']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
