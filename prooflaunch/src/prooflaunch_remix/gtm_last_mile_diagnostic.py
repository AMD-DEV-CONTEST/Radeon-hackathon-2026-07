from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


RULES: tuple[dict[str, Any], ...] = (
    {"id": "unsupported_market_generalization", "severity": "critical", "lanes": ("geo",), "patterns": (r"actively seeking solutions", r"leaders in .+ are (?:actively )?seeking")},
    {"id": "unauthorized_personal_data_retrieval", "severity": "critical", "lanes": ("cross_device_memory",), "patterns": (r"retrieve user(?:'s)? .+profile", r"scrape .+profile")},
    {"id": "consentless_cross_channel_activation", "severity": "critical", "lanes": ("content_schedule", "lifecycle_email"), "patterns": (r"email to .+ engagers", r"email .+ followers")},
    {"id": "unsupported_outcome_prediction", "severity": "critical", "lanes": ("integrated_gtm_strategy", "content_schedule"), "patterns": (r"will generate qualified leads", r"generate qualified leads")},
    {"id": "channel_native_mismatch", "severity": "major", "lanes": ("organic_social_copy",), "patterns": (r"link in bio",)},
    {"id": "unbound_experiment_threshold", "severity": "major", "lanes": ("analytics",), "patterns": (r"conversion rate (?:exceeds|below) \d",)},
    {"id": "placeholder_link", "severity": "major", "lanes": ("organic_social_copy", "lifecycle_email"), "patterns": (r"\[link(?: to [^\]]+)?\]",)},
    {"id": "generic_privacy_assurance", "severity": "major", "lanes": ("cross_device_memory",), "patterns": (r"adhere to all relevant data privacy",)},
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def diagnose(lanes: Mapping[str, object]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for rule in RULES:
        for lane in rule["lanes"]:
            if lane not in lanes:
                continue
            text = _canonical(lanes[lane])
            for pattern in rule["patterns"]:
                match = re.search(pattern, text, re.I)
                if match:
                    findings.append(
                        {
                            "rule_id": rule["id"],
                            "severity": rule["severity"],
                            "lane_id": lane,
                            "matched_excerpt": match.group(0)[:180],
                        }
                    )
                    break
    critical = sum(item["severity"] == "critical" for item in findings)
    major = sum(item["severity"] == "major" for item in findings)
    core: dict[str, Any] = {
        "schema": "ProofLaunchGTMLastMileDeterministicDiagnosticV1",
        "lane_count": len(lanes),
        "finding_count": len(findings),
        "critical_finding_count": critical,
        "major_finding_count": major,
        "findings": findings,
        "blind_review_admission_allowed": critical == 0,
        "automatic_promotion_allowed": False,
        "aesthetic_score_assigned": False,
        "truth_boundary": (
            "This deterministic diagnostic catches enumerated safety, evidence, channel and "
            "operational defects only. A clean result is not aesthetic quality, human preference, "
            "4A parity or Top-1 evidence."
        ),
    }
    core["content_sha256"] = hashlib.sha256(_canonical(core).encode("utf-8")).hexdigest()
    return core
