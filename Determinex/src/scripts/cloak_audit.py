#!/usr/bin/env python3
"""Cloak audit log — chain-of-custody for every cloud-tier (T3) call.

Records every call to a cloud model (DeepSeek, Anthropic, etc.) when
DETERMINEX_CLOAK=1 is set. Each call produces a JSON line:
  {ts, run_name, instance_id, attempt, model, req_sha, req_bytes,
   resp_sha, resp_bytes, latency_s, payload_obfuscated, audit_path}

Light identifier obfuscation: any code blocks inside <compile_error> tags
get function/class/variable identifiers replaced with x_NNNN tokens before
the payload is sent. (Full AST-level cloak lives in determinex_cloak_*.py and
is intended for SWE-bench's repo-edit case, not PB's generation case.)

Public API:
    audit_call(run_name, instance_id, attempt, model, req_text, resp_text,
               latency_s, obfuscated=False) -> Path
        → writes audit record + (optional) full payload to logs/cloak_audit/

    obfuscate_compile_errors(text) -> tuple[str, dict]
        → returns (obfuscated_text, mapping_real_to_token)
        → only touches identifier-shaped tokens inside <compile_error>...</compile_error>

Set DETERMINEX_CLOAK=1 to enable obfuscation; DETERMINEX_CLOAK_AUDIT=1 to enable audit log.
Both default OFF. Orthogonal — you can audit without obfuscating, or vice versa.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
CLOAK_AUDIT_DIR = DETERMINEX_ROOT / "logs" / "cloak_audit"
CLOAK_ON = os.environ.get("DETERMINEX_CLOAK", "0") in ("1", "true", "yes", "on")
AUDIT_ON = os.environ.get("DETERMINEX_CLOAK_AUDIT", "0") in ("1", "true", "yes", "on") or CLOAK_ON
SAVE_FULL_PAYLOADS = os.environ.get("DETERMINEX_CLOAK_SAVE_PAYLOADS", "1") in (
    "1",
    "true",
    "yes",
    "on",
)

# Python keywords + common stdlib names we never obfuscate
_RESERVED = frozenset(
    {
        # Python
        "def",
        "class",
        "return",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "in",
        "and",
        "or",
        "not",
        "import",
        "from",
        "as",
        "with",
        "try",
        "except",
        "finally",
        "raise",
        "yield",
        "lambda",
        "True",
        "False",
        "None",
        "self",
        "cls",
        "pass",
        "break",
        "continue",
        "global",
        "nonlocal",
        "assert",
        "del",
        "is",
        "async",
        "await",
        # Common stdlib
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "bytes",
        "bytearray",
        "open",
        "type",
        "isinstance",
        "hasattr",
        "getattr",
        "setattr",
        "input",
        "format",
        "repr",
        "id",
        "hash",
        "sorted",
        "reversed",
        "enumerate",
        "zip",
        "map",
        "filter",
        "any",
        "all",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "next",
        "iter",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "RuntimeError",
        "FileNotFoundError",
        "OSError",
        "IOError",
        "NotImplementedError",
        "StopIteration",
        "sys",
        "os",
        "json",
        "re",
        "subprocess",
        "argparse",
        "pathlib",
        "Path",
        "time",
        "datetime",
        "io",
        "math",
        "random",
        "string",
        "collections",
        "Counter",
        "defaultdict",
        "main",
        "argv",
        "stdin",
        "stdout",
        "stderr",
        "exit",
        "platform",
        "environ",
        # Shell / common compile.sh
        "bin",
        "bash",
        "echo",
        "cat",
        "cp",
        "mv",
        "rm",
        "chmod",
        "mkdir",
        "cd",
        "ls",
        "grep",
        "sed",
        "awk",
        "find",
        "xargs",
        "sort",
        "uniq",
        "head",
        "tail",
        "executable",
        "compile",
        "src",
        "build",
        "install",
        "true",
        "false",
    }
)

_IDENT_PAT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_COMPILE_ERR_PAT = re.compile(r"<compile_error>(.*?)</compile_error>", re.DOTALL)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def obfuscate_compile_errors(text: str) -> tuple[str, dict[str, str]]:
    """Replace identifier-shaped tokens inside <compile_error> blocks with x_NNNN.

    Returns (new_text, mapping_real_to_token). Only touches the FIRST <compile_error>...</compile_error>
    block (current PB usage only injects one). Idempotent — already-cloaked tokens (x_\\d+)
    are skipped.
    """
    mapping: dict[str, str] = {}
    counter = [0]

    def _obfuscate_block(match: re.Match) -> str:
        body = match.group(1)

        def _rename(m: re.Match) -> str:
            tok = m.group(0)
            if tok in _RESERVED:
                return tok
            if re.fullmatch(r"x_\d+", tok):  # already cloaked
                return tok
            if tok in mapping:
                return mapping[tok]
            counter[0] += 1
            new = f"x_{counter[0]:04d}"
            mapping[tok] = new
            return new

        new_body = _IDENT_PAT.sub(_rename, body)
        return f"<compile_error>{new_body}</compile_error>"

    new_text, n = _COMPILE_ERR_PAT.subn(_obfuscate_block, text)
    return new_text, mapping


def audit_call(
    run_name: str,
    instance_id: str,
    attempt: int,
    model: str,
    req_text: str,
    resp_text: str,
    latency_s: float,
    obfuscated: bool = False,
    obfuscation_map: dict[str, str] | None = None,
) -> Path | None:
    """Append one audit record. Returns the audit file path, or None if AUDIT_ON=False."""
    if not AUDIT_ON:
        return None
    CLOAK_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    ts_str = time.strftime("%Y%m%dT%H%M%S", time.gmtime(ts))
    req_b = req_text.encode("utf-8", errors="replace")
    resp_b = resp_text.encode("utf-8", errors="replace")
    record = {
        "ts": ts,
        "ts_iso": ts_str,
        "run_name": run_name,
        "instance_id": instance_id,
        "attempt": attempt,
        "model": model,
        "req_bytes": len(req_b),
        "req_sha": _sha(req_b),
        "resp_bytes": len(resp_b),
        "resp_sha": _sha(resp_b),
        "latency_s": round(latency_s, 3),
        "obfuscated": obfuscated,
        "n_identifiers_replaced": len(obfuscation_map) if obfuscation_map else 0,
    }
    # JSONL index
    index_path = CLOAK_AUDIT_DIR / f"{run_name}.jsonl"
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    # Optionally save full payload (req + resp + obfuscation map) for verification
    if SAVE_FULL_PAYLOADS:
        payload_dir = CLOAK_AUDIT_DIR / run_name / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = payload_dir / f"{ts_str}_{instance_id}_a{attempt}_{record['req_sha']}.json"
        payload_path.write_text(
            json.dumps(
                {
                    **record,
                    "request": req_text,
                    "response": resp_text,
                    "obfuscation_map": obfuscation_map or {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return payload_path
    return index_path


def summarize(run_name: str) -> str:
    """Read the audit JSONL and produce a human-readable summary."""
    p = CLOAK_AUDIT_DIR / f"{run_name}.jsonl"
    if not p.exists():
        return f"(no audit log at {p})"
    records = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    if not records:
        return f"(audit log empty: {p})"
    by_model: dict[str, int] = {}
    total_req = total_resp = total_idents = 0
    obfuscated_n = 0
    for r in records:
        by_model[r["model"]] = by_model.get(r["model"], 0) + 1
        total_req += r["req_bytes"]
        total_resp += r["resp_bytes"]
        total_idents += r.get("n_identifiers_replaced", 0)
        if r.get("obfuscated"):
            obfuscated_n += 1
    lines = [
        f"=== Cloak audit: {run_name} ===",
        f"Total cloud calls:         {len(records)}",
        f"  obfuscated:              {obfuscated_n}",
        f"  unobfuscated:            {len(records) - obfuscated_n}",
        "By model:                  " + ", ".join(f"{m}={n}" for m, n in by_model.items()),
        f"Total req bytes sent:      {total_req:,}",
        f"Total resp bytes received: {total_resp:,}",
        f"Identifiers cloaked:       {total_idents:,}",
        f"Audit file:                {p}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--summarize", help="run-name to summarize")
    args = ap.parse_args()
    if args.summarize:
        print(summarize(args.summarize))
    else:
        ap.print_help()
