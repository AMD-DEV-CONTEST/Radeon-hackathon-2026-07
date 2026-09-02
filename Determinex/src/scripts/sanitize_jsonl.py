"""
sanitize_jsonl.py — Determinex .jsonl PII scanner and sanitizer

Scans training .jsonl files for patterns that should not appear in
publicly distributed datasets: personal file paths, real email addresses,
SSH key material, and complete private-range IPv4 addresses.

Usage:
    python scripts/sanitize_jsonl.py data/          # scan all .jsonl in dir
    python scripts/sanitize_jsonl.py foo.jsonl      # scan single file
    python scripts/sanitize_jsonl.py data/ --fix    # scan + sanitize in-place

Known false positives (expected, not real PII):
    - ipv4_real: networking code examples (e.g., 192.168.1.1 as a demo router IP,
      10.0.0.0/8 CIDR blocks in sysadmin examples). These are code examples, not
      leaked infrastructure addresses. Review context before deciding to redact.
    - email_real: any real-looking domain not in the exclusion list. Add to the
      exclusion list in _PATTERNS if a new placeholder domain appears in future
      training batches.

Run this script on all new .jsonl before merging into data/ or lora_train.jsonl.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Patterns that must not appear in training data.
# Deliberately narrow — synthetic placeholders (user, name, example.com) are fine.
_PATTERNS: list[tuple[str, str, str]] = [
    # (name, regex, replacement)
    # Real-looking usernames: 3+ chars, not generic placeholder words
    (
        "home_path",
        r"/home/(?!user/|username/|name/|example/)[a-zA-Z][a-zA-Z0-9_-]{2,}/",
        "/home/user/",
    ),
    (
        "users_path_win",
        r"C:[/\\]Users[/\\](?!user[/\\]|username[/\\]|name[/\\]|new[/\\]|admin[/\\]|"
        r"Public[/\\]|Default[/\\]|DefaultAccount[/\\]|WDAGUtility[/\\])[a-zA-Z][a-zA-Z0-9_.-]{2,}[/\\]",
        "C:/Users/user/",
    ),
    ("dev_path", r"C:[/\\]Dev[/\\]", "/workspace/"),
    ("tmp_workspace", r"/tmp/determinex_workspace_[a-zA-Z0-9_-]+/", "/workspace/"),
    ("ssh_privkey", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "[REDACTED_KEY]"),
    ("ssh_pubkey", r"ssh-(rsa|ed25519|ecdsa)\s+AAAA[A-Za-z0-9+/=]{20,}", "[REDACTED_PUBKEY]"),
    # Full IPv4 quads — private ranges with all 4 octets explicitly required
    (
        "ipv4_real",
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b",
        "[REDACTED_IP]",
    ),
    # Real email addresses — exclude obvious placeholder/devops/code-example domains
    (
        "email_real",
        r"\b[a-zA-Z0-9._%+-]+@(?![a-zA-Z0-9.-]*example[a-zA-Z0-9.-]*\.|domain\.|test\.|localhost|"
        r"contoso\.|fabrikam\.|woodgrove\.|corp\.|internal\.|local\.|prod-db\.|staging-db\.|"
        r"dev-db\.|email\.|mail\.)[a-zA-Z0-9.-]{4,}\.[a-zA-Z]{2,}\b",
        "[REDACTED_EMAIL]",
    ),
]

_COMPILED = [(name, re.compile(pat), repl) for name, pat, repl in _PATTERNS]


def scan_value(value: object) -> list[tuple[str, str]]:
    """Return list of (pattern_name, matched_text) for all hits in value."""
    if not isinstance(value, str):
        return []
    hits = []
    for name, rx, _ in _COMPILED:
        for m in rx.finditer(value):
            hits.append((name, m.group()))
    return hits


def sanitize_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    for _, rx, repl in _COMPILED:
        value = rx.sub(repl, value)
    return value


def process_file(path: Path, fix: bool) -> int:
    """Scan (and optionally fix) a .jsonl file. Returns number of dirty lines."""
    dirty = 0
    clean_lines: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                clean_lines.append(raw)
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                clean_lines.append(raw)
                continue

            line_hits: list[tuple[str, str]] = []
            for v in _iter_strings(obj):
                line_hits.extend(scan_value(v))

            if line_hits:
                dirty += 1
                for name, text in line_hits:
                    print(f"  {path}:{lineno}  [{name}]  {text[:80]!r}")

            if fix:
                obj = _sanitize_obj(obj)
            clean_lines.append(json.dumps(obj, ensure_ascii=False))

    if fix and dirty:
        with path.open("w", encoding="utf-8") as fh:
            fh.write("\n".join(clean_lines) + "\n")
        print(f"  -> sanitized {dirty} lines in {path}")

    return dirty


def _iter_strings(obj: object):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item)


def _sanitize_obj(obj: object) -> object:
    if isinstance(obj, str):
        return sanitize_value(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_obj(item) for item in obj]
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan .jsonl files for PII")
    parser.add_argument("targets", nargs="+", help=".jsonl file(s) or director(ies)")
    parser.add_argument("--fix", action="store_true", help="Sanitize hits in-place")
    args = parser.parse_args()

    files: list[Path] = []
    for t in args.targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.jsonl")))
        elif p.suffix == ".jsonl":
            files.append(p)
        else:
            print(f"Skipping {p} (not .jsonl and not a directory)")

    if not files:
        print("No .jsonl files found.")
        sys.exit(0)

    total_dirty = 0
    for f in files:
        hits = process_file(f, fix=args.fix)
        if hits:
            print(f"{f}: {hits} dirty line(s)")
        total_dirty += hits

    if total_dirty:
        verb = "Sanitized" if args.fix else "Found"
        print(f"\n{verb} {total_dirty} dirty line(s) across {len(files)} file(s).")
        if not args.fix:
            print("Re-run with --fix to sanitize in-place.")
        sys.exit(1)
    else:
        print(f"Clean — scanned {len(files)} file(s), 0 issues found.")


if __name__ == "__main__":
    main()
