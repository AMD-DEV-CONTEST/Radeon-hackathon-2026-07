"""
THEMIS Verifier Agent
Cross-checks all findings from Security + Style agents.
Scores confidence (0–1), filters low-confidence noise,
validates CWE IDs, and prevents error cascades.
"""

import json
import uuid
import re
from openai import AsyncOpenAI

from backend.config import get_settings
from backend.agents.types import Finding

settings = get_settings()

# Valid CWE IDs (static lookup — prevents hallucinated CWE references)
# Loaded from data/cwe_id_lookup.json in production; hardcoded top-25 here as fallback
_KNOWN_CWES = {
    "CWE-79", "CWE-89", "CWE-20", "CWE-22", "CWE-78", "CWE-94",
    "CWE-287", "CWE-306", "CWE-311", "CWE-319", "CWE-326", "CWE-327",
    "CWE-330", "CWE-338", "CWE-362", "CWE-400", "CWE-416", "CWE-434",
    "CWE-476", "CWE-502", "CWE-601", "CWE-611", "CWE-676", "CWE-732",
    "CWE-798", "CWE-862", "CWE-918", "CWE-943",
}

_VERIFIER_PROMPT = """You are THEMIS Verifier Agent, a senior security and code review expert.
Your role is to validate findings reported by junior agents and assign confidence scores.

For each finding, evaluate:
1. Is this a REAL vulnerability or a false positive?
2. Is the CWE ID accurate and appropriate?
3. Is the severity rating correct?
4. Is the evidence (code snippet) actually present and problematic?

Return a JSON object with this EXACT structure:
{
  "results": [
    {
      "finding_id": "the-uuid-of-the-finding",
      "is_valid": true,
      "confidence": 0.92,
      "adjusted_severity": "high",
      "reasoning": "One sentence explanation of your decision"
    }
  ]
}

Be conservative: when in doubt, lower confidence rather than dismiss entirely.
Only return valid JSON. No markdown fences."""


def _load_cwe_lookup() -> set[str]:
    """Try to load full CWE ID set from data file, fall back to hardcoded set."""
    try:
        import os
        cwe_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "cwe_id_lookup.json"
        )
        if os.path.exists(cwe_path):
            with open(cwe_path) as f:
                data = json.load(f)
                return set(data.keys())
    except Exception:
        pass
    return _KNOWN_CWES


def validate_cwe_id(cwe_id: str | None) -> bool:
    """Return True if the CWE ID is real and known."""
    if not cwe_id:
        return True  # Missing CWE is OK
    # Normalize format
    cwe_id = cwe_id.upper().strip()
    if not cwe_id.startswith("CWE-"):
        cwe_id = f"CWE-{cwe_id}"
    return cwe_id in _load_cwe_lookup()


async def verifier_agent(state: dict) -> dict:
    """
    Verifier agent:
    1. Combine security + style findings
    2. LLM validates each finding (batch)
    3. Filter findings below confidence threshold
    4. Validate CWE IDs
    5. Return verified_findings list
    """
    security_findings: list[Finding] = state.get("security_findings", [])
    style_findings: list[Finding] = state.get("style_findings", [])
    all_findings = security_findings + style_findings
    errors = []

    if not all_findings:
        return {"verified_findings": [], "confidence_scores": {}, "errors": []}

    verified: list[Finding] = []
    confidence_scores: dict[str, float] = {}

    # ── LLM Verification (batch up to 10 findings) ────────────
    try:
        client = AsyncOpenAI(
            base_url=settings.vllm_base_url,
            api_key="not-needed",
            timeout=settings.vllm_timeout,
        )

        # Process in batches of 10
        batch_size = 10
        for i in range(0, len(all_findings), batch_size):
            batch = all_findings[i : i + batch_size]

            # Prepare batch for LLM
            findings_text = json.dumps(
                [
                    {
                        "finding_id": f.get("id"),
                        "title": f.get("title"),
                        "description": f.get("description"),
                        "severity": f.get("severity"),
                        "cwe_id": f.get("cwe_id"),
                        "evidence": f.get("evidence", "")[:500],  # Truncate evidence
                    }
                    for f in batch
                ],
                indent=2,
            )

            response = await client.chat.completions.create(
                model=settings.vllm_model_name,
                messages=[
                    {"role": "system", "content": _VERIFIER_PROMPT},
                    {
                        "role": "user",
                        "content": f"Verify these findings:\n\n{findings_text}",
                    },
                ],
                temperature=0.05,  # Very deterministic for verification
                max_tokens=1500,
                seed=settings.security_seed,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"```[a-z]*\n?", "", content).strip("`").strip()

            data = json.loads(content)

            # Apply verification results
            results_map = {r["finding_id"]: r for r in data.get("results", [])}

            for finding in batch:
                fid = finding.get("id")
                result = results_map.get(fid, {})

                confidence = float(result.get("confidence", finding.get("confidence", 0.5)))

                # Validate CWE ID
                if not validate_cwe_id(finding.get("cwe_id")):
                    confidence *= 0.7  # Penalty for hallucinated CWE
                    finding["cwe_id"] = None  # Clear invalid CWE

                confidence_scores[fid] = confidence

                # Apply threshold filter
                if result.get("is_valid", True) and confidence >= settings.confidence_threshold:
                    # Apply adjusted severity if provided
                    if "adjusted_severity" in result:
                        finding["severity"] = result["adjusted_severity"]
                    finding["confidence"] = confidence
                    finding["verifier_reasoning"] = result.get("reasoning", "")
                    verified.append(finding)

    except Exception as e:
        errors.append(f"Verifier LLM error: {str(e)[:200]}")
        # Fallback: pass through findings above original confidence threshold
        verified = [
            f for f in all_findings
            if f.get("confidence", 0) >= settings.confidence_threshold
        ]

    # Sort by severity (critical first)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    verified.sort(key=lambda f: severity_order.get(f.get("severity", "low"), 4))

    return {
        "verified_findings": verified,
        "confidence_scores": confidence_scores,
        "errors": errors,
    }
