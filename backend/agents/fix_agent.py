"""
THEMIS Fix Agent
Synthesizes verified findings into concrete code patches and (with HITL approval) opens a GitHub PR.
"""

import uuid
import json
import re
from openai import AsyncOpenAI

from backend.config import get_settings
from backend.agents.types import Finding

settings = get_settings()

_FIX_SYSTEM_PROMPT = """You are THEMIS Fix Agent, an expert software engineer specializing in security remediations.
Your task is to generate concrete, minimal, correct code patches for the provided security findings.

Rules:
1. Generate ONLY the fixed version of the vulnerable code — no explanations inside the code
2. Preserve the original code style and indentation
3. Make the minimal change necessary to fix the vulnerability
4. Do not introduce new functionality — only fix the reported issue
5. If multiple findings are in the same file, generate one unified patch

Return a JSON object with this structure:
{
  "patches": [
    {
      "finding_id": "uuid-of-the-finding",
      "file": "path/to/file.py",
      "original_code": "The vulnerable code block",
      "fixed_code": "The corrected code block",
      "explanation": "One sentence: what was changed and why",
      "patch_diff": "unified diff format of the change"
    }
  ]
}

Only return valid JSON. No markdown fences."""


async def fix_agent(state: dict) -> dict:
    """
    Fix agent:
    1. Takes verified_findings from verifier agent
    2. Generates concrete patches using LLM
    3. Returns patches (does NOT open PR — that requires HITL approval via orchestrator)
    """
    verified_findings: list[Finding] = state.get("verified_findings", [])
    errors = []
    patches = []

    if not verified_findings:
        return {"patches": [], "fix_pr_url": None, "errors": []}

    # Only attempt fixes for critical and high severity findings
    fixable = [
        f for f in verified_findings
        if f.get("severity") in ("critical", "high")
        and f.get("category") == "security"  # Security only for automated fixes
    ]

    if not fixable:
        return {"patches": [], "fix_pr_url": None, "errors": []}

    try:
        client = AsyncOpenAI(
            base_url=settings.vllm_base_url,
            api_key="not-needed",
            timeout=settings.vllm_timeout,
        )

        # Process in batches of 5
        for i in range(0, len(fixable), 5):
            batch = fixable[i : i + 5]

            findings_text = json.dumps(
                [
                    {
                        "finding_id": f.get("id"),
                        "title": f.get("title"),
                        "description": f.get("description"),
                        "file": f.get("file"),
                        "line": f.get("line"),
                        "evidence": f.get("evidence", "")[:800],
                        "cwe_id": f.get("cwe_id"),
                    }
                    for f in batch
                ],
                indent=2,
            )

            diff_context = state.get("sanitized_diff", "")[:8000]  # Context for fixes

            response = await client.chat.completions.create(
                model=settings.vllm_model_name,
                messages=[
                    {"role": "system", "content": _FIX_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Generate fixes for these security findings.\n\n"
                            f"Original diff context:\n{diff_context}\n\n"
                            f"Findings to fix:\n{findings_text}"
                        ),
                    },
                ],
                temperature=settings.fix_temperature,
                top_p=settings.fix_top_p,
                max_tokens=settings.fix_max_tokens,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"```[a-z]*\n?", "", content).strip("`").strip()

            data = json.loads(content)
            for patch in data.get("patches", []):
                patch["id"] = str(uuid.uuid4())
                patch["status"] = "pending_approval"
                patches.append(patch)

    except Exception as e:
        errors.append(f"Fix generation error: {str(e)[:200]}")

    return {
        "patches": patches,
        "fix_pr_url": None,  # Set after HITL approval
        "errors": errors,
    }
