# -*- coding: utf-8 -*-
"""
underwriting/tools/report_extract_tool.py — Medical Record / Health Checkup Report Multimodal Extraction Tool

Reuses the multimodal call pattern from tools/ocr_tool.py (image base64 + prompt
POST to cfg.MODEL_URL), but with a medical-specific prompt to extract structured
information from medical records / health checkup reports.

Calls underwriting.config.MODEL_URL (exposes the OpenAI-compatible endpoint from
root config.py). The model is a thinking-chain model; final JSON is in content
and thinking process is in reasoning_content; parsing uses content first with
reasoning_content as fallback (consistent with ocr_tool).

Output JSON schema (strictly followed; subsequent abnormality_tool / risk_tool
depend on this structure):
{
  "report_type": "Health Checkup Report" | "Medical Record",
  "patient": {"name": "", "gender": "", "age": ""},
  "exam_date": "",
  "items": [{"name":"", "value":"", "unit":"", "reference_range":"", "abnormal": false}],
  "diagnoses": [""],
  "summary": ""
}
On failure returns {"error": "..."}; the pipeline uses this to isolate the report.
"""

import os
import json
import base64

import requests
import urllib3
from langchain_core.tools import tool

# underwriting/__init__.py injects the project root into sys.path;
# underwriting.config exposes the root cfg's LLM endpoint constants.
from underwriting import config as cfg
from underwriting.tools.pdf_loader import (
    is_pdf, extract_pdf_text, pdf_to_images_b64,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Medical-specific system prompt: constrains the model to return only JSON and
# clarifies the field semantics for the two report types.
REPORT_EXTRACT_SYSTEM_PROMPT = """You are a medical information extraction assistant. Carefully identify the medical record or health checkup report image provided by the user and extract structured information.
Return ONLY JSON (no extra text, no explanation, no markdown code blocks), strictly following this schema:
{
  "report_type": "Health Checkup Report" or "Medical Record",
  "patient": {"name": "patient name", "gender": "gender", "age": "age"},
  "exam_date": "examination or visit date (yyyyMMdd, empty string if unrecognizable)",
  "items": [
    {"name": "examination item name", "value": "numeric value or text description", "unit": "unit (empty if none)", "reference_range": "reference range (empty if none)", "abnormal": false}
  ],
  "diagnoses": ["clinical diagnoses"],
  "summary": "report summary (one sentence summarizing main findings)"
}

Extraction guidelines:
- IMPORTANT: ALL extracted text values (patient name, item names, values, diagnoses, summary) MUST be in English. If the original report is in Chinese or any other language, translate all medical findings, terms, and descriptions to English. Patient names should be romanized (e.g. pinyin).
- First determine whether report_type is "Health Checkup Report" or "Medical Record".
- Health Checkup Report: items are individual examination/test entries; value holds the numeric value (as string, e.g. "5.8"), unit holds the unit (e.g. "mmol/L"), reference_range holds the reference range (e.g. "3.9-6.1"), abnormal marks whether the indicator is abnormal (true/false, based on reference range or existing abnormal markers in the report such as arrows up/down).
- Medical Record: items correspond to sections such as chief complaint / present illness / examination & tests / medications; each item's name is the section name (e.g. "Chief Complaint"), value is the text description of that section, unit and reference_range are empty strings, abnormal is false; diagnoses corresponds to the list of clinical diagnoses.
- If any of the three patient fields are missing, use empty strings; do not omit fields.
- For unrecognizable examination items or diagnoses, return an empty array [].
- summary should be one sentence in English summarizing the core findings of the report (e.g. "Elevated fasting blood glucose, recommend recheck" or "History of hypertension, blood pressure currently well controlled")."""


# User text prompt: sent as part of the multimodal array alongside image_url.
REPORT_EXTRACT_USER_PROMPT = "Please extract the structured information from this medical record / health checkup report.\n/no_think"


def encode_image(image_path: str, max_width: int = None) -> str:
    """Read image and base64-encode it; compress proportionally if exceeds max_width.

    Consistent with ocr_tool.encode_image: falls back to direct encoding of the
    original image if PIL is unavailable or processing fails.
    """
    max_width = max_width or cfg.IMAGE_MAX_WIDTH
    try:
        from PIL import Image
        import io

        with Image.open(image_path) as im:
            if im.width > max_width:
                ratio = max_width / float(im.width)
                new_size = (max_width, int(im.height * ratio))
                im = im.convert("RGB").resize(new_size)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=90)
                return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        # Fall back to direct encoding if PIL unavailable or processing fails
        pass
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_model_output(text: str):
    """Extract the first complete JSON object from model output; remove <think> blocks and markdown fences.

    Consistent with ocr_tool.parse_model_output: thinking-chain models may mix
    <think>...</think> into content; strip first, then remove ```json / ```
    fences, then extract the outermost { ... }.
    """
    if not text:
        return None
    import re

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = cleaned.replace("```json", "").replace("```", "")
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def _normalize_patient(patient) -> dict:
    """Normalize patient field: ensure it's a dict with name/gender/age string fields."""
    if not isinstance(patient, dict):
        return {"name": "", "gender": "", "age": ""}
    return {
        "name": str(patient.get("name", "")).strip(),
        "gender": str(patient.get("gender", "")).strip(),
        "age": str(patient.get("age", "")).strip(),
    }


def _normalize_items(items) -> list:
    """Normalize items: ensure list[dict], each with name/value/unit/reference_range/abnormal.

    Consistent with ocr_tool._normalize_items: skip non-dict and items missing
    name; abnormal is forced to bool (default false), other fields forced to string.
    """
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        abnormal_raw = it.get("abnormal", False)
        if isinstance(abnormal_raw, str):
            abnormal = abnormal_raw.strip().lower() in ("true", "1", "yes", "abnormal")
        else:
            abnormal = bool(abnormal_raw)
        out.append({
            "name": name,
            "value": str(it.get("value", "")).strip(),
            "unit": str(it.get("unit", "")).strip(),
            "reference_range": str(it.get("reference_range", it.get("ref_range", ""))).strip(),
            "abnormal": abnormal,
        })
    return out


def _normalize_diagnoses(diagnoses) -> list:
    """Normalize diagnoses: ensure list[str], filter empty strings."""
    if not isinstance(diagnoses, list):
        return []
    out = []
    for d in diagnoses:
        s = str(d).strip() if d is not None else ""
        if s:
            out.append(s)
    return out


def _normalize_report(fields: dict) -> dict:
    """Normalize model JSON output to the standard schema, ensuring stable field types.

    - report_type normalized to "Health Checkup Report" / "Medical Record";
      defaults to "Health Checkup Report" if missing or invalid.
    - patient / items / diagnoses go through their respective normalize functions.
    - exam_date / summary forced to string.
    """
    if not isinstance(fields, dict):
        return {
            "report_type": "Health Checkup Report",
            "patient": {"name": "", "gender": "", "age": ""},
            "exam_date": "",
            "items": [],
            "diagnoses": [],
            "summary": "",
        }

    rt = str(fields.get("report_type", "")).strip()
    if rt not in ("Health Checkup Report", "Medical Record"):
        # Model may return near-synonyms like "Checkup"/"Medical Record Report"/"Health Exam Report"
        if "record" in rt.lower() or "medical" in rt.lower():
            rt = "Medical Record"
        else:
            rt = "Health Checkup Report"

    return {
        "report_type": rt,
        "patient": _normalize_patient(fields.get("patient")),
        "exam_date": str(fields.get("exam_date", fields.get("date", ""))).strip(),
        "items": _normalize_items(fields.get("items", [])),
        "diagnoses": _normalize_diagnoses(fields.get("diagnoses", [])),
        "summary": str(fields.get("summary", "")).strip(),
    }


def _call_model(messages: list) -> dict:
    """POST messages to cfg.MODEL_URL, return standard schema dict or {"error":...}.

    Internally: request -> parse content/reasoning_content -> triple fallback
    JSON extraction -> ``_normalize_report``. Reused by
    ``_extract_from_image_b64`` / ``_extract_from_text`` to avoid duplicating
    request and parsing logic.

    max_tokens uses max(cfg.LLM_MAX_TOKENS, 8192) as floor (medical reports have
    lots of content; thinking-chain reasoning_content consumes heavily, see
    agent.py's floor logic).
    """
    payload = {
        "model": cfg.MODEL_ID,
        "messages": messages,
        "temperature": cfg.LLM_TEMPERATURE,
        "max_tokens": max(cfg.LLM_MAX_TOKENS, 8192),
        "stream": False,
        # Disable Qwen3 thinking chain: structured extraction doesn't need
        # reasoning_content, and avoids thinking chain exhausting max_tokens
        # causing JSON truncation (measured ~50x speedup, see config comments).
        # Follow-up (agent.stream_followup) keeps thinking chain to show reasoning.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        resp = requests.post(
            cfg.MODEL_URL,
            json=payload,
            timeout=cfg.LLM_TIMEOUT,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
    except Exception as e:
        return {"error": f"Model request error: {e}"}

    # Triple fallback: content -> reasoning_content -> concatenation
    fields = parse_model_output(content) or parse_model_output(reasoning) \
        or parse_model_output(content + "\n" + reasoning)
    if not fields:
        tail = (content or reasoning)[-500:]
        return {"error": "Model did not return parseable JSON", "raw": tail}

    return _normalize_report(fields)


def _extract_from_image_b64(b64: str, mime: str = "image/jpeg") -> dict:
    """Single image base64 -> model -> standard schema dict. Returns {"error":...} on failure.

    Args:
        b64   image base64 string (no data: prefix)
        mime  MIME type; defaults to ``image/jpeg`` for images; PDF page renders
              as PNG, pass ``image/png``.

    messages structure: system constrains JSON output + user contains image_url
    (base64) + text instruction. Unlike ocr_tool's single user message, this
    uses system + user segments per spec, helping the model internalize the
    medical schema as a constraint.
    """
    messages = [
        {"role": "system", "content": REPORT_EXTRACT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": REPORT_EXTRACT_USER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        },
    ]
    return _call_model(messages)


def _extract_from_text(text: str) -> dict:
    """Plain text (PDF text layer extraction) -> model -> standard schema dict. Returns {"error":...} on failure.

    Used for text-based PDFs (e.g. system-exported lab reports): after
    ``pdf_loader.extract_pdf_text`` extracts sufficient text, this function
    makes a text-only model call — no visual encoding needed, faster and cheaper.

    user content contains only text (no image_url); system prompt reuses the
    medical schema; a lead-in sentence before the text clarifies that the input
    is PDF-extracted text rather than an image.
    """
    user_text = (
        "The following is text extracted from a PDF. Please identify the structured "
        "information of this medical record / health checkup report based on it:\n\n"
        + text
        + "\n\n/no_think"
    )
    messages = [
        {"role": "system", "content": REPORT_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": user_text}]},
    ]
    return _call_model(messages)


def _merge_page_reports(page_reports: list) -> dict:
    """Merge per-page extraction results from a multi-page PDF into one standard schema dict.

    Merge rules:
    - report_type / exam_date: take the first non-empty page
    - patient: take the first page with a non-empty name as base; fill missing
      gender/age from subsequent pages
    - items: concatenate in page order (preserve all examination item details)
    - diagnoses: concatenate and deduplicate (preserve order)
    - summary: join non-empty page summaries with "; "

    Pages with errors are skipped; if all fail, returns {"error":...}.
    """
    if not page_reports:
        return {"error": "No page results to merge"}

    report_type = ""
    exam_date = ""
    patient = {"name": "", "gender": "", "age": ""}
    items = []
    diagnoses = []
    seen_diag = set()
    summaries = []

    for pr in page_reports:
        if not isinstance(pr, dict) or pr.get("error"):
            continue

        if not report_type:
            report_type = pr.get("report_type", "") or ""
        if not exam_date:
            exam_date = pr.get("exam_date", "") or ""

        # patient: first page with non-empty name sets base; subsequent pages fill gaps
        pr_patient = pr.get("patient", {}) or {}
        if not isinstance(pr_patient, dict):
            pr_patient = {}
        if not patient["name"] and pr_patient.get("name"):
            patient["name"] = str(pr_patient.get("name", "")).strip()
        if not patient["gender"] and pr_patient.get("gender"):
            patient["gender"] = str(pr_patient.get("gender", "")).strip()
        if not patient["age"] and pr_patient.get("age"):
            patient["age"] = str(pr_patient.get("age", "")).strip()

        # items concatenated in page order
        pr_items = pr.get("items", []) or []
        if isinstance(pr_items, list):
            items.extend(pr_items)

        # diagnoses concatenated and deduplicated (preserve order)
        pr_diag = pr.get("diagnoses", []) or []
        if isinstance(pr_diag, list):
            for d in pr_diag:
                s = str(d).strip() if d else ""
                if s and s not in seen_diag:
                    seen_diag.add(s)
                    diagnoses.append(s)

        # summary concatenated
        pr_sum = pr.get("summary", "") or ""
        if pr_sum:
            summaries.append(str(pr_sum).strip())

    return {
        "report_type": report_type or "Health Checkup Report",
        "patient": patient,
        "exam_date": exam_date,
        "items": items,
        "diagnoses": diagnoses,
        "summary": "; ".join(summaries) if summaries else "",
    }


def extract_report(image_path: str) -> dict:
    """Call multimodal model to extract structured medical information from a medical record / health checkup report. Returns standard schema dict.

    Supports both image and PDF inputs, dispatched by file type:
    - **Image** (jpg/jpeg/png/bmp/webp): ``encode_image`` -> base64 ->
      ``_extract_from_image_b64`` (original image processing logic).
    - **PDF**: first ``extract_pdf_text`` to extract text layer;
        sufficient text (>= ``cfg.PDF_TEXT_MIN_CHARS`` after whitespace removal)
        -> ``_extract_from_text`` text-only model call (faster, for system-exported
        text-based lab report PDFs);
        insufficient text (scanned / image PDF) -> ``pdf_to_images_b64`` renders
        pages as PNG -> per-page ``_extract_from_image_b64`` multimodal recognition
        -> ``_merge_page_reports`` merge (aligns with user's "page-by-page reading"
        requirement; single page failure doesn't break the whole report).

    Reuses ocr_tool.extract_invoice call chain: image base64 + prompt POST to
    cfg.MODEL_URL, max_tokens uses max(cfg.LLM_MAX_TOKENS, 8192) floor (medical
    reports have lots of content, thinking chain consumes heavily, see agent.py).

    On failure returns {"error": "..."} without raising, so the pipeline can
    isolate failed reports.
    """
    if not image_path or not os.path.exists(image_path):
        return {"error": f"File not found: {image_path}"}

    # ===== PDF branch: text first, then images if extraction fails =====
    if is_pdf(image_path):
        # 1) Prefer text extraction (text-based PDF, e.g. system-exported lab reports)
        text = extract_pdf_text(image_path)
        if text and len(text.strip()) >= cfg.PDF_TEXT_MIN_CHARS:
            return _extract_from_text(text)

        # 2) Insufficient text (scanned / image PDF) -> convert to images for page-by-page multimodal recognition
        b64_list = pdf_to_images_b64(
            image_path, dpi=cfg.PDF_IMAGE_DPI, max_pages=cfg.PDF_MAX_PAGES
        )
        if not b64_list:
            return {"error": "PDF text extraction and image conversion both failed (PyMuPDF may not be installed or file is corrupted)"}

        # Single page: call directly; multi-page: call per page then merge
        if len(b64_list) == 1:
            return _extract_from_image_b64(b64_list[0], mime="image/png")

        page_reports = []
        for b64 in b64_list:
            r = _extract_from_image_b64(b64, mime="image/png")
            if not r.get("error"):
                page_reports.append(r)
        if not page_reports:
            return {"error": "All PDF pages failed extraction"}
        return _merge_page_reports(page_reports)

    # ===== Image branch (original logic) =====
    try:
        b64 = encode_image(image_path)
    except Exception as e:
        return {"error": f"Image read failed: {e}"}
    return _extract_from_image_b64(b64, mime="image/jpeg")


@tool
def report_extract_tool(image_path: str) -> dict:
    """Extract structured medical information from a medical record / health checkup report image.

    Args: image_path is the local file path of the report image. Returns a JSON object with fields:
    - report_type: "Health Checkup Report" or "Medical Record"
    - patient: {"name", "gender", "age"} patient information
    - exam_date: examination / visit date
    - items: list of examination items, each with name/value/unit/reference_range/abnormal
            (for Medical Record type, items correspond to sections like chief complaint / present illness / tests / medications)
    - diagnoses: list of clinical diagnoses
    - summary: report summary
    Returns {"error": "..."} on extraction failure."""
    return extract_report(image_path)
