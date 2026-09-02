"""
validators/powershell_validator.py — PowerShell parse + Script Analyzer
========================================================================
PowerShell scripts can't use the bash-style `-n` parse-check pattern. Instead
we shell out to powershell.exe (or pwsh) with the System.Management.Automation
AST parser to validate syntax. If PSScriptAnalyzer is installed, we additionally
parse its DiagnosticRecord output for Error-severity findings.

Cross-platform: prefers `pwsh` (PowerShell 7+), falls back to Windows `powershell.exe`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.powershell")

_FENCE_RE = re.compile(r"^```(?:powershell|ps1|pwsh)?\s*\n|\n```\s*$", flags=re.MULTILINE)


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def _powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("pwsh.exe") or shutil.which("powershell.exe")


_PARSE_SCRIPT = r"""
param([string]$Path)
$errors = $null
$tokens = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    $Path, [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) {
    $errors | ForEach-Object {
        [PSCustomObject]@{
            Line    = $_.Extent.StartLineNumber
            Column  = $_.Extent.StartColumnNumber
            Message = $_.Message
        }
    } | ConvertTo-Json -Depth 3 -Compress
    exit 1
}
exit 0
"""


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate a PowerShell script.

    task_meta keys:
        analyzer_strict (bool): warning-level Script Analyzer findings fail.
        skip_analyzer (bool):   parse-only.
    """
    code = _strip_markdown_fences(output)
    if len(code) < 5:
        return False, "Output too short to be a valid PowerShell script"

    pwsh = _powershell_executable()
    if not pwsh:
        return False, "powershell/pwsh not on PATH"

    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as fh:
        fh.write(code)
        script_path = fh.name
    parser_script = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as fh:
            fh.write(_PARSE_SCRIPT)
            parser_script = fh.name

        result = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", parser_script, "-Path", script_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            try:
                err_payload = json.loads(result.stdout.strip() or "{}")
                if isinstance(err_payload, dict):
                    err_payload = [err_payload]
                first = err_payload[0] if err_payload else {}
                return False, (
                    f"PowerShell parse error @ L{first.get('Line', '?')}:"
                    f"{first.get('Column', '?')} — {first.get('Message', 'unknown')}"
                )
            except (json.JSONDecodeError, IndexError):
                return (
                    False,
                    f"PowerShell parse failed: {(result.stdout or result.stderr).strip()[:200]}",
                )

        if task_meta.get("skip_analyzer"):
            return True, "parse passed (analyzer skipped)"

        # PSScriptAnalyzer (optional)
        analyzer_cmd = (
            f"if (Get-Module -ListAvailable PSScriptAnalyzer) {{ "
            f"Invoke-ScriptAnalyzer -Path '{script_path}' -Severity Error,Warning | "
            f"ConvertTo-Json -Depth 3 -Compress }}"
        )
        analyzer = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", analyzer_cmd],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if not analyzer.stdout.strip():
            return True, "parse passed (PSScriptAnalyzer unavailable)"
        try:
            findings = json.loads(analyzer.stdout)
            if isinstance(findings, dict):
                findings = [findings]
        except json.JSONDecodeError:
            findings = []
        errors = [f for f in findings if f.get("Severity") == "Error"]
        warnings = [f for f in findings if f.get("Severity") == "Warning"]
        if errors:
            first = errors[0]
            return False, f"PSScriptAnalyzer {first.get('RuleName')}: {first.get('Message')}"
        if task_meta.get("analyzer_strict") and warnings:
            first = warnings[0]
            return False, f"PSScriptAnalyzer strict {first.get('RuleName')}: {first.get('Message')}"
        return True, f"parse passed; {len(warnings)} analyzer warnings"
    except subprocess.TimeoutExpired:
        return False, "validator timeout"
    finally:
        for path in (script_path, parser_script):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
