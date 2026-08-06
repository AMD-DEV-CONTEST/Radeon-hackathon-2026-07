"""Simple Taint Analysis Module

Tracks data flow from untrusted sources to dangerous sinks.
Single-function variable tracking only — cross-function data flow
requires Call Graph analysis (planned for future release).

Sources (untrusted input):
- C: argv, getenv(), scanf(), fgets(), read()
- Python: input(), sys.argv, request.args, request.form, os.environ

Sinks (dangerous operations):
- C: system(), exec*(), strcpy(), sprintf(), printf(buf)
- Python: eval(), exec(), os.system(), subprocess, pickle.loads()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console

console = Console()


@dataclass
class TaintFlow:
    """A detected data flow from source to sink."""
    source: str          # e.g. "argv[1]", "request.args"
    sink: str            # e.g. "system()", "eval()"
    source_line: int
    sink_line: int
    cwe_id: str
    severity: str        # "critical", "high", "medium"
    description: str
    suggestion: str
    confidence: str      # "high", "medium", "low"
    path: list[str] = field(default_factory=list)  # intermediate variables


# ─── Source Definitions ──────────────────────────────────────────

C_SOURCES = {
    r"\bargv\b": "command-line argument",
    r"\bgetenv\s*\(": "environment variable",
    r"\bscanf\s*\(": "user input (stdin)",
    r"\bfgets\s*\(": "user input (stdin)",
    r"\bread\s*\(": "file/network input",
    r"\brecv\s*\(": "network input",
    r"\baccept\s*\(": "network connection",
}

PYTHON_SOURCES = {
    r"\binput\s*\(": "user input (stdin)",
    r"\bsys\.argv": "command-line argument",
    r"\brequest\.(args|form|json|data|cookies)\b": "HTTP request data",
    r"\bos\.environ\b": "environment variable",
    r"\bos\.getenv\s*\(": "environment variable",
    r"\brandom\.randint\s*\(": "random value (not crypto-safe)",
}

# ─── Sink Definitions ────────────────────────────────────────────

C_SINKS = {
    r"\bsystem\s*\(": ("CWE-78", "high", "Command injection via system()"),
    r"\bexecl[pe]?\s*\(": ("CWE-78", "high", "Command injection via exec()"),
    r"\bstrcpy\s*\(": ("CWE-120", "high", "Buffer overflow via strcpy()"),
    r"\bstrcat\s*\(": ("CWE-120", "high", "Buffer overflow via strcat()"),
    r"\bsprintf\s*\(": ("CWE-134", "high", "Format string via sprintf()"),
    r"\bprintf\s*\(\s*[a-zA-Z_]\w*\s*\)": ("CWE-134", "medium", "Format string via printf(variable)"),
    r"\bgets\s*\(": ("CWE-120", "critical", "Buffer overflow via gets()"),
}

PYTHON_SINKS = {
    r"\beval\s*\(": ("CWE-95", "critical", "Code injection via eval()"),
    r"\bexec\s*\(": ("CWE-95", "critical", "Code injection via exec()"),
    r"\bos\.system\s*\(": ("CWE-78", "high", "Command injection via os.system()"),
    r"\bsubprocess\.(call|run|Popen)\s*\(": ("CWE-78", "medium", "Potential command injection"),
    r"\bpickle\.loads?\s*\(": ("CWE-502", "critical", "Deserialization via pickle"),
    r"\byaml\.load\s*\(": ("CWE-502", "high", "Deserialization via yaml.load()"),
    r"\b__import__\s*\(": ("CWE-95", "high", "Dynamic import via __import__()"),
}

# ─── Variable Tracking ───────────────────────────────────────────

# Simple regex to track variable assignments
# Match: var = expr; OR type var = expr; OR *var = expr;
C_ASSIGN_PATTERN = re.compile(r"(?:(?:\w+\s*\*?\s+)?)(\w+)\s*=\s*(.+);")
PYTHON_ASSIGN_PATTERN = re.compile(r"(\w+)\s*=\s*(.+)")


class TaintAnalyzer:
    """Simple taint analysis engine."""

    def __init__(self):
        self._flows: list[TaintFlow] = []

    def analyze_c(self, content: str, file_path: str) -> list[TaintFlow]:
        """Analyze C code for taint flows."""
        self._flows = []
        lines = content.split("\n")

        # Track tainted variables
        tainted_vars: dict[str, tuple[str, int]] = {}  # var -> (source, line)

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue

            # Check if line assigns from a source
            for source_pattern, source_name in C_SOURCES.items():
                if re.search(source_pattern, line):
                    # Try to find variable assignment
                    assign = C_ASSIGN_PATTERN.search(line)
                    if assign:
                        var_name = assign.group(1)
                        tainted_vars[var_name] = (source_name, i)
                    else:
                        # Direct source usage (e.g., system(argv[1]))
                        self._check_direct_flow(line, i, source_name, "c", file_path)

            # Check if tainted variables flow to sinks
            for sink_pattern, (cwe, severity, desc) in C_SINKS.items():
                if re.search(sink_pattern, line):
                    # Check if any tainted variable is used in this line
                    for var_name, (source_name, source_line) in tainted_vars.items():
                        if re.search(rf"\b{re.escape(var_name)}\b", line):
                            self._flows.append(TaintFlow(
                                source=source_name,
                                sink=sink_pattern.replace(r"\b", "").replace(r"\s*\(", "("),
                                source_line=source_line,
                                sink_line=i,
                                cwe_id=cwe,
                                severity=severity,
                                description=f"Tainted data from {source_name} flows to {desc}",
                                suggestion="Validate and sanitize input before use",
                                confidence="high",
                                path=[var_name],
                            ))

        return self._flows

    def analyze_python(self, content: str, file_path: str) -> list[TaintFlow]:
        """Analyze Python code for taint flows."""
        self._flows = []
        lines = content.split("\n")

        # Track tainted variables
        tainted_vars: dict[str, tuple[str, int]] = {}

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # Check if line assigns from a source
            for source_pattern, source_name in PYTHON_SOURCES.items():
                if re.search(source_pattern, line):
                    assign = PYTHON_ASSIGN_PATTERN.search(line)
                    if assign:
                        var_name = assign.group(1)
                        tainted_vars[var_name] = (source_name, i)
                    else:
                        self._check_direct_flow(line, i, source_name, "python", file_path)

            # Check if tainted variables flow to sinks
            for sink_pattern, (cwe, severity, desc) in PYTHON_SINKS.items():
                if re.search(sink_pattern, line):
                    for var_name, (source_name, source_line) in tainted_vars.items():
                        if re.search(rf"\b{re.escape(var_name)}\b", line):
                            self._flows.append(TaintFlow(
                                source=source_name,
                                sink=sink_pattern.replace(r"\b", "").replace(r"\s*\(", "("),
                                source_line=source_line,
                                sink_line=i,
                                cwe_id=cwe,
                                severity=severity,
                                description=f"Tainted data from {source_name} flows to {desc}",
                                suggestion="Validate and sanitize input before use",
                                confidence="high",
                                path=[var_name],
                            ))

        return self._flows

    def _check_direct_flow(
        self,
        line: str,
        line_num: int,
        source_name: str,
        language: str,
        file_path: str,
    ):
        """Check for direct source-to-sink flow (no intermediate variable)."""
        sinks = C_SINKS if language == "c" else PYTHON_SINKS
        for sink_pattern, (cwe, severity, desc) in sinks.items():
            if re.search(sink_pattern, line):
                self._flows.append(TaintFlow(
                    source=source_name,
                    sink=sink_pattern.replace(r"\b", "").replace(r"\s*\(", "("),
                    source_line=line_num,
                    sink_line=line_num,
                    cwe_id=cwe,
                    severity=severity,
                    description=f"Direct flow from {source_name} to {desc}",
                    suggestion="Validate and sanitize input before use",
                    confidence="medium",
                ))
