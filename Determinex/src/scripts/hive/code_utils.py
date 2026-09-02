"""
scripts/hive/code_utils.py — Code extraction and error analysis utilities
==========================================================================
Extracted from executor.py. Pure functions — no I/O, no imports from other
hive modules. Safe to import from prompt_builder.py without circular deps.
"""

from __future__ import annotations

import re

# ── Chat-template noise stripping ────────────────────────────────────────────

_CHAT_TEMPLATE_TOKENS = re.compile(
    r"<\|im_start\|>.*?<\|im_end\|>|<\|im_start\|>.*|<\|im_end\|>|"
    r"<\|begin_of_text\|>|<\|end_of_text\|>|<\|eot_id\|>|<s>|</s>",
    re.DOTALL,
)

# DSL metadata prefixes that DSL-fine-tuned Builders wrap code output in.
_DSL_META_PREFIXES = (
    "###",
    "obj[",
    "INTENT:",
    "CONFIDENCE:",
    "ENTROPY_CAL:",
    "RESULT:",
    "FOCUS:",
    "CONSTRAINT:",
    "CONTEXT:",
    "LANG:",
    "PATTERN:",
    "VERDICT:",
    "ISSUE:",
    "DSL ",
    # Instruction-echo patterns (model repeating back user message instead of code)
    "CONSTRAINTS:",
    "GOAL:",
    "STEP ",
    "DSL CONTEXT:",
    "TARGET FILE:",
    "CURRENT FILE",
    "LAST COMPILER",
    "•",  # bullet point •
)


def _strip_trailing_fences(code: str) -> str:
    """Remove stray triple-backtick sequences that leak into extracted code."""
    return re.sub(r"`{3,}\s*$", "", code, flags=re.MULTILINE).rstrip()


def _extract_code_block(response_text: str) -> str:
    """
    Extract fenced code block from LLM response.

    Multi-stage strategy — handles DSL-fine-tuned models that may wrap code in
    metadata envelopes (obj['code']```python...```) instead of bare fences:

    1. Standard fence on own line: ```python\\n...\\n```
    2. Inline fence with preamble: obj['code']```python\\n...\\n```
    3. Unterminated fence: extract from open ``` to EOF
    4. Filtered fallback: strip DSL metadata lines, return remaining text
    """
    text = _CHAT_TEMPLATE_TOKENS.sub("", response_text)

    # Stage 1 — well-formed fence on its own line (happy path)
    m = re.search(r"(?:^|\n)```(?:\w+)?\n(.*?)\n```", text, re.DOTALL)
    if m:
        return _strip_trailing_fences(m.group(1)).strip()

    # Stage 2 — fence appears inline (e.g. obj['code']```python\n...\n```)
    m = re.search(r"```(?:\w+)?\n(.*?)\n```", text, re.DOTALL)
    if m:
        return _strip_trailing_fences(m.group(1)).strip()

    # Stage 3 — fence opened but never closed (model hit token limit mid-block)
    m = re.search(r"```(?:\w+)?\n(.*)", text, re.DOTALL)
    if m:
        return _strip_trailing_fences(m.group(1).rstrip("\n")).strip()

    # Stage 4 — no fence: filter out DSL/metadata lines, return remaining code
    lines = text.split("\n")
    code_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped in ("```", "```python", "```py", "```python3"):
            continue
        if any(stripped.startswith(p) for p in _DSL_META_PREFIXES):
            continue
        code_lines.append(line)
    while code_lines and not code_lines[0].strip():
        code_lines.pop(0)
    while code_lines and not code_lines[-1].strip():
        code_lines.pop()
    result = "\n".join(code_lines).strip()

    # Stage 4 validity check: if every non-empty line is a comment, this is
    # planning text echoed back, not code. Return empty to trigger retry.
    non_empty = [l.strip() for l in result.splitlines() if l.strip()]
    if non_empty and all(l.startswith("#") for l in non_empty):
        return ""
    return result


# ── Concurrency keyword detection ────────────────────────────────────────────

_CONCURRENCY_KEYWORDS = frozenset(
    (
        "arc",
        "mutex",
        "rwlock",
        "thread",
        "spawn",
        "concurrent",
        "concurr",
        "channel",
        "tokio",
        "async",
        "await",
        "mpsc",
        "lock",
        "sync",
        "atomic",
        "std::sync",
        "std::thread",
    )
)


def _instruction_requires_concurrency(text: str) -> bool:
    """Return True if the text mentions concurrency primitives that require Arc/Mutex/threads."""
    low = text.lower()
    return any(kw in low for kw in _CONCURRENCY_KEYWORDS)


# ── Compiler error analysis ───────────────────────────────────────────────────


def _extract_missing_derives(compiler_error: str) -> str:
    """
    Parse E0277 compiler errors and return a targeted CRITICAL directive if structs
    are missing derives. This gives the model surgical guidance on retries instead of
    relying on the general DERIVES RULE in the system prompt.
    """
    _derivable = frozenset(
        (
            "Debug",
            "PartialEq",
            "Clone",
            "Hash",
            "Eq",
            "Copy",
            "Display",
            "Serialize",
            "Deserialize",
            "Default",
            "Ord",
            "PartialOrd",
        )
    )
    missing: dict[str, set[str]] = {}

    # e.g. `Task` doesn't implement `Debug`
    for m in re.finditer(r"`(\w+)` doesn't implement `(\w+)`", compiler_error):
        struct, trait = m.group(1), m.group(2)
        if trait in _derivable:
            missing.setdefault(struct, set()).add(trait)

    # e.g. the trait bound `Task: PartialEq` is not satisfied
    # Also handles qualified paths like `Config: serde::Deserialize<'de>`
    for m in re.finditer(
        r"the trait bound `(\w+): (?:\w+::)*(\w+)(?:<[^>]*)?>` is not satisfied",
        compiler_error,
    ):
        struct, trait = m.group(1), m.group(2)
        if trait in _derivable:
            missing.setdefault(struct, set()).add(trait)

    if not missing:
        return ""

    parts = [
        f"  • `{struct}` needs `#[derive({', '.join(sorted(traits))})]`"
        for struct, traits in missing.items()
    ]
    return "\n\nCRITICAL — DERIVE FIX REQUIRED (add these before any other changes):\n" + "\n".join(
        parts
    )


def _extract_trait_scope_fix(compiler_error: str) -> str:
    """
    Parse E0405 'cannot find trait X in this scope' errors and return a targeted fix.
    Catches the common `impl Display for T` (missing `fmt::` prefix) pattern.
    """
    fixes = []

    # E0405: cannot find trait `Display` in this scope
    if "cannot find trait `Display`" in compiler_error or "E0405" in compiler_error:
        if "Display" in compiler_error:
            fixes.append(
                "  • `impl Display for X` is WRONG — change to `impl fmt::Display for X` "
                "(add `fmt::` prefix). With `use std::fmt;`, Display is accessed as `fmt::Display`."
            )

    if not fixes:
        return ""
    return "\n\nCRITICAL — TRAIT SCOPE FIX:\n" + "\n".join(fixes)


def _extract_serde_inference_fix(compiler_error: str) -> str:
    """
    Parse E0282 'type annotations needed' errors on serde_json calls and return
    a targeted fix. Catches the `match serde_json::from_str(...)` without type pattern.
    """
    if "E0282" not in compiler_error and "type annotations needed" not in compiler_error:
        return ""
    if "from_str" not in compiler_error and "from_reader" not in compiler_error:
        return ""
    return (
        "\n\nCRITICAL — SERDE TYPE ANNOTATION REQUIRED (E0282):\n"
        "  `serde_json::from_str()` cannot infer the target type. "
        "You MUST write a typed binding:\n"
        "  `let config: Config = serde_json::from_str(&content)?;`\n"
        "  NOT: `match serde_json::from_str(&content) { ... }` (no type = E0282)\n"
        "  NOT: bare `serde_json::from_str(&content)?` without assigning to a typed variable."
    )


def _extract_type_mismatch_fix(compiler_error: str) -> str:
    """
    Parse E0308 type mismatch errors involving numeric primitives and return
    a targeted CRITICAL directive. Catches the common usize/u32 Vec::len() pattern.
    """
    fixes = []

    # e.g. expected `u32`, found `usize`
    for m in re.finditer(r"expected `([a-z0-9]+)`, found `([a-z0-9]+)`", compiler_error):
        expected, found = m.group(1), m.group(2)
        numeric = {
            "u8",
            "u16",
            "u32",
            "u64",
            "u128",
            "i8",
            "i16",
            "i32",
            "i64",
            "i128",
            "usize",
            "isize",
            "f32",
            "f64",
        }
        if expected in numeric and found in numeric:
            fixes.append(
                f"  • Type mismatch: got `{found}`, need `{expected}`. "
                f"Cast with `value as {expected}` (e.g. `self.tasks.len() as {expected}`)."
            )

    if not fixes:
        return ""
    return (
        "\n\nCRITICAL — TYPE FIX REQUIRED:\n"
        + "\n".join(fixes)
        + "\nFor Vec::len() returning u32: write `self.items.len() as u32`."
    )


def _parse_cargo_deps(cargo_toml: str) -> list[str]:
    """Extract dependency crate names from a Cargo.toml string."""
    deps: list[str] = []
    in_deps = False
    for line in cargo_toml.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_deps = stripped in ("[dependencies]", "[dev-dependencies]", "[build-dependencies]")
            continue
        if in_deps and stripped and not stripped.startswith("#"):
            name = stripped.split("=")[0].strip()
            if name:
                deps.append(name)
    return deps
