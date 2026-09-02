#!/usr/bin/env python3
"""Full-sweep PB iteration: tuned-v11 + English-bullet spec + mini-eval.

For every PB tool that has extracted_tests:
  1. Build English-bullet spec from its pytest tests (pb_spec_extract.py)
  2. Optionally augment with cross-tool RAG (top-K nearest neighbors across corpus)
  3. Generate candidate main.py via determinex-engineer-v11-tuned
  4. Mini-eval: pytest against extracted_tests with EXECUTABLE patched
  5. Compare to baseline (from PB_WORK_MATRIX_200_after_corpus_2026-05-17.md)
  6. Log delta; keep candidate as candidate file (never overwrite live override)
  7. Hardware watchdog: pause if RAM < 1.5GB free or GPU temp > 80C
  8. 20s cooldown between tools

Output:
  logs/full_sweep/run_<ts>/results.json
  logs/full_sweep/run_<ts>/<slug>/{prompt.txt, raw_response.txt, main.py, mini_eval.txt}
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pb_spec_extract import build_spec_prompt  # type: ignore

EXTRACTED = Path("T:/determinex-programbench/_extracted_tests")
MATRIX = ROOT / "corpus/programbench/results/PB_WORK_MATRIX_200_after_corpus_2026-05-17.md"
OUT = ROOT / "logs" / "full_sweep" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)

MODEL = "determinex-observer-v6-tuned"
EMBED_MODEL = "nomic-embed-text:latest"
OLLAMA_URL = "http://localhost:11434"
PG_DSN = "postgresql://determinex:determinex@localhost:5432/determinex"

USE_RAG = True  # cross-tool RAG retrieval — proved to help Observer-3B (dutree sim=0.984)
RAG_K = 3

MIN_FREE_RAM_GB = 1.5
MAX_GPU_TEMP_C = 80
COOLDOWN_S = 15
INFERENCE_TIMEOUT_S = 300
MINI_EVAL_TIMEOUT_S = 120

# Iteration: try up to MAX_ATTEMPTS per tool, feeding first-attempt errors into retry.
# Skip iteration if attempt 1 already wins OR scored too low to recover.
MAX_ATTEMPTS = 2
RETRY_MIN_SCORE_PCT = 5.0  # if attempt 1 < 5%, iteration unlikely to help — skip
RETRY_ONLY_IF_NEAR = True  # only iterate when attempt 1 within 25pp of baseline


def hw_check() -> tuple[bool, str]:
    import psutil

    m = psutil.virtual_memory()
    free_gb = m.available / 1e9
    if free_gb < MIN_FREE_RAM_GB:
        return False, f"RAM low: {free_gb:.2f}GB"
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        temp = int(r.stdout.strip().split()[0])
        if temp > MAX_GPU_TEMP_C:
            return False, f"GPU hot: {temp}C"
    except Exception:
        pass
    return True, f"OK ({free_gb:.1f}GB RAM)"


def hw_wait_for_safe(log) -> None:
    while True:
        ok, reason = hw_check()
        if ok:
            return
        log.write(f"  [hw PAUSE] {reason} — sleep 60s\n")
        log.flush()
        time.sleep(60)


def load_baselines() -> dict[str, float]:
    """Pull tool baseline scores from the PB matrix."""
    out = {}
    if not MATRIX.is_file():
        return out
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*([^/]+)/([^\s|]+)\s*\|\s*([\d.]+)\s*\|", line)
        if m:
            author, tool, score = m.group(1).strip(), m.group(2).strip(), float(m.group(3))
            out[f"{author}__{tool}"] = score
    return out


def find_extracted_branches(slug: str) -> list[Path]:
    """Find test branches for a tool slug. Handles slug-prefix matching."""
    base = slug.split(".")[0] if "." in slug else slug
    # First try exact slug
    direct = EXTRACTED / slug
    if direct.is_dir():
        return [b for b in direct.iterdir() if b.is_dir() and (b / "eval/tests").is_dir()]
    # Fall back to prefix match
    for d in EXTRACTED.iterdir():
        if d.name.startswith(base + "."):
            return [b for b in d.iterdir() if b.is_dir() and (b / "eval/tests").is_dir()]
    return []


def rag_embed(text: str) -> list[float] | None:
    try:
        payload = json.dumps({"model": "nomic-embed-text:latest", "prompt": text[:3000]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["embedding"]
    except Exception as e:
        sys.stderr.write(f"[rag embed fail: {e}]\n")
        return None


def rag_retrieve(slug: str, query_text: str, k: int = 3) -> list[dict]:
    """Retrieve top-K most similar examples from pgvector.

    Prefer same-tool matches (sim weighted higher) but allow cross-tool fallback.
    Returns list of {sim, tool_slug, test_name, example_type, assistant_content}.
    """
    if not USE_RAG:
        return []
    qemb = rag_embed(query_text)
    if qemb is None:
        return []
    try:
        import psycopg

        conn = psycopg.connect(PG_DSN, autocommit=True)
        cur = conn.cursor()
        # Same-tool first
        cur.execute(
            """
            SELECT meta, text, 1 - (embedding <=> %s::vector) AS sim
            FROM rag_chunks
            WHERE corpus='programbench' AND source_path = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """,
            (qemb, slug, qemb, k),
        )
        rows = list(cur.fetchall())
        # If fewer than k, fill from cross-tool
        if len(rows) < k:
            cur.execute(
                """
                SELECT meta, text, 1 - (embedding <=> %s::vector) AS sim
                FROM rag_chunks
                WHERE corpus='programbench' AND source_path != %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """,
                (qemb, slug, qemb, k - len(rows)),
            )
            rows.extend(cur.fetchall())
        conn.close()
        out = []
        for meta, text, sim in rows:
            m = meta if isinstance(meta, dict) else json.loads(meta)
            out.append(
                {
                    "sim": float(sim),
                    "tool_slug": m.get("tool_slug", ""),
                    "test_name": m.get("test_name", ""),
                    "example_type": m.get("example_type", ""),
                    "assistant_content": m.get("assistant_content", "")[:1500],
                }
            )
        return out
    except Exception as e:
        sys.stderr.write(f"[rag retrieve fail: {e}]\n")
        return []


def inject_rag_into_prompt(base_prompt: str, retrieved: list[dict]) -> str:
    """Insert RAG snippets between the example block and the spec block."""
    if not retrieved:
        return base_prompt
    rag_block = ["", "=== REFERENCE IMPLEMENTATIONS (similar tools' working code) ===", ""]
    for i, ex in enumerate(retrieved, 1):
        ans = ex["assistant_content"]
        # Strip "Working impl region:" prefix from training-data artifact
        ans = re.sub(r"^.*?```python\s*\n", "", ans, flags=re.S)
        ans = ans.rsplit("```", 1)[0].strip()
        if not ans or "def " not in ans:
            continue
        rag_block.append(f"# ref {i} (from {ex['tool_slug']}, sim={ex['sim']:.2f}) — pattern hint:")
        for ln in ans.splitlines()[:25]:
            rag_block.append("    " + ln)
        rag_block.append("")
    rag_block.append("=== END REFERENCES ===")
    rag_block.append("")
    # Insert RAG block after the END EXAMPLE marker
    if "=== END EXAMPLE" in base_prompt:
        before, after = base_prompt.split("=== END EXAMPLE", 1)
        idx = after.find("===")  # find end of that line
        if idx >= 0:
            line_end = after.find("\n", idx)
            return (
                before
                + "=== END EXAMPLE"
                + after[: line_end + 1]
                + "\n".join(rag_block)
                + after[line_end + 1 :]
            )
    return base_prompt + "\n" + "\n".join(rag_block)


_ANSI_RE = re.compile(r"\x1b\[[?]*[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")


def strip_ansi(s: str) -> str:
    """Strip ANSI control sequences (spinner, cursor moves) that Ollama emits to stdout."""
    return _ANSI_RE.sub("", s)


def call_model(prompt: str) -> tuple[str, float]:
    """Call tuned v11 via /api/generate (raw HTTP — avoids spinner contamination).

    Ollama's CLI emits ANSI control chars into stdout which break python compile().
    Using the HTTP API directly returns pure model output with no decoration.
    """
    t0 = time.time()
    payload = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": 8192,
                "num_predict": 4096,
                "temperature": 0.2,
                "top_p": 0.9,
                "repeat_penalty": 1.18,
                "repeat_last_n": 256,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=INFERENCE_TIMEOUT_S) as resp:
            body = json.loads(resp.read())
            return body.get("response", ""), time.time() - t0
    except Exception as e:
        return f"<API ERROR: {e}>", time.time() - t0


def _scrub(code: str) -> str:
    """Aggressively scrub generated Python output.

    Models trained on terminal-tool source occasionally hallucinate ANSI escape
    sequences (\\x1b[5D[K cursor-moves) inside f-strings, which break Python's
    tokenizer with 'unterminated string literal' or 'invalid non-printable
    character U+001B'. Instead of relying on regex (which misses bare \\x1b),
    we filter character-by-character: keep printable Unicode + \\n\\t, drop
    everything else (BOM, ESC, BEL, NUL, vertical tab, form feed, DEL, etc.).
    """
    # Strip ANSI CSI/OSC FIRST (multi-char sequences — drop entire sequence
    # rather than just the ESC, so we don't leave [5D[K residue)
    code = re.sub(r"\x1b\[[?]*[0-9;]*[A-Za-z]", "", code)
    code = re.sub(r"\x1b\][^\x07]*\x07", "", code)
    # Now char-by-char: keep printable + newline + tab; drop everything else
    out = []
    for ch in code:
        if ch == "\n" or ch == "\t":
            out.append(ch)
        elif ch == "\r":
            out.append("\n")
        elif ch.isprintable():
            out.append(ch)
        # else: drop (BOM, ESC, BEL, NUL, vertical tab, form feed, DEL, etc.)
    code = "".join(out)
    return code


def extract_python(s: str) -> str | None:
    """Best-effort code extraction from LLM output. Scrubs control chars."""
    s = _scrub(s)
    # Try markdown fenced block first
    m = re.search(r"```(?:python)?\s*\n(.*?)```", s, re.S)
    if m:
        body = m.group(1).strip()
        if "def " in body or "import " in body or "#!" in body:
            return body
    # Try raw — find from shebang to end
    m = re.search(r"(#!/usr/bin/env python.*?)(?:\Z|```)", s, re.S)
    if m:
        return m.group(1).strip()
    # Try from any `import` line
    if "import " in s and "def " in s:
        idx = s.find("import")
        body = s[idx:].strip()
        if "sys.exit(main())" in body:
            body = body[: body.rindex("sys.exit(main())") + len("sys.exit(main())")]
        return body
    return None


def syntactic_validity(code: str) -> tuple[bool, str]:
    """Quick compile check — reject syntax errors before mini-eval."""
    try:
        compile(code, "<candidate>", "exec")
        return True, "OK"
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (line {e.lineno})"


_EXE_VAR_NAMES = (
    "EXECUTABLE",
    "EXE",
    "BINARY",
    "EXEC",
    "EXEPATH",
    "EXECUTABLE_PATH",
    "BIN",
    "CLI",
    "CLI_PATH",
    "PROGRAM",
)


def _patch_runner(path: Path, candidate: Path) -> str | None:
    """Patch utils.py / conftest.py to invoke the candidate Python script.

    Universal approach (works for many PB test layouts):
      1. Insert `import sys` at top if missing
      2. Replace any assignment to common executable-path var names
         (EXECUTABLE, EXE, BINARY, EXEC, BIN, CLI, ...) with the candidate path
      3. Rewrite subprocess.run([VAR, *args]) calls to subprocess.run(
         [sys.executable, VAR, *args]) so Python can execute the candidate .py
      4. Also handle str(VAR) wrapped patterns

    All replacements via lambdas (avoids re.sub backslash interpretation on
    Windows paths).
    """
    if not path.is_file():
        return None
    orig = path.read_text(encoding="utf-8", errors="replace")
    patched = orig
    if "import sys" not in patched[:300]:
        patched = "import sys\n" + patched
    # Some conftests use Path operations (.exists(), .resolve(), str()) on
    # EXECUTABLE — make our injected value a Path so the existing semantics work.
    if "from pathlib import Path" not in patched[:600]:
        patched = "from pathlib import Path as _DeterminexPath\n" + patched
        path_cls = "_DeterminexPath"
    else:
        path_cls = "Path"
    candidate_str = candidate.as_posix()
    sys_exe_str = Path(sys.executable).as_posix()

    # (2) Replace EXECUTABLE / EXE / BINARY = ... assignments
    changed = False
    for vn in _EXE_VAR_NAMES:
        pattern = rf"^{vn}\s*=\s*[^\n]+$"
        new_repl = f'{vn} = {path_cls}(r"{candidate_str}")'
        before = patched
        patched = re.sub(pattern, lambda _m: new_repl, patched, count=1, flags=re.M)
        if patched != before:
            changed = True

    # (3a) Wrap subprocess.run([VAR, *args]) → [sys.executable, str(VAR), *args]
    for vn in _EXE_VAR_NAMES:
        patched = re.sub(
            rf"subprocess\.run\(\s*\[\s*{vn}\b",
            lambda _m, v=vn: f"subprocess.run([sys.executable, str({v})",
            patched,
        )
        patched = re.sub(
            rf"subprocess\.run\(\s*\[\s*str\(\s*{vn}\s*\)",
            lambda _m, v=vn: f"subprocess.run([sys.executable, str({v})",
            patched,
        )

    # (3b) Also handle the common `cmd = [str(EXE), *args]; subprocess.run(cmd, ...)`
    # pattern by rewriting the cmd-list construction
    for vn in _EXE_VAR_NAMES:
        patched = re.sub(
            rf"=\s*\[\s*str\(\s*{vn}\s*\)\s*,",
            lambda _m, v=vn: f"= [sys.executable, str({v}),",
            patched,
        )
        patched = re.sub(
            rf"=\s*\[\s*{vn}\s*,",
            lambda _m, v=vn: f"= [sys.executable, str({v}),",
            patched,
        )

    # (3c) Direct relative invocations in tests, including subprocess.Popen.
    patched = patched.replace('["./executable",', f'[sys.executable, r"{candidate_str}",')
    patched = patched.replace("['./executable',", f"[sys.executable, r'{candidate_str}',")
    patched = patched.replace('"./executable ', f'"{sys_exe_str} {candidate_str} ')

    if patched == orig:
        return None
    path.write_text(patched, encoding="utf-8", newline="\n")
    return orig if changed or patched != orig else None


def mini_eval(candidate: Path, branches: list[Path]) -> tuple[int, int, list[str]]:
    """Run pytest with candidate as EXECUTABLE. Cap to 3 branches.

    Different PB tools use different test layouts:
      - some define `run()` + EXECUTABLE in tests/utils.py
      - some define them in tests/conftest.py
    We patch whichever exists.
    """
    passed_total, total = 0, 0
    errors = []
    for branch in branches[:3]:
        eval_dir = branch / "eval"
        tests_dir = eval_dir / "tests"
        if not tests_dir.is_dir():
            continue
        patch_targets = [tests_dir / "utils.py", tests_dir / "conftest.py"]
        patch_targets.extend(sorted(tests_dir.glob("test_*.py")))
        originals: list[tuple[Path, str]] = []
        for patch_target in patch_targets:
            orig = _patch_runner(patch_target, candidate)
            if orig is not None:
                originals.append((patch_target, orig))
        # Also place a copy of the candidate AT eval/executable so any
        # `EXE.exists()` or `assert (REPO_ROOT / "executable").exists()` checks
        # pass. Tests that invoke the path directly will go through our
        # patched run() helpers; this is just to satisfy existence assertions.
        exe_shim = eval_dir / "executable"
        had_exe = exe_shim.exists()
        if not had_exe:
            try:
                exe_shim.write_text(
                    candidate.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                )
            except Exception:
                pass
        if not originals:
            # Still try pytest — the test may use raw subprocess.run(["./executable",...])
            # which our exe_shim might satisfy on POSIX, but won't on Windows without
            # a registered launcher. Log but continue.
            errors.append(f"{branch.name}: no patchable runner; trying raw")
        try:
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(tests_dir),
                    "-q",
                    "--tb=no",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=MINI_EVAL_TIMEOUT_S,
            )
            out = (r.stdout or "") + (r.stderr or "")
            p = int(m.group(1)) if (m := re.search(r"(\d+) passed", out)) else 0
            f = int(m.group(1)) if (m := re.search(r"(\d+) failed", out)) else 0
            e = int(m.group(1)) if (m := re.search(r"(\d+) error", out)) else 0
            passed_total += p
            total += p + f + e
            if (f + e) > 0 and len(errors) < 3:
                fail = next((ln for ln in out.split("\n") if "FAIL" in ln or "ERROR" in ln), "")
                errors.append(fail[:200])
        except subprocess.TimeoutExpired:
            errors.append(f"timeout on {branch.name}")
        finally:
            for patched_path, original in originals:
                patched_path.write_text(original, encoding="utf-8", newline="\n")
            # Remove the exe_shim if we created it (don't pollute test dirs)
            if not had_exe and exe_shim.exists():
                try:
                    exe_shim.unlink()
                except Exception:
                    pass
    return passed_total, total, errors


def build_retry_prompt(
    tool_name: str, prev_code: str, errors: list[str], prev_score: float, baseline: float
) -> str:
    """Build a fix-it prompt: prev attempt + error messages + ask for correction."""
    err_block = (
        "\n".join(f"  - {e}" for e in errors[:5]) if errors else "  (no error detail captured)"
    )
    return (
        f"Your previous Python `main.py` for the CLI tool `{tool_name}` scored "
        f"{prev_score:.1f}% on the test suite (baseline to beat: {baseline:.1f}%). "
        f"Some tests failed. Here is the previous implementation:\n\n"
        f"```python\n{prev_code[:3000]}\n```\n\n"
        f"These are the first failing tests:\n{err_block}\n\n"
        f"Rewrite the complete main.py with corrections to pass these tests. "
        f"Keep what worked, fix what failed. Output ONLY the raw Python code "
        f"(no markdown fences, no commentary), starting with `#!/usr/bin/env python3` "
        f"and ending with `sys.exit(main())`.\n\nCorrected main.py:\n"
    )


def _generate_and_eval(
    slug: str, candidate_dir: Path, branches: list[Path], prompt: str, attempt: int, log
) -> tuple[dict, str | None, list[str]]:
    """One attempt: gen code, write candidate, mini-eval. Returns (result_dict, code_text, errors)."""
    suffix = f"_attempt{attempt}" if attempt > 1 else ""
    (candidate_dir / f"prompt{suffix}.txt").write_text(prompt, encoding="utf-8")

    try:
        raw, dur = call_model(prompt)
    except subprocess.TimeoutExpired:
        log.write(f"  [att{attempt}] TIMEOUT on inference\n")
        return {"skipped": "inference timeout"}, None, []
    (candidate_dir / f"raw_response{suffix}.txt").write_text(raw, encoding="utf-8")
    log.write(f"  [att{attempt}] model: {dur:.1f}s, {len(raw)} chars\n")

    code = extract_python(raw)
    if not code:
        log.write(f"  [att{attempt}] FAIL — no python in response\n")
        return {"skipped": "no code extracted"}, None, []

    ok, reason = syntactic_validity(code)
    if not ok:
        log.write(f"  [att{attempt}] FAIL — {reason}\n")
        return {"skipped": f"syntax: {reason}"}, None, []

    candidate = candidate_dir / f"main{suffix}.py"
    candidate.write_text(code, encoding="utf-8", newline="\n")
    log.write(f"  [att{attempt}] candidate: {len(code)} bytes, syntax OK\n")

    passed, total, errors = mini_eval(candidate, branches)
    pct = 100.0 * passed / max(1, total)
    log.write(f"  [att{attempt}] mini-eval: {passed}/{total} = {pct:.1f}%\n")
    if errors:
        log.write(f"  [att{attempt}] first err: {errors[0][:120]}\n")
    return (
        {
            "passed": passed,
            "total": total,
            "pct": pct,
            "errors": errors[:3],
        },
        code,
        errors,
    )


def process_one(slug: str, baseline: float, log) -> dict:
    log.write(f"\n=== {slug}  (baseline {baseline:.1f}%) ===\n")
    log.flush()
    branches = find_extracted_branches(slug)
    if not branches:
        log.write("  SKIP — no extracted_tests\n")
        return {"slug": slug, "baseline": baseline, "skipped": "no extracted_tests"}
    tool_name = slug.split("__", 1)[-1].split(".", 1)[0]
    tests_dir = branches[0] / "eval/tests"

    candidate_dir = OUT / slug
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # === ATTEMPT 1 ===
    prompt = build_spec_prompt(tool_name, slug, tests_dir)
    if USE_RAG:
        retrieved = rag_retrieve(slug, prompt, k=RAG_K)
        if retrieved:
            log.write(
                f"  [rag] {len(retrieved)} refs (sims: {[round(r['sim'], 2) for r in retrieved]})\n"
            )
            prompt = inject_rag_into_prompt(prompt, retrieved)

    # Prime with the EXISTING override (if any) so the model starts at the
    # baseline and only needs to ADD missing behavior — not reinvent from scratch.
    # The baseline score in the matrix IS the score of this override.
    override_slug = slug.split(".")[0] if "." in slug else slug
    existing_override = None
    for candidate_path in [
        ROOT / "corpus/programbench/per_tool_overrides" / slug / "main.py",
        ROOT / "corpus/programbench/per_tool_overrides" / override_slug / "main.py",
    ]:
        # discover full slug+hash override dir
        if candidate_path.parent.parent.is_dir():
            for d in candidate_path.parent.parent.iterdir():
                if d.is_dir() and d.name.startswith(override_slug):
                    mp = d / "main.py"
                    if mp.is_file():
                        existing_override = mp
                        break
        if existing_override:
            break
    if existing_override and existing_override.is_file():
        try:
            override_src = existing_override.read_text(encoding="utf-8", errors="replace")
            if 100 < len(override_src) < 8000:
                prime = (
                    f"\n\n=== CURRENT IMPLEMENTATION (scores {baseline:.1f}% on these tests) ===\n"
                    f"This is the existing main.py for `{tool_name}`. It already passes some "
                    f"tests but fails others. Your job is to IMPROVE it: keep what works, fix "
                    f"what fails. Output a complete REPLACEMENT main.py.\n\n"
                    f"{override_src}\n\n"
                    f"=== END CURRENT IMPLEMENTATION ===\n"
                )
                # Insert before the final "Complete main.py:" line
                if "Complete main.py:" in prompt:
                    prompt = prompt.replace("Complete main.py:", prime + "Improved main.py:")
                else:
                    prompt = prompt + prime
                log.write(f"  [prime] existing override {len(override_src)} bytes injected\n")
        except Exception as e:
            log.write(f"  [prime] failed: {e}\n")

    log.write(f"  [att1] prompt: {len(prompt)} chars\n")
    res1, code1, errs1 = _generate_and_eval(slug, candidate_dir, branches, prompt, 1, log)
    if "skipped" in res1:
        return {"slug": slug, "baseline": baseline, **res1}

    best = {
        "passed": res1["passed"],
        "total": res1["total"],
        "pct": res1["pct"],
        "errors": res1["errors"],
        "attempt": 1,
        "code": code1,
    }
    delta1 = res1["pct"] - baseline

    # Decide whether to iterate
    do_retry = (
        MAX_ATTEMPTS >= 2
        and delta1 <= 0  # not already a win
        and res1["pct"] >= RETRY_MIN_SCORE_PCT  # not a total wash
        and (not RETRY_ONLY_IF_NEAR or delta1 >= -25.0)  # within 25pp of baseline
    )
    if do_retry:
        # === ATTEMPT 2: feed errors back ===
        retry_prompt = build_retry_prompt(tool_name, code1, errs1, res1["pct"], baseline)
        log.write(f"  [att2] iterating — retry prompt {len(retry_prompt)} chars\n")
        res2, code2, errs2 = _generate_and_eval(slug, candidate_dir, branches, retry_prompt, 2, log)
        if "skipped" not in res2 and res2["pct"] > best["pct"]:
            best = {
                "passed": res2["passed"],
                "total": res2["total"],
                "pct": res2["pct"],
                "errors": res2["errors"],
                "attempt": 2,
                "code": code2,
            }
            log.write(f"  [att2] LIFT: {res1['pct']:.1f}% → {res2['pct']:.1f}%\n")
        else:
            log.write("  [att2] no improvement\n")
    else:
        log.write(f"  no retry (Δ1={delta1:+.2f}pp, pct={res1['pct']:.1f}%)\n")

    # Save best
    final_delta = best["pct"] - baseline
    log.write(
        f"  FINAL: {best['passed']}/{best['total']} = {best['pct']:.1f}% (att{best['attempt']})  Δ={final_delta:+.2f}pp\n"
    )
    # Overwrite main.py with best variant
    (candidate_dir / "main.py").write_text(best["code"], encoding="utf-8", newline="\n")
    (candidate_dir / "mini_eval.txt").write_text(
        f"baseline={baseline:.2f}\ncandidate={best['pct']:.2f}\ndelta={final_delta:+.2f}pp\n"
        f"best_attempt={best['attempt']}\npassed={best['passed']}/{best['total']}\n\n"
        f"errors:\n" + "\n".join(best["errors"]),
        encoding="utf-8",
    )
    return {
        "slug": slug,
        "baseline": baseline,
        "candidate_passed": best["passed"],
        "candidate_total": best["total"],
        "candidate_score": best["pct"],
        "delta": final_delta,
        "best_attempt": best["attempt"],
        "errors": best["errors"][:2],
    }


def discover_targets() -> list[tuple[str, float]]:
    baselines = load_baselines()
    targets: list[tuple[str, float]] = []
    for d in sorted(EXTRACTED.iterdir()):
        if not d.is_dir():
            continue
        slug = d.name
        base_key = slug.split(".")[0] if "." in slug else slug
        baseline = baselines.get(base_key, 0.0)
        targets.append((slug, baseline))
    return targets


def main():
    log = sys.stderr
    log.write(f"=== full_sweep starting → {OUT} ===\n")
    log.write(f"=== model={MODEL} ===\n")
    targets = discover_targets()
    log.write(f"=== {len(targets)} targets discovered ===\n\n")

    results = []
    for i, (slug, baseline) in enumerate(targets, 1):
        log.write(f"[{i}/{len(targets)}] ")
        hw_wait_for_safe(log)
        try:
            r = process_one(slug, baseline, log)
            results.append(r)
            (OUT / "results.json").write_text(
                json.dumps(results, indent=2, default=str), encoding="utf-8"
            )
        except KeyboardInterrupt:
            log.write("\nInterrupted by user.\n")
            break
        except Exception as e:
            log.write(f"  [EXCEPTION] {type(e).__name__}: {e}\n")
            results.append({"slug": slug, "baseline": baseline, "error": str(e)})
            (OUT / "results.json").write_text(
                json.dumps(results, indent=2, default=str), encoding="utf-8"
            )
        log.write(f"  cooldown {COOLDOWN_S}s\n")
        time.sleep(COOLDOWN_S)

    # Summary
    wins = sorted([r for r in results if r.get("delta", 0) > 0], key=lambda x: -x["delta"])
    losses = sorted([r for r in results if r.get("delta", 0) < 0], key=lambda x: x["delta"])
    skipped = [r for r in results if "skipped" in r or "error" in r]

    log.write("\n\n========== SUMMARY ==========\n")
    log.write(
        f"Total: {len(results)}  |  Wins: {len(wins)}  |  Losses: {len(losses)}  |  Skipped: {len(skipped)}\n\n"
    )
    log.write("TOP WINS:\n")
    for r in wins[:20]:
        log.write(
            f"  {r['slug']:55} {r['baseline']:6.2f} → {r['candidate_score']:6.2f}  ({r['delta']:+.2f}pp)\n"
        )
    log.write(f"\nResults json: {OUT}/results.json\n")


if __name__ == "__main__":
    main()
