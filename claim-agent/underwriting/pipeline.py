# -*- coding: utf-8 -*-
"""
underwriting/pipeline.py — Single Report Underwriting Pipeline (Streaming)

Aligns with spec.md "Underwriting Report Generation": chains report_extract ->
abnormality -> risk -> medical_search in a deterministic order, yielding
progress text per stage, then aggregates into a structured underwriting report
(with recommendation/recommendation_reason) and writes to session memory.

Design (mirrors agent/pipeline.py's process_invoice_stream pattern):
- Streaming generator: yields ``{"status": "🔍 ..."}`` per stage, finally
  yields ``{"done": True, "result": {...}}``;
- Failure isolation: if extract fails, yields failure result and returns;
- Abnormality failure doesn't interrupt: if abnormality returns error, risk
  will also fail, but the pipeline continues to report aggregation with a
  warning annotation;
- recommendation uses ``cfg.RISK_TO_RECOMMENDATION_DEFAULT`` mapping
  (Low -> Standard, Medium -> Substandard - Extra Premium, High -> Decline).

Module entry points:
- ``process_report_stream(image_path, session_id=None)``: streaming generator
- ``process_report(image_path, session_id=None) -> dict``: synchronous wrapper
- ``format_report_text(result) -> str``: plain text summary
- ``format_report_card(result) -> str``: HTML card (risk color block + abnormality/risk tables + references)
"""

import underwriting  # noqa: F401  inject into sys.path
from underwriting import config as cfg
from underwriting.tools.report_extract_tool import extract_report
from underwriting.tools.abnormality_tool import detect_abnormalities
from underwriting.tools.risk_tool import assess_risk
from underwriting.tools.medical_search_tool import search_medical
from underwriting.memory import get_store


# ----------------------------------------------------------------------------
# Risk level -> recommendation mapping (uses config.RISK_TO_RECOMMENDATION_DEFAULT)
# If config mapping value is a list/multi-value, take the first; otherwise use as-is.
# Default fallback: "Standard".
# ----------------------------------------------------------------------------

def _map_recommendation(overall_risk: str) -> str:
    """Map overall risk level to underwriting recommendation.

    Prefers ``cfg.RISK_TO_RECOMMENDATION_DEFAULT``; if mapping value is a list,
    takes the first; falls back to "Standard" (most lenient) if non-string or missing.
    """
    if not overall_risk:
        return cfg.RECOMMENDATION_STANDARD
    mapped = cfg.RISK_TO_RECOMMENDATION_DEFAULT.get(overall_risk)
    if isinstance(mapped, (list, tuple)):
        mapped = mapped[0] if mapped else cfg.RECOMMENDATION_STANDARD
    if isinstance(mapped, str) and mapped.strip():
        return mapped.strip()
    return cfg.RECOMMENDATION_STANDARD


def _build_recommendation_reason(
    overall_risk: str,
    risks: list,
    abnormalities: list,
    search_refs: list,
    search_errors: list,
) -> str:
    """Generate a brief recommendation reason text from overall_risk / risks / abnormalities.

    Examples:
      - "Overall risk is medium, with hypertension and other medium-risk factors, recommend extra premium."
      - "No significant abnormalities, overall risk is low, recommend standard acceptance."
      - "Overall risk is high, with coronary heart disease and other high-risk factors, recommend decline."

    If search references are empty and search_errors is non-empty, appends a
    note about online search being unavailable.
    """
    overall_risk = overall_risk or cfg.RISK_LEVEL_LOW

    # Take the top-risk disease names as representative factors
    risk_priority = {cfg.RISK_LEVEL_HIGH: 3, cfg.RISK_LEVEL_MEDIUM: 2, cfg.RISK_LEVEL_LOW: 1}
    top_risks = sorted(
        [r for r in (risks or []) if isinstance(r, dict)],
        key=lambda r: risk_priority.get(r.get("risk_level", cfg.RISK_LEVEL_LOW), 1),
        reverse=True,
    )
    top_names = [r.get("name", "") for r in top_risks if r.get("name")]
    # Fall back to abnormality names if no risk items
    if not top_names:
        top_names = [a.get("name", "") for a in (abnormalities or [])
                     if isinstance(a, dict) and a.get("name")]
    # Take top 3 to avoid overly long reason
    top_names = [n for n in top_names if n][:3]

    risk_label = {
        cfg.RISK_LEVEL_LOW: "low",
        cfg.RISK_LEVEL_MEDIUM: "medium",
        cfg.RISK_LEVEL_HIGH: "high",
    }.get(overall_risk, overall_risk)

    # Recommendation action description (semantically consistent with recommendation)
    rec = _map_recommendation(overall_risk)
    action_map = {
        cfg.RECOMMENDATION_STANDARD: "recommend standard acceptance",
        cfg.RECOMMENDATION_SUBSTANDARD_EXTRA_PREMIUM: "recommend extra premium",
        cfg.RECOMMENDATION_SUBSTANDARD_EXCLUSION: "recommend exclusion",
        cfg.RECOMMENDATION_POSTPONE: "recommend postponement",
        cfg.RECOMMENDATION_DECLINE: "recommend decline",
    }
    action = action_map.get(rec, f"recommend {rec}")

    if top_names:
        names_text = ", ".join(top_names)
        # Use "etc." to hint there may be other factors
        if len(top_names) < len([r for r in (risks or []) if isinstance(r, dict)]):
            names_text = f"{names_text}, etc."
        reason = f"Overall risk is {risk_label}, with {names_text} as {overall_risk.lower()}-risk factors, {action}."
    else:
        reason = f"No significant abnormalities, overall risk is {risk_label}, {action}."

    # Online search unavailable note
    if not search_refs and search_errors:
        reason += " (Note: online search is currently unavailable, medical evidence is for reference only.)"

    return reason


# ----------------------------------------------------------------------------
# Streaming pipeline
# ----------------------------------------------------------------------------

def process_report_stream(image_path: str, session_id: str = None):
    """Single report underwriting pipeline (streaming generator).

    Fixed order: report_extract -> abnormality -> risk -> medical_search -> aggregate report.
    Yields ``{"status": "🔍 ..."}`` progress text per stage, finally yields
    ``{"done": True, "result": {...}}``.

    Args:
        image_path  local file path of the report image
        session_id  session identifier; if non-empty, writes the final report
                    to session memory for follow-up reuse

    Event sequence:
        {"status": "🔍 Identifying report (multimodal extraction)…"}
        {"status": "✅ ..."}
        ...
        {"done": True, "result": {"ok": True, ...} | {"ok": False, "stage": "...", ...}}
    """
    # ===== Stage 1: Multimodal report extraction =====
    yield {"status": "🔍 Identifying report (multimodal extraction)…"}
    extract = extract_report(image_path)
    if extract.get("error"):
        # Extraction failed: isolate this report, don't continue to subsequent stages
        yield {"done": True, "result": {
            "ok": False,
            "stage": "extract",
            "message": extract["error"],
            "extract": extract,
        }}
        return

    patient = extract.get("patient", {}) or {}
    report_type = extract.get("report_type", "")
    exam_date = extract.get("exam_date", "")
    summary = extract.get("summary", "")
    items = extract.get("items", []) or []
    diagnoses = extract.get("diagnoses", []) or []

    yield {
        "status": f"✅ Report identified: {report_type} | Patient "
                  f"{patient.get('name', '')} {patient.get('gender', '')} "
                  f"Age {patient.get('age', '')} | Exam date {exam_date} | "
                  f"Items {len(items)} | Diagnoses {len(diagnoses)}."
    }

    # ===== Stage 2: Abnormality detection =====
    yield {"status": "🔬 Detecting abnormalities…"}
    abn = detect_abnormalities(extract)
    abnormalities = abn.get("abnormalities", []) or []
    if abn.get("error"):
        # Abnormality failure doesn't interrupt: risks will also fail, but pipeline continues
        yield {"status": f"⚠️ Abnormality detection failed ({abn['error']}), skipping abnormality analysis and continuing."}
    elif abnormalities:
        names = ", ".join([a.get("name", "") for a in abnormalities if a.get("name")][:5])
        yield {"status": f"✅ Detected {len(abnormalities)} abnormalities: {names}"}
    else:
        yield {"status": "✅ No significant abnormalities detected."}

    # ===== Stage 3: Disease risk assessment =====
    yield {"status": "⚠️ Assessing disease risk…"}
    risk = assess_risk(abn, extract)
    risks = risk.get("risks", []) or []
    overall_risk = risk.get("overall_risk", cfg.RISK_LEVEL_LOW)
    if risk.get("error"):
        yield {"status": f"⚠️ Risk assessment failed ({risk['error']}), defaulting to low risk."}
    else:
        high_cnt = sum(1 for r in risks if r.get("risk_level") == cfg.RISK_LEVEL_HIGH)
        med_cnt = sum(1 for r in risks if r.get("risk_level") == cfg.RISK_LEVEL_MEDIUM)
        low_cnt = sum(1 for r in risks if r.get("risk_level") == cfg.RISK_LEVEL_LOW)
        yield {
            "status": f"✅ Risk assessment complete: overall risk \"{overall_risk}\""
                      f" (High {high_cnt} | Medium {med_cnt} | Low {low_cnt})."
        }

    # ===== Stage 4: Medical research online search (dual-backend) =====
    # Extract disease names from abnormalities (deduplicated by name); fall back to diagnoses if empty
    diseases = []
    seen = set()
    for a in abnormalities:
        if isinstance(a, dict):
            n = (a.get("name") or "").strip()
            if n and n not in seen:
                seen.add(n)
                diseases.append(n)
    if not diseases:
        for d in diagnoses:
            s = str(d).strip() if d else ""
            if s and s not in seen:
                seen.add(s)
                diseases.append(s)

    if diseases:
        yield {"status": f"🔎 Searching latest medical research (dual-backend, {len(diseases)} diseases)…"}
    else:
        yield {"status": "🔎 No diseases/abnormalities to search, skipping medical search."}

    search = search_medical(diseases, extract) if diseases else {
        "references": [], "warnings": [], "errors": [],
    }
    references = search.get("references", []) or []
    search_warnings = search.get("warnings", []) or []
    search_errors = search.get("errors", []) or []

    if diseases:
        if references:
            # Source distribution
            src_count = {}
            for r in references:
                s = r.get("source", "unknown")
                src_count[s] = src_count.get(s, 0) + 1
            src_text = ", ".join([f"{k}: {v}" for k, v in src_count.items()])
            extra = ""
            if search_warnings:
                extra += f" | ⚠️ {len(search_warnings)} warnings"
            if search_errors:
                extra += f" | ❌ {len(search_errors)} failures"
            yield {
                "status": f"✅ Medical search complete: found {len(references)} references ({src_text}{extra})."
            }
        else:
            yield {
                "status": "⚠️ Medical search found no references; medical evidence will be based solely on tool-internal judgment."
            }

    # ===== Stage 5: Aggregate report =====
    yield {"status": "📝 Generating underwriting report…"}

    recommendation = _map_recommendation(overall_risk)
    recommendation_reason = _build_recommendation_reason(
        overall_risk=overall_risk,
        risks=risks,
        abnormalities=abnormalities,
        search_refs=references,
        search_errors=search_errors,
    )

    result = {
        "ok": True,
        "image_path": image_path,
        "patient": patient,
        "report_type": report_type,
        "exam_date": exam_date,
        "summary": summary,
        "abnormalities": abnormalities,
        "risks": risks,
        "overall_risk": overall_risk,
        "overall_reasoning": risk.get("overall_reasoning", ""),
        "references": references,
        "search_warnings": search_warnings,
        "search_errors": search_errors,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        # Preserve original extraction result for follow-up reuse (agent.py's stream_followup reads this)
        "extract": extract,
    }

    # Abnormality/risk failure annotations (let frontend/follow-up sense partial degradation)
    if abn.get("error"):
        result["abnormality_error"] = abn["error"]
    if risk.get("error"):
        result["risk_error"] = risk["error"]

    # Write to session memory
    if session_id:
        get_store().set_last_report(session_id, result)

    yield {"done": True, "result": result}


def process_report(image_path: str, session_id: str = None) -> dict:
    """Single report underwriting pipeline synchronous wrapper (consumes process_report_stream's done event).

    Args:
        image_path  local file path of the report image
        session_id  session identifier; if non-empty, writes the final report
                    to session memory for follow-up reuse

    Returns: final report dict (``ok=True`` full structure / ``ok=False`` with stage and message).
    """
    result = {}
    for ev in process_report_stream(image_path, session_id=session_id):
        if ev.get("done"):
            result = ev["result"]
    return result


# ----------------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------------

# Risk color blocks: Low=green / Medium=yellow / High=red (aligns with spec.md and config.RISK_COLOR_MAP)
_RISK_CARD_STYLE = {
    cfg.RISK_LEVEL_LOW: ("✅", "#e6f4ea", "#137333"),       # green
    cfg.RISK_LEVEL_MEDIUM: ("⚠️", "#fef7e0", "#b06000"),    # yellow
    cfg.RISK_LEVEL_HIGH: ("❌", "#fce8e6", "#c5221f"),      # red
}


def _risk_icon_bg_fg(risk_level: str):
    """Return (icon, bg, fg) tuple; unknown level defaults to blue info card."""
    return _RISK_CARD_STYLE.get(risk_level, ("ℹ️", "#e8f0fe", "#1a73e8"))


def _severity_badge(severity_hint: str) -> str:
    """Render abnormality severity_hint as a colored badge HTML."""
    if severity_hint == "Severe":
        return ("<span style='display:inline-block;padding:1px 6px;border-radius:6px;"
                "background:#fce8e6;color:#c5221f;font-size:12px;'>Severe</span>")
    if severity_hint == "Moderate":
        return ("<span style='display:inline-block;padding:1px 6px;border-radius:6px;"
                "background:#fef7e0;color:#b06000;font-size:12px;'>Moderate</span>")
    if severity_hint == "Mild":
        return ("<span style='display:inline-block;padding:1px 6px;border-radius:6px;"
                "background:#e6f4ea;color:#137333;font-size:12px;'>Mild</span>")
    return (f"<span style='display:inline-block;padding:1px 6px;border-radius:6px;"
            f"background:#eee;color:#555;font-size:12px;'>{severity_hint or 'Unknown'}</span>")


def _risk_level_badge(risk_level: str) -> str:
    """Render risk level as a colored badge HTML."""
    icon_bg_fg = {
        cfg.RISK_LEVEL_LOW: ("#e6f4ea", "#137333"),
        cfg.RISK_LEVEL_MEDIUM: ("#fef7e0", "#b06000"),
        cfg.RISK_LEVEL_HIGH: ("#fce8e6", "#c5221f"),
    }
    bg, fg = icon_bg_fg.get(risk_level, ("#eee", "#555"))
    return (f"<span style='display:inline-block;padding:1px 8px;border-radius:6px;"
            f"background:{bg};color:{fg};font-size:12px;font-weight:600;'>"
            f"{risk_level or 'Unknown'}</span>")


def _escape_html(s) -> str:
    """Escape HTML special characters to prevent layout disruption."""
    if s is None:
        return ""
    s = str(s)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def format_report_text(result: dict) -> str:
    """Render the underwriting report as a plain text summary (for CLI / plain text display)."""
    if not result or not result.get("ok"):
        if not result:
            return "Processing failed: no result"
        return f"Processing failed ({result.get('stage', '')}): {result.get('message', '')}"

    lines = []
    patient = result.get("patient", {}) or {}
    lines.append(
        f"Report type: {result.get('report_type', '')} | "
        f"Patient: {patient.get('name', '')} {patient.get('gender', '')} "
        f"Age {patient.get('age', '')} | Exam date: {result.get('exam_date', '')}"
    )
    summary = result.get("summary", "")
    if summary:
        lines.append(f"Report summary: {summary}")
    lines.append("")

    abnormalities = result.get("abnormalities", []) or []
    if abnormalities:
        lines.append(f"Abnormalities ({len(abnormalities)} items):")
        for a in abnormalities:
            lines.append(
                f"  - {a.get('name', '')} | {a.get('type', '')} | "
                f"Severity {a.get('severity_hint', '')} | "
                f"Evidence: {a.get('evidence', '')}"
            )
    else:
        lines.append("Abnormalities: no significant abnormalities")

    lines.append("")
    risks = result.get("risks", []) or []
    if risks:
        lines.append(f"Disease risks ({len(risks)} items):")
        for r in risks:
            factors = ", ".join(r.get("risk_factors", []) or [])
            lines.append(
                f"  - {r.get('name', '')} | Risk level {r.get('risk_level', '')} | "
                f"Risk factors: {factors}"
            )
            reasoning = r.get("reasoning", "")
            if reasoning:
                lines.append(f"      Reasoning: {reasoning}")
    else:
        lines.append("Disease risks: none")

    overall_risk = result.get("overall_risk", "")
    overall_reasoning = result.get("overall_reasoning", "")
    lines.append("")
    lines.append(f"Overall risk level: {overall_risk}")
    if overall_reasoning:
        lines.append(f"Comprehensive assessment: {overall_reasoning}")

    lines.append("")
    lines.append(f"Recommendation: {result.get('recommendation', '')}")
    lines.append(f"Recommendation reason: {result.get('recommendation_reason', '')}")

    references = result.get("references", []) or []
    if references:
        lines.append("")
        lines.append(f"Medical references ({len(references)} items):")
        for i, ref in enumerate(references, 1):
            lines.append(
                f"  {i}. [{ref.get('source', '')}] {ref.get('title', '')}"
                f" ({ref.get('disease', '')})"
            )
            if ref.get("url"):
                lines.append(f"     {ref.get('url')}")

    search_errors = result.get("search_errors", []) or []
    if search_errors:
        lines.append("")
        lines.append(f"({len(search_errors)} online search failures, medical evidence is for reference only)")

    return "\n".join(lines)


def format_report_card(result: dict) -> str:
    """Render the underwriting report as an HTML card (for frontend right-side card display).

    Structure (aligns with spec.md "Report Display"):
      1. Top conclusion card: risk color block + recommendation + patient info
      2. Report summary
      3. Abnormality details table (item/type/severity/evidence)
      4. Risk details table (disease/level/risk factors/reasoning)
      5. Medical references list (title/source/link)
    """
    if not result:
        return ""
    if not result.get("ok"):
        return (f"<div style='padding:12px;border-radius:8px;background:#fce8e6;color:#c5221f;'>"
                f"❌ Processing failed ({result.get('stage', '')}): {result.get('message', '')}</div>")

    patient = result.get("patient", {}) or {}
    overall_risk = result.get("overall_risk", cfg.RISK_LEVEL_LOW)
    recommendation = result.get("recommendation", "")
    recommendation_reason = result.get("recommendation_reason", "")
    icon, bg, fg = _risk_icon_bg_fg(overall_risk)

    # ---- Top conclusion card ----
    header = f"""<div style='padding:14px 16px;border-radius:10px;background:{bg};color:{fg};'>
  <div style='font-size:20px;font-weight:700;'>{icon} Overall Risk: {overall_risk} | Recommendation: {recommendation}</div>
  <div style='margin-top:6px;font-size:13px;color:#444;'>
    Report type {result.get('report_type', '')} | Patient {patient.get('name', '')} {patient.get('gender', '')} Age {patient.get('age', '')} | Exam date {result.get('exam_date', '')}
  </div>
  <div style='margin-top:4px;font-size:13px;color:#444;'>{_escape_html(recommendation_reason)}</div>
</div>
"""

    # ---- Report summary ----
    summary_section = ""
    summary_text = result.get("summary", "")
    if summary_text:
        summary_section = f"""
### 📄 Report Summary

<div style='padding:8px 12px;background:#f7f9fc;border-radius:6px;font-size:13px;color:#333;'>
{_escape_html(summary_text)}
</div>
"""

    # ---- Abnormality details table ----
    abnormalities = result.get("abnormalities", []) or []
    abn_rows = ""
    if abnormalities:
        for a in abnormalities:
            abn_rows += (
                f"<tr><td>{_escape_html(a.get('name', ''))}</td>"
                f"<td style='text-align:center'>{_escape_html(a.get('type', ''))}</td>"
                f"<td style='text-align:center'>{_severity_badge(a.get('severity_hint', ''))}</td>"
                f"<td>{_escape_html(a.get('evidence', ''))}</td></tr>"
            )
        abn_section = f"""
### 🔬 Abnormality Details ({len(abnormalities)} items)

<table style='width:100%;font-size:13px;border-collapse:collapse;'>
<thead><tr style='background:#f0f4f8;'>
<th align='left' style='padding:6px 8px;border:1px solid #e0e0e0;'>Abnormality</th>
<th style='padding:6px 8px;border:1px solid #e0e0e0;'>Type</th>
<th style='padding:6px 8px;border:1px solid #e0e0e0;'>Severity</th>
<th align='left' style='padding:6px 8px;border:1px solid #e0e0e0;'>Evidence</th>
</tr></thead>
<tbody>{abn_rows}</tbody>
</table>
"""
    else:
        abn_section = """
### 🔬 Abnormality Details

<div style='padding:8px 12px;background:#e6f4ea;border-radius:6px;color:#137333;font-size:13px;'>
✅ No significant abnormalities
</div>
"""

    # ---- Risk details table ----
    risks = result.get("risks", []) or []
    risk_rows = ""
    if risks:
        for r in risks:
            factors = ", ".join(r.get("risk_factors", []) or [])
            risk_rows += (
                f"<tr><td>{_escape_html(r.get('name', ''))}</td>"
                f"<td style='text-align:center'>{_risk_level_badge(r.get('risk_level', ''))}</td>"
                f"<td>{_escape_html(factors)}</td>"
                f"<td>{_escape_html(r.get('reasoning', ''))}</td></tr>"
            )
        risk_section = f"""
### ⚠️ Risk Details ({len(risks)} items)

<table style='width:100%;font-size:13px;border-collapse:collapse;'>
<thead><tr style='background:#f0f4f8;'>
<th align='left' style='padding:6px 8px;border:1px solid #e0e0e0;'>Disease/Abnormality</th>
<th style='padding:6px 8px;border:1px solid #e0e0e0;'>Risk Level</th>
<th align='left' style='padding:6px 8px;border:1px solid #e0e0e0;'>Risk Factors</th>
<th align='left' style='padding:6px 8px;border:1px solid #e0e0e0;'>Underwriting Reasoning</th>
</tr></thead>
<tbody>{risk_rows}</tbody>
</table>
"""
    else:
        risk_section = """
### ⚠️ Risk Details

<div style='padding:8px 12px;background:#e6f4ea;border-radius:6px;color:#137333;font-size:13px;'>
No independent risk items
</div>
"""

    # ---- Medical references list ----
    references = result.get("references", []) or []
    search_errors = result.get("search_errors", []) or []
    if references:
        ref_items = ""
        for i, ref in enumerate(references, 1):
            title = _escape_html(ref.get("title", "")) or "(no title)"
            url = ref.get("url", "")
            disease = _escape_html(ref.get("disease", ""))
            source = _escape_html(ref.get("source", ""))
            snippet = _escape_html(ref.get("snippet", ""))
            url_html = (f"<a href='{_escape_html(url)}' target='_blank' "
                        f"style='color:#1a73e8;text-decoration:none;'>"
                        f"{_escape_html(url)}</a>") if url else "<span style='color:#999;'>(no link)</span>"
            ref_items += (
                f"<li style='margin-bottom:8px;font-size:13px;'>"
                f"<div><strong>{i}. {title}</strong>"
                f" <span style='color:#888;font-size:12px;'>[{source}]</span>"
                f" <span style='color:#888;font-size:12px;'>Disease: {disease}</span></div>"
                f"<div style='color:#666;font-size:12px;word-break:break-all;'>{url_html}</div>"
                + (f"<div style='color:#555;font-size:12px;margin-top:2px;'>{snippet}</div>"
                   if snippet else "")
                + "</li>"
            )
        ref_section = f"""
### 📚 Medical References ({len(references)} items)

<ul style='padding-left:18px;list-style:disc;'>{ref_items}</ul>
"""
    elif search_errors:
        ref_section = """
### 📚 Medical References

<div style='padding:8px 12px;background:#fef7e0;border-radius:6px;color:#b06000;font-size:13px;'>
⚠️ Online search is currently unavailable, medical evidence is for reference only
</div>
"""
    else:
        ref_section = """
### 📚 Medical References

<div style='padding:8px 12px;background:#f7f9fc;border-radius:6px;color:#666;font-size:13px;'>
No medical references
</div>
"""

    return header + summary_section + abn_section + risk_section + ref_section
