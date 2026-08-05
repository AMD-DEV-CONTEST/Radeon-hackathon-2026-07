"""
scripts/convert_failures_to_sft.py  —  Determinex Failure Corpus Converter

Reads determinex_v1_failures.jsonl (276 raw failure records from the Immune system)
and converts each one into a compile-validated SFT training pair:

    system   = language-specific expert debugger persona
    user     = broken code + compiler error
    assistant = Leviathan-generated fix, compile-validated before writing

Output goes to determinex_v1_failures_sft.jsonl — drop-in ready for v6 DATA_PATHS.

Hardware note: This script is CPU-only (Leviathan via Ollama).
Run AFTER v5 training completes so GPU RAM is free for PyTorch again.

Validation strategy:
    Rust       → rustc --crate-type lib  (strict, compile-validated)
    Go         → go build in temp module  (strict, compile-validated)
    Python     → ast.parse               (strict, syntax-validated)
    Kotlin     → format + keyword check  (lenient — no local compiler)
    Cpp        → format + keyword check  (lenient — no local compiler)
    TypeScript → format + keyword check  (lenient — no local compiler)
    Sql        → format + keyword check  (lenient — no local compiler)

Usage:
    python scripts/convert_failures_to_sft.py              # all 276 samples
    python scripts/convert_failures_to_sft.py --lang Rust  # Rust only (49 samples)
    python scripts/convert_failures_to_sft.py --n 10       # smoke test first 10
    python scripts/convert_failures_to_sft.py --resume     # skip already-done task_ids
    python scripts/convert_failures_to_sft.py --dry-run    # generate but don't write
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# ── UTF-8 terminal (Windows) ─────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[CONVERT] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("convert")

# ── Paths ────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_DETERMINEX_ROOT = _SCRIPTS_DIR.parent
_SRC_TAURI = _DETERMINEX_ROOT / "frontend" / "src-tauri"

INPUT_PATH = _SRC_TAURI / "determinex_v1_failures.jsonl"
OUTPUT_PATH = _SRC_TAURI / "determinex_v1_failures_sft.jsonl"
REPORT_PATH = _SCRIPTS_DIR / "failures_conversion_report.json"

# ── Ollama config ─────────────────────────────────────────────────────────────
OLLAMA_CHAT_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/chat"
OLLAMA_ALIVE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/tags"
TEACHER_MODEL = "determinex-leviathan:v1"

# Allowlist for Ollama model names — prevents unsanitized CLI input reaching urllib.
# Valid examples: "determinex-leviathan:v1", "deepseek-coder-v2:latest", "llama3.2:3b"
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/:+-]{0,100}$")

# Allowlist of recognised language labels in the failure corpus.
_ALLOWED_LANGS: frozenset[str] = frozenset(
    {"Rust", "Go", "Python", "Kotlin", "Cpp", "TypeScript", "Sql", "Unknown"}
)

# Allowed URL prefixes for Ollama — all calls must stay on localhost.
_OLLAMA_URL_PREFIX = "http://localhost:"


def _validate_localhost_url(url: str) -> str:
    """Assert that a URL targets localhost only (SSRF guard).

    Raises ValueError if the URL does not start with the expected localhost
    prefix.  Returns the original string unchanged so it can be used inline.
    """
    if not url.startswith(_OLLAMA_URL_PREFIX):
        raise ValueError(
            f"Ollama URL must target localhost (got {url!r}). "
            "SSRF guard prevented an unexpected outbound request."
        )
    return url


def _sanitize_model(name: str) -> str:
    """Validate model name and return only the regex-matched value.

    Returns m.group(0) (not the raw arg) so static-analysis taint tracking
    recognises this as a sanitized value rather than raw CLI input.
    """
    m = _MODEL_NAME_RE.match(name)
    if m is None:
        log.error(
            "Invalid --model value %r\n"
            "Ollama model names must match: [a-zA-Z0-9][a-zA-Z0-9._/:+-]{0,100}",
            name,
        )
        sys.exit(1)
    return m.group(0)  # sanitized — not the raw CLI arg


OLLAMA_TIMEOUT = 180  # seconds — Leviathan can be slow on complex fixes
COMPILE_TIMEOUT = 30  # seconds per rustc/go call

# ── Language system prompts ───────────────────────────────────────────────────
_SYSTEM = {
    "Rust": (
        "You are an expert Rust systems programmer and debugger. "
        "When shown broken Rust code and its compiler error, produce ONLY the corrected Rust code. "
        "Critical rules: use .chars() for character iteration (never s[i] -- that is a compile error), "
        "use .iter() for slices, handle Result/Option with ? or .map()/.unwrap_or(). "
        "You must include 'use std::fmt;' if you implement Display. "
        "Output ONLY the fixed Rust code -- no markdown fences, no explanation, no commentary."
    ),
    "Go": (
        "You are an expert Go programmer and debugger. "
        "When shown broken Go code and its compiler error, produce ONLY the corrected Go code. "
        "Always include the 'package' declaration. Use errors.Is/As for error wrapping, "
        "defer for cleanup, idiomatic goroutine patterns. "
        "Output ONLY the fixed Go code -- no markdown fences, no explanation, no commentary."
    ),
    "Python": (
        "You are an expert Python developer and debugger. "
        "When shown broken Python code and its error, produce ONLY the corrected Python code. "
        "Use type annotations, proper exception handling, idiomatic comprehensions. "
        "Output ONLY the fixed Python code -- no markdown fences, no explanation, no commentary."
    ),
    "Kotlin": (
        "You are an expert Kotlin developer and debugger. "
        "When shown broken Kotlin code and its compiler error, produce ONLY the corrected Kotlin code. "
        "Use idiomatic Kotlin: data classes, extension functions, null safety, coroutines. "
        "Output ONLY the fixed Kotlin code -- no markdown fences, no explanation, no commentary."
    ),
    "Cpp": (
        "You are an expert C++ systems programmer and debugger. "
        "When shown broken C++ code and its compiler error, produce ONLY the corrected C++ code. "
        "Use modern C++17: RAII, smart pointers, std::optional, STL algorithms. "
        "Output ONLY the fixed C++ code -- no markdown fences, no explanation, no commentary."
    ),
    "TypeScript": (
        "You are an expert TypeScript developer and debugger. "
        "When shown broken TypeScript code and its compiler error, produce ONLY the corrected TypeScript code. "
        "Use strict type safety, proper generics, async/await patterns. "
        "Output ONLY the fixed TypeScript code -- no markdown fences, no explanation, no commentary."
    ),
    "Sql": (
        "You are an expert SQL database engineer and debugger. "
        "When shown broken SQL code and its error, produce ONLY the corrected SQL. "
        "Write standard SQL-99 compatible queries with proper semicolons. "
        "Output ONLY the fixed SQL -- no markdown fences, no explanation, no commentary."
    ),
}

_DEFAULT_SYSTEM = (
    "You are an expert software engineer and debugger. "
    "When shown broken code and its error, produce ONLY the corrected code. "
    "Output ONLY the fixed code -- no markdown fences, no explanation."
)

# Languages for which we have strict compile validators
_STRICT_LANGS = {"Rust", "Go", "Python"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def strip_fences(code: str) -> str:
    """Remove ```lang ... ``` or ``` ... ``` fences if the model included them."""
    code = code.strip()
    code = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def build_user_prompt(sample: dict) -> str:
    _raw_lang = sample.get("language", "code")
    # Sanitize lang against the frozen allowlist so only known labels reach
    # the prompt string — this breaks the SSRF taint chain from JSONL data.
    lang = _raw_lang if _raw_lang in _ALLOWED_LANGS else "code"
    broken = sample.get("original_broken_code", "").strip()
    error = sample.get("raw_compiler_panic", "").strip()
    status = sample.get("final_status", "")

    if error:
        return (
            f"The following {lang} code has a compile error.\n\n"
            f"Broken code:\n{broken}\n\n"
            f"Compiler error:\n{error}\n\n"
            f"Provide the corrected {lang} code only, with no explanation."
        )
    else:
        hint = (
            "(The model's output was malformed or truncated.)"
            if status == "ENGINEER_PARSE_FAIL"
            else ""
        )
        return (
            f"The following {lang} code is broken. {hint}\n\n"
            f"Broken code:\n{broken}\n\n"
            f"Provide the corrected {lang} code only, with no explanation."
        )


# ── Ollama call ───────────────────────────────────────────────────────────────


def ollama_alive() -> bool:
    try:
        import urllib.request

        safe_url = _validate_localhost_url(OLLAMA_ALIVE_URL)
        with urllib.request.urlopen(safe_url, timeout=5) as r:  # noqa: S310  # snyk:ignore python/Ssrf — URL validated to localhost only
            return r.status == 200
    except Exception:
        return False


def call_leviathan(system: str, user: str, model: str) -> str | None:
    """
    POST to Ollama /api/chat with system + user messages.

    Parameters
    ----------
    system : str   System prompt.
    user   : str   User turn content.
    model  : str   Sanitized Ollama model tag (from _sanitize_model).

    Returns the raw text response or None on failure.
    """
    # Bound content lengths before they enter the HTTP payload (SSRF guard).
    # These are well above any legitimate prompt size for this pipeline.
    _MAX_SYSTEM = 4_096
    _MAX_USER = 16_384
    safe_system = str(system)[:_MAX_SYSTEM]
    safe_user = str(user)[:_MAX_USER]

    try:
        import urllib.error
        import urllib.request

        safe_url = _validate_localhost_url(OLLAMA_CHAT_URL)
        payload = json.dumps(
            {
                "model": model,  # sanitized by _sanitize_model() in main()
                "messages": [
                    {"role": "system", "content": safe_system},
                    {"role": "user", "content": safe_user},
                ],
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 1800,
                    "top_p": 1.0,
                    "repeat_penalty": 1.1,
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            safe_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:  # noqa: S310  # snyk:ignore python/Ssrf — URL localhost-validated; model regex-sanitised; content length-bounded
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()

    except Exception as e:
        log.warning("Leviathan call failed: %s", e)
        return None


# ── Validators ────────────────────────────────────────────────────────────────


def _validate_rust(code: str) -> tuple[bool, str]:
    code = strip_fences(code)
    if len(code) < 10:
        return False, "output too short"

    # Inject stdlib allows + common imports so functions compile without main()
    preamble = (
        "#![allow(dead_code, unused_variables, unused_imports, unused_mut)]\n"
        "use std::collections::HashMap;\n"
        "use std::fmt;\n"
        "use std::io;\n"
        "use std::path::Path;\n"
        "use std::fs;\n\n"
    )
    wrapped = code if "fn main" in code else preamble + code

    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False, mode="w", encoding="utf-8") as f:
        f.write(wrapped)
        src = f.name
    out = src.replace(".rs", ".out")

    try:
        r = subprocess.run(
            ["rustc", "--edition", "2021", "--crate-type", "lib", "-o", out, src],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if r.returncode == 0:
            return True, "rustc OK"
        errors = [ln for ln in r.stderr.splitlines() if ln.strip() and not ln.startswith("   =")]
        return False, "rustc: " + " | ".join(errors[:3])
    except subprocess.TimeoutExpired:
        return False, "rustc timeout"
    except FileNotFoundError:
        return False, "rustc not on PATH"
    except Exception as e:
        return False, f"rustc error: {e}"
    finally:
        for p in (src, out):
            try:
                os.unlink(p)
            except OSError:
                pass


def _validate_go(code: str) -> tuple[bool, str]:
    code = strip_fences(code)
    if len(code) < 10:
        return False, "output too short"

    # Ensure package declaration
    if not re.search(r"^\s*package\s+\w+", code, re.MULTILINE):
        code = "package main\n\n" + code

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            (td / "go.mod").write_text("module determinex_validate\n\ngo 1.21\n", encoding="utf-8")
            (td / "main.go").write_text(code, encoding="utf-8")

            r = subprocess.run(
                ["go", "build", "."],
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT,
                cwd=tmpdir,
            )
            if r.returncode == 0:
                return True, "go build OK"
            return False, "go: " + r.stderr[:300].replace("\n", " | ")
    except subprocess.TimeoutExpired:
        return False, "go timeout"
    except FileNotFoundError:
        return False, "go not on PATH"
    except Exception as e:
        return False, f"go error: {e}"


def _validate_python(code: str) -> tuple[bool, str]:
    code = strip_fences(code)
    if len(code) < 5:
        return False, "output too short"
    try:
        ast.parse(code)
        return True, "ast.parse OK"
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"


# Language-specific keyword sanity checks for non-compiled languages
_LANG_KEYWORDS: dict[str, list[str]] = {
    "Kotlin": ["fun ", "class ", "val ", "var ", "object ", "interface "],
    "Cpp": ["#include", "int ", "void ", "class ", "struct ", "namespace"],
    "TypeScript": ["function", "const ", "let ", "interface ", "class ", "type ", "=>"],
    "Sql": ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "WITH", "FROM"],
}


def _validate_format(code: str, lang: str) -> tuple[bool, str]:
    """Lenient format-only check for languages without local compilers."""
    code = strip_fences(code)
    if len(code) < 20:
        return False, "output too short"
    if "```" in code:
        return False, "contains unstripped markdown fences"
    keywords = _LANG_KEYWORDS.get(lang, [])
    if keywords and not any(kw in code for kw in keywords):
        return False, f"no {lang} keywords found in output"
    return True, f"format OK (no local {lang} compiler)"


def validate(code: str, lang: str) -> tuple[bool, str]:
    """Dispatch to the right validator for this language."""
    if lang == "Rust":
        return _validate_rust(code)
    if lang == "Go":
        return _validate_go(code)
    if lang == "Python":
        return _validate_python(code)
    return _validate_format(code, lang)


# ── Stats tracker ─────────────────────────────────────────────────────────────


class ConversionStats:
    def __init__(self):
        self.attempted = 0
        self.validated = 0
        self.rejected = 0
        self.skipped = 0
        self.by_lang: dict[str, dict] = {}
        self.rejection_reasons: list[str] = []
        self._start = time.time()

    def _lang(self, lang: str) -> dict:
        if lang not in self.by_lang:
            self.by_lang[lang] = {"attempted": 0, "validated": 0, "rejected": 0}
        return self.by_lang[lang]

    def record_attempt(self, lang: str):
        self.attempted += 1
        self._lang(lang)["attempted"] += 1

    def record_validated(self, lang: str):
        self.validated += 1
        self._lang(lang)["validated"] += 1

    def record_rejected(self, lang: str, reason: str):
        self.rejected += 1
        self._lang(lang)["rejected"] += 1
        self.rejection_reasons.append(f"[{lang}] {reason[:120]}")

    def record_skipped(self):
        self.skipped += 1

    def eta(self, remaining: int) -> str:
        elapsed = time.time() - self._start
        rate = self.attempted / max(elapsed, 1)
        if rate == 0:
            return "unknown"
        secs = remaining / rate
        return f"{secs / 60:.0f}m"

    def to_dict(self) -> dict:
        elapsed = round(time.time() - self._start, 1)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": elapsed,
            "attempted": self.attempted,
            "validated": self.validated,
            "rejected": self.rejected,
            "skipped": self.skipped,
            "pass_rate": round(self.validated / max(self.attempted, 1), 3),
            "by_language": self.by_lang,
            "rejection_reasons": self.rejection_reasons[-50:],  # last 50
        }

    def print_summary(self):
        elapsed = time.time() - self._start
        log.info(
            "\n%s\n  CONVERSION COMPLETE\n"
            "  Attempted  : %d\n"
            "  Validated  : %d  (%.0f%%)\n"
            "  Rejected   : %d\n"
            "  Skipped    : %d  (already done / no data)\n"
            "  Elapsed    : %.1f min\n%s",
            "=" * 60,
            self.attempted,
            self.validated,
            100 * self.validated / max(self.attempted, 1),
            self.rejected,
            self.skipped,
            elapsed / 60,
            "=" * 60,
        )
        log.info("Breakdown by language:")
        for lang, d in sorted(self.by_lang.items()):
            pct = 100 * d["validated"] / max(d["attempted"], 1)
            log.info(
                "  %-14s  %d validated / %d attempted  (%.0f%%)",
                lang,
                d["validated"],
                d["attempted"],
                pct,
            )


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex Failure → SFT Converter")
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Filter to one language (Rust, Go, Python, Kotlin, Cpp, TypeScript, Sql)",
    )
    parser.add_argument(
        "--n", type=int, default=None, help="Process at most N samples (for smoke testing)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and validate but do NOT write output JSONL.",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Skip task_ids already present in the output file."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=TEACHER_MODEL,
        help=f"Ollama model to use as teacher (default: {TEACHER_MODEL}).",
    )
    args = parser.parse_args()

    # Validate --lang early against the known allowlist (breaks SSRF taint path).
    if args.lang is not None and args.lang not in _ALLOWED_LANGS:
        log.error(
            "Unknown --lang value %r. Allowed values: %s",
            args.lang,
            ", ".join(sorted(_ALLOWED_LANGS)),
        )
        sys.exit(1)

    teacher = _sanitize_model(args.model)

    # ── Pre-flight checks ────────────────────────────────────────────────────
    if not INPUT_PATH.exists():
        log.error("Input not found: %s", INPUT_PATH)
        sys.exit(1)

    log.info("Checking Ollama is alive at %s ...", OLLAMA_ALIVE_URL)
    if not ollama_alive():
        log.error(
            "Ollama is not responding. Start it with:  ollama serve\n"
            "Then verify teacher is loaded:  ollama list | findstr leviathan"
        )
        sys.exit(1)
    log.info("Ollama OK. Teacher: %s", teacher)

    # ── Load input ───────────────────────────────────────────────────────────
    raw = [
        json.loads(line)
        for line in INPUT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    log.info("Loaded %d failure records from %s", len(raw), INPUT_PATH.name)

    # ── Load already-processed task_ids (--resume) ───────────────────────────
    done_ids: set[str] = set()
    if args.resume and OUTPUT_PATH.exists():
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    meta = json.loads(line).get("_meta", {})
                    if tid := meta.get("task_id"):
                        done_ids.add(tid)
                except Exception:
                    pass
        log.info("Resume mode: %d task_ids already completed", len(done_ids))

    # ── Filter samples ────────────────────────────────────────────────────────
    samples = raw
    if args.lang:
        samples = [s for s in samples if s.get("language") == args.lang]
        log.info("Filtered to lang=%s: %d samples", args.lang, len(samples))
    if args.n:
        samples = samples[: args.n]
        log.info("Capped at --n=%d samples", args.n)

    total = len(samples)
    log.info(
        "\n%s\n  DETERMINEX FAILURE CONVERTER%s\n"
        "  Input    : %d samples\n"
        "  Output   : %s\n"
        "  Teacher  : %s\n%s",
        "=" * 60,
        " [DRY RUN]" if args.dry_run else "",
        total,
        OUTPUT_PATH.name,
        teacher,
        "=" * 60,
    )

    stats = ConversionStats()

    for idx, sample in enumerate(samples):
        task_id = sample.get("task_id", f"unknown_{idx}")
        lang = sample.get("language", "Unknown")
        status = sample.get("final_status", "?")
        broken = sample.get("original_broken_code", "").strip()

        # ── Skip already-done ─────────────────────────────────────────────────
        if task_id in done_ids:
            stats.record_skipped()
            log.info("[%d/%d] SKIP  %s (already converted)", idx + 1, total, task_id)
            continue

        # ── Skip samples with no code to fix ─────────────────────────────────
        if len(broken) < 20:
            stats.record_skipped()
            log.info("[%d/%d] SKIP  %s — no usable broken code", idx + 1, total, task_id)
            continue

        remaining = total - (idx + 1)
        log.info(
            "[%d/%d]  %s  %s  (%s)  ETA ~%s",
            idx + 1,
            total,
            lang,
            task_id,
            status,
            stats.eta(remaining),
        )

        # ── Build prompts ─────────────────────────────────────────────────────
        system_prompt = _SYSTEM.get(lang, _DEFAULT_SYSTEM)
        user_prompt = build_user_prompt(sample)

        # ── Call Leviathan ────────────────────────────────────────────────────
        stats.record_attempt(lang)
        t0 = time.time()
        output = call_leviathan(system_prompt, user_prompt, teacher)
        elapsed_call = round(time.time() - t0, 1)

        if not output or len(output.strip()) < 10:
            reason = "empty or too-short response from Leviathan"
            stats.record_rejected(lang, reason)
            log.warning("  REJECT  %s  (%.1fs)  — %s", task_id, elapsed_call, reason)
            continue

        # ── Validate fix ──────────────────────────────────────────────────────
        fixed_code = strip_fences(output)
        passed, reason = validate(fixed_code, lang)

        if not passed:
            stats.record_rejected(lang, reason)
            log.warning("  REJECT  %s  (%.1fs)  — %s", task_id, elapsed_call, reason)
            continue

        # ── Build SFT sample ──────────────────────────────────────────────────
        strict = lang in _STRICT_LANGS
        sft_sample = {
            "system": system_prompt,
            "user": user_prompt,
            "assistant": fixed_code,
            "_meta": {  # stripped by train_unsloth.py token pre-check
                "task_id": task_id,
                "language": lang,
                "original_status": status,
                "validator": "compile" if strict else "format",
                "validator_result": reason,
                "converted_at": datetime.now(UTC).isoformat(),
            },
        }

        stats.record_validated(lang)
        log.info(
            "  PASS    %s  (%.1fs)  %s  [%s]",
            task_id,
            elapsed_call,
            reason,
            "strict" if strict else "lenient",
        )

        # ── Write ─────────────────────────────────────────────────────────────
        if not args.dry_run:
            with OUTPUT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sft_sample, ensure_ascii=False) + "\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    stats.print_summary()

    # ── Write report ──────────────────────────────────────────────────────────
    if not args.dry_run:
        REPORT_PATH.write_text(
            json.dumps(stats.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Report written: %s", REPORT_PATH)

        if stats.validated > 0:
            log.info(
                "\n  NEXT STEP — add to v6 training:\n"
                '  1. Verify output:  python -c "import pathlib,json; '
                "p=pathlib.Path(r'%s'); "
                "lines=[l for l in p.read_text().splitlines() if l.strip()]; "
                "print(f'{len(lines)} validated samples')\"\n"
                "  2. Add to DATA_PATHS in determinex_trainer/train_unsloth.py (it will appear automatically)\n"
                "  3. Run v6:  python determinex_trainer/train_unsloth.py --version 6 --epochs 2 "
                "--max_seq_length 512 --per_device_batch_size 1 --grad_accum 4 "
                "--mix-general --curriculum-ratio 0.75",
                OUTPUT_PATH,
            )

    if stats.validated == 0 and not args.dry_run:
        log.error(
            "Zero samples validated. Check:\n"
            "  1. Ollama is running: ollama list\n"
            "  2. Leviathan is loaded: ollama list | findstr leviathan\n"
            "  3. rustc on PATH: rustc --version\n"
            "  4. go on PATH:    go version"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
