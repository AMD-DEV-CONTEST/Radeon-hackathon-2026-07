# -*- coding: utf-8 -*-
"""
underwriting/tools/risk_tool.py — Disease Risk Assessment Tool

Aligns with spec.md "Disease Risk Assessment": based on the abnormality list
output by abnormality_tool, combined with abnormality type, severity_hint,
degree of deviation from reference ranges, and potential comorbidities,
estimates the underwriting risk level (Low/Medium/High) for each
abnormality/disease, and aggregates the overall risk level.

Implementation: LLM-assisted judgment + structured output + strict validation fallback.
- Calls cfg.MODEL_URL (OpenAI-compatible endpoint, consistent with ocr_tool);
- Risk levels are strictly limited to Low/Medium/High; invalid LLM values
  default to "Medium";
- overall_risk prefers valid LLM values; otherwise falls back to the highest
  level among individual risks (High > Medium > Low).

Core function assess_risk(abnormality_result, extract=None) can be unit-tested
independently; risk_tool is the LangChain @tool wrapper.

Input contract (abnormality_tool output):
    abnormality_result = {
        "abnormalities": [
            {"name":"", "type":"Lab Abnormality"|"Diagnosis"|"Symptom",
             "severity_hint":"Mild"|"Moderate"|"Severe", "evidence":"", "detail":""}
        ],
        "note": ""
    }

Output JSON schema (pipeline depends on this structure):
    {
        "risks": [
            {"name":"", "risk_level":"Low"|"Medium"|"High",
             "risk_factors":[""], "evidence":"", "reasoning":""}
        ],
        "overall_risk": "Low"|"Medium"|"High",
        "overall_reasoning": ""
    }
"""

import json

import requests
import urllib3
from langchain_core.tools import tool

import tools  # noqa: F401  inject into sys.path
import config as cfg
from underwriting.config import (
    MODEL_URL,
    MODEL_ID,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT,
    RISK_LEVELS,
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_HIGH,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ----------------------------------------------------------------------------
# Risk level ranking and validation utilities
# ----------------------------------------------------------------------------

# Risk level severity ranking: High > Medium > Low (used for overall_risk fallback).
_RISK_RANK = {
    RISK_LEVEL_LOW: 1,
    RISK_LEVEL_MEDIUM: 2,
    RISK_LEVEL_HIGH: 3,
}

# Valid risk level set (for quick validation).
_VALID_RISK_LEVELS = set(RISK_LEVELS)

# Abnormality type enums (for prompt hints only, not enforced).
_VALID_ABNORMALITY_TYPES = ("Lab Abnormality", "Diagnosis", "Symptom")

# Abnormality severity_hint enums (for prompt hints only, not enforced)
_VALID_SEVERITY_HINTS = ("Mild", "Moderate", "Severe")


def _normalize_risk_level(v) -> str:
    """Validate risk level: return valid values as-is, default to "Medium" for invalid."""
    if isinstance(v, str):
        v = v.strip()
        if v in _VALID_RISK_LEVELS:
            return v
    return RISK_LEVEL_MEDIUM


def _max_risk_level(levels) -> str:
    """Return the highest risk level from the list (High > Medium > Low); empty list returns "Low"."""
    if not levels:
        return RISK_LEVEL_LOW
    best = RISK_LEVEL_LOW
    best_rank = _RISK_RANK[RISK_LEVEL_LOW]
    for lv in levels:
        lv_norm = _normalize_risk_level(lv)
        if _RISK_RANK[lv_norm] > best_rank:
            best = lv_norm
            best_rank = _RISK_RANK[lv_norm]
    return best


# ----------------------------------------------------------------------------
# JSON parsing with fault tolerance (reuses ocr_tool's parse_model_output approach)
# ----------------------------------------------------------------------------

def _parse_model_output(text: str):
    """Extract the first complete JSON object from model output; remove <think> blocks and markdown fences."""
    if not text:
        return None
    import re
    # Remove content wrapped in thinking-chain tags (thinking-chain models may mix <think>...</think> into content)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = cleaned.replace("```json", "").replace("```", "")
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


# ----------------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------------

RISK_SYSTEM_PROMPT = (
    "You are an insurance underwriting medical risk assessment assistant. "
    "Evaluate the underwriting risk level for each abnormality/disease based on the abnormality list.\n"
    "IMPORTANT: ALL output fields (risk_factors, evidence, reasoning, overall_reasoning) MUST be in English. "
    "Translate any Chinese medical terms to English.\n"
    "Requirements:\n"
    "1. Risk levels must be one of \"Low\", \"Medium\", \"High\" — no other values allowed;\n"
    "2. Consider the abnormality type (Lab Abnormality/Diagnosis/Symptom), severity_hint "
    "(Mild/Moderate/Severe), the degree of deviation from reference ranges, and potential "
    "comorbidities;\n"
    "3. For each abnormality, provide risk_factors (a list of risk factors in English, at least 1) and "
    "reasoning (underwriting medical reasoning in English, concise);\n"
    "4. Provide an overall_risk (Low/Medium/High) and overall_reasoning (comprehensive assessment in English);\n"
    "5. Return ONLY JSON — no extra text, no explanation, no markdown code blocks."
)


def _build_user_prompt(abnormality_result: dict, extract: dict) -> str:
    """Build user prompt: abnormalities list + extract summary."""
    abnormalities = abnormality_result.get("abnormalities") or []
    note = abnormality_result.get("note") or ""

    # Serialize abnormalities (preserve name/type/severity_hint/evidence/detail)
    abs_lines = []
    for i, ab in enumerate(abnormalities, 1):
        if not isinstance(ab, dict):
            continue
        abs_lines.append(
            f"{i}. name: {ab.get('name', '')}"
            f" | type: {ab.get('type', '')}"
            f" | severity_hint: {ab.get('severity_hint', '')}"
            f" | evidence: {ab.get('evidence', '')}"
            f" | detail: {ab.get('detail', '')}"
        )
    abs_block = "\n".join(abs_lines) if abs_lines else "(none)"

    # Extract summary: only key patient info to avoid overly long prompts
    extract_summary = "(none)"
    if isinstance(extract, dict) and extract:
        patient = extract.get("patient") or {}
        if isinstance(patient, dict):
            patient_str = (
                f"name={patient.get('name','')}, gender={patient.get('gender','')}, "
                f"age={patient.get('age','')}"
            )
        else:
            patient_str = str(patient)
        extract_summary = (
            f"report_type={extract.get('report_type','')}, "
            f"exam_date={extract.get('exam_date','')}, "
            f"patient=[{patient_str}], "
            f"summary={extract.get('summary','')}"
        )

    note_block = f"\nAbnormality note: {note}" if note else ""

    prompt = (
        f"The following is the abnormality list from the abnormality detection stage ({len(abnormalities)} items):\n"
        f"```\n{abs_block}\n```\n"
        f"\nReport context summary: {extract_summary}"
        f"{note_block}\n"
        f"\nPlease assess the underwriting risk level for each abnormality and return "
        f"the following JSON schema (risks count must match abnormalities one-to-one; "
        f"do not omit fields):\n"
        f"{{\n"
        f"  \"risks\": [\n"
        f"    {{\"name\":\"\", \"risk_level\":\"Low\"|\"Medium\"|\"High\", "
        f"\"risk_factors\":[\"\"], \"evidence\":\"\", \"reasoning\":\"\"}}\n"
        f"  ],\n"
        f"  \"overall_risk\": \"Low\"|\"Medium\"|\"High\",\n"
        f"  \"overall_reasoning\": \"\"\n"
        f"}}\n"
        f"/no_think"
    )
    return prompt


# ----------------------------------------------------------------------------
# LLM call
# ----------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str) -> dict:
    """Call OpenAI-compatible endpoint; return parsed dict, or None on failure."""
    payload = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "max_tokens": max(LLM_MAX_TOKENS, 8192),  # With thinking disabled, 8192 is ample for JSON
        "stream": False,
        # Disable Qwen3 thinking chain: risk assessment only needs structured JSON output.
        # Disabling ensures max_tokens is fully available for JSON (prevents truncation)
        # and significantly speeds up processing.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        resp = requests.post(MODEL_URL, json=payload, timeout=LLM_TIMEOUT, verify=False)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
    except Exception:
        return None

    # Triple fallback: content -> reasoning_content -> concatenation
    return _parse_model_output(content) or _parse_model_output(reasoning) \
        or _parse_model_output(content + "\n" + reasoning)


# ----------------------------------------------------------------------------
# Output normalization
# ----------------------------------------------------------------------------

def _normalize_risks(raw_risks, abnormalities) -> list:
    """Normalize risks list: validate each field, default invalid risk_level to "Medium".

    If LLM returns a different count than abnormalities, align to abnormalities
    (pad/truncate) to ensure risks match abnormalities one-to-one (pipeline
    depends on this correspondence).
    """
    if not isinstance(raw_risks, list):
        raw_risks = []

    norm_risks = []
    n = len(abnormalities)
    for i in range(n):
        ab = abnormalities[i] if i < len(abnormalities) else {}
        ab_name = ab.get("name", "") if isinstance(ab, dict) else ""

        if i < len(raw_risks) and isinstance(raw_risks[i], dict):
            r = raw_risks[i]
            name = str(r.get("name", "") or "").strip() or ab_name
            risk_level = _normalize_risk_level(r.get("risk_level"))
            risk_factors = r.get("risk_factors")
            if not isinstance(risk_factors, list):
                risk_factors = []
            risk_factors = [
                str(f).strip() for f in risk_factors
                if isinstance(f, (str, int, float)) and str(f).strip()
            ]
            if not risk_factors:
                risk_factors = [f"Risk factors related to {name}"] if name else ["Unspecified risk factors"]
            evidence = str(r.get("evidence", "") or ab.get("evidence", "") or "")
            reasoning = str(r.get("reasoning", "") or "")
            norm_risks.append({
                "name": name,
                "risk_level": risk_level,
                "risk_factors": risk_factors,
                "evidence": evidence,
                "reasoning": reasoning,
            })
        else:
            # LLM missing this item: construct fallback from abnormality info
            risk_level = RISK_LEVEL_MEDIUM
            severity_hint = ab.get("severity_hint", "") if isinstance(ab, dict) else ""
            # Simple severity_hint to risk_level mapping fallback
            if severity_hint == "Severe":
                risk_level = RISK_LEVEL_HIGH
            elif severity_hint == "Mild":
                risk_level = RISK_LEVEL_LOW
            norm_risks.append({
                "name": ab_name,
                "risk_level": risk_level,
                "risk_factors": [f"Risk factors related to {ab_name}"] if ab_name else ["Unspecified risk factors"],
                "evidence": ab.get("evidence", "") if isinstance(ab, dict) else "",
                "reasoning": f"LLM did not return risk assessment for this item; defaulted to {risk_level} based on severity hint ({severity_hint}).",
            })
    return norm_risks


# ----------------------------------------------------------------------------
# Core function
# ----------------------------------------------------------------------------

def assess_risk(abnormality_result: dict, extract: dict = None) -> dict:
    """Assess underwriting risk level based on the abnormality list.

    Args:
        abnormality_result: output dict from abnormality_tool, containing abnormalities list
            (each with name/type/severity_hint/evidence/detail) and optional note;
            if it contains an "error" field, returns an error response directly.
        extract: optional, output dict from report_extract_tool, used as patient context
            (patient/report_type/exam_date/summary, etc.).

    Returns:
        dict with fixed structure:
        {
            "risks": [{"name","risk_level","risk_factors","evidence","reasoning"}],
            "overall_risk": "Low"|"Medium"|"High",
            "overall_reasoning": ""
        }
        On failure, an "error" field is appended.
    """
    # ---- Defense: invalid abnormality_result ----
    if not isinstance(abnormality_result, dict):
        return {
            "risks": [],
            "overall_risk": RISK_LEVEL_MEDIUM,
            "overall_reasoning": "Risk assessment failed",
            "error": f"abnormality_result has invalid type: {type(abnormality_result).__name__}",
        }

    # ---- Abnormality detection failed: abnormality_result contains error ----
    if abnormality_result.get("error"):
        return {
            "risks": [],
            "overall_risk": RISK_LEVEL_LOW,
            "overall_reasoning": "Abnormality detection failed, unable to assess",
            "error": abnormality_result["error"],
        }

    abnormalities = abnormality_result.get("abnormalities")
    if not isinstance(abnormalities, list):
        abnormalities = []

    # ---- No abnormalities: return low risk directly ----
    if not abnormalities:
        return {
            "risks": [],
            "overall_risk": RISK_LEVEL_LOW,
            "overall_reasoning": "No significant abnormalities detected, overall risk is low",
        }

    # ---- Call LLM for assessment ----
    user_prompt = _build_user_prompt(abnormality_result, extract)
    parsed = _call_llm(RISK_SYSTEM_PROMPT, user_prompt)

    if not parsed:
        # LLM failure: return medium risk + error (per spec)
        return {
            "risks": [],
            "overall_risk": RISK_LEVEL_MEDIUM,
            "overall_reasoning": "Risk assessment failed",
            "error": "LLM call failed or returned unparseable JSON",
        }

    # ---- Normalize risks ----
    raw_risks = parsed.get("risks")
    risks = _normalize_risks(raw_risks, abnormalities)

    # ---- overall_risk: prefer valid LLM value, otherwise fallback to highest among risks ----
    llm_overall = parsed.get("overall_risk")
    overall_risk = _normalize_risk_level(llm_overall)
    # If LLM's overall_risk is invalid (defaulted to "Medium"), recalculate from highest risk
    if not (isinstance(llm_overall, str) and llm_overall.strip() in _VALID_RISK_LEVELS):
        overall_risk = _max_risk_level([r["risk_level"] for r in risks])

    # ---- overall_reasoning ----
    overall_reasoning = parsed.get("overall_reasoning")
    if not isinstance(overall_reasoning, str) or not overall_reasoning.strip():
        # Fallback: generate brief reasoning based on risks and overall_risk
        risk_levels = [r["risk_level"] for r in risks]
        overall_reasoning = (
            f"Assessed {len(risks)} abnormalities, risk level distribution: "
            f"High={risk_levels.count(RISK_LEVEL_HIGH)}, "
            f"Medium={risk_levels.count(RISK_LEVEL_MEDIUM)}, "
            f"Low={risk_levels.count(RISK_LEVEL_LOW)}, overall risk {overall_risk}."
        )

    return {
        "risks": risks,
        "overall_risk": overall_risk,
        "overall_reasoning": overall_reasoning.strip(),
    }


# ----------------------------------------------------------------------------
# LangChain @tool wrapper (optional, for direct Agent invocation)
# ----------------------------------------------------------------------------

@tool
def risk_tool(abnormality_result: dict, extract: dict = None) -> dict:
    """Disease risk assessment tool: estimates underwriting risk level based on the abnormality list."""
    return assess_risk(abnormality_result, extract)
