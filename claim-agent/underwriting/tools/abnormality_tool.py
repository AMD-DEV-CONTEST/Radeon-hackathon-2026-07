# -*- coding: utf-8 -*-
"""
underwriting/tools/abnormality_tool.py — Abnormality Detection Tool (Task 3)

Based on the structured extraction results from report_extract_tool, identifies
abnormal findings:
- Lab Abnormalities (comparing items.value with reference_range, or abnormal=true)
- Abnormal Diagnoses (clinical diagnoses in diagnoses that are not "no abnormality")
- Dangerous Symptoms (chest pain, syncope, hemoptysis, etc. described in summary / items)

Implementation: LLM-assisted detection (medical judgment requires semantic
understanding), reuses ocr_tool's requests POST + JSON fault-tolerant parsing
pattern (strip ```json fences, extract from first { to last }, json.loads).

Calls underwriting.config.MODEL_URL (OpenAI-compatible endpoint). The model is
a thinking-chain model; final JSON is in content, thinking process is in
reasoning_content; parsing uses content first, reasoning_content as fallback
(consistent with ocr_tool).

Core function detect_abnormalities can be unit-tested independently;
abnormality_tool is the LangChain @tool wrapper.

Output JSON schema (risk_tool depends on this structure, strictly followed):
{
  "abnormalities": [
    {"name":"", "type":"Lab Abnormality"|"Diagnosis"|"Symptom", "severity_hint":"Mild"|"Moderate"|"Severe", "evidence":"", "detail":""}
  ],
  "note": ""
}
"""

import json
import re

import requests
import urllib3
from langchain_core.tools import tool

import underwriting  # noqa: F401  注入 sys.path（确保 import config 可用）
from underwriting.config import (
    MODEL_ID,
    MODEL_URL,
    MODEL_API_KEY,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ----------------------------------------------------------------------------
# 枚举（对齐 spec.md「异常点识别」与 risk_tool 依赖结构）
# ----------------------------------------------------------------------------
ABNORMALITY_TYPE_LAB = "Lab Abnormality"
ABNORMALITY_TYPE_DIAGNOSIS = "Diagnosis"
ABNORMALITY_TYPE_SYMPTOM = "Symptom"
ABNORMALITY_TYPES = (ABNORMALITY_TYPE_LAB, ABNORMALITY_TYPE_DIAGNOSIS, ABNORMALITY_TYPE_SYMPTOM)

SEVERITY_LIGHT = "Mild"
SEVERITY_MEDIUM = "Moderate"
SEVERITY_HEAVY = "Severe"
SEVERITIES = (SEVERITY_LIGHT, SEVERITY_MEDIUM, SEVERITY_HEAVY)


SYSTEM_PROMPT = """You are a medical underwriting abnormality detection assistant. Based on the provided examination items (with reference ranges) and diagnoses, identify abnormalities.

IMPORTANT: ALL output fields (name, evidence, detail, note) MUST be in English. Translate any Chinese medical terms, disease names, and descriptions to English.

Detection rules:
1. Lab Abnormality: examination item value exceeds the reference_range, or abnormal=true;
2. Diagnosis: clinical diagnoses in the diagnoses list that are not "no abnormality" (e.g. hypertension, diabetes, coronary heart disease);
3. Symptom: dangerous symptoms described in summary or items (e.g. chest pain, syncope, hemoptysis, dyspnea).

For each abnormality, provide:
- name: the abnormality item name or disease name (in English)
- type: "Lab Abnormality" / "Diagnosis" / "Symptom"
- severity_hint: "Mild" / "Moderate" / "Severe" (based on deviation degree and clinical experience)
- evidence: original report value or description (in English, e.g. "Blood pressure 160/100 mmHg, reference range <140/90")
- detail: brief explanation in English (why it is abnormal, possible clinical significance)

If no significant abnormalities, return an empty abnormalities list and note="No significant abnormalities".
Return ONLY JSON (no extra text, no explanation, no markdown code blocks):
{
  "abnormalities": [
    {"name": "", "type": "Lab Abnormality", "severity_hint": "Moderate", "evidence": "", "detail": ""}
  ],
  "note": ""
}
/no_think"""


def _build_user_prompt(extract: dict) -> str:
    """Compress extract's items/diagnoses/summary into LLM context text.

    All field access is defensive; missing fields don't crash.
    """
    lines = []
    lines.append(f"Report type: {extract.get('report_type', '')}")

    patient = extract.get("patient", {}) or {}
    if isinstance(patient, dict):
        lines.append(
            f"Patient: {patient.get('name', '')} {patient.get('gender', '')} "
            f"Age {patient.get('age', '')}"
        )
    lines.append(f"Exam date: {extract.get('exam_date', '')}")

    items = extract.get("items", []) or []
    if items:
        lines.append("Examination items:")
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("name", "")
            value = it.get("value", "")
            unit = it.get("unit", "")
            ref = it.get("reference_range", "")
            abnormal = it.get("abnormal", False)
            flag = " [ABNORMAL]" if abnormal else ""
            lines.append(
                f"  - {name}: {value}{unit} (ref range: {ref}){flag}"
            )
    else:
        lines.append("Examination items: none")

    diagnoses = extract.get("diagnoses", []) or []
    if diagnoses:
        lines.append("Diagnoses:")
        for d in diagnoses:
            lines.append(f"  - {d}")
    else:
        lines.append("Diagnoses: none")

    summary = extract.get("summary", "")
    if summary:
        lines.append(f"Report summary: {summary}")

    lines.append("")
    lines.append("Please identify abnormalities in the above content. Return ONLY JSON.")
    return "\n".join(lines)


def _parse_json(text: str):
    """Extract the first complete JSON object from model output; remove <think> blocks and markdown fences.

    Reuses ocr_tool.parse_model_output pattern.
    """
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = cleaned.replace("```json", "").replace("```", "")
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def _normalize_abnormalities(abnormalities):
    """Normalize abnormalities: ensure list[dict], each with all 5 fields and valid enum values.

    Ensures risk_tool receives a stable structure, unaffected by LLM output jitter.
    """
    if not isinstance(abnormalities, list):
        return []
    out = []
    for it in abnormalities:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        atype = str(it.get("type", "")).strip()
        if atype not in ABNORMALITY_TYPES:
            atype = ABNORMALITY_TYPE_LAB
        sev = str(it.get("severity_hint", "")).strip()
        if sev not in SEVERITIES:
            sev = SEVERITY_LIGHT
        out.append({
            "name": name,
            "type": atype,
            "severity_hint": sev,
            "evidence": str(it.get("evidence", "")).strip(),
            "detail": str(it.get("detail", "")).strip(),
        })
    return out


def detect_abnormalities(extract: dict) -> dict:
    """Identify abnormalities from the report extraction results.

    Args: extract is the output of report_extract_tool, structured as:
        {
          "report_type": "Health Checkup Report" | "Medical Record",
          "patient": {"name","gender","age"},
          "exam_date": "",
          "items": [{"name","value","unit","reference_range","abnormal"}],
          "diagnoses": [""],
          "summary": ""
        }

    Returns dict: {"abnormalities": [...], "note": ""}.
    - If extract contains an error field, returns {"abnormalities":[], "note":"Extraction failed, cannot detect abnormalities", "error": extract["error"]};
    - If LLM call fails, returns {"abnormalities":[], "note":"Abnormality detection failed", "error":"..."};
    - If no abnormalities, abnormalities is an empty list, note="No significant abnormalities".
    """
    # 1. 入参防御
    if not isinstance(extract, dict):
        return {
            "abnormalities": [],
            "note": "Abnormality detection failed",
            "error": "extract is invalid (not a dict)",
        }

    # 2. extract contains error: return directly, don't call LLM
    if extract.get("error"):
        return {
            "abnormalities": [],
            "note": "Extraction failed, cannot detect abnormalities",
            "error": extract["error"],
        }

    # 3. 构造 prompt 并调用 LLM（与 ocr_tool 同款 requests POST + verify=False）
    user_prompt = _build_user_prompt(extract)
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        # 思维链模型留足输出空间，避免 JSON 被截断（与 ocr_tool 一致用 max() 保底）
        "max_tokens": max(LLM_MAX_TOKENS, 8192),
        "stream": False,
        # 禁用 Qwen3 思维链：异常识别只需结构化 JSON 输出，禁用后 max_tokens 全给
        # JSON（防截断），且大幅提速（17 页报告异常项多时尤其明显）。
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MODEL_API_KEY}",
    }

    try:
        resp = requests.post(
            MODEL_URL, json=payload, headers=headers,
            timeout=LLM_TIMEOUT, verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
    except Exception as e:
        return {
            "abnormalities": [],
            "note": "Abnormality detection failed",
            "error": f"LLM request error: {e}",
        }

    # 4. Triple fallback JSON parsing: content -> reasoning_content -> concatenation
    parsed = (
        _parse_json(content)
        or _parse_json(reasoning)
        or _parse_json(content + "\n" + reasoning)
    )
    if not parsed:
        tail = (content or reasoning)[-500:]
        return {
            "abnormalities": [],
            "note": "Abnormality detection failed",
            "error": "Model did not return parseable JSON",
            "raw": tail,
        }

    # 5. Normalize output (ensure risk_tool gets stable structure)
    abnormalities = _normalize_abnormalities(parsed.get("abnormalities", []))
    note = str(parsed.get("note", "")).strip()
    if not abnormalities and not note:
        note = "No significant abnormalities"

    return {"abnormalities": abnormalities, "note": note}


@tool
def abnormality_tool(extract: dict) -> dict:
    """Identify abnormalities (Lab Abnormality / Diagnosis / Symptom) from medical record / health checkup report extraction results.

    Args: extract is the output of report_extract_tool (contains report_type/patient/items/diagnoses/summary).
    Returns dict: {"abnormalities": [{"name","type"(Lab Abnormality/Diagnosis/Symptom),
    "severity_hint"(Mild/Moderate/Severe),"evidence","detail"}], "note"}.

    If no abnormalities, abnormalities is an empty list, note="No significant abnormalities";
    if extract contains an error or LLM call fails, returns the corresponding error
    branch without raising an exception.
    """
    return detect_abnormalities(extract)
