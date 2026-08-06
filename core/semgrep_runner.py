"""CodeRisk Agent - Semgrep Runner

Wraps Semgrep CLI to scan files and convert results to Risk objects.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from core.models import (
    CodeFile,
    Confidence,
    Evidence,
    Language,
    Risk,
    Severity,
)

console = Console()

# Semgrep severity -> our severity mapping
_SEVERITY_MAP = {
    "ERROR": Severity.HIGH,
    "WARNING": Severity.MEDIUM,
    "INFO": Severity.LOW,
}


def run_semgrep(
    file_path: Path,
    config: str = os.getenv("SEMGREP_RULES", "p/default"),
    timeout: int = 30,
) -> list[dict]:
    """Run Semgrep on a single file, return raw results."""
    try:
        result = subprocess.run(
            ["semgrep", "scan", "--json", f"--config={config}", str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode not in (0, 1):
            console.print(f"[yellow]Semgrep exited with code {result.returncode}[/]")
            if result.stderr:
                console.print(f"[dim]{result.stderr[:200]}[/]")
            return []

        data = json.loads(result.stdout)
        return data.get("results", [])
    except FileNotFoundError:
        console.print("[yellow]Semgrep not installed, skipping Semgrep scan.[/]")
        return []
    except subprocess.TimeoutExpired:
        console.print(f"[yellow]Semgrep timed out after {timeout}s[/]")
        return []
    except json.JSONDecodeError:
        console.print("[yellow]Semgrep output is not valid JSON[/]")
        return []


def semgrep_to_risks(
    raw_results: list[dict],
    code_file: CodeFile,
    risk_counter_start: int = 0,
) -> list[Risk]:
    """Convert Semgrep JSON results to Risk objects."""
    risks: list[Risk] = []
    counter = risk_counter_start

    for item in raw_results:
        counter += 1

        # Extract metadata
        check_id = item.get("check_id", "unknown")
        severity_raw = item.get("extra", {}).get("severity", "WARNING")
        metadata = item.get("extra", {}).get("metadata", {})

        # Build CWE list
        cwe_id = None
        cwe_list = metadata.get("cwe", [])
        if cwe_list:
            cwe_id = cwe_list[0] if isinstance(cwe_list[0], str) else cwe_list[0].get("id")

        # Location
        start_line = item.get("start", {}).get("line", 0)
        end_line = item.get("end", {}).get("line", 0)
        snippet = item.get("extra", {}).get("lines", "")

        # Map severity
        severity = _SEVERITY_MAP.get(severity_raw, Severity.MEDIUM)

        # Build risk
        message = item.get("extra", {}).get("message", check_id)
        fix_msg = item.get("extra", {}).get("fix", "")

        risks.append(Risk(
            id=f"RISK-{counter:03d}",
            title=f"Semgrep: {check_id}",
            description=message,
            severity=severity,
            confidence=Confidence.HIGH,
            cwe_id=cwe_id,
            language=code_file.language,
            file_path=code_file.path,
            line_start=start_line,
            line_end=end_line,
            evidence=[Evidence(
                source="semgrep",
                rule_id=check_id,
                snippet=snippet[:500],
                line_start=start_line,
                line_end=end_line,
                reasoning=f"Semgrep rule {check_id} matched",
            )],
            suggestion=fix_msg or "Review Semgrep documentation for this rule.",
        ))

    return risks


def analyze_with_semgrep(
    code_file: CodeFile,
    config: str = os.getenv("SEMGREP_RULES", "p/default"),
    risk_counter_start: int = 0,
) -> list[Risk]:
    """Full pipeline: run Semgrep on a file and return Risk objects."""
    raw = run_semgrep(code_file.path, config=config)
    if not raw:
        return []
    return semgrep_to_risks(raw, code_file, risk_counter_start)
