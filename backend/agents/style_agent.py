"""
THEMIS Style Agent
Detects code style violations and maintainability issues using
Pylint + ESLint (Docker sandboxed) + LLM style analysis.
"""

import uuid
import json
import re
import tempfile
import os
import shutil
from openai import AsyncOpenAI

from backend.config import get_settings
from backend.tools.sandbox import run_pylint, run_eslint

settings = get_settings()

_STYLE_SYSTEM_PROMPT = """You are THEMIS Style Agent, an expert code quality reviewer.
Analyze the provided code diff for style violations, maintainability issues, and best practice violations.

Focus on:
- Code complexity (functions too long, deeply nested logic)
- Naming conventions (unclear variable/function names)
- Missing error handling (bare excepts, unhandled exceptions)
- Code duplication (DRY violations)
- Dead code (unused variables, unreachable code)
- Missing input validation
- Improper resource management (unclosed files/connections)
- Overly complex boolean expressions
- Magic numbers/strings (use constants)
- Poor separation of concerns

Return findings in this EXACT JSON format:
{
  "findings": [
    {
      "title": "Brief issue title",
      "description": "Why this is a problem and how to fix it",
      "severity": "medium|low",
      "file": "path/to/file.py",
      "line": 42,
      "evidence": "The problematic code snippet",
      "confidence": 0.85
    }
  ]
}

Only return valid JSON. No markdown fences."""


async def style_agent(state: dict) -> dict:
    """
    Style agent — runs Pylint + ESLint + LLM style review.
    Returns style_findings list.
    """
    sanitized_diff = state.get("sanitized_diff", "")
    chunked_diffs = state.get("chunked_diffs", [sanitized_diff])
    file_types = state.get("file_types", [])
    findings = []
    errors = []

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="themis_style_")

        # Write code to temp files for analysis
        diff = state.get("diff", "")
        current_file = None
        current_lines = []

        for line in diff.split("\n"):
            if line.startswith("diff --git"):
                if current_file:
                    filepath = os.path.join(tmpdir, os.path.basename(current_file))
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write("\n".join([l[1:] if l.startswith("+") else l for l in current_lines]))
                match = re.search(r"b/(.+)$", line)
                current_file = match.group(1) if match else None
                current_lines = []
            elif line.startswith("+") and not line.startswith("+++"):
                current_lines.append(line)

        if current_file:
            filepath = os.path.join(tmpdir, os.path.basename(current_file))
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join([l[1:] for l in current_lines]))

        # ── Pylint (Python files) ─────────────────────────────
        if ".py" in file_types:
            pylint_result = run_pylint(tmpdir)
            for issue in pylint_result.get("findings", []):
                severity_map = {"E": "high", "W": "medium", "R": "low", "C": "low"}
                msg_type = issue.get("type", "W")
                findings.append({
                    "id": str(uuid.uuid4()),
                    "agent": "style",
                    "category": "style",
                    "severity": severity_map.get(msg_type[0] if msg_type else "W", "low"),
                    "title": issue.get("symbol", "Style issue"),
                    "description": issue.get("message", ""),
                    "file": issue.get("path", "unknown"),
                    "line": issue.get("line"),
                    "cwe_id": None,
                    "confidence": 0.75,
                    "evidence": "",
                })

        # ── ESLint (JS/TS files) ──────────────────────────────
        js_types = {".js", ".jsx", ".ts", ".tsx"}
        if any(ext in file_types for ext in js_types):
            eslint_result = run_eslint(tmpdir)
            for issue in eslint_result.get("findings", []):
                severity = "medium" if issue.get("severity") == 2 else "low"
                findings.append({
                    "id": str(uuid.uuid4()),
                    "agent": "style",
                    "category": "style",
                    "severity": severity,
                    "title": issue.get("rule", "ESLint issue"),
                    "description": issue.get("message", ""),
                    "file": issue.get("file", "unknown"),
                    "line": issue.get("line"),
                    "cwe_id": None,
                    "confidence": 0.7,
                    "evidence": "",
                })

    except Exception as e:
        errors.append(f"Style static analysis error: {str(e)[:200]}")
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── LLM Style Analysis ────────────────────────────────────
    try:
        client = AsyncOpenAI(
            base_url=settings.vllm_base_url,
            api_key="not-needed",
            timeout=settings.vllm_timeout,
        )

        for i, chunk in enumerate(chunked_diffs[:2]):  # Max 2 chunks for style
            response = await client.chat.completions.create(
                model=settings.vllm_model_name,
                messages=[
                    {"role": "system", "content": _STYLE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Review this code diff for style issues:\n\n{chunk}"},
                ],
                temperature=0.15,
                max_tokens=1500,
                seed=settings.security_seed + 1,
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"```[a-z]*\n?", "", content).strip("`").strip()

            data = json.loads(content)
            for f in data.get("findings", []):
                findings.append({
                    "id": str(uuid.uuid4()),
                    "agent": "style",
                    "category": "style",
                    "severity": f.get("severity", "low"),
                    "title": f.get("title", "Style finding"),
                    "description": f.get("description", ""),
                    "file": f.get("file", "unknown"),
                    "line": f.get("line"),
                    "cwe_id": None,
                    "confidence": float(f.get("confidence", 0.7)),
                    "evidence": f.get("evidence", ""),
                })

    except Exception as e:
        errors.append(f"LLM style analysis error: {str(e)[:200]}")

    return {
        "style_findings": findings,
        "errors": errors,
    }
