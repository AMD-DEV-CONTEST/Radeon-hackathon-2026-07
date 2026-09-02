#!/usr/bin/env python3
"""Model-agnostic worker loop for one ProgramBench tool.

Turns a generated PACKET.md into a repeatable patch/gate/apply loop without
hardcoding any LLM provider. The loop is:

    attempt n in 1..max_attempts:
        1. build prompt (PACKET + cluster report + override view + prior lessons)
        2. write prompt to logs/programbench_factory/<slug>/worker_attempt_<n>_prompt.md
        3. invoke --model-cmd with prompt on stdin, capture stdout
        4. extract unified diff from model output
        5. validate the diff only touches the allowed override path
        6. git apply --check, then git apply
        7. pack candidate (pb_pack_candidate.py)
        8. gate candidate (pb_candidate_gate.py)
        9. pb_apply_gate_decision.py on the gate_result.json
       10. on accept: stop and report success
       11. on reject: git apply -R (revert), continue to next attempt
       12. on subprocess failure mid-step: stop, report, do not iterate

Safety:
    - Default mode is --dry-run (writes prompts + result/report only).
    - --execute is required to actually call the model, apply diffs, run eval.
    - --execute refuses if `git status` shows changes outside the allowed
      override path, unless --allow-dirty is passed.
    - Diff validation: the unified-diff `--- a/...` and `+++ b/...` paths must
      all start with corpus/programbench/per_tool_overrides/<slug>/. /dev/null
      sentinels (for file create/delete) are allowed in the prefix-pair if the
      other side targets the allowed path.
    - Never touches tests/fixtures, never writes under
      corpus/programbench/locked/*, never runs full_sweep_iterate.py.
    - The gate is the only score truth. The loop does not look at local mini-eval.

CLI:
    python scripts\\pb_factory_worker_loop.py <slug>
        [--max-attempts N]            default 3
        [--model-cmd "<shell cmd>"]    required if --execute (reads prompt on stdin,
                                       writes unified diff to stdout)
        [--gate-command "<cmd>"]       optional override; default is derived from board
        [--pack-command "<cmd>"]       optional override; default is derived from slug
        [--execute]                    actually call model, apply diffs, run eval
        [--allow-dirty]                allow --execute with unrelated dirty files
        [--refresh-board]              passed through to pb_apply_gate_decision.py on accept
        [--refresh-rag]                passed through to pb_apply_gate_decision.py on accept
        [--python <interpreter>]       default: current sys.executable
        [--dry-run]                    default behavior (writes no source files)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
INVENTORY_DIR = ROOT / "logs" / "programbench_failure_inventory"
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
LOCKED_DIR_REL = "corpus/programbench/locked/"
ALLOWED_PREFIX_TEMPLATE = "corpus/programbench/per_tool_overrides/{slug}/"

SCRIPTS = {
    "pack": ROOT / "scripts" / "pb_pack_candidate.py",
    "gate": ROOT / "scripts" / "pb_candidate_gate.py",
    "apply": ROOT / "scripts" / "pb_apply_gate_decision.py",
}


# ---------------------------------------------------------------- helpers


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _utc_tag() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _short_name(slug: str) -> str:
    if "__" in slug:
        right = slug.split("__", 1)[1]
        if "." in right:
            return right.split(".", 1)[0]
        return right
    return slug


def _safe_read(path: Path, max_chars: int = 24000) -> str:
    if not path.is_file():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(txt) <= max_chars:
        return txt
    return txt[:max_chars] + "\n\n[... truncated]"


def _board_row(slug: str) -> dict[str, Any] | None:
    if not BOARD_JSON.is_file():
        return None
    try:
        board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None
    for r in board:
        if r.get("slug") == slug:
            return r
    return None


def _git_status_outside(allowed_prefix: str) -> list[str]:
    """Return a list of git-changed paths that fall OUTSIDE the allowed prefix.

    Uses `git status --porcelain` and treats both modified and untracked files
    as 'changed'. A path is 'outside' if it does not start with allowed_prefix.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    outside: list[str] = []
    norm_prefix = allowed_prefix.replace("\\", "/").rstrip("/") + "/"
    for line in (proc.stdout or "").splitlines():
        # `XY path` or `XY path -> new_path` for renames
        if len(line) < 4:
            continue
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        norm = path_part.strip('"').replace("\\", "/")
        if not norm.startswith(norm_prefix):
            outside.append(norm)
    return outside


# ---------------------------------------------------------------- prompt


def _prior_lessons(slug: str, limit: int = 3) -> list[Path]:
    lessons_dir = FACTORY_DIR / slug / "lessons"
    if not lessons_dir.is_dir():
        return []
    files = sorted(lessons_dir.glob("*.lesson.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _override_inventory(slug: str) -> list[dict[str, Any]]:
    p = OVERRIDES_DIR / slug
    out: list[dict[str, Any]] = []
    if not p.is_dir():
        return out
    for child in sorted(p.iterdir()):
        if child.is_file() and not child.name.startswith("."):
            if child.name.endswith((".bak", ".backup", ".regressed_pre_recovery")):
                continue
            out.append({"name": child.name, "size": child.stat().st_size})
    return out


_SRC_EXCLUDE_NAMES = {"executable"}
_SRC_EXCLUDE_DIRS = {"__pycache__", "target", ".git", ".pytest_cache", ".mypy_cache"}
_SRC_EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".o",
    ".a",
    ".lib",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".zip",
    ".whl",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".ico",
    ".pdf",
}
_SRC_LANG_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".rs": "rust",
    ".sh": "bash",
    ".bash": "bash",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".txt": "",
    ".sql": "sql",
}
_SRC_MAX_FILE_BYTES = 80_000


def _looks_text(path: Path, max_probe_bytes: int = 8192) -> bool:
    """Cheap heuristic: file is text if first 8 KB has no NUL and decodes as UTF-8."""
    try:
        with path.open("rb") as f:
            chunk = f.read(max_probe_bytes)
    except Exception:
        return False
    if not chunk:
        return True
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _collect_source_context(slug: str, budget_chars: int) -> tuple[str, dict[str, Any]]:
    """Build a markdown section embedding override source content up to `budget_chars`.

    Returns (section_markdown, metrics_dict). Metrics keys:
      - source_context_chars_requested
      - source_context_chars_used
      - source_files_included: [{name, size, chars_included, truncated?, skipped?}]
    """
    overrides_dir = OVERRIDES_DIR / slug
    allowed = ALLOWED_PREFIX_TEMPLATE.format(slug=slug)
    metrics: dict[str, Any] = {
        "source_context_chars_requested": budget_chars,
        "source_context_chars_used": 0,
        "source_files_included": [],
    }
    if not overrides_dir.is_dir() or budget_chars <= 0:
        return "", metrics

    candidates: list[Path] = []
    for child in sorted(overrides_dir.iterdir()):
        if not child.is_file():
            continue
        name = child.name
        if name.startswith("."):
            continue
        if name in _SRC_EXCLUDE_NAMES:
            continue
        if name.endswith((".bak", ".backup", ".regressed_pre_recovery")):
            continue
        if child.suffix.lower() in _SRC_EXCLUDE_EXTS:
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        if size > _SRC_MAX_FILE_BYTES:
            continue
        if not _looks_text(child):
            continue
        candidates.append(child)

    # Priority order: main.<ext> first, then compile.sh, then alphabetical.
    def _priority(p: Path) -> tuple[int, str]:
        n = p.name.lower()
        if n in ("main.py", "main.go", "main.rs", "main.ts", "main.js", "main.rb"):
            return (0, n)
        if n == "compile.sh":
            return (1, n)
        return (2, n)

    candidates.sort(key=_priority)

    if not candidates:
        return "", metrics

    lines: list[str] = []
    lines.append("## Override source content (READ THIS - diff against this EXACT text)")
    lines.append("")
    lines.append(
        f"Total budget: {budget_chars} chars. Files listed in priority order; "
        "any truncation is explicitly marked. Your diff must use line numbers and "
        "context that exactly match the content below - do not invent file content."
    )
    lines.append("")

    remaining = budget_chars
    for p in candidates:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if remaining <= 200:
            lines.append(
                f"### `{allowed}{p.name}` ({size} B) - [SKIPPED: source-context budget exhausted]"
            )
            lines.append("")
            metrics["source_files_included"].append(
                {
                    "name": p.name,
                    "size": size,
                    "chars_included": 0,
                    "skipped": True,
                }
            )
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if len(content) <= remaining:
            chunk = content
            truncated = False
        else:
            chunk = content[:remaining]
            truncated = True
        lang = _SRC_LANG_BY_EXT.get(p.suffix.lower(), "")
        lines.append(f"### Source file: `{allowed}{p.name}` ({size} B)")
        lines.append("")
        lines.append(f"```{lang}")
        # Trim trailing blank line so the closing fence sits on its own line cleanly
        lines.append(chunk.rstrip("\n"))
        if truncated:
            lines.append(f"[TRUNCATED after {len(chunk)} chars of {size}]")
        lines.append("```")
        lines.append("")
        remaining -= len(chunk)
        metrics["source_files_included"].append(
            {
                "name": p.name,
                "size": size,
                "chars_included": len(chunk),
                "truncated": truncated,
            }
        )

    metrics["source_context_chars_used"] = budget_chars - max(0, remaining)
    return "\n".join(lines), metrics


def build_prompt(
    slug: str,
    packet_text: str,
    cluster_md: str,
    override_files: list[dict[str, Any]],
    lessons_paths: list[Path],
    source_context_md: str = "",
) -> str:
    short = _short_name(slug)
    allowed = ALLOWED_PREFIX_TEMPLATE.format(slug=slug)

    # Detect upstream native language from override file extensions.
    # The patch MUST be in the same language as the upstream tool; Python
    # wrappers for non-Python upstreams are corpus debt and will be rejected.
    detected_lang = None
    detected_main = None
    for f in override_files:
        nm = f.get("name", "")
        if nm.endswith(".rs"):
            detected_lang, detected_main = "rust", "src/main.rs"
        elif nm.endswith(".go"):
            detected_lang, detected_main = "go", "main.go"
        elif nm.endswith(".cpp") or nm.endswith(".cc") or nm.endswith(".cxx"):
            detected_lang, detected_main = "cpp", "main.cpp"
        elif nm.endswith(".c"):
            detected_lang, detected_main = "c", "main.c"
        elif nm.endswith(".hs"):
            detected_lang, detected_main = "haskell", "app/Main.hs"
        if detected_lang:
            break
    if not detected_lang:
        # Fall back: assume the slug's audit language. Python is only OK for
        # genuine Python upstreams (a small minority of ProgramBench tools).
        detected_lang, detected_main = "native", "main.<lang>"

    lines: list[str] = []
    lines.append(f"# ProgramBench worker task: {slug}")
    lines.append("")
    lines.append("## STRICT INSTRUCTIONS (read first)")
    lines.append("")
    lines.append("Return ONLY a unified diff. No markdown. No prose.")
    lines.append("")
    lines.append("The diff must use `git diff`-style format (--- a/path, +++ b/path, @@ hunks).")
    lines.append(f"Touch ONLY files under: {allowed}")
    lines.append(
        "Any path outside that prefix will cause the diff to be rejected without applying."
    )
    lines.append(
        "Every context line and every removed line in the diff must be copied byte-for-byte"
    )
    lines.append(
        "from the source block below. Do not invent variables, imports, comments, or nearby"
    )
    lines.append(
        "lines. If you are unsure of surrounding context, use a smaller hunk with only exact"
    )
    lines.append(
        "source lines you can see. A plausible but non-exact context line is worse than no patch."
    )
    lines.append("")
    lines.append("## NATIVE LANGUAGE REQUIREMENT (HARD RULE)")
    lines.append("")
    lines.append(f"This tool's upstream is **{detected_lang}**. The override already contains real")
    lines.append(f"upstream source. Your patch MUST be in **{detected_lang}** source files")
    lines.append(
        f"(typically `{detected_main}` or another `.{('rs' if detected_lang == 'rust' else 'go' if detected_lang == 'go' else 'cpp' if detected_lang == 'cpp' else 'c' if detected_lang == 'c' else 'hs' if detected_lang == 'haskell' else '<lang>')}` file under `{allowed}`)."
    )
    lines.append("")
    lines.append("DO NOT write Python (`main.py` etc.) for this tool. DO NOT reimplement upstream")
    lines.append(
        "behavior in Python. Patching `compile.sh` is acceptable for build flags / install"
    )
    lines.append(
        f"steps / wrapper-binary handling, but BEHAVIORAL fixes must be in {detected_lang}."
    )
    lines.append("")
    lines.append("Gate rule: A patch is only kept if official eval improves passed count")
    lines.append("AND runnable total is stable. Local mini-eval is not score truth.")
    lines.append("")
    lines.append("Make the smallest possible change targeting one failure cluster.")
    lines.append("Do not rewrite the whole file. Do not edit tests or fixtures.")
    lines.append("Do not touch shared scripts.")
    lines.append("")
    lines.append("## PACKET.md (worker contract)")
    lines.append("")
    lines.append(packet_text.strip() or "[packet missing - abort]")
    lines.append("")
    lines.append("## Current cluster report")
    lines.append("")
    lines.append(cluster_md.strip() or "[cluster report missing]")
    lines.append("")
    lines.append("## Current override inventory")
    lines.append("")
    if override_files:
        for f in override_files:
            lines.append(f"- `{allowed}{f['name']}` ({f['size']} B)")
    else:
        lines.append("[no override files]")
    lines.append("")
    if source_context_md:
        lines.append(source_context_md.rstrip())
        lines.append("")
    if lessons_paths:
        lines.append("## Prior lessons for this slug (most recent first)")
        lines.append("")
        for lp in lessons_paths:
            lines.append(f"### {lp.name}")
            lines.append("")
            lines.append(_safe_read(lp, max_chars=4000).strip() or "[lesson empty]")
            lines.append("")
    lines.append("## Output format reminder")
    lines.append("")
    lines.append("Emit ONLY the unified diff. No prose before or after. Example shape:")
    lines.append("")
    lines.append("```")
    lines.append(f"--- a/{allowed}{detected_main}")
    lines.append(f"+++ b/{allowed}{detected_main}")
    lines.append("@@ -120,3 +120,4 @@")
    lines.append(" some context line")
    lines.append("-old line")
    lines.append("+new line")
    lines.append(" trailing context")
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------- diff handling


_DIFF_HEADER_RE = re.compile(r"^(\+\+\+|---) (?:[ab]/)?(.+?)\s*(?:\t.*)?$")


def extract_unified_diff(model_output: str) -> str:
    """Extract the first unified-diff block from model output.

    Tolerates the model wrapping the diff in ```diff / ``` fences, even though
    the prompt instructs not to. Returns "" if no diff is found.
    """
    if not model_output:
        return ""
    text = model_output

    # Strip ```diff / ``` fences if present
    fence_pat = re.compile(r"```(?:diff|patch)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    m = fence_pat.search(text)
    if m:
        text = m.group(1)

    # Find first --- line; take from there to end (or until obvious prose start)
    lines = text.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("diff --git ") or (
            line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
        ):
            start = i
            break
    if start < 0:
        return ""

    # Trim trailing non-diff prose: a diff line is one of:
    #   diff --git ..., index ..., --- ..., +++ ..., @@ ..., + ..., - ..., space-prefixed context, \ no newline.
    trimmed: list[str] = []
    for line in lines[start:]:
        if (
            line.startswith(("diff --git ", "index ", "--- ", "+++ ", "@@ ", "+", "-", " "))
            or line.startswith("\\ ")
            or line == ""
        ):
            trimmed.append(line)
        else:
            # Likely the model added prose after the diff; stop.
            break

    # Ensure trailing newline
    out = "\n".join(trimmed)
    if not out.endswith("\n"):
        out += "\n"
    return out


def validate_diff_paths(diff_text: str, allowed_prefix: str) -> tuple[bool, list[str]]:
    """Verify every --- a/PATH and +++ b/PATH stays inside allowed_prefix.

    /dev/null sentinels (file creation/deletion) are accepted ONLY if the other
    side of the pair targets the allowed prefix.
    """
    allowed = allowed_prefix.replace("\\", "/")
    bad: list[str] = []
    lines = diff_text.splitlines()
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            m1 = _DIFF_HEADER_RE.match(lines[i])
            m2 = _DIFF_HEADER_RE.match(lines[i + 1])
            if m1 and m2:
                a = m1.group(2).strip()
                b = m2.group(2).strip()
                pairs.append((a, b))
            i += 2
        else:
            i += 1
    if not pairs:
        return False, ["[no valid file headers found in diff]"]
    for a, b in pairs:
        a_norm = a.replace("\\", "/")
        b_norm = b.replace("\\", "/")
        a_ok = a_norm == "/dev/null" or a_norm.startswith(allowed)
        b_ok = b_norm == "/dev/null" or b_norm.startswith(allowed)
        # At least one side must point at the allowed prefix (so a pure /dev/null /dev/null pair would be rejected).
        target_ok = a_norm.startswith(allowed) or b_norm.startswith(allowed)
        if not (a_ok and b_ok and target_ok):
            bad.append(f"--- {a}  +++ {b}")
    return (len(bad) == 0), bad


def diff_has_substantive_change(diff_text: str) -> tuple[bool, str]:
    """Reject model diffs that only alter comments/blank lines.

    ProgramBench evals are expensive. A comment-only patch can pass git-apply
    validation but cannot improve official tests, so stop before pack/eval.
    """
    changed: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith(("--- ", "+++ ", "@@ ", "diff --git ", "index ")):
            continue
        if not line.startswith(("+", "-")):
            continue
        body = line[1:].strip()
        if not body:
            continue
        changed.append(body)
        if body.startswith("#!") or body.startswith(("#[", "#![", "//!")):
            return True, "substantive shebang/attribute/doc change"
        if body.startswith(("#", "//", "/*", "*", "*/")):
            continue
        return True, "substantive code/config change"
    if changed:
        return False, "diff only changes comments/blank lines"
    return False, "diff has no changed content lines"


# ---------------------------------------------------------------- diff repair
#
# repair_unified_diff() takes a model-emitted unified diff that `git apply --check`
# rejected and tries to produce an applicable equivalent by anchoring the body
# against the actual target file. Common LLM errors it handles:
#   1. Wrong hunk counts (header says `@@ -1,3 +1,4 @@` but body has 4/5 lines).
#   2. Missing hunk separator (two non-contiguous edits glued into one hunk).
#   3. Wrong starting line numbers (body is correct, only the @@ position is off).
#
# It refuses if:
#   - target file is outside the allowed prefix
#   - source-sequence (context + removed) can't be uniquely anchored
#   - any removed line doesn't actually exist in the target
#
# Returns (repaired_text, metadata). On failure, returns (input_text, metadata).


def _parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    """Parse a unified diff into [{old_path, new_path, hunks: [{header, body}]}]."""
    files: list[dict[str, Any]] = []
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            i += 1
            continue
        # Skip diff --git/index, etc., that may precede this - we already handled
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            i += 1
            continue
        old_m = _DIFF_HEADER_RE.match(lines[i])
        new_m = _DIFF_HEADER_RE.match(lines[i + 1])
        if not old_m or not new_m:
            i += 1
            continue
        fp: dict[str, Any] = {
            "old_path": old_m.group(2).strip(),
            "new_path": new_m.group(2).strip(),
            "hunks": [],
        }
        i += 2
        while i < len(lines):
            if lines[i].startswith("--- "):
                break
            if lines[i].startswith("@@"):
                header = lines[i]
                i += 1
                body: list[str] = []
                while i < len(lines):
                    cur = lines[i]
                    if cur.startswith("@@") or cur.startswith("--- "):
                        break
                    if (
                        cur.startswith(" ")
                        or cur.startswith("-")
                        or cur.startswith("+")
                        or cur.startswith("\\")
                    ):
                        body.append(cur)
                        i += 1
                        continue
                    # blank line - treat as a context line if it's between body lines
                    # (often a real empty line in source). Otherwise stop the hunk.
                    if cur == "":
                        # Peek ahead: if the next non-blank looks like more body, treat as " "
                        j = i + 1
                        while j < len(lines) and lines[j] == "":
                            j += 1
                        if j < len(lines) and (lines[j].startswith((" ", "-", "+", "\\"))):
                            body.append(" ")  # blank context line
                            i += 1
                            continue
                    break
                fp["hunks"].append({"header": header, "body": body})
            else:
                i += 1
        files.append(fp)
    return files


def _line_kind(line: str) -> str:
    """Return 'ctx', 'del', 'add', or 'meta' for a diff body line."""
    if not line:
        return "ctx"
    c = line[0]
    if c == "+":
        return "add"
    if c == "-":
        return "del"
    if c == " ":
        return "ctx"
    return "meta"


def _hunk_source_text(body: list[str]) -> list[str]:
    """Return target-file lines that this hunk EXPECTS to find in order
    (context + removed lines, stripped of their leading marker)."""
    out: list[str] = []
    for line in body:
        kind = _line_kind(line)
        if kind in ("ctx", "del"):
            out.append(line[1:] if line else "")
    return out


def _find_consecutive(target: list[str], needle: list[str], start: int = 0) -> int:
    """Find `needle` as a consecutive slice of `target`. Returns 0-based index, or -1.

    Caller is responsible for uniqueness checks if needed.
    """
    if not needle:
        return -1
    n = len(needle)
    if n > len(target):
        return -1
    for i in range(start, len(target) - n + 1):
        if target[i : i + n] == needle:
            return i
    return -1


def _count_unique(target: list[str], needle: list[str]) -> int:
    if not needle:
        return 0
    n = len(needle)
    count = 0
    i = 0
    while i <= len(target) - n:
        if target[i : i + n] == needle:
            count += 1
            i += 1  # allow overlapping for safety
        else:
            i += 1
    return count


def _split_body_into_runs(
    body: list[str], target_lines: list[str]
) -> list[tuple[list[str], int]] | None:
    """Walk `body` and split into runs that match consecutively against `target_lines`.

    Each run is `(sub_body, source_start_line_0_based)`. Adds (`+`) lines are
    attached to whichever run is currently open (they don't affect source matching).
    Returns None if any source line (ctx/del) cannot be located.
    """
    runs: list[tuple[list[str], int]] = []
    current: list[str] = []
    current_start: int | None = None
    cursor_in_target: int | None = None  # expected position of NEXT source line

    def open_new_run(first_line_text: str, search_from: int) -> tuple[int, int] | None:
        """Find the first occurrence of first_line_text in target_lines from search_from.
        Returns (run_start, next_cursor) or None if not found.
        """
        for k in range(search_from, len(target_lines)):
            if target_lines[k] == first_line_text:
                return k, k + 1
        # fall back to anywhere
        for k in range(0, len(target_lines)):
            if target_lines[k] == first_line_text:
                return k, k + 1
        return None

    for line in body:
        kind = _line_kind(line)
        text = line[1:] if line and kind in ("ctx", "del", "add") else line
        if kind == "add":
            # Doesn't affect source position; attach to current run if open
            if current_start is None:
                # Start a run anchored at cursor 0 if we have one. Otherwise defer.
                current.append(line)
            else:
                current.append(line)
            continue
        if kind == "meta":
            # `\ No newline at end of file` - attach to current
            if current_start is not None:
                current.append(line)
            continue
        # ctx or del
        if current_start is None:
            # Begin new run; anchor at first occurrence
            found = open_new_run(text, 0)
            if found is None:
                return None
            current_start, cursor_in_target = found
            current.append(line)
            continue
        # Check if this source line is the expected next position
        assert cursor_in_target is not None
        if cursor_in_target < len(target_lines) and target_lines[cursor_in_target] == text:
            current.append(line)
            cursor_in_target += 1
            continue
        # Break: finalize current run, open new one
        runs.append((current, current_start))
        # Locate this line AFTER the previous run's last position
        search_from = cursor_in_target
        found = open_new_run(text, search_from)
        if found is None:
            return None
        current = [line]
        current_start, cursor_in_target = found

    if current:
        if current_start is None:
            # Pure-add hunk with no source lines - keep at line 0 conventionally
            runs.append((current, 0))
        else:
            runs.append((current, current_start))
    return runs


def _render_hunk(body: list[str], old_start_0: int, new_start_0: int) -> tuple[str, list[str]]:
    """Render a hunk header from body and 0-based start positions."""
    old_count = sum(1 for line in body if _line_kind(line) in ("ctx", "del"))
    new_count = sum(1 for line in body if _line_kind(line) in ("ctx", "add"))
    # git's hunk header convention: 1-based line numbers; counts can be 0 (no lines)
    # but git accepts `@@ -A,B +C,D @@` for any non-negative B,D.
    header = f"@@ -{old_start_0 + 1},{old_count} +{new_start_0 + 1},{new_count} @@"
    return header, body


def repair_unified_diff(diff_text: str, root: Path = ROOT) -> tuple[str, dict[str, Any]]:
    """Repair common LLM unified-diff format errors by re-anchoring against actual file content.

    Returns (repaired_text, metadata). On any failure to repair, returns (diff_text, metadata_with_reason).
    """
    meta: dict[str, Any] = {
        "repaired": False,
        "reason": "",
        "files": [],
        "hunks_in": 0,
        "hunks_out": 0,
    }
    file_patches = _parse_unified_diff(diff_text)
    if not file_patches:
        meta["reason"] = "no file patches found"
        return diff_text, meta

    out_chunks: list[str] = []
    total_in = 0
    total_out = 0
    root_resolved = root.resolve()

    for fp in file_patches:
        old_path = fp["old_path"]
        new_path = fp["new_path"]
        target_rel = new_path if new_path != "/dev/null" else old_path
        if target_rel == "/dev/null":
            meta["reason"] = "pure /dev/null patch not supported by repair"
            return diff_text, meta

        target_abs = (root / target_rel).resolve()
        try:
            target_abs.relative_to(root_resolved)
        except ValueError:
            meta["reason"] = f"target path escapes root: {target_rel}"
            return diff_text, meta
        if not target_abs.is_file():
            meta["reason"] = f"target file does not exist: {target_rel}"
            return diff_text, meta
        try:
            target_text = target_abs.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # pragma: no cover (defensive)
            meta["reason"] = f"could not read target: {e}"
            return diff_text, meta
        target_lines = target_text.splitlines()

        file_info: dict[str, Any] = {"path": target_rel, "hunks": []}
        repaired_hunks: list[tuple[str, list[str]]] = []
        cumulative_offset = 0  # net (added - removed) from prior hunks in this file

        for h in fp["hunks"]:
            total_in += 1
            body = h["body"]
            source_seq = _hunk_source_text(body)

            # Case A: source_seq found consecutively (and unique-ish) in target
            anchor = _find_consecutive(target_lines, source_seq) if source_seq else -1
            method = ""
            if anchor >= 0 and source_seq:
                # Prefer uniqueness when possible
                if _count_unique(target_lines, source_seq) == 1:
                    method = "recount_unique"
                else:
                    method = "recount_first_match"
                old_start = anchor
                new_start = anchor + cumulative_offset
                hdr, b = _render_hunk(body, old_start, new_start)
                repaired_hunks.append((hdr, b))
                added = sum(1 for line in body if _line_kind(line) == "add")
                removed = sum(1 for line in body if _line_kind(line) == "del")
                cumulative_offset += added - removed
                file_info["hunks"].append(
                    {
                        "method": method,
                        "anchor": anchor + 1,
                        "source_lines": len(source_seq),
                    }
                )
                total_out += 1
                continue

            # Case B: try splitting into consecutive sub-runs
            runs = _split_body_into_runs(body, target_lines)
            if runs is None:
                meta["reason"] = (
                    f"could not anchor hunk in {target_rel}: "
                    f"first source line not found ({(source_seq or ['<empty>'])[0][:80]!r})"
                )
                return diff_text, meta
            sub_method = "split" if len(runs) > 1 else "anchor"
            for sub_body, sub_start in runs:
                # Skip empty runs
                if not sub_body:
                    continue
                old_start = sub_start
                new_start = sub_start + cumulative_offset
                hdr, b = _render_hunk(sub_body, old_start, new_start)
                repaired_hunks.append((hdr, b))
                added = sum(1 for line in sub_body if _line_kind(line) == "add")
                removed = sum(1 for line in sub_body if _line_kind(line) == "del")
                cumulative_offset += added - removed
                total_out += 1
            file_info["hunks"].append({"method": sub_method, "n_sub": len(runs)})

        meta["files"].append(file_info)
        out_chunks.append(f"--- a/{old_path}")
        out_chunks.append(f"+++ b/{new_path}")
        for hdr, b in repaired_hunks:
            out_chunks.append(hdr)
            out_chunks.extend(b)

    repaired = "\n".join(out_chunks)
    if not repaired.endswith("\n"):
        repaired += "\n"
    meta["repaired"] = True
    meta["hunks_in"] = total_in
    meta["hunks_out"] = total_out
    return repaired, meta


# ---------------------------------------------------------------- git apply


def git_apply(diff_text: str, check_only: bool, reverse: bool) -> tuple[int, str, str]:
    """Run `git apply` (or `git apply --check`/`git apply -R`). Returns (rc, stdout, stderr).

    Reads the diff from stdin via BINARY input so Python's universal-newlines
    handling doesn't silently translate `\\n` to `\\r\\n` on Windows (which would
    cause spurious "patch does not apply" failures against LF-encoded files).
    """
    cmd = ["git", "apply"]
    if check_only:
        cmd.append("--check")
    if reverse:
        cmd.append("-R")
    # Use --whitespace=nowarn to ignore harmless trailing whitespace differences.
    cmd.append("--whitespace=nowarn")
    # Normalize the diff to LF before piping in case the model emitted CRLF.
    payload = diff_text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        input=payload,
        capture_output=True,
        text=False,
        timeout=60,
    )
    stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


# ---------------------------------------------------------------- subprocess plumbing


def _run(cmd: list[str], stdin_text: str | None = None, timeout: int = 1800) -> dict[str, Any]:
    started = _utc_now()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-3000:],
            "stderr_tail": (proc.stderr or "")[-3000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"timeout after {timeout}s",
        }
    except Exception as e:
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"{type(e).__name__}: {e}",
        }


def _shell(cmd_str: str, stdin_text: str | None = None, timeout: int = 1800) -> dict[str, Any]:
    """Run a string command via the shell (for --model-cmd / --gate-command overrides)."""
    started = _utc_now()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            cmd_str,
            cwd=str(ROOT),
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            shell=True,
        )
        return {
            "cmd": cmd_str,
            "started": started,
            "finished": _utc_now(),
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-3000:],
            "stderr_tail": (proc.stderr or "")[-3000:],
            "stdout_full": (proc.stdout or ""),  # caller may need full text (model output)
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": cmd_str,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"timeout after {timeout}s",
        }
    except Exception as e:
        return {
            "cmd": cmd_str,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"{type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------- worker attempt


def derive_default_commands(
    slug: str, run_root: Path, py: str, baseline_eval: str, min_passed: int
) -> dict[str, list[str]]:
    return {
        "pack": [py, str(SCRIPTS["pack"]), slug, "--run-root", str(run_root)],
        "gate": [
            py,
            str(SCRIPTS["gate"]),
            slug,
            str(run_root),
            "--baseline-eval",
            baseline_eval,
            "--min-baseline-passed",
            str(min_passed),
            "--python",
            py,
        ],
    }


def attempt_once(
    *,
    slug: str,
    n: int,
    model_cmd: str | None,
    pack_cmd_override: str | None,
    gate_cmd_override: str | None,
    py: str,
    run_root: Path,
    baseline_eval: str,
    min_passed: int,
    allowed_prefix: str,
    factory_slug_dir: Path,
    refresh_board: bool,
    refresh_rag: bool,
    dry_run: bool,
    prompt_text: str,
    model_output_file: Path | None = None,
) -> dict[str, Any]:
    """Run one attempt of the worker loop. Returns a record dict."""
    record: dict[str, Any] = {
        "attempt": n,
        "started": _utc_now(),
        "steps": [],
        "dry_run": dry_run,
    }
    prompt_path = factory_slug_dir / f"worker_attempt_{n}_prompt.md"
    factory_slug_dir.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text, encoding="utf-8")
    record["prompt_path"] = str(prompt_path)

    # ---- Obtain model output (from file in offline-replay mode, else by calling model_cmd) ----
    raw_output = ""
    raw_output_path = factory_slug_dir / f"worker_attempt_{n}_model_output.txt"
    if model_output_file is not None:
        if not model_output_file.is_file():
            record["error"] = f"--model-output-file not found: {model_output_file}"
            record["disposition"] = "preflight-failed"
            record["finished"] = _utc_now()
            return record
        try:
            raw_output = model_output_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            record["error"] = f"could not read --model-output-file: {e}"
            record["finished"] = _utc_now()
            return record
        # Mirror the offline output into the per-attempt log so artifacts are uniform.
        factory_slug_dir.mkdir(parents=True, exist_ok=True)
        raw_output_path.write_text(raw_output, encoding="utf-8")
        record["model_output_path"] = str(raw_output_path)
        record["steps"].append(
            {
                "step": "model_cmd",
                "source": "offline_file",
                "path": str(model_output_file),
                "chars": len(raw_output),
                "returncode": 0,
            }
        )
    elif dry_run:
        # No model call in dry-run without an offline file; render the plan as before.
        record["steps"].append(
            {"step": "model_cmd", "planned": model_cmd or "(none provided)", "executed": False}
        )
        record["steps"].append({"step": "extract_diff", "planned": True, "executed": False})
        record["steps"].append({"step": "validate_diff", "planned": True, "executed": False})
        record["steps"].append({"step": "git_apply_check", "planned": True, "executed": False})
        record["steps"].append({"step": "git_apply", "planned": True, "executed": False})
        defaults = derive_default_commands(slug, run_root, py, baseline_eval, min_passed)
        record["steps"].append(
            {
                "step": "pack",
                "planned_cmd": pack_cmd_override or " ".join(defaults["pack"]),
                "executed": False,
            }
        )
        record["steps"].append(
            {
                "step": "gate",
                "planned_cmd": gate_cmd_override or " ".join(defaults["gate"]),
                "executed": False,
            }
        )
        apply_plan = [
            py,
            str(SCRIPTS["apply"]),
            slug,
            str(run_root / "gate_result.json"),
            "--run-root",
            str(run_root),
        ]
        if refresh_board:
            apply_plan.append("--refresh-board")
        if refresh_rag:
            apply_plan.append("--refresh-rag")
        record["steps"].append(
            {"step": "apply_gate_decision", "planned_cmd": " ".join(apply_plan), "executed": False}
        )
        record["disposition"] = "dry-run (no model call, no diff applied, no eval)"
        record["finished"] = _utc_now()
        return record
    else:
        # EXECUTE path with model_cmd
        if not model_cmd:
            record["error"] = "--execute requires --model-cmd (or --model-output-file)"
            record["finished"] = _utc_now()
            return record
        model_run = _shell(model_cmd, stdin_text=prompt_text, timeout=600)
        raw_output = model_run.pop("stdout_full", "") or ""
        raw_output_path.write_text(raw_output, encoding="utf-8")
        record["model_output_path"] = str(raw_output_path)
        record["steps"].append({"step": "model_cmd", **model_run})
        if model_run["returncode"] != 0:
            record["error"] = "model command failed"
            record["finished"] = _utc_now()
            return record

    # ---- 2. Extract diff (offline-replay falls through to here too) ----
    diff_text = extract_unified_diff(raw_output)
    record["steps"].append(
        {"step": "extract_diff", "diff_chars": len(diff_text), "ok": bool(diff_text)}
    )
    extracted_diff_path = factory_slug_dir / f"worker_attempt_{n}_extracted.diff"
    if diff_text:
        extracted_diff_path.write_text(diff_text, encoding="utf-8")
        record["extracted_diff_path"] = str(extracted_diff_path)
    if not diff_text:
        record["error"] = "no unified diff in model output"
        record["finished"] = _utc_now()
        return record

    # ---- 3. Validate paths ----
    paths_ok, bad_paths = validate_diff_paths(diff_text, allowed_prefix)
    record["steps"].append({"step": "validate_paths", "ok": paths_ok, "bad": bad_paths})
    if not paths_ok:
        record["error"] = f"diff touches paths outside {allowed_prefix}: {bad_paths}"
        record["finished"] = _utc_now()
        return record

    substantive_ok, substantive_reason = diff_has_substantive_change(diff_text)
    record["steps"].append(
        {
            "step": "validate_substantive_change",
            "ok": substantive_ok,
            "reason": substantive_reason,
        }
    )
    if not substantive_ok:
        record["error"] = substantive_reason
        record["finished"] = _utc_now()
        return record

    # ---- 4. git apply --check (with repair fallback) ----
    rc, _so, se = git_apply(diff_text, check_only=True, reverse=False)
    record["steps"].append({"step": "git_apply_check", "rc": rc, "stderr_tail": se[-1500:]})
    diff_for_apply = diff_text
    diff_repaired = False
    repair_path = factory_slug_dir / f"worker_attempt_{n}_repair.json"
    repaired_diff_path = factory_slug_dir / f"worker_attempt_{n}_repaired.diff"
    if rc != 0:
        # Repair pass
        repaired_text, repair_meta = repair_unified_diff(diff_text, ROOT)
        record["steps"].append(
            {
                "step": "repair_diff",
                "repaired": repair_meta.get("repaired"),
                "reason": repair_meta.get("reason"),
                "hunks_in": repair_meta.get("hunks_in"),
                "hunks_out": repair_meta.get("hunks_out"),
            }
        )
        try:
            repair_path.write_text(
                json.dumps(repair_meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            record["repair_meta_path"] = str(repair_path)
        except Exception:
            pass
        if repair_meta.get("repaired"):
            repaired_diff_path.write_text(repaired_text, encoding="utf-8")
            record["repaired_diff_path"] = str(repaired_diff_path)
            # Re-validate repaired paths (defensive - repair should keep them inside)
            rp_ok, rp_bad = validate_diff_paths(repaired_text, allowed_prefix)
            record["steps"].append({"step": "validate_paths_repaired", "ok": rp_ok, "bad": rp_bad})
            if rp_ok:
                rc2, _so2, se2 = git_apply(repaired_text, check_only=True, reverse=False)
                record["steps"].append(
                    {"step": "git_apply_check_repaired", "rc": rc2, "stderr_tail": se2[-1500:]}
                )
                if rc2 == 0:
                    diff_for_apply = repaired_text
                    diff_repaired = True
        if not diff_repaired:
            record["error"] = "git apply --check rejected the diff (repair attempt failed)"
            record["finished"] = _utc_now()
            return record
    record["diff_repaired"] = diff_repaired

    # In dry-run with offline-replay, stop here - we don't mutate working tree.
    if dry_run:
        record["disposition"] = (
            f"offline-replay-complete: diff_repaired={diff_repaired}, git_apply_check would pass"
        )
        record["finished"] = _utc_now()
        return record

    # ---- 5. git apply (the real one) ----
    rc, _so, se = git_apply(diff_for_apply, check_only=False, reverse=False)
    record["steps"].append({"step": "git_apply", "rc": rc, "stderr_tail": se[-1500:]})
    if rc != 0:
        record["error"] = "git apply failed after --check passed"
        record["finished"] = _utc_now()
        return record
    applied_diff_path = factory_slug_dir / f"worker_attempt_{n}_applied.diff"
    applied_diff_path.write_text(diff_for_apply, encoding="utf-8")
    record["applied_diff_path"] = str(applied_diff_path)

    # 6. Pack
    defaults = derive_default_commands(slug, run_root, py, baseline_eval, min_passed)
    if pack_cmd_override:
        pack_result = _shell(pack_cmd_override, timeout=300)
    else:
        pack_result = _run(defaults["pack"], timeout=300)
    record["steps"].append(
        {"step": "pack", **{k: v for k, v in pack_result.items() if k != "stdout_full"}}
    )
    if pack_result["returncode"] != 0:
        # Revert the applied diff so the repo is clean again
        _revert(diff_for_apply, record)
        record["error"] = "pack failed"
        record["finished"] = _utc_now()
        return record

    # 7. Gate (this runs the official Docker eval inside)
    if gate_cmd_override:
        gate_result = _shell(gate_cmd_override, timeout=7200)
    else:
        gate_result = _run(defaults["gate"], timeout=7200)
    record["steps"].append(
        {"step": "gate", **{k: v for k, v in gate_result.items() if k != "stdout_full"}}
    )

    gate_json_path = run_root / "gate_result.json"
    gate_record: dict[str, Any] = {}
    if gate_json_path.is_file():
        try:
            gate_record = json.loads(gate_json_path.read_text(encoding="utf-8"))
        except Exception:
            gate_record = {}
    record["gate_json"] = str(gate_json_path)
    record["gate_decision"] = gate_record.get("decision")
    record["gate_delta"] = gate_record.get("delta")

    if gate_record.get("decision") == "accept":
        # 8a. Apply-decision chain
        apply_cmd = [
            py,
            str(SCRIPTS["apply"]),
            slug,
            str(gate_json_path),
            "--run-root",
            str(run_root),
        ]
        if refresh_board:
            apply_cmd.append("--refresh-board")
        if refresh_rag:
            apply_cmd.append("--refresh-rag")
        apply_cmd += ["--python", py]
        apply_result = _run(apply_cmd, timeout=600)
        record["steps"].append({"step": "apply_gate_decision", **apply_result})
        record["disposition"] = "accepted"
        record["finished"] = _utc_now()
        return record

    # 8b. Reject path - revert the diff, run reject-side apply-decision for the lesson
    _revert(diff_for_apply, record)
    apply_cmd = [
        py,
        str(SCRIPTS["apply"]),
        slug,
        str(gate_json_path),
        "--run-root",
        str(run_root),
        "--python",
        py,
    ]
    apply_result = _run(apply_cmd, timeout=120)
    record["steps"].append({"step": "apply_gate_decision_reject", **apply_result})
    record["disposition"] = "rejected"
    record["finished"] = _utc_now()
    return record


def _revert(diff_text: str, record: dict[str, Any]) -> None:
    rc, _, se = git_apply(diff_text, check_only=False, reverse=True)
    record["steps"].append({"step": "git_apply_reverse", "rc": rc, "stderr_tail": se[-1500:]})
    if rc != 0:
        record["revert_failed"] = True


# ---------------------------------------------------------------- reporting


def write_result_artifacts(slug: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = FACTORY_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "worker_loop_result.json"
    md_path = out_dir / "worker_loop_report.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# {slug} worker loop report")
    lines.append("")
    lines.append(f"Generated: {payload.get('generated_at')}")
    lines.append(f"Mode: {'dry-run' if payload.get('dry_run') else 'execute'}")
    lines.append(f"Max attempts: {payload.get('max_attempts')}")
    lines.append(f"Attempts run: {len(payload.get('attempts') or [])}")
    lines.append(f"Final disposition: **{payload.get('final_disposition') or 'unknown'}**")
    if payload.get("exit_code") is not None:
        lines.append(f"Exit code: {payload['exit_code']}")
    lines.append("")
    if payload.get("dirty_outside"):
        lines.append(
            "## Dirty paths outside the allowed override prefix (--allow-dirty must be set to override)"
        )
        lines.append("")
        for p in payload["dirty_outside"]:
            lines.append(f"- {p}")
        lines.append("")
    lines.append("## Per-attempt summary")
    lines.append("")
    for a in payload.get("attempts") or []:
        lines.append(
            f"### Attempt {a.get('attempt')}: {a.get('disposition') or a.get('error') or 'unknown'}"
        )
        lines.append("")
        lines.append(f"- Prompt: `{a.get('prompt_path')}`")
        if a.get("model_output_path"):
            lines.append(f"- Model output: `{a['model_output_path']}`")
        if a.get("applied_diff_path"):
            lines.append(f"- Applied diff: `{a['applied_diff_path']}`")
        if a.get("gate_json"):
            lines.append(f"- Gate JSON: `{a['gate_json']}` (decision = `{a.get('gate_decision')}`)")
        if a.get("revert_failed"):
            lines.append("- **REVERT FAILED** -- repo is dirty; manual cleanup needed.")
        lines.append("")
    lines.append("## Next safe action")
    lines.append("")
    lines.append(payload.get("next_safe_action", "(none)"))
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument(
        "--model-cmd",
        default=None,
        help="shell command; reads prompt on stdin, writes unified diff to stdout. Required for --execute.",
    )
    ap.add_argument(
        "--gate-command",
        default=None,
        help="optional explicit gate command (overrides default derivation)",
    )
    ap.add_argument(
        "--pack-command",
        default=None,
        help="optional explicit pack command (overrides default derivation)",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="actually call model, apply diffs, and run eval. Default is dry-run.",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit --execute even if git has changes outside the override path",
    )
    ap.add_argument(
        "--refresh-board",
        action="store_true",
        help="pass --refresh-board to pb_apply_gate_decision.py on accept",
    )
    ap.add_argument(
        "--refresh-rag",
        action="store_true",
        help="pass --refresh-rag to pb_apply_gate_decision.py on accept",
    )
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter for pack/gate/apply subprocesses",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="explicit dry-run (default behavior when --execute is absent)",
    )
    ap.add_argument(
        "--source-context-chars",
        type=int,
        default=60000,
        help="Total character budget for embedded override source in the prompt (default 60000). "
        "Files included in priority: main.<ext>, compile.sh, then alphabetical.",
    )
    ap.add_argument(
        "--model-output-file",
        type=Path,
        default=None,
        help="Path to a file whose contents will be used as the model output, bypassing --model-cmd. "
        "Lets you replay saved raw model outputs offline (no API call). Works in both --dry-run "
        "and --execute. In --dry-run, extraction + repair analysis still run but nothing is applied.",
    )
    args = ap.parse_args()

    if "__" not in args.slug:
        sys.stderr.write(f"ERROR: bad slug {args.slug!r}\n")
        return 3

    # Default to dry-run unless --execute
    dry_run = (not args.execute) or args.dry_run

    factory_slug_dir = FACTORY_DIR / args.slug
    allowed_prefix = ALLOWED_PREFIX_TEMPLATE.format(slug=args.slug)

    payload: dict[str, Any] = {
        "slug": args.slug,
        "generated_at": _utc_now(),
        "dry_run": dry_run,
        "max_attempts": args.max_attempts,
        "model_cmd": args.model_cmd,
        "pack_cmd_override": args.pack_command,
        "gate_cmd_override": args.gate_command,
        "refresh_board": bool(args.refresh_board),
        "refresh_rag": bool(args.refresh_rag),
        "allowed_prefix": allowed_prefix,
        "attempts": [],
    }

    # ----- preflight: load packet + cluster + board row -----
    packet_path = factory_slug_dir / "PACKET.md"
    cluster_path = INVENTORY_DIR / f"{args.slug}.official_cluster_report.md"
    packet_text = _safe_read(packet_path)
    cluster_md = _safe_read(cluster_path)
    if not packet_text:
        payload["final_disposition"] = "preflight-failed"
        payload["exit_code"] = 3
        payload["error"] = f"packet missing: {packet_path}. Run pb_make_packet.py first."
        payload["next_safe_action"] = (
            f"Run: scripts\\pb_make_packet.py {args.slug}, then retry this worker loop."
        )
        write_result_artifacts(args.slug, payload)
        sys.stderr.write(payload["error"] + "\n")
        return 3

    row = _board_row(args.slug)
    if row is None:
        payload["final_disposition"] = "preflight-failed"
        payload["exit_code"] = 3
        payload["error"] = f"slug not found in board: {args.slug}"
        payload["next_safe_action"] = "Run scripts\\pb_score_audit.py to refresh the board."
        write_result_artifacts(args.slug, payload)
        return 3

    baseline_eval = row.get("best_eval_path") or ""
    min_passed = int(row.get("best_passed") or 0)
    payload["baseline_eval"] = baseline_eval
    payload["min_baseline_passed"] = min_passed

    # ----- pb_packet_preflight classification (advisory) -----
    preflight_path = ROOT / "scripts" / "pb_packet_preflight.py"
    if preflight_path.is_file():
        try:
            pre_proc = subprocess.run(
                [args.python, str(preflight_path), args.slug, "--json-only"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            pre_json = json.loads(pre_proc.stdout) if pre_proc.stdout else None
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
            pre_json = None
        if pre_json is not None:
            payload["preflight"] = pre_json
            cls = pre_json.get("classification")
            if cls and cls != "PATCH":
                sys.stderr.write(
                    f"WARNING: preflight classification is {cls} (not PATCH). "
                    f"Reasons: {pre_json.get('reasons')}\n"
                )

    # ----- dirty-state guard (execute mode only) -----
    dirty_outside = _git_status_outside(allowed_prefix)
    payload["dirty_outside"] = dirty_outside
    if args.execute and dirty_outside and not args.allow_dirty:
        payload["final_disposition"] = "preflight-failed"
        payload["exit_code"] = 3
        payload["error"] = (
            f"git has {len(dirty_outside)} change(s) outside {allowed_prefix}. "
            "Refusing to --execute without --allow-dirty."
        )
        payload["next_safe_action"] = (
            "Either commit/stash the unrelated changes, or pass --allow-dirty if "
            "they are intentional and reviewed."
        )
        write_result_artifacts(args.slug, payload)
        sys.stderr.write(payload["error"] + "\n")
        return 3

    # ----- build run_root once per loop invocation -----
    run_root = (
        ROOT / ".determinex_staging" / f"pb_{_short_name(args.slug)}_worker_loop_{_utc_tag()}"
    )
    payload["run_root"] = str(run_root)

    # ----- build prompt once (model gets the same task each attempt; future v2 may
    # inject prior-attempt feedback into the prompt) -----
    override_files = _override_inventory(args.slug)
    lessons = _prior_lessons(args.slug, limit=3)
    source_context_md, source_metrics = _collect_source_context(
        args.slug, args.source_context_chars
    )
    payload.update(source_metrics)
    prompt_text = build_prompt(
        args.slug,
        packet_text,
        cluster_md,
        override_files,
        lessons,
        source_context_md=source_context_md,
    )
    payload["prompt_chars"] = len(prompt_text)

    # ----- attempt loop -----
    final_disposition = "no-attempts"
    exit_code = 1
    for n in range(1, args.max_attempts + 1):
        rec = attempt_once(
            slug=args.slug,
            n=n,
            model_cmd=args.model_cmd,
            pack_cmd_override=args.pack_command,
            gate_cmd_override=args.gate_command,
            py=args.python,
            run_root=run_root,
            baseline_eval=baseline_eval,
            min_passed=min_passed,
            allowed_prefix=allowed_prefix,
            factory_slug_dir=factory_slug_dir,
            refresh_board=args.refresh_board,
            refresh_rag=args.refresh_rag,
            dry_run=dry_run,
            prompt_text=prompt_text,
            model_output_file=args.model_output_file,
        )
        payload["attempts"].append(rec)

        if rec.get("revert_failed"):
            final_disposition = "revert-failed"
            exit_code = 2
            break

        if rec.get("disposition") == "accepted":
            final_disposition = "accepted"
            exit_code = 0
            break

        if dry_run:
            # Don't loop in dry-run; one attempt is enough to demonstrate the plan
            final_disposition = "dry-run-complete"
            exit_code = 0
            break

        if rec.get("disposition") == "rejected":
            final_disposition = "rejected-continuing"
            exit_code = 1
            continue

        # Subprocess or validation error: stop the loop, don't keep paying for model calls
        final_disposition = f"attempt-error: {rec.get('error', 'unknown')}"
        exit_code = 2
        break

    if final_disposition == "rejected-continuing":
        final_disposition = "rejected-all-attempts"
        exit_code = 1

    payload["final_disposition"] = final_disposition
    payload["exit_code"] = exit_code

    # ----- next safe action -----
    if final_disposition == "accepted":
        payload["next_safe_action"] = (
            "Patch was accepted by the gate and the apply-decision chain ran. "
            "Codex should review the working-tree diff and commit when ready."
        )
    elif final_disposition.startswith("rejected"):
        payload["next_safe_action"] = (
            "All attempts were rejected by the gate. Inspect each attempt's "
            "applied.diff (now reverted) and the gate_result.json under run_root. "
            "Consider a narrower cluster target or run pb_upstream_oracle.py for "
            "any cross-branch contradictions before retrying."
        )
    elif final_disposition == "revert-failed":
        payload["next_safe_action"] = (
            "A `git apply -R` failed mid-loop and the working tree is dirty. "
            "Inspect `git status` manually and decide whether to checkout the "
            "override or keep the partial change."
        )
    elif final_disposition == "dry-run-complete":
        payload["next_safe_action"] = (
            "Dry-run wrote the prompt and the planned commands. Re-run with --execute "
            "and a real --model-cmd (e.g., a shell wrapper around an LLM API call) "
            "to invoke the full loop."
        )
    else:
        payload["next_safe_action"] = "Review worker_loop_result.json for the specific error."

    write_result_artifacts(args.slug, payload)
    print(
        json.dumps(
            {
                "slug": args.slug,
                "dry_run": dry_run,
                "final_disposition": final_disposition,
                "exit_code": exit_code,
                "attempts": len(payload["attempts"]),
                "result_json": str(FACTORY_DIR / args.slug / "worker_loop_result.json"),
                "report_md": str(FACTORY_DIR / args.slug / "worker_loop_report.md"),
            },
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
