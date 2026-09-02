"""
micro_eval.py — Determinex Student Multi-Concept Evaluator

Ground-truth validation: rustc, go run, python execution — no LLM opinion.

Concepts (20 probes total, 5 per concept):
    count_chars  — Rust   : count char occurrences in &str
    first_even   — Rust   : find first even number in &[i32]
    safe_divide  — Python : divide with None-on-zero, type-annotated
    wrap_error   — Go     : fmt.Errorf %%w error wrapping

Usage:
    python scripts/micro_eval.py                           # all 4 concepts
    python scripts/micro_eval.py --concept count_chars     # one concept
    python scripts/micro_eval.py --model llama3.2:3b --save-baseline
    python scripts/micro_eval.py --compare                 # vs saved baseline
    python scripts/micro_eval.py --verbose                 # show raw output
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="[EVAL] %(message)s")
log = logging.getLogger("eval")

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DETERMINEX_ROOT = _SCRIPTS_DIR.parent
_RESULTS_DIR = _DETERMINEX_ROOT / "logs" / "eval_results"
_BASELINE_FILE = _RESULTS_DIR / "baseline.json"

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# ── Fence stripping ───────────────────────────────────────────────────────────


def _strip_fences(code: str) -> str:
    """Strip markdown code fences and LLM chat template tokens."""
    code = code.strip()
    # Strip markdown fences (handles ```<|eot_id|> trailing variants too)
    code = re.sub(r"^```\w*\s*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n```[^\n]*$", "", code, flags=re.MULTILINE)
    # Strip ALL chat template tokens leaked from training data.
    # Covers LLaMA3/Qwen2.5 special tokens in any combination:
    #   <|eot_id|>, <|eot_id|, <|eot|>, <|eot|, <|/system|>,
    #   <|start_header_id|>...<|end_header_id|>, etc.
    code = re.sub(r"<\|eot(?:_id)?\|>?", "", code)
    code = re.sub(r"<\|/?(?:system|user|assistant|start_header_id|end_header_id)\|>?", "", code)
    # Strip anything after the FIRST occurrence of these tokens (full conversation leakage)
    # Detect: </s>, <s>, or repeated header-start patterns — marks start of leaked training examples
    code = re.sub(r"</?s>.*", "", code, flags=re.DOTALL)
    code = re.sub(r"\n\n(?:system|user|assistant)\n.*", "", code, flags=re.DOTALL)
    return code.strip()


# ── Rust helpers ──────────────────────────────────────────────────────────────


def _extract_rust_main(harness: str) -> str:
    """Return the fn main() block from a Rust harness string."""
    m = re.search(r"fn\s+main\s*\(\s*\)\s*\{", harness)
    return harness[m.start() :] if m else ""


def _extract_rust_fn(code: str, fn_name: str) -> str:
    """
    Extract a complete Rust function by name using brace-depth counting.
    Returns the full `fn foo(...) { ... }` block, or "" if not found.
    """
    sig = re.compile(rf"\bfn\s+{re.escape(fn_name)}\s*\(")
    m = sig.search(code)
    if not m:
        return ""
    pos = m.start()
    while pos < len(code) and code[pos] != "{":
        pos += 1
    if pos >= len(code):
        return ""
    depth, i, start = 0, pos, m.start()
    while i < len(code):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[start : i + 1].strip()
        i += 1
    return code[start:].strip()


def _extract_rust_preamble(harness: str) -> str:
    """
    Extract only `use` declarations from the harness. These must be prepended to
    student code in full-function mode so that imported types (Arc, Mutex, RefCell,
    etc.) are in scope. Function skeleton lines are intentionally excluded — the
    student provides the complete function, so the harness skeleton is not needed.
    """
    use_lines = [line for line in harness.splitlines() if line.strip().startswith("use ")]
    return "\n".join(use_lines)


def compile_and_test_rust(student_code: str, harness: str, fn_name: str) -> tuple[bool, str, str]:
    """
    Compile and run Rust student code.

    Full-function mode  — student wrote a complete `fn <fn_name>(...)` block.
      Prepends harness preamble (use imports) + student function + harness fn main().
      This preserves Arc, Mutex, RefCell etc. that the harness declares.

    Body-injection mode — student wrote only the function body.
      Injects into the harness skeleton at // <<STUDENT_CODE>>.
    """
    cleaned = _strip_fences(student_code)
    fn_code = _extract_rust_fn(cleaned, fn_name)

    if fn_code:
        preamble = _extract_rust_preamble(harness)
        main_block = _extract_rust_main(harness)
        if main_block:
            parts = [p for p in [preamble, fn_code, main_block] if p]
            full_code = "\n\n".join(parts)
        else:
            full_code = harness.replace("// <<STUDENT_CODE>>", student_code)
    else:
        full_code = harness.replace("// <<STUDENT_CODE>>", cleaned)

    return _rustc_run(full_code)


def _rustc_run(full_code: str) -> tuple[bool, str, str]:
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full_code)
        src = f.name
    bin_path = src.replace(".rs", ".exe" if sys.platform == "win32" else ".bin")
    try:
        r = subprocess.run(
            ["rustc", "--edition", "2021", "-o", bin_path, src],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return False, r.stderr[:600], ""
        r2 = subprocess.run([bin_path], capture_output=True, text=True, timeout=10)
        stdout = r2.stdout.strip()
        return (r2.returncode == 0 and bool(stdout)), r2.stderr[:300], stdout
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", ""
    except FileNotFoundError:
        return False, "rustc not found in PATH", ""
    finally:
        for p in (src, bin_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# ── Python helpers ────────────────────────────────────────────────────────────


def compile_and_test_python(student_code: str, harness: str, fn_name: str) -> tuple[bool, str, str]:
    """
    Run Python student code in a test harness.

    The harness uses # <<STUDENT_CODE>> as placeholder.
    Student output is expected to be a complete function def.
    """
    cleaned = _strip_fences(student_code)
    full_code = harness.replace("# <<STUDENT_CODE>>", cleaned)

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full_code)
        src = f.name
    try:
        r = subprocess.run([sys.executable, src], capture_output=True, text=True, timeout=15)
        stdout = r.stdout.strip()
        if r.returncode == 0 and stdout:
            return True, "", stdout
        return False, (r.stderr or r.stdout)[:400], stdout
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", ""
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


# ── Go helpers ────────────────────────────────────────────────────────────────


def _extract_go_fn(code: str, fn_name: str) -> str:
    """
    Extract a complete Go function by name, stripping any package/import
    declarations the student may have included.
    """
    # Remove package and import blocks — harness already provides them
    cleaned = re.sub(r"package\s+\w+\s*\n?", "", code)
    cleaned = re.sub(r"import\s*\(.*?\)", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'import\s+"[^"]*"', "", cleaned)

    sig = re.compile(rf"\bfunc\s+{re.escape(fn_name)}\s*\(")
    m = sig.search(cleaned)
    if not m:
        return ""
    pos, start = m.start(), m.start()
    while pos < len(cleaned) and cleaned[pos] != "{":
        pos += 1
    if pos >= len(cleaned):
        return ""
    depth, i = 0, pos
    while i < len(cleaned):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1].strip()
        i += 1
    return cleaned[start:].strip()


def _normalize_go_fn(fn_code: str) -> str:
    """
    Add explicit semicolons in single-line Go functions at statement boundaries.

    Go's automatic semicolon insertion only fires at line boundaries. Single-line
    multi-statement functions from models are syntactically invalid without explicit
    semicolons. Two main cases:
      1. `} <stmt>` — closing brace of inner block followed by next statement
      2. `) return`  — end of call expression followed by return statement
    """
    if fn_code.count("\n") >= 3:
        return fn_code  # Already multi-line — leave it alone

    # Case 1: } followed by identifier/keyword (not else or }) → add ;
    fn_code = re.sub(r"\}\s+(?!else\b|\})(?=[a-zA-Z_])", "}; ", fn_code)

    # Case 2: ) or identifier/nil followed by return/go/defer/panic → add ;
    _STMT_KW = r"(?:return|go|defer|panic|if|for|select|switch|var|const)\b"
    fn_code = re.sub(rf"\)\s+(?={_STMT_KW})", "); ", fn_code)
    fn_code = re.sub(rf"(?<=\bnil)\s+(?={_STMT_KW})", "; ", fn_code)

    return fn_code


def compile_and_test_go(student_code: str, harness: str, fn_name: str) -> tuple[bool, str, str]:
    """
    Compile and run Go student code.

    Full-function mode — inject student func between harness preamble and func main().
    Body-injection mode — inject into // <<STUDENT_CODE>> placeholder.
    """
    cleaned = _strip_fences(student_code)
    fn_code = _extract_go_fn(cleaned, fn_name)

    if fn_code:
        fn_code = _normalize_go_fn(fn_code)  # Fix single-line semicolon issues
        main_idx = harness.find("func main(")
        if main_idx >= 0:
            preamble = harness[:main_idx].rstrip()
            main_block = harness[main_idx:]
            full_code = preamble + "\n\n" + fn_code + "\n\n" + main_block
        else:
            full_code = harness.replace("// <<STUDENT_CODE>>", cleaned)
    else:
        full_code = harness.replace("// <<STUDENT_CODE>>", cleaned)

    with tempfile.NamedTemporaryFile(suffix=".go", delete=False, mode="w", encoding="utf-8") as f:
        f.write(full_code)
        src = f.name
    try:
        r = subprocess.run(["go", "run", src], capture_output=True, text=True, timeout=30)
        stdout = r.stdout.strip()
        if r.returncode == 0 and stdout:
            return True, "", stdout
        return False, (r.stderr or r.stdout)[:500], stdout
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", ""
    except FileNotFoundError:
        return False, "go not found in PATH", ""
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass


def compile_and_test_typescript(
    student_code: str, harness: str, _fn_name: str
) -> tuple[bool, str, str]:
    """
    Compile and run TypeScript student code via tsc --outDir + node.
    Injects student code at // <<STUDENT_CODE>> placeholder.
    """
    cleaned = _strip_fences(student_code)
    full_code = harness.replace("// <<STUDENT_CODE>>", cleaned)

    _is_win = sys.platform == "win32"
    tmpdir = tempfile.mkdtemp()
    src = os.path.join(tmpdir, "eval.ts")
    with open(src, "w", encoding="utf-8") as f:
        f.write(full_code)

    try:
        # tsc --outDir: works on all platforms, avoids deprecated --outFile
        cmd = [
            "tsc",
            "--module",
            "commonjs",
            "--target",
            "ES2020",
            "--strict",
            "--outDir",
            tmpdir,
            src,
        ]
        rc = subprocess.run(cmd, capture_output=True, text=True, shell=_is_win, timeout=30)
        if rc.returncode != 0:
            return False, (rc.stderr or rc.stdout)[:500], ""
        js_file = os.path.join(tmpdir, "eval.js")
        r = subprocess.run(["node", js_file], capture_output=True, text=True, timeout=30)
        stdout = r.stdout.strip()
        if r.returncode == 0 and stdout:
            return True, "", stdout
        if r.returncode == 0:
            return False, "No output (missing console.log?)", stdout
        return False, (r.stderr or r.stdout)[:500], stdout
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", ""
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Dispatch ──────────────────────────────────────────────────────────────────


def run_probe(student_code: str, probe: dict) -> tuple[bool, str, str]:
    lang = probe["lang"]
    fn = probe["fn_name"]
    h = probe["test_harness"]
    if lang == "rust":
        return compile_and_test_rust(student_code, h, fn)
    if lang == "python":
        return compile_and_test_python(student_code, h, fn)
    if lang == "go":
        return compile_and_test_go(student_code, h, fn)
    if lang == "typescript":
        return compile_and_test_typescript(student_code, h, fn)
    return False, f"Unknown language: {lang}", ""


# ── Concept definitions ───────────────────────────────────────────────────────

CONCEPTS = {
    # ── 1. count_chars (Rust) ─────────────────────────────────────────────────
    "count_chars": {
        "lang": "rust",
        "description": "count_chars(s: &str, target: char) -> usize",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "CC_P1_basic",
                "label": "Basic: count a specific char",
                "lang": "rust",
                "fn_name": "count_chars",
                "prompt": (
                    "Write a Rust function called count_chars that takes a string slice &str "
                    "and a target char, and returns the count of times that char appears in "
                    "the string as usize."
                ),
                "test_harness": """
fn count_chars(s: &str, target: char) -> usize {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(count_chars("hello world", 'l'), 3);
    assert_eq!(count_chars("hello world", 'z'), 0);
    assert_eq!(count_chars("", 'a'), 0);
    assert_eq!(count_chars("aaa", 'a'), 3);
    println!("CC_P1 PASS");
}
""",
            },
            {
                "id": "CC_P2_empty",
                "label": "Edge case: empty string returns 0",
                "lang": "rust",
                "fn_name": "count_chars",
                "prompt": (
                    "Write a Rust function count_chars(s: &str, target: char) -> usize that "
                    "counts how many times target appears in s. It must return 0 for an empty string."
                ),
                "test_harness": """
fn count_chars(s: &str, target: char) -> usize {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(count_chars("", 'x'), 0, "empty string failed");
    assert_eq!(count_chars("x", 'x'), 1, "single char failed");
    assert_eq!(count_chars("xyz", 'z'), 1, "last char failed");
    println!("CC_P2 PASS");
}
""",
            },
            {
                "id": "CC_P3_unicode",
                "label": "Unicode: multi-byte chars",
                "lang": "rust",
                "fn_name": "count_chars",
                "prompt": (
                    "Write a Rust function count_chars(s: &str, target: char) -> usize. "
                    "It must correctly handle Unicode characters, not just ASCII bytes."
                ),
                "test_harness": """
fn count_chars(s: &str, target: char) -> usize {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(count_chars("caf\u00e9 caf\u00e9", '\u00e9'), 2);
    assert_eq!(count_chars("hello", 'l'), 2);
    println!("CC_P3 PASS");
}
""",
            },
            {
                "id": "CC_P4_idiomatic",
                "label": "Idiomatic: iterator style",
                "lang": "rust",
                "fn_name": "count_chars",
                "prompt": (
                    "Write a Rust function count_chars(s: &str, target: char) -> usize "
                    "using idiomatic Rust iterator style (no explicit for loop)."
                ),
                "test_harness": """
fn count_chars(s: &str, target: char) -> usize {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(count_chars("mississippi", 's'), 4);
    assert_eq!(count_chars("mississippi", 'p'), 2);
    println!("CC_P4 PASS");
}
""",
            },
            {
                "id": "CC_P5_rename",
                "label": "Concept transfer: renamed function",
                "lang": "rust",
                "fn_name": "char_frequency",
                "prompt": (
                    "Write a Rust function named char_frequency that accepts a text: &str "
                    "and a ch: char and returns how many times ch appears in text, as usize."
                ),
                "test_harness": """
fn char_frequency(text: &str, ch: char) -> usize {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(char_frequency("banana", 'a'), 3);
    assert_eq!(char_frequency("banana", 'n'), 2);
    assert_eq!(char_frequency("banana", 'z'), 0);
    println!("CC_P5 PASS");
}
""",
            },
        ],
    },
    # ── 2. first_even (Rust) ──────────────────────────────────────────────────
    "first_even": {
        "lang": "rust",
        "description": "first_even(nums: &[i32]) -> Option<i32>",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "FE_P1_basic",
                "label": "Basic: mixed slice",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even that takes a slice of i32 values (&[i32]) "
                    "and returns the first even number wrapped in Some, or None if no even number exists."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[1, 2, 3, 4]), Some(2));
    assert_eq!(first_even(&[1, 3, 5]), None);
    assert_eq!(first_even(&[7, 4, 2]), Some(4));
    println!("FE_P1 PASS");
}
""",
            },
            {
                "id": "FE_P2_empty",
                "label": "Edge case: empty slice returns None",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32> that returns "
                    "the first even number in the slice, or None if the slice is empty or has no even numbers."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[]), None, "empty slice must return None");
    assert_eq!(first_even(&[2]), Some(2), "single even failed");
    assert_eq!(first_even(&[1]), None, "single odd failed");
    println!("FE_P2 PASS");
}
""",
            },
            {
                "id": "FE_P3_all_odd",
                "label": "All odd: returns None",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32>. "
                    "If every number in the slice is odd, return None."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[1, 3, 5, 7, 9]), None);
    assert_eq!(first_even(&[11, 13, 15]), None);
    assert_eq!(first_even(&[1, 3, 5, 8]), Some(8));
    println!("FE_P3 PASS");
}
""",
            },
            {
                "id": "FE_P4_first_is_even",
                "label": "First element is even",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32> that returns "
                    "the first even number. It must return the FIRST one, not any other."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[2, 1, 3, 5]), Some(2), "first element is even");
    assert_eq!(first_even(&[2, 4, 6]), Some(2), "should return 2 not 4");
    assert_eq!(first_even(&[1, 2, 4, 6]), Some(2), "should skip 1 and return 2");
    println!("FE_P4 PASS");
}
""",
            },
            {
                "id": "FE_P5_negative",
                "label": "Negative even numbers",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32>. "
                    "It must correctly identify negative even numbers (e.g., -2 is even)."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[-3, -2, -1]), Some(-2));
    assert_eq!(first_even(&[-1, -3, -5]), None);
    assert_eq!(first_even(&[0, 1, 2]), Some(0), "zero is even");
    println!("FE_P5 PASS");
}
""",
            },
        ],
    },
    # ── 3. safe_divide (Python) ───────────────────────────────────────────────
    "safe_divide": {
        "lang": "python",
        "description": "safe_divide(a: float, b: float) -> Optional[float]",
        "system": (
            "You are an expert Python programmer. Write clean, type-annotated Python. "
            "Output ONLY the Python function — no markdown fences, no preamble, no explanation."
        ),
        "probes": [
            {
                "id": "SD_P1_basic",
                "label": "Basic: normal division",
                "lang": "python",
                "fn_name": "safe_divide",
                "prompt": (
                    "Write a Python function safe_divide(a: float, b: float) -> Optional[float] "
                    "that returns a divided by b if b is not zero, or None if b is zero. "
                    "Import Optional from typing."
                ),
                "test_harness": """from typing import Optional

# <<STUDENT_CODE>>

assert safe_divide(10.0, 2.0) == 5.0, f"Expected 5.0, got {safe_divide(10.0, 2.0)}"
assert safe_divide(6.0, 3.0) == 2.0, f"Expected 2.0, got {safe_divide(6.0, 3.0)}"
assert safe_divide(1.0, 4.0) == 0.25, f"Expected 0.25, got {safe_divide(1.0, 4.0)}"
print("SD_P1 PASS")
""",
            },
            {
                "id": "SD_P2_zero_divisor",
                "label": "Zero divisor returns None",
                "lang": "python",
                "fn_name": "safe_divide",
                "prompt": (
                    "Write a Python function safe_divide(a: float, b: float) -> Optional[float]. "
                    "If b is zero, return None instead of raising an exception."
                ),
                "test_harness": """from typing import Optional

# <<STUDENT_CODE>>

assert safe_divide(5.0, 0.0) is None, "zero divisor must return None"
assert safe_divide(0.0, 0.0) is None, "0/0 must return None"
assert safe_divide(100.0, 0.0) is None, "100/0 must return None"
print("SD_P2 PASS")
""",
            },
            {
                "id": "SD_P3_zero_dividend",
                "label": "Zero dividend returns 0.0, not None",
                "lang": "python",
                "fn_name": "safe_divide",
                "prompt": (
                    "Write a Python function safe_divide(a: float, b: float) -> Optional[float]. "
                    "Return None only when b is zero. If a is zero but b is nonzero, return 0.0."
                ),
                "test_harness": """from typing import Optional

# <<STUDENT_CODE>>

assert safe_divide(0.0, 5.0) == 0.0, f"0/5 should be 0.0, got {safe_divide(0.0, 5.0)}"
assert safe_divide(0.0, -3.0) == 0.0, f"0/-3 should be 0.0"
assert safe_divide(0.0, 0.0) is None, "0/0 should be None"
print("SD_P3 PASS")
""",
            },
            {
                "id": "SD_P4_negative",
                "label": "Negative numbers",
                "lang": "python",
                "fn_name": "safe_divide",
                "prompt": (
                    "Write a Python function safe_divide(a: float, b: float) -> Optional[float] "
                    "that handles negative inputs correctly."
                ),
                "test_harness": """from typing import Optional

# <<STUDENT_CODE>>

assert safe_divide(-6.0, 2.0) == -3.0, f"Expected -3.0, got {safe_divide(-6.0, 2.0)}"
assert safe_divide(-6.0, -2.0) == 3.0, f"Expected 3.0, got {safe_divide(-6.0, -2.0)}"
assert safe_divide(6.0, -2.0) == -3.0, f"Expected -3.0, got {safe_divide(6.0, -2.0)}"
print("SD_P4 PASS")
""",
            },
            {
                "id": "SD_P5_rename",
                "label": "Concept transfer: renamed function",
                "lang": "python",
                "fn_name": "find_quotient",
                "prompt": (
                    "Write a Python function find_quotient(numerator: float, denominator: float) -> Optional[float] "
                    "that returns the result of dividing numerator by denominator, "
                    "or None if denominator is zero. Import Optional from typing."
                ),
                "test_harness": """from typing import Optional

# <<STUDENT_CODE>>

assert find_quotient(10.0, 2.0) == 5.0
assert find_quotient(5.0, 0.0) is None
assert find_quotient(-9.0, 3.0) == -3.0
print("SD_P5 PASS")
""",
            },
        ],
    },
    # ── 4. wrap_error (Go) ────────────────────────────────────────────────────
    "wrap_error": {
        "lang": "go",
        "description": "wrap_error(msg string, err error) error",
        "system": (
            "You are an expert Go programmer. Write idiomatic Go. "
            "Output ONLY the Go function — no package declaration, no imports, no main, "
            "no explanation. Use fmt.Errorf with %%w for wrapping."
        ),
        "probes": [
            {
                "id": "WE_P1_basic",
                "label": "Basic: errors.Is chain works after wrap",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function wrap_error(msg string, err error) error that returns "
                    "a new error wrapping err with the message msg, using fmt.Errorf with %%w."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("base error")
\twrapped := wrap_error("context", base)
\tif !errors.Is(wrapped, base) {
\t\tpanic("errors.Is failed — must use %%w in fmt.Errorf")
\t}
\tfmt.Println("WE_P1 PASS")
}
""",
            },
            {
                "id": "WE_P2_message",
                "label": "Wrapped message contains both parts",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function wrap_error(msg string, err error) error. "
                    "The returned error's message must contain both msg and the original error message."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
\t"strings"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("file not found")
\twrapped := wrap_error("open config", base)
\tmsg := wrapped.Error()
\tif !strings.Contains(msg, "open config") {
\t\tpanic(fmt.Sprintf("message missing context: got %%q", msg))
\t}
\tif !strings.Contains(msg, "file not found") {
\t\tpanic(fmt.Sprintf("message missing original: got %%q", msg))
\t}
\tfmt.Println("WE_P2 PASS")
}
""",
            },
            {
                "id": "WE_P3_double_wrap",
                "label": "Double-wrapped: errors.Is reaches base",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function wrap_error(msg string, err error) error using fmt.Errorf %%w. "
                    "The wrap must be transitive — errors.Is should find the original error through multiple wrapping layers."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("root cause")
\twrap1 := wrap_error("layer 1", base)
\twrap2 := wrap_error("layer 2", wrap1)
\tif !errors.Is(wrap2, base) {
\t\tpanic("errors.Is failed to reach root through double wrap")
\t}
\tif !errors.Is(wrap2, wrap1) {
\t\tpanic("errors.Is failed to reach layer 1")
\t}
\tfmt.Println("WE_P3 PASS")
}
""",
            },
            {
                "id": "WE_P4_unwrap",
                "label": "errors.Unwrap returns the original",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function wrap_error(msg string, err error) error. "
                    "The returned error must implement Unwrap() so that errors.Unwrap returns the original err."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("original")
\twrapped := wrap_error("context", base)
\tunwrapped := errors.Unwrap(wrapped)
\tif unwrapped != base {
\t\tpanic(fmt.Sprintf("Unwrap returned %%v, want %%v", unwrapped, base))
\t}
\tfmt.Println("WE_P4 PASS")
}
""",
            },
            {
                "id": "WE_P5_rename",
                "label": "Concept transfer: renamed function",
                "lang": "go",
                "fn_name": "wrap_err",
                "prompt": (
                    "Write a Go function named wrap_err(context string, cause error) error "
                    "that wraps cause with context using fmt.Errorf %%w. "
                    "errors.Is must work on the result."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("disk full")
\twrapped := wrap_err("write file", base)
\tif !errors.Is(wrapped, base) {
\t\tpanic("errors.Is failed on renamed function")
\t}
\tfmt.Println("WE_P5 PASS")
}
""",
            },
        ],
    },
    # ── 5. arc_mutex (Rust) ───────────────────────────────────────────────────
    "arc_mutex": {
        "lang": "rust",
        "description": "count_concurrent(data: Vec<i32>) -> i32  [Arc<Mutex<>>]",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation. "
            "Include all necessary use statements inside the function or at the top of your output."
        ),
        "probes": [
            {
                "id": "AM_P1_basic",
                "label": "Basic: Arc<Mutex<i32>> shared counter across threads",
                "lang": "rust",
                "fn_name": "count_concurrent",
                "prompt": (
                    "Write a Rust function count_concurrent(data: Vec<i32>) -> i32 that uses "
                    "Arc<Mutex<i32>> and std::thread::spawn to sum all values in data across "
                    "multiple threads. Return the total sum. Include use statements for Arc, Mutex, and thread."
                ),
                "test_harness": """use std::sync::{Arc, Mutex};
use std::thread;

// <<STUDENT_CODE>>

fn main() {
    assert_eq!(count_concurrent(vec![1, 2, 3, 4, 5]), 15);
    assert_eq!(count_concurrent(vec![10, 20]), 30);
    assert_eq!(count_concurrent(vec![]), 0);
    println!("AM_P1 PASS");
}
""",
            },
            {
                "id": "AM_P2_correct_sum",
                "label": "Correct sum with race-free accumulation",
                "lang": "rust",
                "fn_name": "count_concurrent",
                "prompt": (
                    "Write a Rust function count_concurrent(data: Vec<i32>) -> i32. "
                    "Use Arc<Mutex<i32>> so multiple threads safely add their values. "
                    "All threads must join before returning. Include use statements."
                ),
                "test_harness": """use std::sync::{Arc, Mutex};
use std::thread;

// <<STUDENT_CODE>>

fn main() {
    let result = count_concurrent(vec![100, 200, 300]);
    assert_eq!(result, 600, "expected 600 got {}", result);
    let result2 = count_concurrent(vec![-1, -2, -3]);
    assert_eq!(result2, -6, "negative sum failed");
    println!("AM_P2 PASS");
}
""",
            },
            {
                "id": "AM_P3_large",
                "label": "Large dataset, no data races",
                "lang": "rust",
                "fn_name": "count_concurrent",
                "prompt": (
                    "Write a Rust function count_concurrent(data: Vec<i32>) -> i32 using "
                    "Arc<Mutex<i32>> for thread-safe accumulation. The function must handle "
                    "any size of input correctly without data races."
                ),
                "test_harness": """use std::sync::{Arc, Mutex};
use std::thread;

// <<STUDENT_CODE>>

fn main() {
    let data: Vec<i32> = (1..=100).collect();
    let expected: i32 = (1..=100).sum();
    let result = count_concurrent(data);
    assert_eq!(result, expected, "sum 1..=100 failed: got {}", result);
    println!("AM_P3 PASS");
}
""",
            },
            {
                "id": "AM_P4_empty",
                "label": "Edge case: empty vec returns 0",
                "lang": "rust",
                "fn_name": "count_concurrent",
                "prompt": (
                    "Write a Rust function count_concurrent(data: Vec<i32>) -> i32 using "
                    "Arc<Mutex<i32>> and threads. Must return 0 for an empty input."
                ),
                "test_harness": """use std::sync::{Arc, Mutex};
use std::thread;

// <<STUDENT_CODE>>

fn main() {
    assert_eq!(count_concurrent(vec![]), 0, "empty must return 0");
    assert_eq!(count_concurrent(vec![42]), 42, "single element failed");
    println!("AM_P4 PASS");
}
""",
            },
            {
                "id": "AM_P5_rename",
                "label": "Concept transfer: renamed to parallel_sum",
                "lang": "rust",
                "fn_name": "parallel_sum",
                "prompt": (
                    "Write a Rust function named parallel_sum(values: Vec<i32>) -> i32 that "
                    "uses Arc<Mutex<i32>> and std::thread::spawn to sum all values concurrently. "
                    "Join all threads before returning the total."
                ),
                "test_harness": """use std::sync::{Arc, Mutex};
use std::thread;

// <<STUDENT_CODE>>

fn main() {
    assert_eq!(parallel_sum(vec![1, 2, 3, 4, 5]), 15);
    assert_eq!(parallel_sum(vec![7, 7, 7]), 21);
    println!("AM_P5 PASS");
}
""",
            },
        ],
    },
    # ── 6. refcell_borrow (Rust) ──────────────────────────────────────────────
    "refcell_borrow": {
        "lang": "rust",
        "description": "append_all(cell: &RefCell<Vec<i32>>, items: &[i32])",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation. "
            "Include all necessary use statements."
        ),
        "probes": [
            {
                "id": "RB_P1_basic",
                "label": "Basic: borrow_mut to push items",
                "lang": "rust",
                "fn_name": "append_all",
                "prompt": (
                    "Write a Rust function append_all(cell: &RefCell<Vec<i32>>, items: &[i32]) "
                    "that borrows the RefCell mutably and appends all items to the Vec inside. "
                    "Include 'use std::cell::RefCell;' in your output."
                ),
                "test_harness": """use std::cell::RefCell;

// <<STUDENT_CODE>>

fn main() {
    let cell = RefCell::new(vec![1, 2, 3]);
    append_all(&cell, &[4, 5, 6]);
    assert_eq!(*cell.borrow(), vec![1, 2, 3, 4, 5, 6]);
    println!("RB_P1 PASS");
}
""",
            },
            {
                "id": "RB_P2_empty",
                "label": "Appending to empty RefCell vec",
                "lang": "rust",
                "fn_name": "append_all",
                "prompt": (
                    "Write a Rust function append_all(cell: &RefCell<Vec<i32>>, items: &[i32]). "
                    "Use cell.borrow_mut() to mutably access the inner Vec and extend it with items. "
                    "Include use std::cell::RefCell."
                ),
                "test_harness": """use std::cell::RefCell;

// <<STUDENT_CODE>>

fn main() {
    let cell = RefCell::new(vec![]);
    append_all(&cell, &[10, 20, 30]);
    assert_eq!(*cell.borrow(), vec![10, 20, 30], "empty->filled failed");
    append_all(&cell, &[]);
    assert_eq!(*cell.borrow(), vec![10, 20, 30], "empty items changed vec");
    println!("RB_P2 PASS");
}
""",
            },
            {
                "id": "RB_P3_multiple_borrows",
                "label": "Multiple sequential borrow_mut calls",
                "lang": "rust",
                "fn_name": "append_all",
                "prompt": (
                    "Write a Rust function append_all(cell: &RefCell<Vec<i32>>, items: &[i32]) "
                    "that uses RefCell::borrow_mut to push all items. The function must release "
                    "the borrow before returning so it can be called multiple times."
                ),
                "test_harness": """use std::cell::RefCell;

// <<STUDENT_CODE>>

fn main() {
    let cell = RefCell::new(vec![]);
    append_all(&cell, &[1, 2]);
    append_all(&cell, &[3, 4]);
    append_all(&cell, &[5]);
    assert_eq!(*cell.borrow(), vec![1, 2, 3, 4, 5]);
    println!("RB_P3 PASS");
}
""",
            },
            {
                "id": "RB_P4_read_after",
                "label": "borrow() readable after borrow_mut completes",
                "lang": "rust",
                "fn_name": "append_all",
                "prompt": (
                    "Write a Rust function append_all(cell: &RefCell<Vec<i32>>, items: &[i32]). "
                    "After calling it, the RefCell must be readable via borrow(). "
                    "Include use std::cell::RefCell."
                ),
                "test_harness": """use std::cell::RefCell;

// <<STUDENT_CODE>>

fn main() {
    let cell = RefCell::new(vec![1]);
    append_all(&cell, &[2, 3]);
    let v = cell.borrow();
    assert_eq!(v.len(), 3);
    assert_eq!(v[0], 1);
    assert_eq!(v[2], 3);
    println!("RB_P4 PASS");
}
""",
            },
            {
                "id": "RB_P5_rename",
                "label": "Concept transfer: renamed to push_into_cell",
                "lang": "rust",
                "fn_name": "push_into_cell",
                "prompt": (
                    "Write a Rust function named push_into_cell(storage: &RefCell<Vec<i32>>, new_items: &[i32]) "
                    "that appends new_items into the RefCell's Vec using borrow_mut. "
                    "Include use std::cell::RefCell."
                ),
                "test_harness": """use std::cell::RefCell;

// <<STUDENT_CODE>>

fn main() {
    let storage = RefCell::new(vec![]);
    push_into_cell(&storage, &[7, 8, 9]);
    assert_eq!(*storage.borrow(), vec![7, 8, 9]);
    println!("RB_P5 PASS");
}
""",
            },
        ],
    },
    # ── 7. go_panic_recover (Go) ──────────────────────────────────────────────
    "go_panic_recover": {
        "lang": "go",
        "description": "safe_call(fn func()) (err error)  [recover from panic]",
        "system": (
            "You are an expert Go programmer. Write idiomatic Go. "
            "Output ONLY the Go function — no package declaration, no imports, no main, "
            "no explanation. Use recover() inside a deferred function to catch panics."
        ),
        "probes": [
            {
                "id": "GP_P1_basic",
                "label": "Basic: recover panic and return error",
                "lang": "go",
                "fn_name": "safe_call",
                "prompt": (
                    "Write a Go function safe_call(fn func()) (err error) that calls fn() "
                    "and recovers from any panic, returning it as an error. "
                    "If fn does not panic, return nil. Use defer and recover()."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\terr := safe_call(func() { panic("something went wrong") })
\tif err == nil {
\t\tpanic("expected error from panic, got nil")
\t}
\terr2 := safe_call(func() {})
\tif err2 != nil {
\t\tpanic(fmt.Sprintf("expected nil, got: %v", err2))
\t}
\t_ = errors.New("ok")
\tfmt.Println("GP_P1 PASS")
}
""",
            },
            {
                "id": "GP_P2_string_panic",
                "label": "String panic message preserved in error",
                "lang": "go",
                "fn_name": "safe_call",
                "prompt": (
                    "Write a Go function safe_call(fn func()) (err error). "
                    "When fn panics with a string, the returned error message must contain that string. "
                    "Use defer/recover. No panic should escape the function."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"strings"
)

// <<STUDENT_CODE>>

func main() {
\terr := safe_call(func() { panic("disk full") })
\tif err == nil {
\t\tpanic("expected non-nil error")
\t}
\tif !strings.Contains(err.Error(), "disk full") {
\t\tpanic(fmt.Sprintf("error missing panic message: got %q", err.Error()))
\t}
\tfmt.Println("GP_P2 PASS")
}
""",
            },
            {
                "id": "GP_P3_no_panic",
                "label": "No panic returns nil",
                "lang": "go",
                "fn_name": "safe_call",
                "prompt": (
                    "Write a Go function safe_call(fn func()) (err error) that uses defer/recover. "
                    "If fn executes without panicking, the function must return nil."
                ),
                "test_harness": """package main

import "fmt"

// <<STUDENT_CODE>>

func main() {
\tcalled := false
\terr := safe_call(func() { called = true })
\tif err != nil {
\t\tpanic(fmt.Sprintf("expected nil, got %v", err))
\t}
\tif !called {
\t\tpanic("fn was not called")
\t}
\tfmt.Println("GP_P3 PASS")
}
""",
            },
            {
                "id": "GP_P4_error_panic",
                "label": "Panic with error value",
                "lang": "go",
                "fn_name": "safe_call",
                "prompt": (
                    "Write a Go function safe_call(fn func()) (err error). "
                    "Handle the case where fn panics with an error value (not just a string). "
                    "The recovered error should be returned directly if it is already an error type."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tsentinel := errors.New("sentinel error")
\terr := safe_call(func() { panic(sentinel) })
\tif err == nil {
\t\tpanic("expected error, got nil")
\t}
\tfmt.Println("GP_P4 PASS")
}
""",
            },
            {
                "id": "GP_P5_rename",
                "label": "Concept transfer: renamed to catch_panic",
                "lang": "go",
                "fn_name": "catch_panic",
                "prompt": (
                    "Write a Go function named catch_panic(f func()) (err error) that uses "
                    "defer and recover() to catch any panic from f and return it as an error. "
                    "Return nil if f completes without panicking."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
\t"strings"
)

// <<STUDENT_CODE>>

func main() {
\terr := catch_panic(func() { panic("test panic") })
\tif err == nil {
\t\tpanic("expected non-nil error from panic")
\t}
\tif !strings.Contains(err.Error(), "test panic") {
\t\tpanic(fmt.Sprintf("message not preserved: %q", err.Error()))
\t}
\terr2 := catch_panic(func() {})
\tif err2 != nil {
\t\tpanic(fmt.Sprintf("clean fn returned error: %v", err2))
\t}
\t_ = errors.New
\tfmt.Println("GP_P5 PASS")
}
""",
            },
        ],
    },
    # ── 8. go_fmt_errorf (Go) ─────────────────────────────────────────────────
    "go_fmt_errorf": {
        "lang": "go",
        "description": "wrap_error(msg string, err error) error  [fmt.Errorf %%w]",
        "system": (
            "You are an expert Go programmer. Write idiomatic Go. "
            "Output ONLY the Go function definition — no package declaration, no imports, "
            "no func main, no explanation. The function must be named exactly as specified "
            "in the prompt and use fmt.Errorf with %%w to wrap errors."
        ),
        "probes": [
            {
                "id": "GF_P1_basic",
                "label": "Basic: fmt.Errorf with %w wraps correctly",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function named wrap_error with signature: "
                    "wrap_error(msg string, err error) error\n"
                    'It must return fmt.Errorf("%s: %w", msg, err). '
                    "Output only the function definition, nothing else."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("base error")
\twrapped := wrap_error("context", base)
\tif !errors.Is(wrapped, base) {
\t\tpanic("errors.Is failed — must use %%w in fmt.Errorf")
\t}
\tfmt.Println("GF_P1 PASS")
}
""",
            },
            {
                "id": "GF_P2_message",
                "label": "Wrapped error message contains msg and original",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function named wrap_error(msg string, err error) error. "
                    'Use fmt.Errorf("%s: %w", msg, err). The returned error.Error() string '
                    "must contain both msg and the original error text. Output only the function."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
\t"strings"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("file not found")
\twrapped := wrap_error("open config", base)
\tmsg := wrapped.Error()
\tif !strings.Contains(msg, "open config") || !strings.Contains(msg, "file not found") {
\t\tpanic(fmt.Sprintf("message wrong: got %%q", msg))
\t}
\tfmt.Println("GF_P2 PASS")
}
""",
            },
            {
                "id": "GF_P3_chain",
                "label": "Double-wrapped: errors.Is reaches root",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function named wrap_error(msg string, err error) error "
                    "using fmt.Errorf with %%w. When called twice, errors.Is must reach "
                    "the original error through the chain. Output only the function definition."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("root")
\twrap1 := wrap_error("layer1", base)
\twrap2 := wrap_error("layer2", wrap1)
\tif !errors.Is(wrap2, base) {
\t\tpanic("errors.Is failed through double wrap")
\t}
\tfmt.Println("GF_P3 PASS")
}
""",
            },
            {
                "id": "GF_P4_nil_safe",
                "label": "Nil error input returns nil",
                "lang": "go",
                "fn_name": "wrap_error",
                "prompt": (
                    "Write a Go function named wrap_error(msg string, err error) error. "
                    'If err is nil, return nil. Otherwise return fmt.Errorf("%s: %w", msg, err). '
                    "Output only the function definition."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tif wrap_error("ctx", nil) != nil {
\t\tpanic("nil input must return nil")
\t}
\tbase := errors.New("oops")
\twrapped := wrap_error("ctx", base)
\tif !errors.Is(wrapped, base) {
\t\tpanic("errors.Is failed on non-nil input")
\t}
\tfmt.Println("GF_P4 PASS")
}
""",
            },
            {
                "id": "GF_P5_rename",
                "label": "Concept transfer: renamed to annotate_error",
                "lang": "go",
                "fn_name": "annotate_error",
                "prompt": (
                    "Write a Go function named annotate_error(context string, cause error) error "
                    'that returns fmt.Errorf("%s: %w", context, cause). '
                    "Output only the function definition, nothing else."
                ),
                "test_harness": """package main

import (
\t"errors"
\t"fmt"
)

// <<STUDENT_CODE>>

func main() {
\tbase := errors.New("timeout")
\twrapped := annotate_error("read db", base)
\tif !errors.Is(wrapped, base) {
\t\tpanic("errors.Is failed")
\t}
\tfmt.Println("GF_P5 PASS")
}
""",
            },
        ],
    },
    # ── 9. first_even_zero (Rust) — targeted zero edge case ──────────────────
    "first_even_zero": {
        "lang": "rust",
        "description": "first_even(nums: &[i32]) — zero and negative even numbers",
        "system": (
            "You are an expert Rust programmer. Write idiomatic, safe, production-ready Rust. "
            "Output ONLY the Rust function — no markdown fences, no preamble, no explanation. "
            "Remember: 0 is even. Negative even numbers like -2, -4 are also even."
        ),
        "probes": [
            {
                "id": "FEZ_P1_zero",
                "label": "Zero is even — must return Some(0)",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32> that returns "
                    "the first even number. Remember: 0 is even (0 % 2 == 0), so Some(0) must be "
                    "returned when 0 is the first even number in the slice."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[1, 0, 3]), Some(0), "zero is even");
    assert_eq!(first_even(&[0]), Some(0), "single zero");
    assert_eq!(first_even(&[1, 3, 5]), None, "all odd");
    assert_eq!(first_even(&[2, 0]), Some(2), "first even wins");
    println!("FEZ_P1 PASS");
}
""",
            },
            {
                "id": "FEZ_P2_negative_even",
                "label": "Negative even numbers are even",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32>. "
                    "Negative even numbers (-2, -4, -100) must be returned as Some. "
                    "Use n % 2 == 0 as the even check — this works for negatives in Rust."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[-1, -2, -3]), Some(-2), "negative even failed");
    assert_eq!(first_even(&[-1, -3, -5]), None, "all negative odd");
    assert_eq!(first_even(&[1, 3, 0]), Some(0), "zero as first even");
    println!("FEZ_P2 PASS");
}
""",
            },
            {
                "id": "FEZ_P3_mixed",
                "label": "Mixed positive, negative, and zero",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32>. "
                    "Must correctly identify even numbers among positives, negatives, and zero. "
                    "A number n is even if n % 2 == 0."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[3, -4, 0, 2]), Some(-4));
    assert_eq!(first_even(&[-1, 1, 0]), Some(0));
    assert_eq!(first_even(&[]), None);
    println!("FEZ_P3 PASS");
}
""",
            },
            {
                "id": "FEZ_P4_idiomatic",
                "label": "Idiomatic iterator style with zero/negative awareness",
                "lang": "rust",
                "fn_name": "first_even",
                "prompt": (
                    "Write a Rust function first_even(nums: &[i32]) -> Option<i32> using "
                    "iterator style (.iter().find()). The even check n % 2 == 0 handles "
                    "zero and negative numbers correctly."
                ),
                "test_harness": """
fn first_even(nums: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(first_even(&[1, 3, 0, 5]), Some(0));
    assert_eq!(first_even(&[-6, -3, -1]), Some(-6));
    assert_eq!(first_even(&[1, 3, 5, 7]), None);
    println!("FEZ_P4 PASS");
}
""",
            },
            {
                "id": "FEZ_P5_rename",
                "label": "Concept transfer: renamed, must still handle zero",
                "lang": "rust",
                "fn_name": "find_first_even",
                "prompt": (
                    "Write a Rust function named find_first_even(data: &[i32]) -> Option<i32> "
                    "that returns the first even number. Zero (0) and negative evens (-2, -4) "
                    "must be returned correctly. n % 2 == 0 is the correct even check."
                ),
                "test_harness": """
fn find_first_even(data: &[i32]) -> Option<i32> {
    // <<STUDENT_CODE>>
}

fn main() {
    assert_eq!(find_first_even(&[1, 0, 2]), Some(0));
    assert_eq!(find_first_even(&[-3, -2, -1]), Some(-2));
    assert_eq!(find_first_even(&[1, 3, 5]), None);
    println!("FEZ_P5 PASS");
}
""",
            },
        ],
    },
    # ── 10. go_goroutine (Go) ─────────────────────────────────────────────────
    "go_goroutine": {
        "lang": "go",
        "description": "sum_concurrent(nums []int) int  [goroutine + channel]",
        "system": (
            "You are an expert Go programmer. Write idiomatic Go with goroutines and channels. "
            "Output ONLY the Go function — no package declaration, no imports, no main, no explanation."
        ),
        "probes": [
            {
                "id": "GG_P1_basic",
                "label": "Basic: sum with goroutine and channel",
                "lang": "go",
                "fn_name": "sum_concurrent",
                "prompt": (
                    "Write a Go function sum_concurrent(nums []int) int that sums a slice "
                    "using a goroutine and a channel to send the result back."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

var _ = sync.WaitGroup{}

// <<STUDENT_CODE>>

func main() {
\tgot := sum_concurrent([]int{1, 2, 3, 4, 5})
\tif got != 15 {
\t\tpanic(fmt.Sprintf("expected 15, got %d", got))
\t}
\tfmt.Println("GG_P1 PASS")
}
""",
            },
            {
                "id": "GG_P2_empty",
                "label": "Empty slice returns 0",
                "lang": "go",
                "fn_name": "sum_concurrent",
                "prompt": (
                    "Write a Go function sum_concurrent(nums []int) int that returns 0 for an empty slice, "
                    "otherwise sums using a goroutine and channel."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

var _ = sync.WaitGroup{}

// <<STUDENT_CODE>>

func main() {
\tif got := sum_concurrent([]int{}); got != 0 {
\t\tpanic(fmt.Sprintf("expected 0, got %d", got))
\t}
\tfmt.Println("GG_P2 PASS")
}
""",
            },
            {
                "id": "GG_P3_negative",
                "label": "Handles negative numbers",
                "lang": "go",
                "fn_name": "sum_concurrent",
                "prompt": (
                    "Write a Go function sum_concurrent(nums []int) int that sums the slice "
                    "including negative values, using a goroutine and channel."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

var _ = sync.WaitGroup{}

// <<STUDENT_CODE>>

func main() {
\tgot := sum_concurrent([]int{-5, 10, -3})
\tif got != 2 {
\t\tpanic(fmt.Sprintf("expected 2, got %d", got))
\t}
\tfmt.Println("GG_P3 PASS")
}
""",
            },
            {
                "id": "GG_P4_single",
                "label": "Single element",
                "lang": "go",
                "fn_name": "sum_concurrent",
                "prompt": (
                    "Write a Go function sum_concurrent(nums []int) int using goroutine+channel."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

var _ = sync.WaitGroup{}

// <<STUDENT_CODE>>

func main() {
\tif got := sum_concurrent([]int{42}); got != 42 {
\t\tpanic(fmt.Sprintf("expected 42, got %d", got))
\t}
\tfmt.Println("GG_P4 PASS")
}
""",
            },
            {
                "id": "GG_P5_large",
                "label": "Large slice (100 elements)",
                "lang": "go",
                "fn_name": "sum_concurrent",
                "prompt": (
                    "Write a Go function sum_concurrent(nums []int) int using goroutine+channel."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

var _ = sync.WaitGroup{}

// <<STUDENT_CODE>>

func main() {
\tnums := make([]int, 100)
\tfor i := range nums { nums[i] = i + 1 }
\tgot := sum_concurrent(nums)
\tif got != 5050 {
\t\tpanic(fmt.Sprintf("expected 5050, got %d", got))
\t}
\tfmt.Println("GG_P5 PASS")
}
""",
            },
        ],
    },
    # ── 11. go_waitgroup (Go) ─────────────────────────────────────────────────
    "go_waitgroup": {
        "lang": "go",
        "description": "parallel_map(nums []int, f func(int) int) []int  [WaitGroup]",
        "system": (
            "You are an expert Go programmer. Write idiomatic Go using sync.WaitGroup. "
            "Output ONLY the Go function — no package declaration, no imports, no main, no explanation."
        ),
        "probes": [
            {
                "id": "GW_P1_double",
                "label": "Double each element in parallel",
                "lang": "go",
                "fn_name": "parallel_map",
                "prompt": (
                    "Write a Go function parallel_map(nums []int, f func(int) int) []int that applies "
                    "f to each element concurrently using goroutines and sync.WaitGroup, returning results "
                    "in the original order."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

// <<STUDENT_CODE>>

func main() {
\tresult := parallel_map([]int{1, 2, 3, 4}, func(n int) int { return n * 2 })
\texpected := []int{2, 4, 6, 8}
\tfor i, v := range expected {
\t\tif result[i] != v {
\t\t\tpanic(fmt.Sprintf("index %d: expected %d got %d", i, v, result[i]))
\t\t}
\t}
\tfmt.Println("GW_P1 PASS")
}
""",
            },
            {
                "id": "GW_P2_identity",
                "label": "Identity function preserves order",
                "lang": "go",
                "fn_name": "parallel_map",
                "prompt": (
                    "Write a Go function parallel_map(nums []int, f func(int) int) []int using WaitGroup."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

// <<STUDENT_CODE>>

func main() {
\tinput := []int{5, 3, 1, 4, 2}
\tresult := parallel_map(input, func(n int) int { return n })
\tfor i, v := range input {
\t\tif result[i] != v {
\t\t\tpanic(fmt.Sprintf("index %d: expected %d got %d", i, v, result[i]))
\t\t}
\t}
\tfmt.Println("GW_P2 PASS")
}
""",
            },
            {
                "id": "GW_P3_empty",
                "label": "Empty slice returns empty",
                "lang": "go",
                "fn_name": "parallel_map",
                "prompt": (
                    "Write a Go function parallel_map(nums []int, f func(int) int) []int using WaitGroup."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

// <<STUDENT_CODE>>

func main() {
\tresult := parallel_map([]int{}, func(n int) int { return n * 2 })
\tif len(result) != 0 {
\t\tpanic(fmt.Sprintf("expected empty, got %v", result))
\t}
\tfmt.Println("GW_P3 PASS")
}
""",
            },
            {
                "id": "GW_P4_negate",
                "label": "Negate all elements",
                "lang": "go",
                "fn_name": "parallel_map",
                "prompt": (
                    "Write a Go function parallel_map(nums []int, f func(int) int) []int using WaitGroup."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

// <<STUDENT_CODE>>

func main() {
\tresult := parallel_map([]int{1, -2, 3}, func(n int) int { return -n })
\texpected := []int{-1, 2, -3}
\tfor i, v := range expected {
\t\tif result[i] != v {
\t\t\tpanic(fmt.Sprintf("index %d: expected %d got %d", i, v, result[i]))
\t\t}
\t}
\tfmt.Println("GW_P4 PASS")
}
""",
            },
            {
                "id": "GW_P5_single",
                "label": "Single element",
                "lang": "go",
                "fn_name": "parallel_map",
                "prompt": (
                    "Write a Go function parallel_map(nums []int, f func(int) int) []int using WaitGroup."
                ),
                "test_harness": """package main

import (
\t"fmt"
\t"sync"
)

// <<STUDENT_CODE>>

func main() {
\tresult := parallel_map([]int{7}, func(n int) int { return n * n })
\tif result[0] != 49 {
\t\tpanic(fmt.Sprintf("expected 49, got %d", result[0]))
\t}
\tfmt.Println("GW_P5 PASS")
}
""",
            },
        ],
    },
    # ── 12. py_dataclass (Python) ─────────────────────────────────────────────
    "py_dataclass": {
        "lang": "python",
        "description": "Point dataclass with distance_to method",
        "system": (
            "You are an expert Python programmer. Write idiomatic Python 3.10+ with type hints. "
            "Output ONLY the class definition — no main, no test code, no explanation."
        ),
        "probes": [
            {
                "id": "PDC_P1_basic",
                "label": "Point dataclass exists and is instantiable",
                "lang": "python",
                "fn_name": "Point",
                "prompt": (
                    "Write a Python dataclass Point with fields x: float and y: float, "
                    "and a method distance_to(other: Point) -> float using Euclidean distance."
                ),
                "test_harness": """import math
from dataclasses import dataclass

# <<STUDENT_CODE>>

p1 = Point(0.0, 0.0)
p2 = Point(3.0, 4.0)
d = p1.distance_to(p2)
assert abs(d - 5.0) < 1e-9, f"expected 5.0, got {d}"
print("PDC_P1 PASS")
""",
            },
            {
                "id": "PDC_P2_same",
                "label": "Distance to self is zero",
                "lang": "python",
                "fn_name": "Point",
                "prompt": (
                    "Write a Python dataclass Point(x: float, y: float) with distance_to(other: Point) -> float."
                ),
                "test_harness": """import math
from dataclasses import dataclass

# <<STUDENT_CODE>>

p = Point(1.5, 2.5)
assert p.distance_to(p) == 0.0, "distance to self must be 0"
print("PDC_P2 PASS")
""",
            },
            {
                "id": "PDC_P3_negative",
                "label": "Negative coordinates",
                "lang": "python",
                "fn_name": "Point",
                "prompt": (
                    "Write a Python dataclass Point(x: float, y: float) with distance_to(other: Point) -> float."
                ),
                "test_harness": """import math
from dataclasses import dataclass

# <<STUDENT_CODE>>

p1 = Point(-3.0, -4.0)
p2 = Point(0.0, 0.0)
d = p1.distance_to(p2)
assert abs(d - 5.0) < 1e-9, f"expected 5.0, got {d}"
print("PDC_P3 PASS")
""",
            },
            {
                "id": "PDC_P4_symmetry",
                "label": "Distance is symmetric",
                "lang": "python",
                "fn_name": "Point",
                "prompt": (
                    "Write a Python dataclass Point(x: float, y: float) with distance_to(other: Point) -> float."
                ),
                "test_harness": """import math
from dataclasses import dataclass

# <<STUDENT_CODE>>

a = Point(1.0, 2.0)
b = Point(4.0, 6.0)
assert abs(a.distance_to(b) - b.distance_to(a)) < 1e-9
print("PDC_P4 PASS")
""",
            },
            {
                "id": "PDC_P5_unit",
                "label": "Unit distance along x-axis",
                "lang": "python",
                "fn_name": "Point",
                "prompt": (
                    "Write a Python dataclass Point(x: float, y: float) with distance_to(other: Point) -> float."
                ),
                "test_harness": """import math
from dataclasses import dataclass

# <<STUDENT_CODE>>

p1 = Point(0.0, 0.0)
p2 = Point(1.0, 0.0)
assert abs(p1.distance_to(p2) - 1.0) < 1e-9
print("PDC_P5 PASS")
""",
            },
        ],
    },
    # ── 13. py_retry (Python) ─────────────────────────────────────────────────
    "py_retry": {
        "lang": "python",
        "description": "retry(fn, times, delay) -> T",
        "system": (
            "You are an expert Python programmer. Write idiomatic Python 3.10+ with type hints. "
            "Output ONLY the function definition — no imports above the function are allowed unless part of the function body, no test code, no explanation."
        ),
        "probes": [
            {
                "id": "PRT_P1_succeeds_first",
                "label": "Succeeds on first try",
                "lang": "python",
                "fn_name": "retry",
                "prompt": (
                    "Write a Python function retry(fn, times: int, delay: float) that calls fn() "
                    "and returns its result. If fn() raises, sleep delay seconds and retry up to "
                    "times total attempts. Raise the last exception if all attempts fail."
                ),
                "test_harness": """import time

# <<STUDENT_CODE>>

calls = []
def ok():
    calls.append(1)
    return 42

result = retry(ok, 3, 0.0)
assert result == 42
assert len(calls) == 1
print("PRT_P1 PASS")
""",
            },
            {
                "id": "PRT_P2_retries",
                "label": "Retries then succeeds",
                "lang": "python",
                "fn_name": "retry",
                "prompt": (
                    "Write a Python function retry(fn, times: int, delay: float) that retries fn() "
                    "on exception up to times attempts total."
                ),
                "test_harness": """import time

# <<STUDENT_CODE>>

attempts = [0]
def flaky():
    attempts[0] += 1
    if attempts[0] < 3:
        raise ValueError("not yet")
    return "done"

result = retry(flaky, 5, 0.0)
assert result == "done"
assert attempts[0] == 3
print("PRT_P2 PASS")
""",
            },
            {
                "id": "PRT_P3_all_fail",
                "label": "All attempts fail — raises last exception",
                "lang": "python",
                "fn_name": "retry",
                "prompt": (
                    "Write a Python function retry(fn, times: int, delay: float) that raises "
                    "the last exception after all attempts fail."
                ),
                "test_harness": """import time

# <<STUDENT_CODE>>

def always_fail():
    raise RuntimeError("always")

try:
    retry(always_fail, 3, 0.0)
    assert False, "should have raised"
except RuntimeError as e:
    assert "always" in str(e)
print("PRT_P3 PASS")
""",
            },
            {
                "id": "PRT_P4_once",
                "label": "times=1 means one attempt only",
                "lang": "python",
                "fn_name": "retry",
                "prompt": ("Write a Python function retry(fn, times: int, delay: float)."),
                "test_harness": """import time

# <<STUDENT_CODE>>

calls = [0]
def fail():
    calls[0] += 1
    raise ValueError("x")

try:
    retry(fail, 1, 0.0)
except ValueError:
    pass
assert calls[0] == 1, f"expected 1 call, got {calls[0]}"
print("PRT_P4 PASS")
""",
            },
            {
                "id": "PRT_P5_return_type",
                "label": "Preserves non-None return value",
                "lang": "python",
                "fn_name": "retry",
                "prompt": (
                    "Write a Python function retry(fn, times: int, delay: float) that returns fn()'s result."
                ),
                "test_harness": """import time

# <<STUDENT_CODE>>

result = retry(lambda: {"key": "value"}, 3, 0.0)
assert result == {"key": "value"}
print("PRT_P5 PASS")
""",
            },
        ],
    },
    # ── 14. ts_generic (TypeScript) ───────────────────────────────────────────
    "ts_generic": {
        "lang": "typescript",
        "description": "identity<T>(value: T): T  — basic TypeScript generics",
        "system": (
            "You are an expert TypeScript programmer. Write correct, idiomatic TypeScript. "
            "Output ONLY the function — no imports, no module declarations, no explanation."
        ),
        "probes": [
            {
                "id": "TSG_P1_identity",
                "label": "Identity function compiles and returns value",
                "lang": "typescript",
                "fn_name": "identity",
                "prompt": (
                    "Write a TypeScript generic function identity<T>(value: T): T that returns its argument unchanged."
                ),
                "test_harness": """// <<STUDENT_CODE>>

const n = identity<number>(42);
if (n !== 42) throw new Error(`expected 42, got ${n}`);
const s = identity<string>("hello");
if (s !== "hello") throw new Error(`expected hello, got ${s}`);
console.log("TSG_P1 PASS");
""",
            },
            {
                "id": "TSG_P2_group_by",
                "label": "groupBy works on an array of objects",
                "lang": "typescript",
                "fn_name": "groupBy",
                "prompt": (
                    "Write a TypeScript generic function groupBy<T, K extends string>(arr: T[], keyFn: (item: T) => K): Record<K, T[]> "
                    "that groups array elements by the key returned by keyFn."
                ),
                "test_harness": """// <<STUDENT_CODE>>

const data = [{type: "a", v: 1}, {type: "b", v: 2}, {type: "a", v: 3}];
const result = groupBy(data, (x) => x.type as "a" | "b");
if (result.a.length !== 2) throw new Error(`expected 2 a's, got ${result.a.length}`);
if (result.b.length !== 1) throw new Error(`expected 1 b, got ${result.b.length}`);
console.log("TSG_P2 PASS");
""",
            },
            {
                "id": "TSG_P3_pick",
                "label": "pick returns object with only selected keys",
                "lang": "typescript",
                "fn_name": "pick",
                "prompt": (
                    "Write a TypeScript generic function pick<T, K extends keyof T>(obj: T, keys: K[]): Pick<T, K> "
                    "that returns a new object containing only the specified keys."
                ),
                "test_harness": """// <<STUDENT_CODE>>

const obj = {a: 1, b: 2, c: 3};
const result = pick(obj, ["a", "c"]);
if (result.a !== 1) throw new Error(`a should be 1`);
if (result.c !== 3) throw new Error(`c should be 3`);
if ("b" in result) throw new Error(`b should not be in result`);
console.log("TSG_P3 PASS");
""",
            },
            {
                "id": "TSG_P4_unique",
                "label": "unique removes duplicates",
                "lang": "typescript",
                "fn_name": "unique",
                "prompt": (
                    "Write a TypeScript generic function unique<T>(arr: T[]): T[] that returns a new array "
                    "with duplicate values removed, preserving order of first occurrence."
                ),
                "test_harness": """// <<STUDENT_CODE>>

const result = unique([1, 2, 1, 3, 2, 4]);
if (JSON.stringify(result) !== JSON.stringify([1, 2, 3, 4]))
    throw new Error(`expected [1,2,3,4], got ${JSON.stringify(result)}`);
console.log("TSG_P4 PASS");
""",
            },
            {
                "id": "TSG_P5_partition",
                "label": "partition splits array into two groups",
                "lang": "typescript",
                "fn_name": "partition",
                "prompt": (
                    "Write a TypeScript generic function partition<T>(arr: T[], pred: (x: T) => boolean): [T[], T[]] "
                    "that returns [matching, nonMatching]."
                ),
                "test_harness": """// <<STUDENT_CODE>>

const [evens, odds] = partition([1, 2, 3, 4, 5], (x) => x % 2 === 0);
if (JSON.stringify(evens) !== JSON.stringify([2, 4]))
    throw new Error(`evens: expected [2,4], got ${JSON.stringify(evens)}`);
if (JSON.stringify(odds) !== JSON.stringify([1, 3, 5]))
    throw new Error(`odds: expected [1,3,5], got ${JSON.stringify(odds)}`);
console.log("TSG_P5 PASS");
""",
            },
        ],
    },
}

CONCEPT_KEYS = list(CONCEPTS.keys())


# ── Coverage Analysis ─────────────────────────────────────────────────────────
#
# Scans all training JSONL files and cross-references against eval concepts.
# Reports every language / category that has training data but no eval probe
# so blind spots surface automatically — no piecemeal discovery.
#
# Run automatically on --save-baseline. Also available standalone via --coverage.

_TRAINING_SOURCES = [
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_gap_curriculum.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_gap_curriculum_v2.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_targeted_gaps.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_distilled_claude.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_distilled_gemini.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_distilled_observer.jsonl",
    _DETERMINEX_ROOT / "frontend" / "src-tauri" / "determinex_v1_failures_sft.jsonl",
]

# Which languages have real eval probes and how many concepts
_EVAL_LANG_CONCEPTS: dict[str, list[str]] = {
    "Rust": ["count_chars", "first_even", "arc_mutex", "refcell_borrow", "first_even_zero"],
    "Python": ["safe_divide"],
    "Go": ["wrap_error", "go_fmt_errorf", "go_panic_recover"],
}

# Training categories that map to an eval concept (has a probe)
_CAT_HAS_PROBE: set[str] = {
    "rust_concurrency",
    "rust_concurrency_adv",
    "rust_interior_mut",
    "rust_interior_mut_adv",
    "go_concurrency",
    "go_concurrency_adv",
    "go_panic_recover",
    "go_panic_recover_adv",
    "go_fmt_errorf",
    "python_threading",
    "python_threading_adv",
    "first_even_zero",
    "fe_p5_fix",
    "targeted_wrap_error",
    "targeted_go_panic",
    "targeted_first_even",
}


def run_coverage_analysis() -> dict:
    """
    Scan training corpus and return language + category coverage gaps.
    Uses both _meta key conventions (lang/cat from gap curriculum,
    language/category from targeted gaps).
    """
    lang_counts: dict[str, int] = {}
    cat_counts: dict[str, int] = {}

    for src in _TRAINING_SOURCES:
        if not src.exists():
            continue
        try:
            text = src.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("_meta") or {}
            if isinstance(m, str):
                try:
                    m = json.loads(m)
                except Exception:
                    m = {}
            lang = m.get("language") or m.get("lang") or "UNTAGGED"
            cat = m.get("category") or m.get("cat") or m.get("source") or "UNTAGGED"
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Build language status
    lang_info = {}
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        concepts = _EVAL_LANG_CONCEPTS.get(lang, [])
        if lang == "UNTAGGED":
            status = "UNTAGGED"
        elif not concepts:
            status = "NO_PROBES"
        elif len(concepts) >= 3:
            status = "COVERED"
        else:
            status = "PARTIAL"
        lang_info[lang] = {"samples": count, "n_concepts": len(concepts), "status": status}

    # Build category status
    cat_info = {}
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        if cat == "UNTAGGED":
            continue
        cat_info[cat] = {"samples": count, "has_probe": cat in _CAT_HAS_PROBE}

    return {"languages": lang_info, "categories": cat_info}


def print_coverage_report(coverage: dict) -> None:
    print()
    print("━" * 64)
    print("  EVAL COVERAGE AUDIT — training corpus vs eval probes")
    print("━" * 64)

    # Language table
    print()
    print(f"  {'Language':<16}  {'Samples':>7}  {'Concepts':>8}  Status")
    print(f"  {'-' * 16}  {'-' * 7}  {'-' * 8}  {'-' * 22}")
    icons = {
        "COVERED": "✓  covered",
        "PARTIAL": "~  partial",
        "NO_PROBES": "✗  BLIND SPOT — no eval probes",
        "UNTAGGED": "?  untagged (distillation bulk)",
    }
    for lang, info in coverage["languages"].items():
        icon = icons.get(info["status"], "?")
        print(f"  {lang:<16}  {info['samples']:>7}  {info['n_concepts']:>8}  {icon}")

    # Category table
    print()
    print(f"  {'Category':<30}  {'Samples':>7}  Probe?")
    print(f"  {'-' * 30}  {'-' * 7}  {'-' * 22}")
    for cat, info in coverage["categories"].items():
        probe = "✓" if info["has_probe"] else "✗  NO PROBE"
        print(f"  {cat:<30}  {info['samples']:>7}  {probe}")

    # Blind spot summary
    blind_langs = [l for l, i in coverage["languages"].items() if i["status"] == "NO_PROBES"]
    blind_cats = [c for c, i in coverage["categories"].items() if not i["has_probe"]]

    print()
    if blind_langs or blind_cats:
        print("  ⚠  BLIND SPOTS — training data exists, no eval coverage:")
        for l in blind_langs:
            n = coverage["languages"][l]["samples"]
            print(f"       Language  '{l}':  {n} training samples, 0 eval probes")
        for c in blind_cats:
            n = coverage["categories"][c]["samples"]
            print(f"       Category  '{c}':  {n} training samples, no mapped probe")
        print()
        print("  ACTION: add eval probes for the above before next training cycle.")
    else:
        print("  ✓  All tagged training categories have eval coverage.")

    print("━" * 64)


# ── Ollama call ───────────────────────────────────────────────────────────────

_model_arch_cache: dict[str, str] = {}


def _get_model_arch(model: str) -> str:
    """Probe Ollama /api/show to get model architecture family. Cached."""
    import urllib.request

    if model in _model_arch_cache:
        return _model_arch_cache[model]
    try:
        payload = json.dumps({"model": model, "verbose": False}).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_URL + "/api/show",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        arch = data.get("model_info", {}).get("general.architecture", "llama").lower()
    except Exception:
        arch = "llama"  # safe default
    _model_arch_cache[model] = arch
    return arch


def _build_prompt(arch: str, system: str, user: str) -> str:
    """Build the correct prompt format for the model's architecture."""
    if arch in ("qwen2", "qwen3", "mistral", "gemma", "phi3"):
        # ChatML format used by Qwen2, Mistral (instruct), Gemma, Phi-3
        return (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
    else:
        # Llama 3 format (default for llama architecture)
        return (
            f"<|begin_of_text|>"
            f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
            f"<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"
            f"<|start_header_id|>assistant<|end_header_id|>\n\n"
        )


def _prewarm_model(model: str, timeout: int = 360) -> bool:
    """
    Send a minimal 1-token request to force Ollama to load the model into
    memory before the timed eval probes begin.  Returns True if the model
    responded, False if it timed out.

    Called automatically for models whose GGUF is larger than VRAM — those
    models have cold-load times that would blow past the per-probe timeout.
    Without pre-warming, the first eval probe always SKIPs on large models
    stored on slow media (HDD), making the result misleading.
    """
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": "hi",
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 1},
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def ask_student(model: str, system: str, user: str) -> str | None:
    """Call Ollama /api/generate synchronously. Returns text or None on error.

    Auto-detects model architecture and uses the correct prompt template:
    - Qwen2/Mistral/Gemma/Phi-3 → ChatML (<|im_start|>)
    - Llama 3 → Llama 3 header format (<|begin_of_text|>)

    Timeout is 300s to accommodate large models (7B+) on slow storage.
    Models are pre-warmed before the first probe — see run_eval().
    """
    import urllib.error
    import urllib.request

    arch = _get_model_arch(model)
    prompt = _build_prompt(arch, system, user)
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 512},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())["response"].strip()
    except Exception as e:
        log.warning("Ollama error: %s", e)
        return None


# ── Concept evaluator ─────────────────────────────────────────────────────────


def run_concept(model: str, concept_key: str, verbose: bool = False) -> dict:
    """Run all 5 probes for one concept. Returns a result dict."""
    concept = CONCEPTS[concept_key]
    probes = concept["probes"]
    system = concept["system"]
    lang = concept["lang"]

    print(f"\n  ┌─ [{concept_key.upper()}]  {concept['description']}  ({lang})")

    results, passed_count = [], 0

    for probe in probes:
        t0 = time.time()
        print(f"  │  [{probe['id']}] {probe['label']}", end=" ", flush=True)

        raw = ask_student(model, system, probe["prompt"])
        elapsed = time.time() - t0

        if raw is None:
            print("SKIP (ollama unreachable)")
            results.append(
                {
                    **probe,
                    "passed": False,
                    "reason": "ollama_unreachable",
                    "elapsed": elapsed,
                    "raw_output": "",
                }
            )
            continue

        if verbose:
            print("\n  │    ── raw output ──")
            for line in raw.split("\n")[:12]:
                print(f"  │    {line}")
            print("  │    ────────────────")

        passed, err, stdout = run_probe(raw, probe)

        if passed:
            passed_count += 1
            print(f"  PASS ({elapsed:.1f}s)  [{stdout[:40]}]")
        else:
            reason = err[:120] if err else "runtime_fail"
            print(f"  FAIL ({elapsed:.1f}s)")
            if verbose or len(err) < 150:
                print(f"  │    Reason: {reason}")

        results.append(
            {
                "probe_id": probe["id"],
                "label": probe["label"],
                "passed": passed,
                "elapsed": round(elapsed, 2),
                "compile_error": err[:300] if not passed else "",
                "runtime_out": stdout,
            }
        )

    score_pct = round(100 * passed_count / len(probes))
    grade = (
        "S"
        if score_pct == 100
        else "A"
        if score_pct >= 80
        else "B"
        if score_pct >= 60
        else "C"
        if score_pct >= 40
        else "F"
    )
    print(f"  └─ SCORE: {passed_count}/{len(probes)} ({score_pct}%)  GRADE: {grade}")

    return {
        "concept": concept_key,
        "lang": lang,
        "passed": passed_count,
        "total": len(probes),
        "score_pct": score_pct,
        "grade": grade,
        "probes": results,
    }


# ── Full evaluation run ───────────────────────────────────────────────────────


def run_evaluation(model: str, concepts: list[str], verbose: bool = False) -> dict:
    """Run all requested concepts and aggregate results."""
    print(f"\n{'═' * 62}")
    print(f"  DETERMINEX EVAL — {model}")
    print(f"  Concepts: {', '.join(concepts)}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'═' * 62}")

    # Pre-warm: force model load before the timed probes start.
    # Large models on slow storage can take minutes to cold-load — if we skip
    # this, the first probe always times out and is marked SKIP, which makes
    # the result look wrong.  The pre-warm absorbs the load time with a
    # generous timeout (360s) and a clear progress message.
    print(f"  [pre-warm] Loading {model} into memory...", end=" ", flush=True)
    ok = _prewarm_model(model, timeout=360)
    if ok:
        print("ready.")
    else:
        print("TIMEOUT — model may not respond. Continuing anyway.")

    concept_results = {}
    total_passed, total_probes = 0, 0

    for key in concepts:
        r = run_concept(model, key, verbose)
        concept_results[key] = r
        total_passed += r["passed"]
        total_probes += r["total"]

    overall_pct = round(100 * total_passed / total_probes) if total_probes else 0
    overall_grade = (
        "S"
        if overall_pct == 100
        else "A"
        if overall_pct >= 80
        else "B"
        if overall_pct >= 60
        else "C"
        if overall_pct >= 40
        else "F"
    )

    print(f"\n{'─' * 62}")
    print(f"  OVERALL: {total_passed}/{total_probes} ({overall_pct}%)  GRADE: {overall_grade}")
    print(f"{'═' * 62}\n")

    return {
        "model": model,
        "timestamp": datetime.now().isoformat(),
        "concepts": concept_results,
        "total_passed": total_passed,
        "total_probes": total_probes,
        "overall_pct": overall_pct,
        "overall_grade": overall_grade,
    }


# ── Comparison ────────────────────────────────────────────────────────────────


def print_comparison(result: dict, baseline: dict):
    delta = result["overall_pct"] - baseline["overall_pct"]
    sign = "+" if delta >= 0 else ""
    print(f"\n  COMPARISON vs BASELINE  ({baseline['timestamp'][:16]})")
    print(f"  {'Concept':<16}  {'Baseline':>8}  {'Current':>8}  {'Delta':>6}")
    print(f"  {'─' * 16}  {'─' * 8}  {'─' * 8}  {'─' * 6}")

    for key in result["concepts"]:
        b = baseline.get("concepts", {}).get(key, {})
        b_pct = b.get("score_pct", "--")
        c_pct = result["concepts"][key]["score_pct"]
        if isinstance(b_pct, int):
            d = c_pct - b_pct
            dsign = "+" if d >= 0 else ""
            arrow = "↑" if d > 0 else "↓" if d < 0 else "="
            print(f"  {key:<16}  {b_pct:>7}%  {c_pct:>7}%  {dsign}{d:>4}% {arrow}")
        else:
            print(f"  {key:<16}  {'N/A':>8}  {c_pct:>7}%  {'new':>6}")

    sign = "+" if delta >= 0 else ""
    arrow = "↑ IMPROVED" if delta > 0 else "↓ REGRESSED" if delta < 0 else "= NO CHANGE"
    print(f"  {'─' * 16}  {'─' * 8}  {'─' * 8}  {'─' * 6}")
    print(
        f"  {'OVERALL':<16}  {baseline['overall_pct']:>7}%  {result['overall_pct']:>7}%  {sign}{delta:>4}% {arrow}"
    )
    print()

    # Per-probe diff for changed concepts
    for key, cr in result["concepts"].items():
        bc = baseline.get("concepts", {}).get(key, {})
        bp = {p["probe_id"]: p for p in bc.get("probes", [])}
        changed = [
            (p, bp.get(p["probe_id"], {}))
            for p in cr["probes"]
            if p["passed"] != bp.get(p["probe_id"], {}).get("passed")
        ]
        if changed:
            print(f"  Changes in [{key}]:")
            for p, b in changed:
                was = "PASS" if b.get("passed") else "FAIL"
                now = "PASS" if p["passed"] else "FAIL"
                print(f"    {p['probe_id']:<20}  {was} → {now}")
            print()


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex Multi-Concept Evaluator")
    parser.add_argument(
        "--model", default="llama3.2:3b", help="Ollama model tag to test (default: llama3.2:3b)"
    )
    parser.add_argument(
        "--concept",
        default="all",
        choices=["all"] + CONCEPT_KEYS,
        help="Which concept to test (default: all)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show raw student output for each probe"
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="Save result as pre-training baseline"
    )
    parser.add_argument("--compare", action="store_true", help="Compare against saved baseline")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Show training corpus vs eval probe coverage audit (no eval run needed)",
    )
    args = parser.parse_args()

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Coverage-only mode: audit training corpus vs eval probes, no model needed
    if args.coverage and args.concept == "all":
        coverage = run_coverage_analysis()
        print_coverage_report(coverage)
        # Still run eval unless --coverage was the only flag
        if not any([args.save_baseline, args.compare]):
            return

    concepts = CONCEPT_KEYS if args.concept == "all" else [args.concept]
    result = run_evaluation(args.model, concepts, verbose=args.verbose)

    # Save timestamped result
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = args.model.replace(":", "_").replace("/", "_")
    out = _RESULTS_DIR / f"eval_{slug}_{ts}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("Result saved: %s", out.name)

    if args.save_baseline:
        _BASELINE_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
        log.info("Baseline saved → %s", _BASELINE_FILE.name)
        # Always run coverage audit when saving a baseline — blind spots are
        # most important to see at the moment you're establishing ground truth.
        coverage = run_coverage_analysis()
        print_coverage_report(coverage)

    elif args.coverage:
        coverage = run_coverage_analysis()
        print_coverage_report(coverage)

    if args.compare and _BASELINE_FILE.exists():
        baseline = json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
        print_comparison(result, baseline)


if __name__ == "__main__":
    main()
