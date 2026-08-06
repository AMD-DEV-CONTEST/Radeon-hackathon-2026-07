# -*- coding: utf-8 -*-
"""
underwriting/batch_pipeline.py — Batch Underwriting Pipeline

Aligns with spec.md "Batch Underwriting": upload a folder of multiple report
images at once, underwrite concurrently, push progress per report via SSE,
skip duplicate reports with annotation, isolate failures without affecting the
batch, and finally aggregate batch results (with summary text / risk
distribution / recommendation distribution), persist JSON to
``data/underwriting_results/``, exportable as UTF-8 BOM CSV.

Design mirrors ``agent/batch_pipeline.py``'s batch invoice pipeline pattern:
- ``list_images``: scans folder filtering by ``DOCUMENT_EXTS`` (images + PDF,
  reuses agent's flexible input semantics).
- ``process_batch_stream``: streaming generator, yields
  ``{"type":"progress",...}`` per report, finally yields
  ``{"type":"done","result":{...}}``.
- Duplicate detection: prefers image file content md5 hash (dedup works even
  if extraction fails), falls back to ``report.patient.name + report.exam_date``.
- Failure isolation: a single ``process_report`` exception or ``ok=False``
  doesn't affect the batch; goes into errors list and marked in reports with
  ``ok=False, stage, message``.
- Concurrency: ``ThreadPoolExecutor(max_workers=UNDERWRITING_BATCH_MAX_WORKERS)``.
  To ensure progress events are pushed per report in submission order and
  duplicate detection proceeds in submission order, uses "serial submit +
  immediate wait" strategy (consistent with agent/batch_pipeline.py);
  ``UNDERWRITING_BATCH_MAX_WORKERS`` controls the nominal concurrency上限.

Module entry points:
- ``list_images(folder_or_files) -> List[str]``
- ``process_batch_stream(folder_or_files, session_id=None)``: streaming generator
- ``process_batch(folder_or_files, session_id=None) -> dict``: synchronous wrapper
- ``export_batch_csv(batch_result) -> str``: UTF-8 BOM CSV string
"""

import os
import csv
import io
import json
import hashlib
import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor

import underwriting  # noqa: F401  inject into sys.path
from underwriting import config as cfg
from underwriting.pipeline import process_report
from underwriting.memory import get_store


# ----------------------------------------------------------------------------
# File collection (reuses agent/batch_pipeline.py's list_images pattern, filters by DOCUMENT_EXTS)
# ----------------------------------------------------------------------------

def list_images(folder_or_files) -> List[str]:
    """Collect a list of file paths to underwrite (images + PDF), reuses agent.batch_pipeline.list_images semantics.

    Flexible input:
    - Single folder path (str): lists files at the **top level** (non-recursive)
      of the folder, filtered by ``cfg.DOCUMENT_EXTS`` (case-insensitive),
      including images and PDFs.
    - List of file paths (list/tuple): filters for image and PDF files, skips
      others and non-existent files.
    - Single file path (str): includes it if it's an image or PDF.

    Returns absolute paths sorted by filename (os.path.basename); non-existent
    paths are silently skipped.
    """
    exts = tuple(e.lower() for e in cfg.DOCUMENT_EXTS)
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

    return []


# ----------------------------------------------------------------------------
# Duplicate detection: image file content md5 hash
# ----------------------------------------------------------------------------

def _md5_file(path: str, chunk_size: int = 65536) -> str:
    """Compute md5 hash of file content; returns empty string on read failure (no dedup)."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _patient_date_key(report: dict) -> str:
    """Extract ``patient.name + exam_date`` from a single report as a dedup fallback key.

    Returns empty string on extraction failure or missing fields (no dedup).
    """
    if not isinstance(report, dict) or not report.get("ok"):
        return ""
    patient = report.get("patient", {}) or {}
    name = (patient.get("name", "") or "").strip()
    exam_date = (report.get("exam_date", "") or "").strip()
    if not name or not exam_date:
        return ""
    return f"{name}|{exam_date}"


# ----------------------------------------------------------------------------
# Aggregation: batch result statistics and summary text
# ----------------------------------------------------------------------------

def _aggregate_batch(reports: List[dict]) -> dict:
    """Aggregate batch underwriting results, outputting summary text and risk/recommendation distribution.

    Statistics are based only on ``ok=True and duplicate_of is None`` successful
    reports (duplicates are not double-counted in distribution).

    Returns:
        {
            "summary_text": "...",
            "overall_risk_distribution": {"Low":x,"Medium":y,"High":z},
            "recommendation_distribution": {"Standard":x,"Substandard - Extra Premium":y,...},
        }
    """
    # Initialize distribution (cover all enum values to avoid missing keys)
    risk_dist = {cfg.RISK_LEVEL_LOW: 0, cfg.RISK_LEVEL_MEDIUM: 0, cfg.RISK_LEVEL_HIGH: 0}
    rec_dist = {r: 0 for r in cfg.RECOMMENDATIONS}

    success_unique = 0  # Successful and non-duplicate report count
    for item in reports:
        if not isinstance(item, dict):
            continue
        if not item.get("ok"):
            continue
        if item.get("duplicate_of") is not None:
            continue  # Duplicates not double-counted in distribution
        success_unique += 1
        report = item.get("report")
        if not isinstance(report, dict):
            continue
        overall_risk = report.get("overall_risk", cfg.RISK_LEVEL_LOW)
        if overall_risk in risk_dist:
            risk_dist[overall_risk] += 1
        recommendation = report.get("recommendation", "")
        if recommendation in rec_dist:
            rec_dist[recommendation] += 1

    total = len(reports)
    duplicate_count = sum(1 for r in reports if isinstance(r, dict)
                          and r.get("ok") and r.get("duplicate_of") is not None)
    fail_count = sum(1 for r in reports if isinstance(r, dict) and not r.get("ok"))

    # Summary text
    risk_text = ", ".join([f"{k}: {v}" for k, v in risk_dist.items()])
    rec_text = ", ".join([f"{k}: {v}" for k, v in rec_dist.items()])
    summary_text = (
        f"Total {total} reports, success {success_unique}, "
        f"duplicates {duplicate_count}, failures {fail_count}. "
        f"Overall risk distribution: {risk_text}. Recommendation distribution: {rec_text}."
    )

    return {
        "summary_text": summary_text,
        "overall_risk_distribution": risk_dist,
        "recommendation_distribution": rec_dist,
    }


# ----------------------------------------------------------------------------
# Persistence (mirrors agent.batch_pipeline + tools.export_tool.persist_batch_result pattern)
# ----------------------------------------------------------------------------

def _persist_batch_result(session_id: str, batch_result: dict) -> str:
    """Persist batch underwriting results as JSON to ``UNDERWRITING_PERSIST_DIR``.

    - Controlled by ``cfg.UNDERWRITING_PERSIST_ENABLED`` switch: returns None if False.
    - session_id defaults to "default" if empty.
    - File path: ``os.path.join(cfg.UNDERWRITING_PERSIST_DIR, f"{session_id}.json")``.
    - Writes with ensure_ascii=False, indent=2; on exception prints warning and
      returns None without interrupting the main flow.
    """
    if not cfg.UNDERWRITING_PERSIST_ENABLED:
        return None
    if not session_id:
        session_id = "default"
    if not isinstance(batch_result, dict):
        return None
    try:
        os.makedirs(cfg.UNDERWRITING_PERSIST_DIR, exist_ok=True)
        file_path = os.path.join(cfg.UNDERWRITING_PERSIST_DIR, f"{session_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(batch_result, f, ensure_ascii=False, indent=2)
        return file_path
    except Exception as e:
        print(f"[_persist_batch_result] Failed to persist batch underwriting results: {e}")
        return None


# ----------------------------------------------------------------------------
# Streaming batch underwriting
# ----------------------------------------------------------------------------

def process_batch_stream(folder_or_files, session_id: str = None):
    """Batch underwriting streaming generator: yields progress events per report, finally yields batch result.

    Args:
        folder_or_files  folder path / image path list / single image path
                         (internally expanded to image path list via ``list_images``)
        session_id       session identifier; if non-empty, writes batch results
                         to session memory + persists JSON

    Event sequence:
        {"type":"progress", "status":"...", "index":i, "total":N,
         "filename":"...", "stage":"extract"|"done"|"duplicate"|"error",
         "conclusion":None|str}
            Per-report stage progress (for frontend real-time display)
        {"type":"done", "result": <BatchUnderwritingResult dict>}
            Final batch structured underwriting result

    Design:
    - Duplicate detection: prefers image file md5 hash; after extraction success,
      falls back to patient+exam_date check. Duplicate reports skip
      ``process_report`` call, marked with ``duplicate_of`` (pointing to first index).
    - Failure isolation: a single ``process_report`` exception or ``ok=False``
      doesn't affect the batch; goes into errors list and marked in reports with
      ``ok=False, stage, message``.
    - Concurrency: ``ThreadPoolExecutor(max_workers=UNDERWRITING_BATCH_MAX_WORKERS)``,
      uses "serial submit + immediate wait" strategy, ensuring progress events
      are pushed per report in submission order and duplicate detection proceeds
      in submission order (consistent with agent/batch_pipeline.py pattern).
    """
    image_paths = list_images(folder_or_files)
    total = len(image_paths)

    # Empty list edge case: yield empty batch result directly
    if total == 0:
        empty_result = {
            "ok": True,
            "session_id": session_id,
            "created_at": datetime.datetime.now().isoformat(),
            "total": 0,
            "success_count": 0,
            "duplicate_count": 0,
            "fail_count": 0,
            "reports": [],
            "duplicates": [],
            "errors": [],
            "aggregate": _aggregate_batch([]),
        }
        # Write to session memory + persist (failure doesn't interrupt)
        if session_id:
            try:
                get_store().set_batch_report(session_id, empty_result)
            except Exception:
                pass
        _persist_batch_result(session_id, empty_result)
        yield {"type": "done", "result": empty_result}
        return

    reports: List[dict] = []
    errors: List[dict] = []
    duplicates: List[dict] = []
    seen_hashes: dict = {}   # file_md5 -> first_index
    seen_patient_date: dict = {}  # "name|exam_date" -> first_index

    max_workers = max(1, int(cfg.UNDERWRITING_BATCH_MAX_WORKERS))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i, path in enumerate(image_paths):
            filename = os.path.basename(path)

            # ===== 1) Duplicate detection (based on file content md5 hash) =====
            file_hash = _md5_file(path)
            dup_of = None
            if file_hash and file_hash in seen_hashes:
                dup_of = seen_hashes[file_hash]
            else:
                if file_hash:
                    seen_hashes[file_hash] = i

            if dup_of is not None:
                # Duplicate report: skip process_report call
                duplicates.append({
                    "index": i, "filename": filename,
                    "duplicate_of": dup_of, "file_hash": file_hash,
                })
                reports.append({
                    "index": i, "filename": filename, "image_path": path,
                    "ok": True, "stage": "duplicate",
                    "message": "Duplicate report, skipping underwriting",
                    "duplicate_of": dup_of,
                    "report": None,
                })
                yield {
                    "type": "progress",
                    "status": f"[{i + 1}/{total}] {filename} · ⚠️ Duplicate report"
                              f" (same as #{dup_of + 1}), skipping underwriting",
                    "index": i, "total": total, "filename": filename,
                    "stage": "duplicate", "conclusion": "Duplicate",
                }
                continue

            # ===== 2) Non-duplicate: call single report underwriting pipeline =====
            yield {
                "type": "progress",
                "status": f"[{i + 1}/{total}] {filename} · 🔍 Underwriting…",
                "index": i, "total": total, "filename": filename,
                "stage": "extract", "conclusion": None,
            }

            try:
                report = executor.submit(
                    process_report, path, session_id
                ).result()
            except Exception as e:
                # Exception isolation: goes into errors, doesn't affect batch
                msg = str(e)
                errors.append({"index": i, "filename": filename,
                               "stage": "process", "message": msg})
                reports.append({
                    "index": i, "filename": filename, "image_path": path,
                    "ok": False, "stage": "process", "message": msg,
                    "duplicate_of": None, "report": None,
                })
                yield {
                    "type": "progress",
                    "status": f"[{i + 1}/{total}] {filename} · ❌ Processing failed: {msg}",
                    "index": i, "total": total, "filename": filename,
                    "stage": "error", "conclusion": "Failed",
                }
                continue

            # process_report returned ok=False (e.g. extract failure)
            if not isinstance(report, dict) or not report.get("ok"):
                msg = (report or {}).get("message", "Unknown error") if isinstance(report, dict) else "Unknown error"
                stage = (report or {}).get("stage", "extract") if isinstance(report, dict) else "extract"
                errors.append({"index": i, "filename": filename,
                               "stage": stage, "message": msg})
                reports.append({
                    "index": i, "filename": filename, "image_path": path,
                    "ok": False, "stage": stage, "message": msg,
                    "duplicate_of": None, "report": report,
                })
                yield {
                    "type": "progress",
                    "status": f"[{i + 1}/{total}] {filename} · ❌ Processing failed ({stage}): {msg}",
                    "index": i, "total": total, "filename": filename,
                    "stage": "error", "conclusion": "Failed",
                }
                continue

            # ===== 3) Success: fallback dedup (patient.name + exam_date) =====
            # Two images with different file hashes may extract the same patient+date
            # (e.g. different photos of the same report); treat as duplicate,
            # duplicate_of points to the first one.
            pd_key = _patient_date_key(report)
            if pd_key and pd_key in seen_patient_date:
                first_idx = seen_patient_date[pd_key]
                duplicates.append({
                    "index": i, "filename": filename,
                    "duplicate_of": first_idx, "patient_date_key": pd_key,
                })
                reports.append({
                    "index": i, "filename": filename, "image_path": path,
                    "ok": True, "stage": "duplicate",
                    "message": "Duplicate report (same patient+date), skipping underwriting",
                    "duplicate_of": first_idx,
                    "report": report,
                })
                yield {
                    "type": "progress",
                    "status": f"[{i + 1}/{total}] {filename} · ⚠️ Duplicate report"
                              f" (same patient+date as #{first_idx + 1}), skipping underwriting",
                    "index": i, "total": total, "filename": filename,
                    "stage": "duplicate", "conclusion": "Duplicate",
                }
                continue

            if pd_key:
                seen_patient_date[pd_key] = i

            # ===== 4) Success and non-duplicate =====
            reports.append({
                "index": i, "filename": filename, "image_path": path,
                "ok": True, "stage": None, "message": None,
                "duplicate_of": None, "report": report,
            })
            overall_risk = report.get("overall_risk", "")
            recommendation = report.get("recommendation", "")
            yield {
                "type": "progress",
                "status": f"[{i + 1}/{total}] {filename} · ✅ Overall risk \"{overall_risk}\""
                          f" | Recommendation {recommendation}",
                "index": i, "total": total, "filename": filename,
                "stage": "done",
                "conclusion": f"{overall_risk}/{recommendation}",
            }

    # ===== All complete: aggregate + build batch result =====
    success_count = sum(1 for r in reports if isinstance(r, dict)
                        and r.get("ok") and r.get("duplicate_of") is None)
    duplicate_count = sum(1 for r in reports if isinstance(r, dict)
                          and r.get("ok") and r.get("duplicate_of") is not None)
    fail_count = sum(1 for r in reports if isinstance(r, dict) and not r.get("ok"))

    aggregate = _aggregate_batch(reports)
    batch_result = {
        "ok": True,
        "session_id": session_id,
        "created_at": datetime.datetime.now().isoformat(),
        "total": total,
        "success_count": success_count,
        "duplicate_count": duplicate_count,
        "fail_count": fail_count,
        "reports": reports,
        "duplicates": duplicates,
        "errors": errors,
        "aggregate": aggregate,
    }

    # Write to session memory (failure doesn't interrupt main flow)
    if session_id:
        try:
            get_store().set_batch_report(session_id, batch_result)
        except Exception:
            pass

    # Persist JSON (failure doesn't interrupt main flow)
    _persist_batch_result(session_id, batch_result)

    yield {"type": "done", "result": batch_result}


def process_batch(folder_or_files, session_id: str = None) -> dict:
    """Batch underwriting synchronous wrapper: consumes ``process_batch_stream``, returns the final done event's result.

    Args:
        folder_or_files  folder path / image path list / single image path
        session_id       session identifier; if non-empty, writes batch results
                         to session memory + persists JSON

    Returns: batch underwriting result dict (contains reports/duplicates/errors/aggregate, etc.).
    """
    result = {}
    for ev in process_batch_stream(folder_or_files, session_id=session_id):
        if ev.get("type") == "done":
            result = ev["result"]
    return result


# ----------------------------------------------------------------------------
# CSV export (mirrors tools/export_tool.export_batch_csv, UTF-8 BOM, Excel-friendly)
# ----------------------------------------------------------------------------

def _to_csv_str(v) -> str:
    """Convert any value to a CSV cell string; None is treated as empty string."""
    if v is None:
        return ""
    return str(v)


def export_batch_csv(batch_result) -> str:
    """Export batch underwriting results as a UTF-8 BOM CSV string (Excel-friendly).

    Header columns (exact order):
        No., Filename, Patient Name, Report Type, Overall Risk, Recommendation,
        Abnormalities, References, Status, Remarks

    Iterates ``batch_result["reports"]``, one row per report:
    - Duplicate reports: status "Duplicate", remarks "Duplicate of #N";
    - Failed reports: status "Failed (stage)", remarks = message;
    - Successful reports: status "Success", remarks empty.

    All fields use defensive ``.get``; None is treated as empty string; a single
    report's missing fields don't crash the overall export.
    """
    output = io.StringIO()
    # Write UTF-8 BOM for Excel to correctly recognize encoding
    output.write("\ufeff")

    reports = []
    if isinstance(batch_result, dict):
        reports = batch_result.get("reports") or []

    writer = csv.writer(output)
    writer.writerow([
        "No.", "Filename", "Patient Name", "Report Type",
        "Overall Risk", "Recommendation", "Abnormalities", "References",
        "Status", "Remarks",
    ])

    for item in reports:
        if not isinstance(item, dict):
            continue

        # No.: index + 1, defensive for non-int
        index = item.get("index", 0)
        try:
            seq = int(index) + 1
        except (TypeError, ValueError):
            seq = ""

        filename = _to_csv_str(item.get("filename", ""))
        ok = bool(item.get("ok", False))
        duplicate_of = item.get("duplicate_of", None)
        stage = _to_csv_str(item.get("stage", ""))
        message = _to_csv_str(item.get("message", ""))

        report = item.get("report")
        if not isinstance(report, dict):
            report = {}

        patient = report.get("patient", {}) or {}
        patient_name = _to_csv_str(patient.get("name", ""))
        report_type = _to_csv_str(report.get("report_type", ""))
        overall_risk = _to_csv_str(report.get("overall_risk", ""))
        recommendation = _to_csv_str(report.get("recommendation", ""))

        abnormalities = report.get("abnormalities", []) or []
        try:
            abn_count = len(abnormalities)
        except TypeError:
            abn_count = 0

        references = report.get("references", []) or []
        try:
            ref_count = len(references)
        except TypeError:
            ref_count = 0

        # Status and remarks: Duplicate > Failed > Success
        if duplicate_of is not None:
            status = "Duplicate"
            try:
                remark = f"Duplicate of #{int(duplicate_of) + 1}"
            except (TypeError, ValueError):
                remark = "Duplicate of a previous report"
        elif not ok:
            status = f"Failed ({stage})"
            remark = message
        else:
            status = "Success"
            remark = ""

        writer.writerow([
            seq, filename, patient_name, report_type,
            overall_risk, recommendation, abn_count, ref_count,
            status, remark,
        ])

    return output.getvalue()
