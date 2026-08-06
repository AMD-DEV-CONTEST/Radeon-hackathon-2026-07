"""SpriteFusion2D submission builder (S01).

Builds an independent ``SpriteFusion2D/`` submission directory from the current
repository using an explicit allowlist of git-tracked files (never copy-all +
delete-blacklist). Pure standard library (Python >= 3.10); only ``git`` is
invoked, for the tracked-file list.

- candidates come exclusively from ``git ls-files``
- explicit carve-outs: AMD_BOX.md, docs/luna-workpack, mock screenshots,
  internal plans, testdata, uv.lock, .git/.github
- path-traversal and symlink protection for source and output trees
- sensitive scan: error hits fail always, warnings fail under ``--strict``;
  the tool and its tests are never scanned (no self-hits)
- dual LICENSE / upstream attribution guard
- outputs ``FILES.txt``, ``BUILD_RECEIPT.json`` and ``MANIFEST.sha256``;
  MANIFEST.sha256 never hashes itself (stated in its header)
- ``--dry-run`` plans and scans without writing; ``--check`` verifies a build
- non-empty target refused unless ``--force`` rebuilds over a previous receipt
- no placeholder files for public materials that are not tracked
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

TOOL_NAME = "build_submission.py"
TOOL_VERSION = "1.0.0"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_NAME = "SpriteFusion2D"
META_FILES = ("FILES.txt", "BUILD_RECEIPT.json", "MANIFEST.sha256")
REQUIRED_LICENSES = ("LICENSE", "LICENSE-spritefusion-pixel-snapper")

# Never content-scanned, so the tool's rules and test fixtures cannot self-hit.
SELF_SKIP_PATHS = frozenset(
    {
        "scripts/build_submission.py",
        "tests/test_build_submission.py",
    }
)

# Explicit allowlist: only these tracked path families are considered. The
# excluded families are listed so their exclusion is an explicit carve-out.
INCLUDE_PATTERNS: Tuple[str, ...] = (
    "__init__.py",
    "pyproject.toml",
    "pixel_snapper_core.py",
    "pixel_snapper_node.py",
    "README.md",
    "ARCHITECTURE.md",
    "BENCHMARKS.md",
    "LICENSE",
    "LICENSE-*",
    "AGENTS.md",
    ".gitignore",
    "icon.png",
    "sprite_workshop/**",
    "benchmarks/**",
    "scripts/*",
    "tests/**",
    "frontend/**",
    "AMD_BOX.md",
    "BACKEND_CLI_PLAN.md",
    "BACKEND_PLAN_V2.md",
    "FRONTEND_PLAN.md",
    "FRONTEND_PLAN_V2.md",
    "PIXEL_TOOLING_RESEARCH.md",
    "uv.lock",
    "docs/**",
    "testdata/**",
    ".github/**",
    ".scratch-amd/**",
)

EXCLUDE_PATTERNS: Tuple[str, ...] = (
    # internal ops / agent knowledge
    "AMD_BOX.md",
    "docs/**",
    "docs/luna-workpack/**",
    # internal plans and research notes
    "BACKEND_CLI_PLAN.md",
    "BACKEND_PLAN_V2.md",
    "FRONTEND_PLAN.md",
    "FRONTEND_PLAN_V2.md",
    "PIXEL_TOOLING_RESEARCH.md",
    # mock / scratch screenshots and their capture tooling
    ".scratch-amd/**",
    "frontend/.scratch-amd/**",
    "frontend/capture.sh",
    # VCS internals and CI metadata
    ".git/**",
    ".github/**",
    # locked deps, caches, local config
    "uv.lock",
    "testdata/**",
    "node_modules/**",
    "**/node_modules/**",
    "dist/**",
    "**/__pycache__/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "sidecar.config.json",
    "**/sidecar.config.json",
    "*.log",
)

# Absence of optional public materials is only reported; no placeholders are
# ever created for files that are not tracked.
OPTIONAL_PUBLIC_MATERIALS: Dict[str, str] = {
    "demo": "D01 demo assets / demo manifest",
    "docs/images": "D04 real Radeon screenshots + MANIFEST.md",
    "THIRD_PARTY_NOTICES.md": "D03 third-party notices",
}


class BuildError(Exception):
    """Fatal, user-facing build failure."""

_PATTERN_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _compile_glob(pattern: str) -> "re.Pattern[str]":
    """Glob with ``**`` (any depth), ``*`` and ``?`` (no slash)."""
    cached = _PATTERN_CACHE.get(pattern)
    if cached is not None:
        return cached
    out: List[str] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _PATTERN_CACHE[pattern] = rx
    return rx


def _matches(relpath: str, patterns: Sequence[str]) -> bool:
    return any(_compile_glob(pattern).match(relpath) for pattern in patterns)


def _is_within(child: str, parent: str) -> bool:
    """True when ``child`` equals ``parent`` or lives inside it."""
    child_real = os.path.realpath(child)
    parent_real = os.path.realpath(parent)
    try:
        common = os.path.commonpath([child_real, parent_real])
    except ValueError:
        return False
    return common == parent_real


def _validate_relpath(relpath: str) -> str:
    """Reject absolute, traversing, backslash or denormalized relative paths."""
    if not relpath or relpath in (".", "/"):
        raise BuildError(f"invalid candidate path: {relpath!r}")
    if os.path.isabs(relpath) or relpath.startswith("/") or "\\" in relpath:
        raise BuildError(f"non-relative candidate path: {relpath!r}")
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BuildError(
            f"unsafe candidate path (empty/./.. component): {relpath!r}"
        )
    if os.path.normpath(relpath).replace("\\", "/") != relpath:
        raise BuildError(f"denormalized candidate path: {relpath!r}")
    return relpath


def _reject_symlink_sources(repo_root: str, relpaths: Iterable[str]) -> None:
    """Refuse candidates that are symlinks or resolve outside the repository."""
    repo_real = os.path.realpath(repo_root)
    for rel in relpaths:
        src = os.path.join(repo_root, rel.replace("/", os.sep))
        if os.path.islink(src):
            raise BuildError(f"candidate is a symlink (refusing to follow): {rel}")
        if not _is_within(src, repo_real):
            raise BuildError(f"candidate resolves outside the repository: {rel}")


def _resolve_output_path(target_root: str, relpath: str) -> str:
    target_real = os.path.realpath(target_root)
    out = os.path.realpath(os.path.join(target_real, relpath.replace("/", os.sep)))
    if not _is_within(out, target_real):
        raise BuildError(f"output path escapes target directory: {relpath}")
    return out


def _makedirs_safe(target_root: str, directory: str) -> None:
    if not directory:
        return
    os.makedirs(directory, exist_ok=True)
    if not _is_within(directory, target_root):
        raise BuildError(f"output parent escapes target directory: {directory}")


def _check_target_safe(repo_root: str, target_root: str) -> None:
    """Refuse targets that contain or equal the repository itself."""
    if _is_within(repo_root, target_root):
        raise BuildError(
            f"refusing to use a target that contains the repository: {target_root}"
        )

SENSITIVE_IP_RULE_ID = "sensitive-ip-assignment"

SENSITIVE_RULES: Tuple[Dict[str, object], ...] = (
    {
        "id": "aws-access-key-id",
        "pattern": r"\bAKIA[0-9A-Z]{16}\b",
        "flags": re.IGNORECASE,
        "severity": "error",
        "description": "AWS access key id",
    },
    {
        "id": "private-key-block",
        "pattern": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
        "flags": 0,
        "severity": "error",
        "description": "private key material",
    },
    {
        "id": "secret-assignment",
        "pattern": (
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
            r"access[_-]?token|auth[_-]?token|client[_-]?secret|"
            r"session[_-]?secret|private[_-]?key|connection[_-]?string)\b\s*[:=]\s*"
            r"[\"'](?![$]{)[^\"'\n]{6,}[\"']"
        ),
        "flags": 0,
        "severity": "error",
        "description": "quoted secret assignment",
    },
    {
        "id": "secret-assignment-unquoted",
        "pattern": (
            r"(?im)^[ \t]*(?:password|passwd|pwd|token|secret|api[_-]?key|"
            r"access[_-]?token|auth[_-]?token)\s*=\s*"
            r"[A-Za-z0-9_\-./+]{8,}[ \t]*\r?$"
        ),
        "flags": 0,
        "severity": "warning",
        "description": "unquoted secret-style assignment (dotenv style)",
    },
    {
        "id": "personal-path-windows",
        "pattern": r"\b[A-Za-z]:\\Users\\[^\"'\n\r]+",
        "flags": 0,
        "severity": "error",
        "description": "user-specific Windows path",
    },
    {
        "id": "personal-path-posix",
        "pattern": r"(?<![A-Za-z0-9_])/(?:Users|home)/[^\"'\s:]+",
        "flags": 0,
        "severity": "error",
        "description": "user-specific POSIX path",
    },
    {
        # Only an IP assigned to a sensitive connection key is flagged; bare
        # public IPv4 in prose is NOT flagged; private/reserved ranges are exempt.
        "id": SENSITIVE_IP_RULE_ID,
        "pattern": (
            r"(?im)^[ \t]*(?P<key>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*"
            r"[\"']?(?P<ip>\d{1,3}(?:\.\d{1,3}){3})[\"']?[ \t]*\r?$"
        ),
        "flags": 0,
        "severity": "warning",
        "description": "public IP assigned to a sensitive connection key",
    },
)


def _parse_ipv4(ip: str) -> Optional[Tuple[int, int, int, int]]:
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        octets = tuple(int(part) for part in parts)
    except ValueError:
        return None
    if any(octet < 0 or octet > 255 for octet in octets):
        return None
    return octets  # type: ignore[return-value]


def _is_public_ipv4(ip: str) -> bool:
    """True for a valid IPv4 that is not private/reserved/local."""
    octets = _parse_ipv4(ip)
    if octets is None:
        return False
    a, b = octets[0], octets[1]
    if a in (0, 10, 127):
        return False
    if a == 100 and 64 <= b <= 127:  # CGNAT
        return False
    if a == 169 and b == 254:  # link-local
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 192 and b == 168:
        return False
    if a == 198 and b in (18, 19):  # benchmarking
        return False
    if a >= 224:  # multicast + reserved
        return False
    return True


SENSITIVE_IP_KEY_TOKENS = frozenset(
    {
        "ssh",
        "server",
        "host",
        "endpoint",
        "remote",
        "jump",
        "bastion",
        "backend",
        "ws",
    }
)


def _is_sensitive_ip_key(key: str) -> bool:
    """True when ``key`` names a sensitive connection endpoint."""
    parts = re.split(r"[_-]+", key.lower())
    return any(part in SENSITIVE_IP_KEY_TOKENS for part in parts)


@dataclass(frozen=True)
class Hit:
    rule_id: str
    severity: str
    path: str
    lineno: int
    preview: str


def _redact_line(line: str, start: int, end: int) -> str:
    start = max(0, min(start, len(line)))
    end = max(start, min(end, len(line)))
    return line[:start] + "***" + line[end:]


def _hits_for_text(relpath: str, text: str) -> List[Hit]:
    hits: List[Hit] = []
    for rule in SENSITIVE_RULES:
        rule_id = str(rule["id"])
        pattern = str(rule["pattern"])
        flags = int(rule.get("flags", 0))
        severity = str(rule["severity"])
        for match in re.finditer(pattern, text, flags):
            if rule_id == SENSITIVE_IP_RULE_ID:
                ip = match.group("ip")
                if not _is_public_ipv4(ip) or not _is_sensitive_ip_key(
                    match.group("key")
                ):
                    continue
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            rel_start = match.start() - line_start
            rel_end = min(match.end(), line_end) - line_start
            hits.append(
                Hit(
                    rule_id=rule_id,
                    severity=severity,
                    path=relpath,
                    lineno=text.count("\n", 0, match.start()) + 1,
                    preview=_redact_line(line, rel_start, rel_end),
                )
            )
    return hits


def scan_text(text: str) -> List[Hit]:
    """Scan an in-memory text blob (used by unit tests)."""
    return _hits_for_text("<text>", text)


def scan_files(
    pairs: Sequence[Tuple[str, str]], skip: Sequence[str] = ()
) -> Tuple[List[Hit], int]:
    """Scan ``(relpath, abspath)`` pairs; returns ``(hits, scanned_count)``."""
    skip_set = set(skip)
    hits: List[Hit] = []
    scanned = 0
    for rel, abspath in pairs:
        if rel in skip_set:
            continue
        with open(abspath, "rb") as fh:
            raw = fh.read()
        if b"\x00" in raw[:8192]:
            continue  # binary
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # non-UTF-8 text is not scanned
        scanned += 1
        hits.extend(_hits_for_text(rel, text))
    return hits, scanned
# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _is_git_repo(repo_root: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def collect_candidates(repo_root: str) -> List[str]:
    if not _is_git_repo(repo_root):
        raise BuildError(f"not a git repository: {repo_root}")
    proc = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "-z"],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise BuildError(f"git ls-files failed: {detail}")
    return [
        path
        for path in proc.stdout.decode("utf-8", "replace").split("\0")
        if path
    ]


def select_payload(
    relpaths: Sequence[str],
) -> Tuple[List[str], Dict[str, str]]:
    """Return ``(selected, skipped_reasons)`` for tracked relative paths."""
    selected: List[str] = []
    skipped: Dict[str, str] = {}
    for rel in relpaths:
        rel = _validate_relpath(rel)
        if not _matches(rel, INCLUDE_PATTERNS):
            skipped[rel] = "not-in-allowlist"
        elif _matches(rel, EXCLUDE_PATTERNS):
            skipped[rel] = "excluded"
        else:
            selected.append(rel)
    return sorted(set(selected)), skipped


def _license_guard(payload: Set[str]) -> List[str]:
    return [name for name in REQUIRED_LICENSES if name not in payload]


def _material_notes(payload: Set[str]) -> List[str]:
    notes: List[str] = []
    for rel, what in OPTIONAL_PUBLIC_MATERIALS.items():
        if not any(path == rel or path.startswith(rel + "/") for path in payload):
            notes.append(
                f"not included (not present as tracked files): {rel} ({what})"
            )
    return notes


# ---------------------------------------------------------------------------
# Hashing and manifest
# ---------------------------------------------------------------------------

MANIFEST_HEADER = (
    "# SpriteFusion2D submission manifest\n"
    "# Format: '<sha256-hex>  <relative-path>' (hex, two spaces, POSIX path)\n"
    "# MANIFEST.sha256 does NOT hash itself: it contains no self-entry.\n"
    "# Entries cover every payload file plus FILES.txt and BUILD_RECEIPT.json.\n"
)


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def write_manifest(target_root: str, entries: Sequence[Tuple[str, str]]) -> None:
    parts = [line + "\n" for line in MANIFEST_HEADER.rstrip("\n").splitlines()]
    parts.extend(f"{digest}  {rel}\n" for rel, digest in entries)
    with open(
        os.path.join(target_root, "MANIFEST.sha256"), "w", encoding="utf-8", newline="\n"
    ) as fh:
        fh.write("".join(parts))


def parse_manifest(path: str) -> Dict[str, str]:
    """Parse ``<hex>  <path>`` entries; comments (``#``) are ignored."""
    entries: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                raise BuildError(f"{os.path.basename(path)}:{lineno}: malformed entry")
            entries[parts[1]] = parts[0].lower()
    return entries
# ---------------------------------------------------------------------------
# Target handling
# ---------------------------------------------------------------------------


def _read_previous_build(target_root: str) -> Optional[Set[str]]:
    """Files owned by a previous build of this tool, or None if absent."""
    receipt_path = os.path.join(target_root, "BUILD_RECEIPT.json")
    files_path = os.path.join(target_root, "FILES.txt")
    if not os.path.isfile(receipt_path):
        return None
    owned: Set[str] = set()
    try:
        with open(receipt_path, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
        if receipt.get("tool") != TOOL_NAME:
            return None
        if os.path.isfile(files_path):
            with open(files_path, "r", encoding="utf-8") as fh:
                owned.update(
                    line for line in fh.read().splitlines() if line.strip()
                )
    except (OSError, ValueError):
        return None
    return owned


def prepare_target(target_root: str, force: bool) -> Optional[Set[str]]:
    """Refuse non-empty targets unless ``--force`` over a previous receipt."""
    if os.path.isdir(target_root) and os.listdir(target_root):
        previous = _read_previous_build(target_root)
        if not force or previous is None:
            raise BuildError(
                f"target directory is not empty: {target_root} "
                "(pass --force to rebuild over a previous BUILD_RECEIPT.json)"
            )
        return previous
    return None


def _prune_previous(target_root: str, owned: Set[str]) -> None:
    for rel in sorted(owned, reverse=True):
        path = os.path.join(target_root, rel.replace("/", os.sep))
        if not _is_within(path, target_root):
            raise BuildError(f"previous build entry escapes target: {rel}")
        if os.path.lexists(path):
            try:
                os.remove(path)
            except OSError as exc:
                raise BuildError(
                    f"cannot remove previous build file {rel}: {exc}"
                ) from exc
    for meta in META_FILES:
        path = os.path.join(target_root, meta)
        if os.path.lexists(path):
            os.remove(path)
    for root, dirs, _files in os.walk(target_root, topdown=False):
        for name in dirs:
            candidate = os.path.join(root, name)
            if _is_within(candidate, target_root):
                try:
                    os.rmdir(candidate)
                except OSError:
                    pass  # not empty


def _unowned_files(target_root: str, expected: Set[str]) -> List[str]:
    ok = set(expected) | set(META_FILES)
    stray: List[str] = []
    for root, _dirs, files in os.walk(target_root):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), target_root).replace(
                "\\", "/"
            )
            if rel not in ok:
                stray.append(rel)
    return sorted(stray)


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        moment = datetime.datetime.fromtimestamp(
            int(epoch), tz=datetime.timezone.utc
        )
    else:
        moment = datetime.datetime.now(datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_commit(repo_root: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def build_receipt(
    repo_root: str,
    target_root: str,
    payload: List[str],
    skipped: Dict[str, str],
    scanned: int,
    hits: List[Hit],
    warnings: Sequence[Dict[str, object]],
    notes: Sequence[str],
    strict: bool,
) -> Dict[str, object]:
    errors = [hit for hit in hits if hit.severity == "error"]
    warns = [hit for hit in hits if hit.severity == "warning"]
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "format": "BUILD_RECEIPT.json v1",
        "created_utc": _now_utc(),
        "mode": "strict" if strict else "default",
        "source": {
            "candidates": "git ls-files (tracked files only)",
            "git_commit": _git_commit(repo_root),
        },
        "output": {
            "directory_name": os.path.basename(target_root),
            "payload_files": len(payload),
            "meta_files": list(META_FILES),
        },
        "selection": {
            "skipped_not_in_allowlist": sum(
                1 for reason in skipped.values() if reason == "not-in-allowlist"
            ),
            "skipped_excluded": sum(
                1 for reason in skipped.values() if reason == "excluded"
            ),
        },
        "license_guard": {
            "status": "pass",
            "licenses": list(REQUIRED_LICENSES),
        },
        "sensitive_scan": {
            "scanned_files": scanned,
            "error_hits": len(errors),
            "warning_hits": len(warns),
            "rules": [str(rule["id"]) for rule in SENSITIVE_RULES],
        },
        "manifest": {
            "file": "MANIFEST.sha256",
            "self_hash": "excluded",
            "note": "MANIFEST.sha256 does not hash itself (no self-entry).",
        },
        "warnings": [dict(w) for w in warnings],
        "notes": list(notes),
    }
# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


class Reporter:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet

    def info(self, message: str) -> None:
        if not self.quiet:
            print(message)

    @staticmethod
    def error(message: str) -> None:
        print(f"error: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _run_build(
    repo_root: str,
    target_root: str,
    *,
    dry_run: bool,
    strict: bool,
    force: bool,
    quiet: bool,
) -> int:
    reporter = Reporter(quiet=quiet)
    candidates = collect_candidates(repo_root)
    payload, skipped = select_payload(candidates)
    if not payload:
        raise BuildError("no tracked files selected by the allowlist")
    reserved = [name for name in META_FILES if name in payload]
    if reserved:
        raise BuildError(
            "payload conflicts with reserved meta file name(s): "
            + ", ".join(reserved)
        )
    _reject_symlink_sources(repo_root, payload)

    pairs = [
        (rel, os.path.join(repo_root, rel.replace("/", os.sep))) for rel in payload
    ]
    hits, scanned = scan_files(pairs, skip=SELF_SKIP_PATHS)
    errors = [hit for hit in hits if hit.severity == "error"]
    warns = [hit for hit in hits if hit.severity == "warning"]
    missing_licenses = _license_guard(set(payload))
    notes = _material_notes(set(payload))

    if errors:
        for hit in errors:
            reporter.error(
                f"({hit.rule_id}) {hit.path}:{hit.lineno}: {hit.preview}"
            )
        return 1
    if strict and warns:
        for hit in warns:
            reporter.error(
                f"--strict: ({hit.rule_id}) {hit.path}:{hit.lineno}: {hit.preview}"
            )
        return 1
    if missing_licenses:
        for name in missing_licenses:
            reporter.error(
                f"license guard: required license is missing from the payload: {name}"
            )
        return 1

    target_state = "does not exist"
    if os.path.isdir(target_root) and os.listdir(target_root):
        target_state = "exists and is not empty (a real build needs --force)"
    reporter.info("== SpriteFusion2D submission builder ==")
    reporter.info(f"repo:               {repo_root}")
    reporter.info("mode:               " + ("dry-run" if dry_run else "build"))
    reporter.info(f"git commit:         {_git_commit(repo_root) or 'n/a'}")
    reporter.info(f"tracked candidates: {len(candidates)}")
    reporter.info(f"included payload:   {len(payload)} files")
    reporter.info(
        "excluded:           "
        f"{len(skipped)} tracked files "
        "(not-in-allowlist: "
        f"{sum(1 for r in skipped.values() if r == 'not-in-allowlist')}, "
        f"carve-outs: {sum(1 for r in skipped.values() if r == 'excluded')})"
    )
    reporter.info(
        "sensitive scan:     "
        f"{scanned} text files scanned; {len(errors)} error(s), "
        f"{len(warns)} warning(s)"
    )
    reporter.info("license guard:      pass (" + ", ".join(REQUIRED_LICENSES) + ")")
    for note in notes:
        reporter.info(f"note:               {note}")
    reporter.info(f"target:             {target_root} ({target_state})")
    if dry_run:
        reporter.info("dry-run: nothing was written")
        return 0

    previous = prepare_target(target_root, force)
    if previous is not None:
        reporter.info("rebuild: pruning files from the previous build")
        _prune_previous(target_root, previous)
        stray = _unowned_files(target_root, set(payload))
        if stray:
            raise BuildError(
                "target contains files not owned by a previous build; "
                f"refusing to overwrite: {', '.join(stray[:5])}"
            )
    os.makedirs(target_root, exist_ok=True)

    for rel in payload:
        src = os.path.join(repo_root, rel.replace("/", os.sep))
        out = _resolve_output_path(target_root, rel)
        if os.path.islink(out):
            raise BuildError(f"refusing to write through symlink: {rel}")
        _makedirs_safe(target_root, os.path.dirname(out))
        shutil.copyfile(src, out)

    with open(
        os.path.join(target_root, "FILES.txt"), "w", encoding="utf-8", newline="\n"
    ) as fh:
        fh.write("\n".join(payload) + "\n")

    warnings = [
        {"rule": hit.rule_id, "path": hit.path, "line": hit.lineno} for hit in warns
    ]
    receipt = build_receipt(
        repo_root,
        target_root,
        payload,
        skipped,
        scanned,
        hits,
        warnings,
        notes,
        strict,
    )
    with open(
        os.path.join(target_root, "BUILD_RECEIPT.json"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")

    entries: List[Tuple[str, str]] = []
    for rel in sorted(payload):
        entries.append(
            (rel, sha256_file(os.path.join(target_root, rel.replace("/", os.sep))))
        )
    for meta in ("FILES.txt", "BUILD_RECEIPT.json"):
        entries.append((meta, sha256_file(os.path.join(target_root, meta))))
    write_manifest(target_root, entries)

    reporter.info(
        f"wrote:              {os.path.abspath(target_root)} "
        "(FILES.txt, BUILD_RECEIPT.json, MANIFEST.sha256)"
    )
    return 0
def _run_check(target_root: str, *, strict: bool, quiet: bool) -> int:
    reporter = Reporter(quiet=quiet)
    problems: List[str] = []
    manifest_path = os.path.join(target_root, "MANIFEST.sha256")
    files_path = os.path.join(target_root, "FILES.txt")

    if not os.path.isdir(target_root):
        reporter.error(f"check target does not exist: {target_root}")
        return 1

    for meta in META_FILES:
        if not os.path.isfile(os.path.join(target_root, meta)):
            problems.append(f"missing {meta}")
    if problems:
        for problem in problems:
            reporter.error(problem)
        return 1

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            header = fh.read(512)
        entries = parse_manifest(manifest_path)
    except (OSError, BuildError) as exc:
        reporter.error(str(exc))
        return 1

    if "does NOT hash itself" not in header:
        problems.append(
            "MANIFEST.sha256 header is missing the self-hash exclusion note"
        )
    if "MANIFEST.sha256" in entries:
        problems.append(
            "MANIFEST.sha256 contains a self-entry (it must not hash itself)"
        )

    for rel in entries:
        try:
            _validate_relpath(rel)
        except BuildError as exc:
            problems.append(str(exc))

    payload = sorted(rel for rel in entries if rel not in META_FILES)
    for rel in payload:
        path = os.path.join(target_root, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            problems.append(f"manifest entry missing on disk: {rel}")
        elif sha256_file(path) != entries[rel]:
            problems.append(f"hash mismatch: {rel}")

    for meta in ("FILES.txt", "BUILD_RECEIPT.json"):
        path = os.path.join(target_root, meta)
        if not os.path.isfile(path):
            problems.append(f"missing {meta}")
        elif sha256_file(path) != entries.get(meta, ""):
            problems.append(f"hash mismatch: {meta}")

    try:
        with open(files_path, "r", encoding="utf-8") as fh:
            listed = [line for line in fh.read().splitlines() if line.strip()]
    except OSError as exc:
        problems.append(f"cannot read FILES.txt: {exc}")
        listed = []
    if listed != payload:
        problems.append("FILES.txt does not match the manifest payload")

    missing_licenses = _license_guard(set(payload))
    for name in missing_licenses:
        problems.append(f"license guard: missing {name}")

    for rel in _unowned_files(target_root, set(payload)):
        problems.append(f"stray file not owned by the build: {rel}")

    pairs = [
        (rel, os.path.join(target_root, rel.replace("/", os.sep))) for rel in payload
    ]
    hits, scanned = scan_files(pairs, skip=SELF_SKIP_PATHS)
    for hit in hits:
        if hit.severity == "error":
            problems.append(
                f"sensitive scan: ({hit.rule_id}) {hit.path}:{hit.lineno}: "
                f"{hit.preview}"
            )
        elif strict:
            problems.append(
                f"--strict: ({hit.rule_id}) {hit.path}:{hit.lineno}: {hit.preview}"
            )

    if problems:
        for problem in problems:
            reporter.error(problem)
        return 1

    reporter.info("== SpriteFusion2D submission check ==")
    reporter.info(f"target:             {os.path.abspath(target_root)}")
    reporter.info(
        f"verified:           {len(entries)} manifest entries, "
        f"{scanned} text files scanned, all hashes OK"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Build an independent SpriteFusion2D/ submission directory from "
            "git-tracked files using an explicit allowlist."
        ),
    )
    parser.add_argument("--repo", default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--out",
        default=None,
        help=f"output directory (default: <repo>/{DEFAULT_OUT_NAME})",
    )
    parser.add_argument(
        "--check", action="store_true", help="verify an existing build instead of building"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="plan and scan only; write nothing"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat sensitive-scan warnings as build failures",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild over a previous build (requires BUILD_RECEIPT.json)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress informational output"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    return parser.parse_args(argv)


def _main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = os.path.abspath(args.repo)
    target_root = os.path.abspath(
        args.out or os.path.join(repo_root, DEFAULT_OUT_NAME)
    )
    _check_target_safe(repo_root, target_root)
    if args.check:
        if args.dry_run or args.force:
            raise BuildError("--check cannot be combined with --dry-run or --force")
        return _run_check(target_root, strict=args.strict, quiet=args.quiet)
    return _run_build(
        repo_root,
        target_root,
        dry_run=args.dry_run,
        strict=args.strict,
        force=args.force,
        quiet=args.quiet,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return _main(argv)
    except (BuildError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())