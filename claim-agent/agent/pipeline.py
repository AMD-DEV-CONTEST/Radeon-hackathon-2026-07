# -*- coding: utf-8 -*-
"""
agent/pipeline.py — Deterministic End-to-End Claim Pipeline

Follows the fixed order from the design document, with the entire amount chain
running through deterministic code (not LLM free-form), ensuring auditability:

  invoice_ocr -> invoice_verify -> (per-item) drug_catalog_rag -> claim_decision

Complements the LLM-driven Agent in agent.py: this pipeline serves as the reliable
backbone (frontend main review action uses it), while the Agent handles
multi-turn conversation and follow-up explanations.
"""

import agent  # noqa: F401  inject into sys.path
from tools.ocr_tool import extract_invoice
from tools.verify_tool import verify_invoice_core
from tools.rag_tool import query_catalog
from tools.decision_tool import decide_claim_core
from agent.memory import get_store


def _enrich_item(item: dict) -> dict:
    """Use RAG search results to populate a single drug item's catalog info (category/ratio/self-pay/cap, etc.).

    Key point: only adopt catalog info when the matched item is genuinely in the
    catalog (in_catalog=True, i.e. similarity above threshold) or is a commercial
    innovative drug; otherwise treat as out-of-catalog, to avoid incorrectly
    applying low-score semantic neighbor categories/ratios to unrelated products.
    """
    out = dict(item)
    res = query_catalog(item.get("name", ""))
    matches = res.get("matches", [])
    m = matches[0] if matches else None
    if m and (m.get("in_catalog") or m.get("commercial_innovative")):
        out.update({
            "matched_name": m.get("matched_name", ""),
            "category": m.get("category", ""),
            "in_catalog": bool(m.get("in_catalog", False)),
            "commercial_innovative": bool(m.get("commercial_innovative", False)),
            "self_pay_2": m.get("self_pay_2", 0.0),
            "reimburse_ratio": m.get("reimburse_ratio", 0.0),
            "cap": m.get("cap", None),
            "rag_score": m.get("score", 0.0),
        })
    else:
        out.update({
            "matched_name": "", "category": "Out of Catalog", "in_catalog": False,
            "commercial_innovative": False, "self_pay_2": 0.0,
            "reimburse_ratio": 0.0, "cap": None,
            "rag_score": m.get("score", 0.0) if m else 0.0,
        })
    return out


def process_invoice_stream(image_path: str, do_verify: bool = True, session_id: str = None):
    """End-to-end processing of a single invoice (streaming): yields progress per stage, finally yields the full result.

    Output format:
      {"status": "..."}                 stage progress text (for frontend real-time display)
      {"done": True, "result": {...}}   final structured claim result

    Fixed stage order: OCR extraction -> authenticity verification -> per-item catalog search -> deterministic decision.
    """
    # 1) Multimodal extraction
    yield {"status": "🔍 Identifying invoice (multimodal extraction of fields and drug details)…"}
    extract = extract_invoice(image_path)
    if extract.get("error"):
        yield {"done": True, "result": {
            "ok": False, "stage": "ocr", "message": extract["error"], "extract": extract}}
        return

    items = extract.get("items", []) or []
    yield {"status": f"✅ Identification complete: Invoice No. {extract.get('fphm', '')}, total amount "
                     f"{extract.get('code', '')}, drug details {len(items)} items."}

    # 2) Official authenticity verification
    if do_verify:
        yield {"status": "🛡️ Verifying invoice authenticity (official verification API)…"}
        verify = verify_invoice_core(
            extract.get("fpdm", ""), extract.get("fphm", ""),
            extract.get("date", ""), extract.get("code", ""),
        )
    else:
        verify = {"verified": True, "code": "0", "message": "Verification skipped (demo mode)",
                  "official": {}, "field_match": {}}
    verified = bool(verify.get("verified", False))
    yield {"status": ("✅ Authenticity verification passed" if verified else "❌ Authenticity verification failed")
                     + f" ({verify.get('message', '')})"}

    # 3) Per-item RAG catalog info enrichment
    enriched = []
    for it in items:
        yield {"status": f"📚 Searching drug reimbursement catalog: {it.get('name', '')}…"}
        enriched.append(_enrich_item(it))

    # 4) Deterministic claim decision (internally rejects if verification failed)
    yield {"status": "🧮 Calculating reimbursable amounts per claim rules…"}
    decision = decide_claim_core(verified, enriched)

    result = {
        "ok": True,
        "image_path": image_path,
        "extract": extract,
        "verify": verify,
        "decision": decision,
    }

    if session_id:
        get_store().set_last_claim(session_id, result)

    yield {"done": True, "result": result}


def process_invoice(image_path: str, do_verify: bool = True, session_id: str = None) -> dict:
    """End-to-end processing of a single invoice, returns structured claim result (sync wrapper for process_invoice_stream).

    Args:
      image_path  local file path of the invoice image
      do_verify   whether to call the official verification API (False means passed, for demo RAG+decision chain only)
      session_id  session identifier; if non-empty, writes result to session memory for follow-up reuse
    """
    result = {}
    for ev in process_invoice_stream(image_path, do_verify=do_verify, session_id=session_id):
        if ev.get("done"):
            result = ev["result"]
    return result


def format_result_text(result: dict) -> str:
    """Render the pipeline result as a summary text (for frontend/CLI display)."""
    if not result.get("ok"):
        return f"Processing failed ({result.get('stage')}): {result.get('message')}"

    extract = result["extract"]
    verify = result["verify"]
    decision = result["decision"]

    lines = []
    v_flag = "✅ Passed" if verify.get("verified") else "❌ Failed"
    lines.append(f"Invoice authenticity: {v_flag} ({verify.get('message', '')})")
    lines.append(
        f"Invoice No. {extract.get('fphm', '')} | Invoice date {extract.get('date', '')} | "
        f"Total amount {extract.get('code', '')}"
    )
    lines.append("")
    lines.append(decision.get("summary_text", ""))
    lines.append("")
    lines.append("Per-item details:")
    for it in decision.get("items", []):
        med = it.get("medical_reimbursable", 0.0)
        com = it.get("commercial_reimbursable", 0.0)
        lines.append(
            f"- {it.get('name', '')} | Amount {it.get('amount', 0)} | {it.get('category', '')} | "
            f"Medical reimbursable {med} | Commercial reimbursable {com} | {it.get('reason', '')}"
        )
    return "\n".join(lines)


_CONCLUSION_STYLE = {
    "Full Pass": ("✅", "#e6f4ea", "#137333"),
    "Partial Pass": ("⚠️", "#fef7e0", "#b06000"),
    "Rejected": ("❌", "#fce8e6", "#c5221f"),
}


def format_decision_card(result: dict) -> str:
    """Render the claim result as a conclusion card (Markdown/HTML, for frontend right-side card display)."""
    if not result:
        return ""
    if not result.get("ok"):
        return (f"<div style='padding:12px;border-radius:8px;background:#fce8e6;color:#c5221f;'>"
                f"❌ Processing failed ({result.get('stage', '')}): {result.get('message', '')}</div>")

    extract = result["extract"]
    verify = result["verify"]
    decision = result["decision"]
    conclusion = decision.get("conclusion", "")
    icon, bg, fg = _CONCLUSION_STYLE.get(conclusion, ("ℹ️", "#e8f0fe", "#1a73e8"))

    v_flag = "✅ Passed" if verify.get("verified") else "❌ Failed"
    total = decision.get("total_amount", 0.0)
    reimb = decision.get("total_reimbursable", 0.0)
    med = decision.get("total_medical_insurance", 0.0)
    com = decision.get("total_commercial", 0.0)

    rows = ""
    for it in decision.get("items", []):
        rows += (
            f"<tr><td>{it.get('name', '')}</td>"
            f"<td style='text-align:right'>{it.get('amount', 0)}</td>"
            f"<td style='text-align:center'>{it.get('category', '')}</td>"
            f"<td style='text-align:right'>{it.get('medical_reimbursable', 0)}</td>"
            f"<td style='text-align:right'>{it.get('commercial_reimbursable', 0)}</td></tr>"
        )

    return f"""<div style='padding:14px 16px;border-radius:10px;background:{bg};color:{fg};'>
  <div style='font-size:20px;font-weight:700;'>{icon} Claim Conclusion: {conclusion}</div>
  <div style='margin-top:6px;font-size:13px;color:#444;'>
    Invoice authenticity: {v_flag} | Invoice No. {extract.get('fphm', '')} | Invoice date {extract.get('date', '')}
  </div>
</div>

### 💰 Amount Summary

| Item | Amount |
|------|--------:|
| Total amount | {total} |
| **Total reimbursable** | **{reimb}** |
| └ Medical insurance | {med} |
| └ Commercial insurance | {com} |

### 📋 Per-Item Details

<table style='width:100%;font-size:13px;'>
<thead><tr><th align='left'>Drug</th><th>Amount</th><th>Category</th><th>Medical reimbursable</th><th>Commercial reimbursable</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""
