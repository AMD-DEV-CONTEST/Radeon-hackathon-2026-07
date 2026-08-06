# -*- coding: utf-8 -*-
"""
tools/decision_tool.py — Claim Rules Deterministic Calculation Tool (pure Python, no LLM)

Implements the three-tier decision logic: per-item drug calculated along two lines
(medical insurance reimbursable / commercial insurance reimbursable), finally
aggregated into a claim conclusion (Full Pass / Partial Pass / Rejected).
Amounts are auditable, ensuring accuracy.
"""

from typing import Any, Dict, List

from langchain_core.tools import tool

import tools  # noqa: F401  inject into sys.path
import config as cfg


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _round2(v: float) -> float:
    return round(float(v) + 1e-9, 2)


def _normalize_category(category: str) -> str:
    """Normalize Chinese category values to English (for backward compatibility)."""
    if category == "甲类":
        return "Category A"
    if category == "乙类":
        return "Category B"
    if category == "目录外":
        return "Out of Catalog"
    if category == "商保创新药":
        return "Commercial Innovative Drug"
    return category


def _decide_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Single-item drug three-tier decision, returns medical_reimbursable / commercial_reimbursable / reason."""
    name = item.get("name", "")
    price = _to_float(item.get("priceSum", 0.0))
    category = _normalize_category(item.get("category", "") or "")
    in_catalog = bool(item.get("in_catalog", False))
    innovative = bool(item.get("commercial_innovative", False))
    self_pay_2 = _to_float(item.get("self_pay_2", 0.0))
    reimburse_ratio = _to_float(item.get("reimburse_ratio", cfg.DEFAULT_REIMBURSE_RATIO))
    cap = item.get("cap", None)

    medical = 0.0
    commercial = 0.0

    # Tier 2 priority: commercial innovative drug catalog (medical insurance does not cover, commercial is core)
    if innovative:
        medical = 0.0
        commercial = price * cfg.DEFAULT_COMMERCIAL_RATIO
        reason = "Commercial innovative drug catalog; medical insurance does not cover, commercial insurance reimburses per agreement"
    # Tier 1: within basic medical insurance catalog (must genuinely match, in_catalog=True)
    elif in_catalog and category == "Category A":
        medical = price * reimburse_ratio
        reason = f"Category A fully included in base; reimbursed at {reimburse_ratio*100:.0f}% per pool"
    elif in_catalog and category == "Category B":
        pre_self = price * self_pay_2
        medical = (price - pre_self) * reimburse_ratio
        reason = f"Category B: self-pay {self_pay_2*100:.0f}% first, then reimbursed at {reimburse_ratio*100:.0f}% per pool"
    # Tier 3: out of catalog (not matched or non-medical/commercial item)
    else:
        medical = 0.0
        commercial = 0.0
        reason = "Not in medical/commercial insurance reimbursement catalog; not reimbursable"

    # Cap (applies to medical insurance reimbursable portion)
    if cap is not None:
        cap_v = _to_float(cap, default=-1.0)
        if cap_v >= 0 and medical > cap_v:
            medical = cap_v
            reason += f"; medical reimbursable hit cap of {cap_v:.0f}"

    return {
        "name": name,
        "amount": _round2(price),
        "category": category if category else ("Commercial Innovative Drug" if innovative else "Out of Catalog"),
        "commercial_innovative": innovative,
        "medical_reimbursable": _round2(medical),
        "commercial_reimbursable": _round2(commercial),
        "reason": reason,
    }


def decide_claim_core(verified: bool, items: List[Dict[str, Any]]) -> dict:
    """Calculate claim conclusion based on authenticity result and per-item catalog info."""
    items = items or []
    total_amount = _round2(sum(_to_float(it.get("priceSum", 0.0)) for it in items))

    # Verification failed: direct rejection
    if not verified:
        return {
            "conclusion": "Rejected",
            "verified": False,
            "total_amount": total_amount,
            "total_reimbursable": 0.0,
            "total_medical_insurance": 0.0,
            "total_commercial": 0.0,
            "items": [{
                "name": it.get("name", ""),
                "amount": _round2(_to_float(it.get("priceSum", 0.0))),
                "medical_reimbursable": 0.0,
                "commercial_reimbursable": 0.0,
                "reason": "Invoice authenticity verification failed/info mismatch; full amount not reimbursable",
            } for it in items],
            "summary_text": f"Invoice authenticity verification failed; total amount {total_amount}, not reimbursable.",
        }

    decided = [_decide_item(it) for it in items]
    total_medical = _round2(sum(d["medical_reimbursable"] for d in decided))
    total_commercial = _round2(sum(d["commercial_reimbursable"] for d in decided))
    total_reimbursable = _round2(total_medical + total_commercial)

    # Whether any reimbursable item exists (in catalog or commercial innovative), to identify non-medical invoices
    any_covered = any(
        bool(it.get("in_catalog")) or bool(it.get("commercial_innovative")) for it in items
    )

    if total_amount > 0 and abs(total_reimbursable - total_amount) < 0.01:
        conclusion = "Full Pass"
    elif total_reimbursable > 0:
        conclusion = "Partial Pass"
    else:
        conclusion = "Rejected"

    if conclusion == "Rejected" and not any_covered and items:
        summary_text = (
            f"Total amount {total_amount}; none of the item details matched the medical/commercial "
            f"reimbursement catalog. Suspected non-medical/drug invoice, not within this system's claim scope."
        )
    else:
        summary_text = (
            f"Total amount {total_amount}, total reimbursable {total_reimbursable} "
            f"(medical {total_medical} + commercial {total_commercial}), conclusion: {conclusion}."
        )

    return {
        "conclusion": conclusion,
        "verified": True,
        "total_amount": total_amount,
        "total_reimbursable": total_reimbursable,
        "total_medical_insurance": total_medical,
        "total_commercial": total_commercial,
        "items": decided,
        "summary_text": summary_text,
    }


@tool
def claim_decision_tool(verified: bool, items: List[Dict[str, Any]]) -> dict:
    """Deterministically calculate reimbursable amounts and claim conclusion based on invoice authenticity and per-item drug catalog info.
    Args: verified = whether invoice verification passed; items = drug list, each needing name, priceSum (amount),
    category (Category A/Category B/Out of Catalog), in_catalog, commercial_innovative, self_pay_2, reimburse_ratio, cap.
    Returns conclusion (Full Pass/Partial Pass/Rejected), total_amount, total_reimbursable,
    total_medical_insurance, total_commercial, per-item details and reasons. Amounts are pure rule-based, auditable."""
    return decide_claim_core(verified, items)


# ============================================================================
# Batch invoice cross-invoice aggregate decision (Task 2)
# ============================================================================


def decide_batch_core(invoice_results: List[Dict[str, Any]]) -> dict:
    """Cross-invoice aggregate decision: summarize batch invoice results, calculate totals, annual cap deduction and overall conclusion.

    Args: invoice_results = list of invoice results from the batch pipeline, each typically containing
    ok (success), duplicate_of (duplicate index or None), extract (with fphm/date/code total amount),
    decision (single-invoice decide_claim_core result); failed or duplicate elements may contain only
    partial fields (e.g. {"ok": False, ...}), handled defensively.

    Returns aggregate dict with fixed keys:
    total_invoices / success_count / failed_count / duplicate_count,
    total_amount / total_medical_insurance / total_commercial / total_reimbursable,
    medical_after_cap / annual_cap / cap_applied / cap_note,
    conclusion (All Passed/Partial Pass/All Rejected) and summary_text.
    Amounts are pure rule-based, auditable."""
    invoice_results = invoice_results or []

    total_invoices = len(invoice_results)
    success_count = 0
    failed_count = 0
    duplicate_count = 0

    total_amount = 0.0
    total_medical_insurance = 0.0
    total_commercial = 0.0

    conclusions: List[str] = []

    for r in invoice_results:
        if not isinstance(r, dict):
            failed_count += 1
            continue

        ok = bool(r.get("ok", False))
        duplicate_of = r.get("duplicate_of", None)
        is_duplicate = duplicate_of is not None

        if not ok:
            failed_count += 1
        if is_duplicate:
            duplicate_count += 1

        # Only "successful and non-duplicate" invoices participate in amount accumulation and conclusion
        if not ok or is_duplicate:
            continue

        success_count += 1

        extract = r.get("extract")
        if not isinstance(extract, dict):
            extract = {}
        # extract.code is the total amount
        total_amount += _to_float(extract.get("code", 0.0))

        decision = r.get("decision")
        if not isinstance(decision, dict):
            decision = {}
        total_medical_insurance += _to_float(decision.get("total_medical_insurance", 0.0))
        total_commercial += _to_float(decision.get("total_commercial", 0.0))
        dc = decision.get("conclusion")
        if isinstance(dc, str) and dc:
            conclusions.append(dc)

    total_amount = _round2(total_amount)
    total_medical_insurance = _round2(total_medical_insurance)
    total_commercial = _round2(total_commercial)

    # Annual cap (applies to total medical insurance reimbursable): only enabled when cfg.ANNUAL_CAP > 0
    annual_cap_raw = _to_float(getattr(cfg, "ANNUAL_CAP", 0.0), default=0.0)
    if annual_cap_raw > 0 and total_medical_insurance > annual_cap_raw:
        annual_cap = _round2(annual_cap_raw)
        medical_after_cap = _round2(annual_cap_raw)
        cap_applied = True
        cap_note = (
            f"Total medical reimbursable {total_medical_insurance} exceeds annual cap "
            f"{annual_cap_raw}; after capping, medical reimbursable is {medical_after_cap}"
        )
    else:
        annual_cap = _round2(annual_cap_raw) if annual_cap_raw > 0 else 0.0
        medical_after_cap = total_medical_insurance
        cap_applied = False
        cap_note = ""

    # After cap trigger, total_reimbursable recalculated as capped medical + commercial
    total_reimbursable = _round2(medical_after_cap + total_commercial)

    # Overall conclusion: based on successful non-duplicate invoice conclusions
    if success_count == 0 or not conclusions:
        conclusion = "All Rejected"
    elif all(c == "Full Pass" for c in conclusions):
        conclusion = "All Passed"
    elif all(c == "Rejected" for c in conclusions):
        conclusion = "All Rejected"
    else:
        conclusion = "Partial Pass"

    # Summary text
    if total_invoices > 0 and failed_count == total_invoices:
        summary_text = f"This batch contains {total_invoices} invoices, all processing failed, no claim amounts."
    else:
        summary_text = (
            f"This batch contains {total_invoices} invoices (success {success_count}, failed {failed_count}, "
            f"duplicates {duplicate_count}), total amount {total_amount}, total reimbursable "
            f"{total_reimbursable} (medical {total_medical_insurance} + commercial "
            f"{total_commercial}), conclusion: {conclusion}."
        )
        if cap_applied:
            summary_text += " " + cap_note + "."

    return {
        "total_invoices": total_invoices,
        "success_count": success_count,
        "failed_count": failed_count,
        "duplicate_count": duplicate_count,
        "total_amount": total_amount,
        "total_medical_insurance": total_medical_insurance,
        "total_commercial": total_commercial,
        "total_reimbursable": total_reimbursable,
        "medical_after_cap": medical_after_cap,
        "annual_cap": annual_cap,
        "cap_applied": cap_applied,
        "cap_note": cap_note,
        "conclusion": conclusion,
        "summary_text": summary_text,
    }


@tool
def claim_batch_decision_tool(invoice_results: List[Dict[str, Any]]) -> dict:
    """Batch invoice cross-invoice aggregate decision tool.

    Args: invoice_results = list of invoice results from the batch pipeline, each needing
    ok (success), duplicate_of (duplicate index or None), extract (with fphm/date/code total amount),
    decision (single-invoice decide_claim_core result); failed or duplicate elements may contain only
    partial fields, handled defensively without crashing the aggregation.

    Returns aggregate dict: total_invoices / success_count / failed_count / duplicate_count,
    total_amount / total_medical_insurance / total_commercial / total_reimbursable,
    medical_after_cap / annual_cap / cap_applied / cap_note, overall conclusion
    (All Passed/Partial Pass/All Rejected) and summary_text.
    Duplicate invoices do not participate in amount accumulation; failed invoices only count. Amounts are pure rule-based, auditable."""
    return decide_batch_core(invoice_results)
