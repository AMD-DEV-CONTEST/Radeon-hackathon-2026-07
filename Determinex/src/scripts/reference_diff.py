#!/usr/bin/env python3
"""Reference-binary differential — exec the original tool with each failing test's
input, capture its output, expose as ground truth for the model.

The Docker image `programbench/<iid>:task_cleanroom` ships with the ORIGINAL
tool's compiled binary at `/workspace/executable`. By extracting each failing
test's input (stdin bytes + argv) and running it against this reference, we get
the expected stdout/stderr/returncode for that EXACT input — usable as
"REFERENCE_OUTPUT: ..." injection into the next attempt's prompt.

Public API:
    diff_one_test(image, args, stdin_bytes, timeout=20)
        → {returncode, stdout, stderr, error?}
    extract_run_call(test_code) → {args, stdin}
    diff_batch(image, failures, max_n=8) → list[dict] with reference_output added
"""

from __future__ import annotations

import re
import subprocess
from typing import Any


def extract_run_call(test_code: str) -> dict[str, Any]:
    """Best-effort: parse pytest test body for the executable invocation.

    Recognized patterns (most ProgramBench tests use these helpers):
      - run_executable(input_json, ["-flag", "value"])
      - run_executable(input_bytes)
      - run("--ci", "-direct", stdin=json_input)
      - subprocess.run(['/workspace/executable', ...], input=...)

    Returns {"args": list[str], "stdin": str_or_bytes}.
    Empty dict if no invocation found.
    """
    out: dict[str, Any] = {"args": [], "stdin": ""}

    # Pattern 1: run_executable(<stdin>, [args])  OR run_executable(<stdin>)
    m = re.search(
        r"run_executable\(\s*([^\),]+?)(?:\s*,\s*(\[[^\]]*\]))?\s*\)",
        test_code,
    )
    if m:
        stdin_expr = m.group(1).strip()
        args_expr = (m.group(2) or "[]").strip()
        try:
            args = eval(args_expr, {"__builtins__": {}}, {})  # safe: list literal only
            if isinstance(args, list):
                out["args"] = [str(a) for a in args]
        except Exception:
            pass
        # Resolve stdin: literal string or variable name
        out["stdin"] = _resolve_value(stdin_expr, test_code)
        return out

    # Pattern 2: run("-flag", "-other", stdin=<var>)
    m = re.search(r"\brun\((.*?)\)", test_code, re.DOTALL)
    if m:
        body = m.group(1)
        # Split top-level args by comma (rough — works for string literals)
        toks = _split_top_level_commas(body)
        args: list[str] = []
        stdin_val: Any = ""
        for t in toks:
            t = t.strip()
            if t.startswith("stdin="):
                stdin_val = _resolve_value(t[6:].strip(), test_code)
            elif (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
                args.append(t[1:-1])
        if args or stdin_val:
            out["args"] = args
            out["stdin"] = stdin_val
            return out

    return out


def _resolve_value(expr: str, test_code: str) -> Any:
    """If expr is a literal, parse it. If it's a variable name, find its definition
    in test_code (e.g. `json_input = b'{"foo":"bar"}'`) and return that.
    """
    expr = expr.strip().rstrip(",")
    # Literal bytes/string
    if expr.startswith(("b'", 'b"', "'", '"')):
        try:
            return eval(expr, {"__builtins__": {}}, {})
        except Exception:
            return ""
    # Variable name → grep test_code for `<name> = ...`
    if re.match(r"^[A-Za-z_]\w*$", expr):
        m = re.search(
            rf"\b{re.escape(expr)}\s*=\s*([^\n]+(?:\n[ \t]+[^\n]+)*)",
            test_code,
        )
        if m:
            val_expr = m.group(1).strip()
            # Triple-quoted heredocs
            if val_expr.startswith(('"""', "'''", 'b"""', "b'''")):
                # Find matching closing triple-quote
                quote = val_expr[1:4] if val_expr.startswith("b") else val_expr[:3]
                full = test_code[m.start(1) :]
                end = full.find(quote, 3 + (1 if val_expr.startswith("b") else 0))
                if end > 0:
                    body = full[: end + 3]
                    try:
                        return eval(body, {"__builtins__": {}}, {})
                    except Exception:
                        return body
            try:
                return eval(val_expr, {"__builtins__": {}}, {})
            except Exception:
                return val_expr[:200]
    return ""


def _split_top_level_commas(s: str) -> list[str]:
    """Split string on commas not inside [], (), {}, or quoted strings."""
    out: list[str] = []
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def diff_one_test(image: str, args: list[str], stdin_value: Any, timeout: int = 20) -> dict:
    """Run reference binary in Docker with given args + stdin. Capture output.
    Returns {returncode, stdout, stderr, error}. error="" on success.
    """
    if isinstance(stdin_value, str):
        stdin_bytes = stdin_value.encode("utf-8", errors="replace")
    elif isinstance(stdin_value, bytes):
        stdin_bytes = stdin_value
    else:
        stdin_bytes = str(stdin_value or "").encode("utf-8", errors="replace")
    cmd = ["docker", "run", "--rm", "-i", image, "/workspace/executable"] + list(args)
    try:
        r = subprocess.run(cmd, input=stdin_bytes, capture_output=True, timeout=timeout)
        return {
            "returncode": r.returncode,
            "stdout": r.stdout.decode("utf-8", errors="replace")[:1500],
            "stderr": r.stderr.decode("utf-8", errors="replace")[:600],
            "error": "",
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "", "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "error": f"{type(e).__name__}: {str(e)[:120]}",
        }


def diff_batch(image: str, failures: list[dict], max_n: int = 6) -> list[dict]:
    """For each failure (up to max_n), attempt to extract args+stdin from test_code
    and exec the reference binary. Attach `reference_output` field to the failure.
    Returns the same failures list with new fields added.
    """
    for f in failures[:max_n]:
        invocation = extract_run_call(f.get("test_code", ""))
        if not invocation.get("args") and not invocation.get("stdin"):
            continue  # couldn't extract — skip
        ref = diff_one_test(image, invocation["args"], invocation["stdin"])
        f["reference_invocation"] = {
            "args": invocation["args"][:5],
            "stdin_preview": str(invocation["stdin"])[:200],
        }
        f["reference_output"] = ref
    return failures
