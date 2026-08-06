"""Agent 1: Tree-sitter Static Analyzer

Responsibilities:
- Parse AST using Tree-sitter
- Detect dangerous patterns in C/Python code
- Output structured risk list
"""

from __future__ import annotations

import re
import threading
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

# ─── C Dangerous Patterns ───────────────────────────────────────

C_DANGEROUS_FUNCTIONS = {
    "gets": {
        "cwe": "CWE-120",
        "severity": Severity.CRITICAL,
        "title": "Buffer Overflow via gets()",
        "desc": "gets() does not check buffer bounds, can cause stack buffer overflow",
        "fix": "Replace with fgets(buf, sizeof(buf), stdin)",
    },
    "strcpy": {
        "cwe": "CWE-120",
        "severity": Severity.HIGH,
        "title": "Unbounded strcpy()",
        "desc": "strcpy() does not check destination buffer size",
        "fix": "Replace with strncpy() or strlcpy()",
    },
    "strcat": {
        "cwe": "CWE-120",
        "severity": Severity.HIGH,
        "title": "Unbounded strcat()",
        "desc": "strcat() does not check remaining space in destination buffer",
        "fix": "Replace with strncat() or strlcat()",
    },
    "sprintf": {
        "cwe": "CWE-134",
        "severity": Severity.HIGH,
        "title": "Format String via sprintf()",
        "desc": "sprintf() does not check destination buffer size and may be vulnerable to format string attacks",
        "fix": "Replace with snprintf(buf, sizeof(buf), ...)",
    },
    "scanf": {
        "cwe": "CWE-120",
        "severity": Severity.MEDIUM,
        "title": "Unbounded scanf()",
        "desc": 'scanf("%s", ...) has no length limit',
        "fix": 'Use scanf("%99s", buf) to limit length, or use fgets',
    },
    "system": {
        "cwe": "CWE-78",
        "severity": Severity.HIGH,
        "title": "OS Command Injection via system()",
        "desc": "system() directly executes shell commands, may be injected",
        "fix": "Avoid system(), use exec family functions instead",
    },
    "memcpy": {
        "cwe": "CWE-120",
        "severity": Severity.MEDIUM,
        "title": "Unchecked memcpy()",
        "desc": "memcpy() does not check destination buffer size, may cause overflow",
        "fix": "Ensure destination buffer is large enough, or use memcpy_s()",
    },
    "popen": {
        "cwe": "CWE-78",
        "severity": Severity.HIGH,
        "title": "Command Injection via popen()",
        "desc": "popen() executes shell commands, may be injected",
        "fix": "Use pipe+exec instead, avoid shell interpretation",
    },
}

C_VULNERABLE_PATTERNS = [
    {
        "pattern": r"malloc\s*\(.*\)\s*;",
        "check_null": True,
        "cwe": "CWE-476",
        "severity": Severity.MEDIUM,
        "title": "malloc() Return Value Not Checked",
        "desc": "malloc() may return NULL, direct use leads to null pointer dereference",
        "fix": "Check if malloc() return value is NULL",
    },
    {
        "pattern": r"free\s*\([^)]+\)\s*;",
        "check_double_free": True,
        "cwe": "CWE-415",
        "severity": Severity.HIGH,
        "title": "Potential Double Free",
        "desc": "Pointer not set to NULL after free(), may be freed again",
        "fix": "Set ptr = NULL immediately after free(ptr)",
    },
]

# ─── Python Dangerous Patterns ──────────────────────────────────

PYTHON_DANGEROUS_CALLS = {
    "eval": {
        "cwe": "CWE-95",
        "severity": Severity.CRITICAL,
        "title": "Code Injection via eval()",
        "desc": "eval() executes arbitrary code, extremely dangerous",
        "fix": "Use ast.literal_eval() or refactor logic to avoid dynamic execution",
    },
    "exec": {
        "cwe": "CWE-95",
        "severity": Severity.CRITICAL,
        "title": "Code Injection via exec()",
        "desc": "exec() executes arbitrary code",
        "fix": "Refactor logic to avoid dynamic execution",
    },
    "pickle.loads": {
        "cwe": "CWE-502",
        "severity": Severity.CRITICAL,
        "title": "Deserialization via pickle.loads()",
        "desc": "pickle.loads() deserializing untrusted data can execute arbitrary code",
        "fix": "Use json or msgpack instead of pickle",
    },
    "subprocess.call": {
        "cwe": "CWE-78",
        "severity": Severity.MEDIUM,
        "title": "Shell Injection Risk",
        "desc": "subprocess.call() with shell=True may be injected",
        "fix": "Use subprocess.run(args, shell=False) with a list",
    },
    "os.system": {
        "cwe": "CWE-78",
        "severity": Severity.HIGH,
        "title": "OS Command Injection via os.system()",
        "desc": "os.system() directly executes shell commands",
        "fix": "Use subprocess.run() instead",
    },
    "yaml.load": {
        "cwe": "CWE-502",
        "severity": Severity.HIGH,
        "title": "Deserialization via yaml.load()",
        "desc": "yaml.load() without SafeLoader can execute arbitrary code",
        "fix": "Use yaml.safe_load() instead",
    },
    "xml.etree.ElementTree.parse": {
        "cwe": "CWE-611",
        "severity": Severity.HIGH,
        "title": "XXE via xml.etree.ElementTree",
        "desc": "Parsing untrusted XML may lead to XXE attacks",
        "fix": "Use defusedxml, or disable external entity processing",
    },
    "tempfile.mktemp": {
        "cwe": "CWE-377",
        "severity": Severity.MEDIUM,
        "title": "Insecure Temporary File",
        "desc": "mktemp() has a race condition and is insecure",
        "fix": "Use tempfile.mkstemp() or TemporaryFile() instead",
    },
    "hashlib.md5": {
        "cwe": "CWE-328",
        "severity": Severity.MEDIUM,
        "title": "Weak Hash: MD5",
        "desc": "MD5 is proven insecure, vulnerable to collision attacks",
        "fix": "Use hashlib.sha256() or stronger hash algorithm",
    },
    "hashlib.sha1": {
        "cwe": "CWE-328",
        "severity": Severity.LOW,
        "title": "Weak Hash: SHA-1",
        "desc": "SHA-1 is proven insecure, vulnerable to collision attacks",
        "fix": "Use hashlib.sha256() or stronger hash algorithm",
    },
}

PYTHON_VULNERABLE_PATTERNS = [
    {
        "pattern": r"open\s*\([^)]*['\"]w['\"]",
        "cwe": "CWE-73",
        "severity": Severity.LOW,
        "title": "File Write Without Validation",
        "desc": "File path should be validated before writing to prevent path traversal",
        "fix": "Use os.path.realpath() to verify path is within expected directory",
    },
    {
        "pattern": r"assert\s+",
        "cwe": "CWE-617",
        "severity": Severity.LOW,
        "title": "Assert in Production Code",
        "desc": "assert is skipped in -O mode, should not be used for security checks",
        "fix": "Use if + raise instead of assert",
    },
]

# ─── New C Patterns (inspired by vigolium/pentest-ai) ────────────

C_NEW_PATTERNS = [
    {
        "pattern": r"(?:access|fopen|open)\s*\([^)]*argv",
        "cwe": "CWE-22",
        "severity": Severity.HIGH,
        "title": "Path Traversal via User Input",
        "desc": "File operations use command-line arguments, potential path traversal",
        "fix": "Validate path is within expected directory, use realpath() normalization",
    },
    {
        "pattern": r"(?:MD5|DES|RC4)\s*\(",
        "cwe": "CWE-327",
        "severity": Severity.MEDIUM,
        "title": "Use of Weak Cryptographic Algorithm",
        "desc": "Uses a known insecure cryptographic algorithm",
        "fix": "Replace with AES-256/SHA-256 or other modern algorithms",
    },
    {
        "pattern": r"atoi\s*\(|atol\s*\(|atof\s*\(",
        "cwe": "CWE-190",
        "severity": Severity.LOW,
        "title": "Integer Overflow via atoi/atol",
        "desc": "atoi/atol does not check for overflow, large values may wrap around",
        "fix": "Use strtol/strtoul and check errno",
    },
]

# ─── New Python Patterns ────────────────────────────────────────

PYTHON_NEW_PATTERNS = [
    {
        "pattern": r"password\s*=\s*['\"].*['\"]",
        "cwe": "CWE-798",
        "severity": Severity.HIGH,
        "title": "Hard-coded Credentials",
        "desc": "Password is hard-coded in source, should not appear in code",
        "fix": "Use environment variables or config files to store credentials",
    },
    {
        "pattern": r"(?:secret|token|api_key)\s*=\s*['\"][a-zA-Z0-9+/=]{8,}['\"]",
        "cwe": "CWE-798",
        "severity": Severity.HIGH,
        "title": "Hard-coded Secret/Token",
        "desc": "Secret or token is hard-coded in source",
        "fix": "Use environment variables or a secrets manager",
    },
]


class StaticAnalyzer:
    """Tree-sitter Static Analyzer Agent."""

    def __init__(self, custom_rules: list[dict] | None = None):
        self._risk_counter = 0
        self._counter_lock = threading.Lock()
        self._custom_rules = custom_rules or []

    def analyze(self, code_file: CodeFile) -> list[Risk]:
        """Analyze a single file and return risk list."""
        risks: list[Risk] = []

        if code_file.language == Language.C:
            risks.extend(self._analyze_c(code_file))
        elif code_file.language == Language.PYTHON:
            risks.extend(self._analyze_python(code_file))

        # Apply custom rules
        if self._custom_rules:
            risks.extend(self._apply_custom_rules(code_file))

        return risks

    def _apply_custom_rules(self, code_file: CodeFile) -> list[Risk]:
        """Apply user-provided custom detection rules."""
        risks: list[Risk] = []
        lines = code_file.content.split("
")

        lang_str = "C" if code_file.language == Language.C else "Python"

        for rule in self._custom_rules:
            rule_lang = rule.get("language", "all")
            if rule_lang != "all" and rule_lang != lang_str:
                continue

            pattern = rule.get("pattern", "")
            if not pattern:
                continue

            try:
                regex = re.compile(pattern)
            except re.error:
                continue

            for i, line in enumerate(lines, start=1):
                if regex.search(line):
                    risks.append(self._make_risk(
                        title=rule.get("description", rule.get("id", "Custom rule")),
                        description=rule.get("description", "Custom rule matched"),
                        severity=Severity(rule.get("severity", "MEDIUM")),
                        confidence=Confidence.MEDIUM,
                        cwe_id=rule.get("cwe", "CWE-0"),
                        file_path=str(code_file.path),
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        fix_suggestion=rule.get("fix", ""),
                    ))

        return risks

    def analyze_batch(self, files: list[CodeFile]) -> list[Risk]:
        """Analyze multiple files in batch."""
        all_risks: list[Risk] = []
        for f in files:
            risks = self.analyze(f)
            all_risks.extend(risks)
            if risks:
                console.print(f"  [red]⚠ {f.path}: {len(risks)} risks[/]")
            else:
                console.print(f"  [green]✓ {f.path}: clean[/]")
        return all_risks

    # ─── C Analysis ─────────────────────────────────────────────

    def _analyze_c(self, code_file: CodeFile) -> list[Risk]:
        """Analyze C code for dangerous patterns."""
        risks: list[Risk] = []
        lines = code_file.content.split("\n")

        for i, line in enumerate(lines, start=1):
            # Check dangerous function calls
            for func, info in C_DANGEROUS_FUNCTIONS.items():
                if re.search(rf"\b{func}\s*\(", line):
                    risks.append(self._make_risk(
                        title=info["title"],
                        description=info["desc"],
                        severity=info["severity"],
                        confidence=Confidence.HIGH,
                        cwe_id=info["cwe"],
                        language=Language.C,
                        file_path=code_file.path,
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        source="pattern_match",
                        reasoning=f"Dangerous function {func}() call detected",
                        suggestion=info["fix"],
                    ))

            # Check vulnerability patterns
            for pat in C_VULNERABLE_PATTERNS:
                if re.search(pat["pattern"], line):
                    # malloc: check 3 lines after for NULL check
                    if pat.get("check_null"):
                        context = "\n".join(lines[i:i+3])
                        if "NULL" not in context and "null" not in context:
                            risks.append(self._make_risk(
                                title=pat["title"],
                                description=pat["desc"],
                                severity=pat["severity"],
                                confidence=Confidence.MEDIUM,
                                cwe_id=pat["cwe"],
                                language=Language.C,
                                file_path=code_file.path,
                                line_start=i,
                                line_end=i,
                                snippet=line.strip(),
                                source="pattern_match",
                                reasoning=f"Pattern matched: {pat['pattern']}",
                                suggestion=pat["fix"],
                            ))
                    # double free: only flag if same variable freed 2+ times
                    if pat.get("check_double_free"):
                        import re as _re
                        m = _re.search(r"free\s*\((\w+)\)", line)
                        if m:
                            var = m.group(1)
                            free_count = sum(1 for ln in lines if _re.search(rf"free\s*\({var}\)", ln))
                            if free_count >= 2:
                                risks.append(self._make_risk(
                                    title=pat["title"],
                                    description=f"{pat['desc']} (variable '{var}' freed {free_count} times)",
                                    severity=pat["severity"],
                                    confidence=Confidence.HIGH,
                                    cwe_id=pat["cwe"],
                                    language=Language.C,
                                    file_path=code_file.path,
                                    line_start=i,
                                    line_end=i,
                                    snippet=line.strip(),
                                    source="pattern_match",
                                    reasoning=f"Variable '{var}' has {free_count} free() calls",
                                    suggestion=pat["fix"],
                                ))

            # Check new patterns (inspired by vigolium/pentest-ai)
            for pat in C_NEW_PATTERNS:
                if re.search(pat["pattern"], line):
                    risks.append(self._make_risk(
                        title=pat["title"],
                        description=pat["desc"],
                        severity=pat["severity"],
                        confidence=Confidence.MEDIUM,
                        cwe_id=pat["cwe"],
                        language=Language.C,
                        file_path=code_file.path,
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        source="pattern_match",
                        reasoning=f"Pattern matched: {pat['pattern']}",
                        suggestion=pat["fix"],
                    ))

        return risks

    # ─── Python Analysis ────────────────────────────────────────

    def _analyze_python(self, code_file: CodeFile) -> list[Risk]:
        """Analyze Python code for dangerous patterns."""
        risks: list[Risk] = []
        lines = code_file.content.split("\n")

        for i, line in enumerate(lines, start=1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Check dangerous function calls
            for func, info in PYTHON_DANGEROUS_CALLS.items():
                if re.search(rf"\b{func}\s*\(", line):
                    risks.append(self._make_risk(
                        title=info["title"],
                        description=info["desc"],
                        severity=info["severity"],
                        confidence=Confidence.HIGH,
                        cwe_id=info["cwe"],
                        language=Language.PYTHON,
                        file_path=code_file.path,
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        source="pattern_match",
                        reasoning=f"Dangerous function {func}() call detected",
                        suggestion=info["fix"],
                    ))

            # Check vulnerability patterns
            for pat in PYTHON_VULNERABLE_PATTERNS:
                if re.search(pat["pattern"], line):
                    risks.append(self._make_risk(
                        title=pat["title"],
                        description=pat["desc"],
                        severity=pat["severity"],
                        confidence=Confidence.MEDIUM,
                        cwe_id=pat["cwe"],
                        language=Language.PYTHON,
                        file_path=code_file.path,
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        source="pattern_match",
                        reasoning=f"Pattern matched: {pat['pattern']}",
                        suggestion=pat["fix"],
                    ))

            # Check new patterns
            for pat in PYTHON_NEW_PATTERNS:
                if re.search(pat["pattern"], line):
                    risks.append(self._make_risk(
                        title=pat["title"],
                        description=pat["desc"],
                        severity=pat["severity"],
                        confidence=Confidence.MEDIUM,
                        cwe_id=pat["cwe"],
                        language=Language.PYTHON,
                        file_path=code_file.path,
                        line_start=i,
                        line_end=i,
                        snippet=line.strip(),
                        source="pattern_match",
                        reasoning=f"Pattern matched: {pat['pattern']}",
                        suggestion=pat["fix"],
                    ))

        return risks

    # ─── Utility Methods ────────────────────────────────────────

    def _make_risk(self, **kwargs) -> Risk:
        """Create a Risk with auto-generated ID."""
        with self._counter_lock:
            self._risk_counter += 1
            risk_id = f"RISK-{self._risk_counter:03d}"
        snippet = kwargs.pop("snippet")
        source = kwargs.pop("source")
        reasoning = kwargs.pop("reasoning")
        return Risk(
            id=risk_id,
            evidence=[Evidence(
                source=source,
                snippet=snippet,
                line_start=kwargs["line_start"],
                line_end=kwargs["line_end"],
                reasoning=reasoning,
            )],
            **kwargs,
        )
