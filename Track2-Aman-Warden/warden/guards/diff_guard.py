"""
Diff Guard - Static AST analysis + regex + Semgrep + LLM for code security.

Scans AI-generated code diffs before commit for the blind spots
AI-generated code is prone to: code injection, SQL injection, hardcoded
secrets, insecure deserialization, path traversal, SSRF, weak crypto.

Pipeline:
  1. AST static analysis (ALWAYS - language-aware, <5ms, zero deps)
  2. Regex analysis     (ALWAYS - catches non-Python diffs too)
  3. Semgrep            (if installed - adds community rule coverage)
  4. LLM escalation     (for complex diffs when GPU is available)
"""

from __future__ import annotations

import ast
import logging
import math
import re
import subprocess
import json
import time
from typing import Optional

from warden.tiers.base import ScanResult, VulnerabilityFinding
from warden.tiers.tier2_llm import Tier2LLM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex pattern catalogue: (vuln_type, severity, pattern, explanation)
# Applied to added-lines text AFTER AST scan so already-caught types are skipped.
# ---------------------------------------------------------------------------
_REGEX_PATTERNS: list[tuple[str, str, str, str]] = [
    # Code injection
    (
        "code_injection", "critical",
        r"(?<!['\"\w])(eval|exec|compile)\s*\(",
        "Critical code injection: eval/exec/compile called - never pass user input to these functions",
    ),
    (
        "code_injection", "critical",
        r"__import__\s*\(",
        "Dynamic import via __import__() allows arbitrary module loading",
    ),
    # OS command injection
    (
        "os_command_injection", "critical",
        r"\bos\.system\s*\(|\bos\.popen\s*\(",
        "OS command injection via os.system/os.popen - use subprocess with shell=False",
    ),
    (
        "os_command_injection", "critical",
        r"subprocess\.(call|run|Popen|check_output)\s*\(.*shell\s*=\s*True",
        "Shell injection: subprocess with shell=True - attacker controls shell metacharacters",
    ),
    (
        "os_command_injection", "high",
        r"subprocess\.(call|run|Popen|check_output)\s*\(\s*f['\"]",
        "Potential command injection: subprocess called with f-string argument",
    ),
    # SQL Injection
    (
        "sql_injection", "critical",
        r"(?i)(execute|executemany|raw|query)\s*\(\s*f['\"]",
        "SQL Injection: f-string passed to database execute() - use parameterized queries",
    ),
    (
        "sql_injection", "critical",
        r"(?i)(execute|executemany|raw|query)\s*\(\s*['\"][^'\"]*['\"\s]\s*\+",
        "SQL Injection: string concatenation (+) in database query - use parameterized queries",
    ),
    (
        "sql_injection", "critical",
        r"(?i)(execute|executemany|raw|query)\s*\(\s*['\"][^'\"]*%\s*[(%]",
        "SQL Injection: %-formatting in database query - use parameterized queries",
    ),
    (
        "sql_injection", "high",
        r"(?i)f['\"]SELECT .*(WHERE|AND|OR).*\{",
        "SQL Injection: f-string interpolation in SQL SELECT statement",
    ),
    # Hardcoded secrets
    (
        "hardcoded_secret", "critical",
        r"AKIA[A-Z0-9]{16}",
        "Hardcoded AWS Access Key ID detected",
    ),
    (
        "hardcoded_secret", "critical",
        r"ghp_[A-Za-z0-9]{36}|gh[pousr]_[A-Za-z0-9]{36,}",
        "Hardcoded GitHub personal access token detected",
    ),
    (
        "hardcoded_secret", "critical",
        r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----",
        "Hardcoded private key detected",
    ),
    (
        "hardcoded_secret", "critical",
        r"(sk|pk)_(live|test)_[A-Za-z0-9]{24,}",
        "Hardcoded Stripe API key detected",
    ),
    (
        "hardcoded_secret", "critical",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        "Hardcoded Slack token detected",
    ),
    (
        "hardcoded_secret", "high",
        r"(?i)(password|passwd|secret|api_key|apikey|token)\s*=\s*['\"][A-Za-z0-9@#$!%^&*_+=]{8,}['\"]",
        "Hardcoded credential assignment - use environment variables or a secrets manager",
    ),
    # Insecure deserialization
    (
        "insecure_deserialization", "critical",
        r"\bpickle\.loads?\s*\(",
        "Insecure deserialization: pickle.load() with untrusted data = arbitrary code execution",
    ),
    (
        "insecure_deserialization", "critical",
        r"\byaml\.load\s*\([^)]*\)",
        "Insecure deserialization: yaml.load() without Loader= allows code execution - use yaml.safe_load()",
    ),
    (
        "insecure_deserialization", "high",
        r"\bmarshal\.loads?\s*\(",
        "Insecure deserialization via marshal - equivalent to arbitrary code execution",
    ),
    # Path traversal
    (
        "path_traversal", "high",
        r"open\s*\([^)]*\.\./",
        "Path traversal: open() with ../ - validate and sanitize file paths",
    ),
    (
        "path_traversal", "high",
        r"open\s*\(\s*(request\.|user_input|f['\"])",
        "Path traversal risk: open() with user-controlled path",
    ),
    # SSRF
    (
        "ssrf", "high",
        r"requests\.(get|post|put|delete)\s*\(\s*(url|request\.|user_)",
        "SSRF risk: HTTP request with user-controlled URL - validate against allowlist",
    ),
    # Weak crypto
    (
        "weak_crypto", "medium",
        r"hashlib\.(md5|sha1)\s*\(",
        "Weak hash: MD5/SHA-1 are cryptographically broken - use SHA-256+",
    ),
    (
        "weak_crypto", "medium",
        r"(?i)Crypto\.Cipher\.DES|DES3|ARC4|RC4",
        "Weak cipher: DES/RC4 are broken - use AES-256-GCM",
    ),
    # Unsafe flags
    (
        "debug_code", "medium",
        r"(?i)\bdebug\s*=\s*True",
        "Debug mode enabled: debug=True must never reach production",
    ),
    (
        "insecure_flag", "medium",
        r"(?i)\bverify\s*=\s*False",
        "SSL verification disabled: verify=False exposes to MitM attacks",
    ),
    (
        "insecure_flag", "high",
        r"(?i)ALLOW_ALL_ORIGINS\s*=\s*True|CORS.*\*",
        "Overly permissive CORS: wildcard origin exposes API to cross-site attacks",
    ),
]


class DiffGuard:
    """
    Scans code diffs for security vulnerabilities.

    Pipeline:
    1. AST static analysis (ALWAYS - language-aware, catches eval(), SQLi, secrets)
    2. Regex analysis (ALWAYS - catches non-Python patterns, shell scripts, YAML)
    3. Semgrep (if installed - adds community rules on top)
    4. LLM escalation (if diff is complex and GPU is available)
    """

    def __init__(
        self,
        llm_tier: Optional[Tier2LLM] = None,
        semgrep_rules: str = "p/owasp-top-ten",
        escalation_threshold: int = 3,  # Added lines to trigger LLM escalation
    ):
        self.llm_tier = llm_tier
        self.semgrep_rules = semgrep_rules
        self.escalation_threshold = escalation_threshold

    def scan_diff(self, diff_text: str) -> ScanResult:
        """
        Scan a code diff for vulnerabilities.
        AST + regex analysis runs on ALL diffs. Semgrep and LLM enhance it.
        """
        start = time.perf_counter()
        findings: list[VulnerabilityFinding] = []
        scanners_used: list[str] = []

        # Extract added lines (lines starting with '+', not '+++')
        added_lines = [
            line[1:] for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        added_code = "\n".join(added_lines) if added_lines else diff_text

        # Step 1: AST static analysis (ALWAYS - primary scanner)
        ast_findings = self._ast_scan(added_code)
        if ast_findings:
            findings.extend(ast_findings)
            scanners_used.append("ast_static_analysis")

        # Step 2: Regex analysis (ALWAYS - catches patterns AST misses + non-Python)
        regex_findings = self._regex_scan(added_code, diff_text, existing=findings)
        if regex_findings:
            findings.extend(regex_findings)
            scanners_used.append("regex_static_analysis")

        # Step 3: Semgrep (optional enhancement)
        semgrep_findings = self._run_semgrep(added_code)
        if semgrep_findings:
            findings.extend(semgrep_findings)
            scanners_used.append("semgrep")

        # Step 4: LLM escalation for complex diffs
        if len(added_lines) >= self.escalation_threshold:
            if self.llm_tier and self.llm_tier.is_available():
                llm_findings = self._run_llm_scan(diff_text)
                if llm_findings:
                    findings.extend(llm_findings)
                    scanners_used.append("llm")

        # Deduplicate by (vuln_type, line)
        seen: set[tuple[str, int]] = set()
        deduped: list[VulnerabilityFinding] = []
        for f in findings:
            key = (f.vuln_type, f.line or 0)
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        latency = (time.perf_counter() - start) * 1000
        return ScanResult(
            vulnerabilities=deduped,
            latency_ms=latency,
            scanner="+".join(scanners_used) if scanners_used else "none",
            diff_size_lines=len(diff_text.splitlines()),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ast_scan(self, added_code: str) -> list[VulnerabilityFinding]:
        """
        Python AST static analysis. Catches eval/exec, SQLi f-strings,
        high-entropy secrets, insecure calls - structurally, not by pattern.
        """
        findings: list[VulnerabilityFinding] = []
        try:
            tree = ast.parse(added_code)
        except SyntaxError:
            return findings  # Non-Python diff - regex scan handles it

        for node in ast.walk(tree):
            # --- Entropy-based secret detection on string constants ---
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if len(val) >= 20:
                    prob = [float(val.count(c)) / len(val) for c in dict.fromkeys(val)]
                    entropy = -sum(p * math.log2(p) for p in prob if p > 0)
                    if entropy > 4.2 and re.search(r"[A-Za-z0-9+/=]{20,}", val):
                        findings.append(VulnerabilityFinding(
                            vuln_type="hardcoded_secret",
                            severity="critical",
                            line=getattr(node, "lineno", 1),
                            file_path="diff",
                            explanation=(
                                f"High-entropy secret constant detected "
                                f"(Shannon H={entropy:.2f}) - likely hardcoded credential"
                            ),
                            source="ast_entropy_analysis",
                        ))
                continue

            if not isinstance(node, ast.Call):
                continue

            # Resolve function/method name
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
                module_name = (
                    node.func.value.id
                    if isinstance(node.func.value, ast.Name)
                    else ""
                )
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id
                module_name = ""
            else:
                continue

            lineno = getattr(node, "lineno", 1)

            # --- Code injection: eval / exec / compile / __import__ ---
            if func_name in ("eval", "exec", "compile", "__import__"):
                findings.append(VulnerabilityFinding(
                    vuln_type="code_injection",
                    severity="critical",
                    line=lineno,
                    file_path="diff",
                    explanation=(
                        f"Critical code injection: {func_name}() executes arbitrary "
                        f"code - never pass user input to {func_name}()"
                    ),
                    source="ast_static_analysis",
                ))

            # --- OS command injection ---
            elif func_name in ("system", "popen") and module_name == "os":
                findings.append(VulnerabilityFinding(
                    vuln_type="os_command_injection",
                    severity="critical",
                    line=lineno,
                    file_path="diff",
                    explanation=f"OS command injection: os.{func_name}() passes args to shell",
                    source="ast_static_analysis",
                ))

            # --- subprocess shell=True ---
            elif func_name in ("call", "run", "Popen", "check_output") and module_name == "subprocess":
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        findings.append(VulnerabilityFinding(
                            vuln_type="os_command_injection",
                            severity="critical",
                            line=lineno,
                            file_path="diff",
                            explanation=(
                                "Shell injection: subprocess called with shell=True - "
                                "attacker controls shell metacharacters"
                            ),
                            source="ast_static_analysis",
                        ))

            # --- SQL injection: dynamic f-string or concatenation ---
            elif func_name in ("execute", "executemany", "raw", "query"):
                if node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.JoinedStr):
                        findings.append(VulnerabilityFinding(
                            vuln_type="sql_injection",
                            severity="critical",
                            line=lineno,
                            file_path="diff",
                            explanation=(
                                "SQL Injection: f-string interpolation passed to "
                                "database execute() - use parameterized queries"
                            ),
                            source="ast_static_analysis",
                        ))
                    elif isinstance(first_arg, ast.BinOp):
                        findings.append(VulnerabilityFinding(
                            vuln_type="sql_injection",
                            severity="critical",
                            line=lineno,
                            file_path="diff",
                            explanation=(
                                "SQL Injection: string concatenation/% formatting "
                                "in database query - use parameterized queries"
                            ),
                            source="ast_static_analysis",
                        ))

            # --- Insecure deserialization ---
            elif func_name in ("loads", "load") and module_name == "pickle":
                findings.append(VulnerabilityFinding(
                    vuln_type="insecure_deserialization",
                    severity="critical",
                    line=lineno,
                    file_path="diff",
                    explanation=(
                        "Insecure deserialization: pickle.load() on untrusted "
                        "data = arbitrary code execution"
                    ),
                    source="ast_static_analysis",
                ))
            elif func_name == "load" and module_name == "yaml":
                has_loader = any(kw.arg == "Loader" for kw in node.keywords)
                if not has_loader:
                    findings.append(VulnerabilityFinding(
                        vuln_type="insecure_deserialization",
                        severity="critical",
                        line=lineno,
                        file_path="diff",
                        explanation=(
                            "Insecure deserialization: yaml.load() without Loader= "
                            "allows code execution - use yaml.safe_load()"
                        ),
                        source="ast_static_analysis",
                    ))

        return findings

    def _regex_scan(
        self,
        added_code: str,
        full_diff: str,
        existing: list[VulnerabilityFinding],
    ) -> list[VulnerabilityFinding]:
        """
        Regex-based scan covering all vuln patterns.
        Runs on both added_code and full_diff to catch non-Python diffs.
        Already-caught vuln types are skipped to avoid double-reporting.
        """
        findings: list[VulnerabilityFinding] = []
        existing_types = {f.vuln_type for f in existing}

        for vuln_type, severity, pattern, explanation in _REGEX_PATTERNS:
            if vuln_type in existing_types:
                continue
            for text in (added_code, full_diff):
                m = re.search(pattern, text)
                if m:
                    line = text[: m.start()].count("\n") + 1
                    findings.append(VulnerabilityFinding(
                        vuln_type=vuln_type,
                        severity=severity,
                        line=line,
                        file_path="diff",
                        explanation=explanation,
                        source="regex_static_analysis",
                    ))
                    existing_types.add(vuln_type)
                    break

        return findings

    def _run_semgrep(self, added_code: str) -> list[VulnerabilityFinding]:
        """Run Semgrep on added code lines. Optional - gracefully skipped if not installed."""
        import tempfile
        import os

        findings: list[VulnerabilityFinding] = []
        fd, temp_path = tempfile.mkstemp(suffix=".py")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(added_code)
            cmd = ["semgrep", "scan", "--json", "--config=p/python", temp_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=15
            )
            if result.stdout:
                data = json.loads(result.stdout)
                for match in data.get("results", []):
                    findings.append(VulnerabilityFinding(
                        vuln_type=match.get("check_id", "unknown"),
                        severity=match.get("extra", {}).get("severity", "medium").lower(),
                        line=match.get("start", {}).get("line"),
                        file_path=match.get("path", ""),
                        explanation=match.get("extra", {}).get("message", "Semgrep finding"),
                        source="semgrep",
                    ))
        except Exception as e:
            logger.debug(f"Semgrep not available ({e}) - AST+regex covers primary cases")
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return findings

    def _run_llm_scan(self, diff_text: str) -> list[VulnerabilityFinding]:
        """Escalate to LLM for semantic code analysis of complex diffs."""
        if not self.llm_tier:
            return []
        result = self.llm_tier.check_code(diff_text)
        findings: list[VulnerabilityFinding] = []
        if result.raw_output and isinstance(result.raw_output, dict):
            for vuln in result.raw_output.get("vulnerabilities", []):
                findings.append(VulnerabilityFinding(
                    vuln_type=vuln.get("type", "unknown"),
                    severity=vuln.get("severity", "medium"),
                    line=vuln.get("line", 0),
                    explanation=vuln.get("explanation", ""),
                    source="llm",
                ))
        return findings
