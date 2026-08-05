"""
Secret scanner for corpus code ingest.

Scans source code files for embedded secrets before ingest.
Any file containing a detected secret is REJECTED — not redacted.
(Redaction is for screenshots. Code secrets mean the whole file is suspect.)

Detection: regex patterns covering API keys, tokens, credentials, private keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SecretFinding:
    category: str
    line_number: int
    excerpt: str  # never the full secret — just enough to locate it
    pattern_name: str


@dataclass
class ScanResult:
    path: str
    clean: bool  # True = no secrets found
    findings: list[SecretFinding] = field(default_factory=list)
    lines_scanned: int = 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "clean": self.clean,
            "finding_count": len(self.findings),
            "categories": list({f.category for f in self.findings}),
        }


# ---------------------------------------------------------------------------
# Secret patterns
# Each tuple: (pattern_name, category, compiled_regex)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # Private keys — highest specificity, check first
    (
        "rsa_private_key",
        "private_key",
        re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("pgp_private_key", "private_key", re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-----")),
    # LLM keys — specific prefixes, check before generic api_key
    ("anthropic_key", "llm_key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("openai_key", "llm_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    # Cloud providers
    ("aws_access_key", "aws", re.compile(r"\bAKIA[0-9A-Z]{14,20}\b")),
    (
        "aws_secret_key",
        "aws",
        re.compile(
            r"""aws[_-]?secret[_-]?access[_-]?key\s*[=:'"]\s*['"]?([A-Za-z0-9/+=]{20,})""", re.I
        ),
    ),
    ("gcp_service_account", "gcp", re.compile(r'"type"\s*:\s*"service_account"')),
    # GitHub / VCS tokens — specific prefix
    ("github_pat", "vcs_token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_oauth", "vcs_token", re.compile(r"\bgho_[A-Za-z0-9]{36}\b")),
    ("github_actions", "vcs_token", re.compile(r"\bghs_[A-Za-z0-9]{36}\b")),
    # Service tokens — specific prefix
    ("slack_token", "service_token", re.compile(r"\bxox[bpoas]-[0-9A-Za-z\-]{10,}\b")),
    ("stripe_key", "service_token", re.compile(r"\bsk_(?:live|test)_[0-9A-Za-z]{24,}\b")),
    ("twilio_sid", "service_token", re.compile(r"\bAC[0-9a-f]{32}\b")),
    # JWT (non-test)
    (
        "jwt_token",
        "token",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b"),
    ),
    # Database URLs with credentials
    (
        "db_url_with_creds",
        "database",
        re.compile(r"(?:postgres|mysql|mongodb|redis)://[^:@\s]+:[^@\s]{4,}@", re.I),
    ),
    # Generic high-entropy secrets — last resort, after specific patterns
    (
        "generic_api_key",
        "api_key",
        re.compile(
            r"""(?:api[_-]?key|apikey|api[_-]?secret|client[_-]?secret)\s*[=:'"]\s*['"]?([A-Za-z0-9\-_/+]{20,})""",
            re.I,
        ),
    ),
    (
        "generic_token",
        "token",
        re.compile(
            r"""(?:token|access[_-]?token|auth[_-]?token|bearer)\s*[=:'"]\s*['"]?([A-Za-z0-9\-_/+.]{20,})""",
            re.I,
        ),
    ),
    (
        "generic_password",
        "password",
        re.compile(r"""(?:password|passwd|pwd|secret)\s*[=:'"]\s*['"]([^'"]{8,})['"]""", re.I),
    ),
]

# Lines to skip (tests, examples, documentation)
_SKIP_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*#"),  # comments
    re.compile(
        r"\bEXAMPLE\b|\bPLACEHOLDER\b|\bYOUR_KEY\b|\bREPLACE_ME\b|<your|\bTODO\b|\bFIXME\b", re.I
    ),
    re.compile(r"test|spec|mock|fake|dummy|sample", re.I),
    re.compile(r"sk-ant-api\*+|sk-[x\*]{10,}|AWS_KEY_PLACEHOLDER\b"),  # redacted/example
]

# File extensions to skip entirely
_SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".rst",
        ".txt",
        ".json.example",
        ".env.example",
        ".sample",
        ".template",
    }
)


def scan_content(content: str, path: str = "<content>") -> ScanResult:
    """Scan a string for secrets. Returns ScanResult."""
    findings: list[SecretFinding] = []
    lines = content.splitlines()

    for line_num, line in enumerate(lines, 1):
        # Skip obviously safe lines
        if any(p.search(line) for p in _SKIP_PATTERNS):
            continue
        for name, category, pattern in _PATTERNS:
            if pattern.search(line):
                excerpt = line.strip()[:80]
                findings.append(
                    SecretFinding(
                        category=category,
                        line_number=line_num,
                        excerpt=excerpt,
                        pattern_name=name,
                    )
                )
                break  # one finding per line is enough

    return ScanResult(
        path=path,
        clean=len(findings) == 0,
        findings=findings,
        lines_scanned=len(lines),
    )


def scan_file(path: Path) -> ScanResult:
    """Scan a file for secrets."""
    # Skip binary and excluded extensions
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return ScanResult(path=str(path), clean=True, lines_scanned=0)

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return ScanResult(
            path=str(path),
            clean=False,
            findings=[SecretFinding("read_error", 0, str(exc), "io_error")],
        )
    return scan_content(content, path=str(path))


def scan_directory(path: Path, max_files: int = 10_000) -> list[ScanResult]:
    """Recursively scan all text files in a directory."""
    results = []
    count = 0
    for f in path.rglob("*"):
        if count >= max_files:
            break
        if f.is_file() and not any(part.startswith(".") for part in f.parts):
            results.append(scan_file(f))
            count += 1
    return results


def is_clean(path: Path) -> bool:
    """Quick check: True if no secrets found."""
    if path.is_dir():
        return all(r.clean for r in scan_directory(path))
    return scan_file(path).clean
