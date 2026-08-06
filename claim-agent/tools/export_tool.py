# -*- coding: utf-8 -*-
"""
tools/export_tool.py — 批量发票处理结果持久化与 CSV 导出工具

提供两个内部工具函数（非 LangChain @tool，由前端/流水线直接调用）：
- persist_batch_result  将批量处理结果以 JSON 形式持久化到 cfg.BATCH_PERSIST_DIR
- export_batch_csv      将批量结果导出为带 UTF-8 BOM 的 CSV 字符串（Excel 友好）

设计原则：对所有入参字段做防御性处理，单张发票字段缺失不致整体崩溃；
持久化失败不抛断主流程，仅 print 警告并返回 None。
"""

import os
import csv
import io
import json
import datetime  # noqa: F401  预留：batch_result 已含 created_at，无需额外时间戳

import tools  # noqa: F401  注入 sys.path
import config as cfg


def persist_batch_result(session_id, batch_result) -> str | None:
    """将批量处理结果持久化为 JSON 文件，返回写入路径；未启用或失败时返回 None。

    - 受 cfg.BATCH_PERSIST_ENABLED 开关控制：False 时直接返回 None。
    - session_id 为空时用 "default" 兜底。
    - 文件路径：os.path.join(cfg.BATCH_PERSIST_DIR, f"{session_id}.json")。
    - 写入使用 ensure_ascii=False, indent=2；batch_result 已含 created_at，不再追加时间戳。
    - 异常时 print 警告并返回 None，不抛断主流程。
    """
    if not cfg.BATCH_PERSIST_ENABLED:
        return None

    if not session_id:
        session_id = "default"

    if not isinstance(batch_result, dict):
        print(f"[persist_batch_result] batch_result 非法（{type(batch_result).__name__}），跳过持久化")
        return None

    try:
        os.makedirs(cfg.BATCH_PERSIST_DIR, exist_ok=True)
        file_path = os.path.join(cfg.BATCH_PERSIST_DIR, f"{session_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(batch_result, f, ensure_ascii=False, indent=2)
        return file_path
    except Exception as e:
        print(f"[persist_batch_result] 持久化批量结果失败: {e}")
        return None


def _to_csv_str(v) -> str:
    """将任意值转为 CSV 单元格字符串，None 视为空字符串。"""
    if v is None:
        return ""
    return str(v)


def export_batch_csv(batch_result) -> str:
    """将批量结果导出为带 UTF-8 BOM 的 CSV 字符串（Excel 友好）。

    表头列（精确顺序）：
    序号,文件名,发票号,开票日期,价税合计,医保可报,商保可报,可报合计,结论,备注

    遍历 batch_result["invoices"]，每张一行：
    - 重复发票结论填「重复」，备注「与第 N 张重复」；
    - 失败发票结论填「失败（stage）」，备注填 message；
    - 成功发票结论填 decision.conclusion，备注留空。
    重复发票行同样输出并标注。所有字段做 .get 防御，None 视为空字符串，不致崩溃。
    """
    output = io.StringIO()
    # 写入 UTF-8 BOM，便于 Excel 正确识别中文编码
    output.write("\ufeff")

    invoices = []
    if isinstance(batch_result, dict):
        invoices = batch_result.get("invoices") or []

    writer = csv.writer(output)
    writer.writerow(["序号", "文件名", "发票号", "开票日期", "价税合计",
                     "医保可报", "商保可报", "可报合计", "结论", "备注"])

    for inv in invoices:
        if not isinstance(inv, dict):
            continue

        # 序号：index + 1，防御非整型
        index = inv.get("index", 0)
        try:
            seq = int(index) + 1
        except (TypeError, ValueError):
            seq = ""

        filename = _to_csv_str(inv.get("filename", ""))
        ok = bool(inv.get("ok", False))
        duplicate_of = inv.get("duplicate_of", None)
        stage = _to_csv_str(inv.get("stage", ""))
        message = _to_csv_str(inv.get("message", ""))

        extract = inv.get("extract")
        if not isinstance(extract, dict):
            extract = {}
        fphm = _to_csv_str(extract.get("fphm", ""))
        date = _to_csv_str(extract.get("date", ""))
        code = _to_csv_str(extract.get("code", ""))

        decision = inv.get("decision")
        if not isinstance(decision, dict):
            decision = {}
        medical = _to_csv_str(decision.get("total_medical_insurance", ""))
        commercial = _to_csv_str(decision.get("total_commercial", ""))
        reimbursable = _to_csv_str(decision.get("total_reimbursable", ""))
        conclusion = _to_csv_str(decision.get("conclusion", ""))

        # 结论与备注：重复 > 失败 > 成功
        if duplicate_of is not None:
            csv_conclusion = "重复"
            try:
                remark = f"与第 {int(duplicate_of) + 1} 张重复"
            except (TypeError, ValueError):
                remark = "与之前的发票重复"
        elif not ok:
            csv_conclusion = f"失败（{stage}）"
            remark = message
        else:
            csv_conclusion = conclusion
            remark = ""  # 成功备注留空，避免行过长

        writer.writerow([seq, filename, fphm, date, code,
                         medical, commercial, reimbursable,
                         csv_conclusion, remark])

    return output.getvalue()
