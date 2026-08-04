"""
Deterministic, LLM-free risk baseline — a guardrail against the fine-tuned
model's verdict.

Model status (see docs/PROJECT_SPEC.md "Model Status & Roadmap"): the
current Qwen3-14B QLoRA checkpoint is an early/trial fine-tune and known to
hallucinate on some inputs. Rather than trusting its verdict outright, this
module computes a risk level directly from the 7 modules' raw findings —
plain on-chain facts, not model output — and orchestrator.py flags any case
where the LLM's verdict disagrees with it, so a wrong LLM answer surfaces as
"needs review" instead of silently standing as the final answer.

This is intentionally simple (a red-flag count, not a calibrated score) —
it exists to catch gross LLM disagreement, not to replace the production
CIA engine's actual calibrated scoring (rugbuster-scoring-engine/engine.py),
which this submission does not touch.
"""

from __future__ import annotations

from typing import Any


def compute_baseline_risk(findings: dict[str, Any]) -> dict[str, Any]:
    red_flags: list[str] = []

    backdoor = findings.get("contract_backdoor") or {}
    if backdoor.get("has_backdoor"):
        red_flags.append(f"contract_backdoor: {backdoor.get('backdoor_functions')}")

    concentration = findings.get("holder_concentration") or {}
    if concentration.get("concentration_risk") in ("HIGH", "CRITICAL"):
        red_flags.append(
            f"holder_concentration: {concentration.get('concentration_risk')} "
            f"(top5={concentration.get('top5_pct')}%)"
        )

    entropy = findings.get("tx_entropy") or {}
    if entropy.get("is_bot_pattern"):
        red_flags.append("tx_entropy: dominant-amount bot pattern")

    wash = findings.get("wash_pattern") or {}
    if wash.get("wash_detected"):
        red_flags.append("wash_pattern: wash trading detected")

    cluster = findings.get("holder_cluster_age") or {}
    if cluster.get("is_bot_farm"):
        red_flags.append("holder_cluster_age: bot-farm holder pattern")

    latency = findings.get("deployment_latency") or {}
    if latency.get("is_sniped"):
        red_flags.append("deployment_latency: sniped (<3s first buy)")

    funding = findings.get("funding_origin") or {}
    if funding.get("all_fresh"):
        red_flags.append("funding_origin: all funding-chain wallets are fresh (<7d)")

    count = len(red_flags)
    if count >= 3:
        level = "DANGER"
    elif count >= 1:
        level = "WARN"
    else:
        level = "GOOD"

    return {"level": level, "red_flag_count": count, "red_flags": red_flags}


def extract_verdict_keyword(llm_text: str) -> str | None:
    """Pull the first GOOD/WARN/DANGER token out of the LLM's free-text response."""
    upper = llm_text.upper()
    positions = {kw: upper.find(kw) for kw in ("GOOD", "WARN", "DANGER") if kw in upper}
    if not positions:
        return None
    return min(positions, key=positions.get)


def check_guardrail(llm_text: str, baseline: dict[str, Any]) -> dict[str, Any]:
    """
    Compare the LLM's stated verdict against the deterministic baseline.
    Disagreement doesn't mean the LLM is wrong (the baseline is a coarse
    heuristic, not the calibrated production engine) — it means this result
    should not be trusted without a human/deterministic-engine look, given
    the model's known early-checkpoint hallucination issue.
    """
    llm_verdict = extract_verdict_keyword(llm_text)
    agrees = llm_verdict == baseline["level"] if llm_verdict else False
    if llm_verdict is None:
        note = "Could not parse a GOOD/WARN/DANGER verdict from the LLM response — treat as low confidence."
    elif agrees:
        note = "LLM verdict matches the deterministic red-flag baseline."
    else:
        note = (
            f"LLM said {llm_verdict} but the deterministic baseline (raw on-chain findings, "
            f"no LLM involved) says {baseline['level']} ({baseline['red_flag_count']} red flags). "
            "This checkpoint is an early/trial fine-tune (see docs/PROJECT_SPEC.md) — "
            "do not trust the LLM verdict alone here; defer to the baseline / a human review."
        )
    return {"llm_verdict": llm_verdict, "baseline_verdict": baseline["level"], "agrees": agrees, "note": note}
