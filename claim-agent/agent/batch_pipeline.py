# -*- coding: utf-8 -*-
"""
agent/batch_pipeline.py — 批量发票处理流水线

对一批发票图片逐张执行：OCR 提取 → 重复检测 →（非重复的）真伪查验 + 逐项
RAG 目录补全 + 确定性理赔决策，最后跨发票聚合得出批量理赔结论。

与 agent/pipeline.py 的单张流式流水线互补：
- 单张流水线（process_invoice_stream）一次跑完 OCR→verify→enrich→decide；
- 批量流水线**分阶段**：先单独调 extract_invoice 拿到 OCR 结果做重复检测
  （避免对重复发票再次调用昂贵的 VLM 查验/决策），非重复的再跑 verify+enrich+decide。

设计目标：
- 单张异常隔离：某一张 OCR/查验/决策抛错不影响其他发票，错误归入 errors 列表。
- 重复发票跳过：以 (fphm, code) 为 key，重复发票仅记录不重复处理，避免对重复
  发票再次调用昂贵的查验与决策。
- 流式进度：逐张 yield 进度事件，供前端实时展示；最后 yield 批量结构化结果。
- 持久化可选：批量结果可写入会话记忆与本地文件（export_tool 就绪时），失败不阻断主流程。
"""

import os
import datetime
from typing import List

import agent  # noqa: F401  注入 sys.path
import config as cfg
from tools.ocr_tool import extract_invoice
from tools.verify_tool import verify_invoice_core
from tools.decision_tool import decide_claim_core, decide_batch_core
from agent.pipeline import _enrich_item
from agent.memory import get_store


def list_images(folder_or_files) -> List[str]:
    """收集待处理的发票图片路径列表。

    入参灵活：
    - 单个文件夹路径（str）：列出该文件夹**顶层**（不递归子目录）的图片文件，
      按 config.IMAGE_EXTS（小写比较）筛选。
    - 文件路径列表（list/tuple）：筛选其中的图片文件，跳过非图片与不存在文件。
    - 单个文件路径（str）：若是图片则包含它。

    返回按文件名（os.path.basename）排序后的绝对路径列表；对不存在的路径静默跳过。
    """
    exts = tuple(e.lower() for e in cfg.IMAGE_EXTS)
    collected: List[str] = []

    if isinstance(folder_or_files, str):
        path = folder_or_files
        if not os.path.exists(path):
            return []
        if os.path.isdir(path):
            for name in os.listdir(path):
                full = os.path.join(path, name)
                if os.path.isfile(full) and name.lower().endswith(exts):
                    collected.append(os.path.abspath(full))
        elif os.path.isfile(path) and path.lower().endswith(exts):
            collected.append(os.path.abspath(path))
        # 既非目录也非文件（如设备/链接异常）：返回空
        return sorted(collected, key=lambda p: os.path.basename(p))

    if isinstance(folder_or_files, (list, tuple)):
        for p in folder_or_files:
            if not isinstance(p, str):
                continue
            if not os.path.exists(p) or not os.path.isfile(p):
                continue
            if p.lower().endswith(exts):
                collected.append(os.path.abspath(p))
        return sorted(collected, key=lambda p: os.path.basename(p))

    # 其他类型：返回空
    return []


def process_batch_stream(image_paths, do_verify: bool = True, session_id: str = None):
    """批量发票流式处理生成器：逐张 yield 进度事件，最后 yield 批量结果。

    单张异常隔离：某张 OCR/查验/决策抛错时归入 errors 列表，不中断整批处理。
    重复发票跳过：以 (fphm, code) 为 key 检测重复，重复发票仅记录不重复跑
    verify/decision，避免对重复发票再次调用昂贵的查验与决策。

    产出格式：
      {"status": "...", "index": int, "total": int, "filename": str,
       "stage": "ocr"|"verify"|"decision"|"duplicate"|"error", "conclusion": None|str}
        逐张阶段进度（供前端实时展示）
      {"done": True, "result": <BatchClaimResult dict>}
        最终批量结构化理赔结果
    """
    total = len(image_paths) if image_paths else 0

    # 空列表边界：直接 yield 空批量结果
    if total == 0:
        yield {"done": True, "result": {
            "ok": True,
            "session_id": session_id,
            "created_at": datetime.datetime.now().isoformat(),
            "invoices": [],
            "aggregate": decide_batch_core([]),
            "errors": [],
            "duplicates": [],
        }}
        return

    invoices: List[dict] = []
    errors: List[dict] = []
    duplicates: List[dict] = []
    seen: dict = {}  # (fphm, code) -> 首次出现 index

    for i, path in enumerate(image_paths):
        filename = os.path.basename(path)

        # 1) OCR 阶段
        yield {"status": f"[{i + 1}/{total}] {filename} · 🔍 Identifying…",
               "index": i, "total": total, "filename": filename,
               "stage": "ocr", "conclusion": None}
        try:
            extract = extract_invoice(path)
        except Exception as e:
            msg = str(e)
            errors.append({"index": i, "filename": filename,
                           "stage": "ocr", "message": msg})
            # 失败发票同时入 invoices（ok=False），保证聚合计数正确
            invoices.append({
                "index": i, "filename": filename, "image_path": path,
                "ok": False, "stage": "ocr", "message": msg,
                "duplicate_of": None,
                "extract": None, "verify": None, "decision": None,
            })
            yield {"status": f"[{i + 1}/{total}] {filename} · ❌ Identification failed: {msg}",
                   "index": i, "total": total, "filename": filename,
                   "stage": "error", "conclusion": "Failed"}
            continue

        if extract.get("error"):
            msg = extract.get("error")
            errors.append({"index": i, "filename": filename,
                           "stage": "ocr", "message": msg})
            # 失败发票同时入 invoices（ok=False），保证聚合计数正确
            invoices.append({
                "index": i, "filename": filename, "image_path": path,
                "ok": False, "stage": "ocr", "message": msg,
                "duplicate_of": None,
                "extract": extract, "verify": None, "decision": None,
            })
            yield {"status": f"[{i + 1}/{total}] {filename} · ❌ Identification failed: {msg}",
                   "index": i, "total": total, "filename": filename,
                   "stage": "error", "conclusion": "Failed"}
            continue

        # 3) 取 fphm / code 构造查重 key
        fphm = extract.get("fphm", "") or ""
        code = extract.get("code", "") or ""
        key = (fphm, code)

        # 4) 重复检测：仅当两者都非空才查重
        if fphm and code and key in seen:
            first_idx = seen[key]
            duplicates.append({
                "index": i, "filename": filename,
                "duplicate_of": first_idx, "fphm": fphm, "code": code,
            })
            invoices.append({
                "index": i, "filename": filename, "image_path": path,
                "ok": True, "stage": None,
                "message": "Duplicate invoice, skipping verification and decision",
                "duplicate_of": first_idx,
                "extract": extract, "verify": None, "decision": None,
            })
            yield {"status": f"[{i + 1}/{total}] {filename} · ⚠️ Duplicate invoice (same as #{first_idx + 1}), skipping verification and decision",
                   "index": i, "total": total, "filename": filename,
                   "stage": "duplicate", "conclusion": "Duplicate"}
            continue

        # 5) 非重复：登记 seen，跑 verify + enrich + decide（合并为一个进度，整段 try/except）
        seen[key] = i
        yield {"status": f"[{i + 1}/{total}] {filename} · 🛡️ Verifying + searching + deciding…",
               "index": i, "total": total, "filename": filename,
               "stage": "verify", "conclusion": None}
        try:
            # verify
            stage = "verify"
            if do_verify:
                verify = verify_invoice_core(
                    extract.get("fpdm", ""), fphm,
                    extract.get("date", ""), code,
                )
            else:
                verify = {"verified": True, "code": "0",
                          "message": "Verification skipped (demo mode)",
                          "official": {}, "field_match": {}}
            # enrich + decide
            stage = "decision"
            enriched = [_enrich_item(it) for it in extract.get("items", [])]
            decision = decide_claim_core(bool(verify.get("verified", False)), enriched)
        except Exception as e:
            msg = str(e)
            errors.append({"index": i, "filename": filename,
                           "stage": stage, "message": msg})
            # 失败发票同时入 invoices（ok=False），保证聚合计数正确
            invoices.append({
                "index": i, "filename": filename, "image_path": path,
                "ok": False, "stage": stage, "message": msg,
                "duplicate_of": None,
                "extract": extract, "verify": None, "decision": None,
            })
            yield {"status": f"[{i + 1}/{total}] {filename} · ❌ Processing failed: {msg}",
                   "index": i, "total": total, "filename": filename,
                   "stage": "error", "conclusion": "Failed"}
            continue

        invoices.append({
            "index": i, "filename": filename, "image_path": path,
            "ok": True, "stage": None, "message": None,
            "duplicate_of": None,
            "extract": extract, "verify": verify, "decision": decision,
        })
        conc = decision.get("conclusion", "")
        reimb = decision.get("total_reimbursable", 0.0)
        yield {"status": f"[{i + 1}/{total}] {filename} · ✅ {conc}, reimbursable {reimb}",
               "index": i, "total": total, "filename": filename,
               "stage": "decision", "conclusion": conc}

    # 全部完成：聚合 + 构造批量结果
    aggregate = decide_batch_core(invoices)
    batch_result = {
        "ok": True,
        "session_id": session_id,
        "created_at": datetime.datetime.now().isoformat(),
        "invoices": invoices,
        "aggregate": aggregate,
        "errors": errors,
        "duplicates": duplicates,
    }

    # 写入会话记忆
    if session_id:
        try:
            get_store().set_batch_claim(session_id, batch_result)
        except Exception:
            pass

    # 持久化（懒导入，export_tool 未就绪或未启用时静默跳过，不阻断主流程）
    try:
        from tools.export_tool import persist_batch_result
        persist_batch_result(session_id, batch_result)
    except Exception:
        pass

    yield {"done": True, "result": batch_result}


def process_batch(image_paths, do_verify: bool = True, session_id: str = None) -> dict:
    """批量发票同步处理：消费 process_batch_stream，返回最终 done 事件的 result。

    参数：
      image_paths  图片路径列表（调用方通常先用 list_images 展开为列表）
      do_verify    是否调用官方查验接口（False 时视为已通过，仅用于演示 RAG+决策链路）
      session_id   会话标识，非空时将批量结果写入会话记忆供追问复用
    """
    result = {}
    for ev in process_batch_stream(image_paths, do_verify=do_verify, session_id=session_id):
        if ev.get("done"):
            result = ev["result"]
    return result
