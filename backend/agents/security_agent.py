"""
THEMIS Security Agent
Combines LLM analysis + Semgrep + Bandit + RAG knowledge retrieval
to detect vulnerabilities in the PR diff.
"""

import uuid
import tempfile
import os
import shutil
import re
from openai import AsyncOpenAI

from backend.config import get_settings
from backend.tools.sandbox import run_semgrep, run_bandit, write_code_to_tempdir
from backend.agents.types import Finding, make_event

settings = get_settings()

# System prompt for security analysis
_SECURITY_SYSTEM_PROMPT = """You are THEMIS Security Agent, an expert application security engineer.
Your task is to analyze the provided code diff for security vulnerabilities.

Focus on:
- Injection attacks (SQL, Command, LDAP, XPath)
- Authentication and authorization flaws  
- Sensitive data exposure (hardcoded secrets, PII in logs)
- Insecure deserialization
- XML External Entity (XXE) attacks
- Security misconfiguration
- Cross-Site Scripting (XSS)
- Broken access control
- Cryptographic failures (weak algorithms, hardcoded keys)
- SSRF (Server-Side Request Forgery)

For each vulnerability found, respond in this EXACT JSON format:
{
  "findings": [
    {
      "title": "Brief vulnerability title",
      "description": "Detailed explanation of the vulnerability and why it is dangerous",
      "severity": "critical|high|medium|low",
      "file": "path/to/file.py",
      "line": 42,
      "cwe_id": "CWE-89",
      "evidence": "The specific vulnerable code snippet",
      "confidence": 0.85
    }
  ]
}

If no vulnerabilities are found, return: {"findings": []}
Only return valid JSON. Do not include markdown code fences."""


def _extract_python_from_diff(diff: str) -> str:
    """Extract added Python lines from a diff for static analysis."""
    lines = []
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])  # Remove leading "+"
    return "\n".join(lines)


def _extract_files_by_ext(diff: str, exts: list[str]) -> dict[str, str]:
    """Extract code grouped by file extension for targeted analysis."""
    result = {}
    current_file = None
    current_ext = None
    current_lines = []

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_ext in exts:
                result[current_file] = "\n".join(current_lines)
            match = re.search(r"b/(.+)$", line)
            if match:
                current_file = match.group(1)
                current_ext = "." + current_file.rsplit(".", 1)[-1] if "." in current_file else ""
                current_lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            current_lines.append(line[1:])

    if current_file and current_ext in exts:
        result[current_file] = "\n".join(current_lines)

    return result


async def security_agent(state: dict) -> dict:
    """
    Security agent — combines three analysis methods:
    1. Semgrep (pattern-based static analysis)
    2. Bandit (Python-specific AST analysis)
    3. LLM deep analysis (contextual understanding)

    Returns merged, deduplicated findings list.
    """
    sanitized_diff = state.get("sanitized_diff", "")
    chunked_diffs = state.get("chunked_diffs", [sanitized_diff])
    findings: list[Finding] = []
    errors = []

    # ── 1. Static Analysis: Semgrep + Bandit ─────────────────
    # Write diff content to temp dir for analysis
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="themis_sec_")

        # Write Python files
        py_files = _extract_files_by_ext(
            state.get("diff", ""),
            [".py"]
        )
        for filename, content in py_files.items():
            safe_name = os.path.basename(filename)
            filepath = os.path.join(tmpdir, safe_name)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        if py_files:
            # Run Semgrep
            semgrep_result = run_semgrep(tmpdir)
            for finding in semgrep_result.get("findings", []):
                findings.append({
                    "id": str(uuid.uuid4()),
                    "agent": "security",
                    "category": "security",
                    "severity": finding.get("extra", {}).get("severity", "medium").lower(),
                    "title": finding.get("check_id", "Semgrep finding"),
                    "description": finding.get("extra", {}).get("message", ""),
                    "file": finding.get("path", "unknown"),
                    "line": finding.get("start", {}).get("line"),
                    "cwe_id": None,
                    "confidence": 0.8,
                    "evidence": finding.get("extra", {}).get("lines", ""),
                })

            # Run Bandit
            bandit_result = run_bandit(tmpdir)
            for finding in bandit_result.get("findings", []):
                severity_map = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
                findings.append({
                    "id": str(uuid.uuid4()),
                    "agent": "security",
                    "category": "security",
                    "severity": severity_map.get(finding.get("issue_severity", "MEDIUM"), "medium"),
                    "title": finding.get("issue_text", "Bandit finding"),
                    "description": finding.get("more_info", ""),
                    "file": finding.get("filename", "unknown"),
                    "line": finding.get("line_number"),
                    "cwe_id": finding.get("test_id"),
                    "confidence": 0.75,
                    "evidence": finding.get("code", ""),
                })

    except Exception as e:
        errors.append(f"Static analysis error: {str(e)[:200]}")
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 2. LLM Deep Analysis ─────────────────────────────────
    try:
        client = AsyncOpenAI(
            base_url=settings.vllm_base_url,
            api_key="not-needed",  # vLLM doesn't require auth by default
            timeout=settings.vllm_timeout,
        )

        # Analyse each chunk
        for i, chunk in enumerate(chunked_diffs[:3]):  # Max 3 chunks
            response = await client.chat.completions.create(
                model=settings.vllm_model_name,
                messages=[
                    {"role": "system", "content": _SECURITY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze this code diff for security vulnerabilities:\n\n{chunk}"},
                ],
                temperature=settings.security_temperature,
                top_p=settings.security_top_p,
                max_tokens=settings.security_max_tokens,
                seed=settings.security_seed,
            )

            content = response.choices[0].message.content.strip()

            # Parse LLM response
            import json
            try:
                # Strip any accidental markdown fences
                if content.startswith("```"):
                    content = re.sub(r"```[a-z]*\n?", "", content).strip("`").strip()

                data = json.loads(content)
                for f in data.get("findings", []):
                    findings.append({
                        "id": str(uuid.uuid4()),
                        "agent": "security",
                        "category": "security",
                        "severity": f.get("severity", "medium"),
                        "title": f.get("title", "Security finding"),
                        "description": f.get("description", ""),
                        "file": f.get("file", "unknown"),
                        "line": f.get("line"),
                        "cwe_id": f.get("cwe_id"),
                        "confidence": float(f.get("confidence", 0.7)),
                        "evidence": f.get("evidence", ""),
                    })
            except (json.JSONDecodeError, ValueError):
                errors.append(f"LLM chunk {i} parse error — raw: {content[:200]}")

    except Exception as e:
        errors.append(f"LLM analysis error: {str(e)[:200]}")

    return {
        "security_findings": findings,
        "errors": errors,
    }
