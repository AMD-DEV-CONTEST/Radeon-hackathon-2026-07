"""
scripts/hive/prompt_builder.py — Builder and Monitor message assembly
======================================================================
Extracted from executor.py. Builds the chat message lists consumed by
api_call() and parses Monitor verdict responses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hive.code_utils import (
    _extract_missing_derives,
    _extract_serde_inference_fix,
    _extract_trait_scope_fix,
    _extract_type_mismatch_fix,
    _instruction_requires_concurrency,
    _parse_cargo_deps,
)
from hive.constants import MAX_LINES_BEFORE_FORCE_REPLACE, MAX_RETRIES_PER_STEP
from hive.manifest import ManifestSession, StepRecord
from hive.workspace import assemble_builder_context


def _build_builder_messages(
    session: ManifestSession,
    step: StepRecord,
    workspace: Path,
    compiler_error: str = "",
    attempt: int = 0,
    prune_context: bool = False,
) -> list[dict]:
    """Assemble the chat messages list for a Builder call.

    #7 Attention-Aware Rollup: on attempt >= 2 (prune_context=True), the
    Orchestrator prunes accumulated failed context from the message history.
    Only the original spec/instruction and the LATEST compiler error are kept.
    This prevents 'Lost in the Middle' attention collapse where the model
    fixates on old errors and forgets the core business logic.
    """
    if session.correctness_test_harness:
        setattr(step, "_session_correctness_test_harness", session.correctness_test_harness)
    builder_ctx = assemble_builder_context(
        workspace,
        step,
        session.lang,
        # #7: On pruned retries, strip out the last compiler error from context
        # assembly too — we inject the clean latest error explicitly below.
        last_compiler_error="" if prune_context else compiler_error,
    )

    # Determine which external crates are actually available in this session's Cargo.toml.
    _available_crates: list[str] = (
        _parse_cargo_deps(session.cargo_toml) if session.cargo_toml else []
    )
    _serde_available = "serde" in _available_crates or "serde_json" in _available_crates

    system_msg = (
        f"You are a {session.lang.capitalize()} code generator. "
        f"Output ONLY a fenced code block — nothing before it, nothing after it.\n"
        f"Format:\n```{session.lang}\n<code here>\n```\n"
        f"Do NOT include explanations, DSL tags, JSON, or metadata. "
        f"Do not include tests unless the step explicitly asks for them.\n"
        f"Write_mode: {step.write_mode}. Target file: {step.target_file}."
    )
    if session.lang == "rust":
        if _available_crates:
            system_msg += (
                f"\nAVAILABLE CRATES (only these may be imported): {', '.join(_available_crates)}."
            )
        else:
            system_msg += "\nAVAILABLE CRATES: NONE — use only std:: (stdlib). Do NOT import serde, serde_json, or any crate not in std."
    # Rust-specific guardrails
    if session.lang == "rust":
        system_msg += (
            "\n\nRust RULES — follow exactly or the code will not compile:"
            "\n- ERROR TYPE RULE: if any function uses `?` on BOTH io::Error AND other errors (ParseIntError, serde_json::Error), the return type MUST be `Result<T, Box<dyn std::error::Error>>`, NOT `io::Result<T>`."
            "\n- LAST EXPRESSION RULE: a bare `serde_json::from_reader(x)` or `serde_json::from_str(&s)` as the last expression of a `Box<dyn Error>` function does NOT auto-coerce. Write `Ok(serde_json::from_reader(x)?)` instead."
            "\n- MATCH ON STRING RULE: use `match args[1].as_str()` with string literals. Do NOT use `match &args[1]`."
            '\n- PATH EXISTS RULE: use `std::path::Path::new("file.json").exists()`. Do NOT call `.exists()` on `&str`.'
            "\n- MUTABILITY RULE: declare `let mut x` if you will modify x."
            "\n- SCOPE RULE: helper functions CANNOT access variables from main() unless passed as parameters."
            "\n- ARGS ITERATOR RULE: `args().next()` returns the PROGRAM NAME. Use `args().nth(1)` or collect to Vec."
            '\n- ARGS UNWRAP RULE: `args.get(n)` returns `Option<&String>`. Do NOT use `.unwrap_or("")` — '
            "that expects `&String` not `&str` and causes E0308. "
            'Use `.map(|s| s.as_str()).unwrap_or("")` to get `&str`, '
            "or `.cloned().unwrap_or_default()` to get `String`."
            "\n- SERDE DESERIALIZE RULE: `serde_json::from_str()` and `serde_json::from_reader()` need a type. "
            "Rust cannot infer it — E0282 will fire. ALWAYS write `let config: Config = serde_json::from_str(&content)?;`. "
            "Do NOT write `match serde_json::from_str(&content)` without a type annotation. "
            "Do NOT write `serde_json::from_str(&content)?` as a bare expression. "
            "Correct pattern: `let cfg: MyStruct = serde_json::from_str(&std::fs::read_to_string(path)?)?;`"
            "\n- SERDE_JSON ERROR RULE: Do NOT pattern match on `serde_json::Error` variants (e.g. `Error::Io(...)`) — "
            "they are PRIVATE and will not compile. Use `?` to propagate or `.map_err(Into::into)` to box."
            "\n- FILE WRITE RULE: `File::create(p)?.write_all(b)?` requires `use std::io::Write;`. "
            "Simpler: use `std::fs::write(path, bytes)?` which needs NO trait import."
            "\n- FILE READ RULE: to read a whole file, use `std::fs::read_to_string(path)?`. "
            "Then pass the string to `serde_json::from_str(&content)?`. No File, no BufReader needed."
            "\n- SELF MUTABILITY RULE: any method that modifies fields, calls `push()`, `get_mut()`, or otherwise mutates `self` MUST be `fn method(&mut self, ...)`. "
            "Using `&self` with mutation operations causes E0596. When in doubt, use `&mut self`."
            "\n- MUTABLE ITERATOR RULE: to mutate fields of elements while iterating a Vec, you need BOTH: "
            "(1) `&mut self` in the method signature AND (2) `for item in &mut self.collection`. "
            "Having `&mut self` with `for item in &self.collection` still yields immutable `&T` refs — you CANNOT assign through them. "
            "Example: `fn mark_done(&mut self, id: u32) -> bool { for task in &mut self.tasks { if task.id == id { task.done = true; return true; } } false }`"
            "\n- PUSH-THEN-USE RULE: after `vec.push(value)`, `value` is MOVED and no longer accessible. "
            "Save needed data BEFORE the push: `let id = self.tasks.len() as u32; self.tasks.push(task); id` — NOT `self.tasks.push(task); task.id`."
            "\n- NUMERIC CAST RULE: Vec::len() and slice/array indices return `usize`. "
            "If your function signature returns u32/u64/i32/i64, you MUST cast: `self.tasks.len() as u32`. "
            "Do NOT return a bare `usize` where `u32` is expected — it will not compile."
            "\n- DISPLAY RULE: to impl Display for a struct, write EXACTLY this:\n"
            "  `use std::fmt;`  ← at top of file\n"
            "  `impl fmt::Display for MyStruct {`  ← the `fmt::` prefix before Display is MANDATORY\n"
            "  `    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, ...) }`\n"
            "  Writing `impl Display for` (without `fmt::`) causes E0405 — it WILL NOT compile."
            "\n- DERIVES RULE: Custom structs need the right derives. "
            "If you use `.contains()` on Vec<T> where T is a custom struct, T needs `#[derive(PartialEq)]`. "
            'If you use `println!("{:?}", ...)` or `{:?}` on a custom type, it needs `#[derive(Debug)]`. '
            "For most structs use `#[derive(Debug, Clone, PartialEq)]`. "
            "NEVER add Serialize or Deserialize unless serde is listed in AVAILABLE CRATES."
            "\n- EXACT RETURN TYPES RULE: Follow the EXACT return type specified in the step instruction. "
            "If the spec says `fn add(...) -> u32`, return `u32` — NOT `Result<u32, _>`. "
            "If the spec says `fn complete(...) -> bool`, return `bool` — NOT `Result<bool, _>`. "
            "Do NOT add Result<> wrappers unless the function does I/O or the step explicitly says Result. "
            "'Must not use unwrap()' means use `if let`/`match`/`.ok()` — it does NOT mean wrap everything in Result. "
            "Vec::push() never fails. Matching an id in a Vec never fails. Those do not need Result."
            "\n- PUB VISIBILITY RULE: In a lib.rs + main.rs project, EVERYTHING that main.rs uses must be `pub`. "
            "This applies to (1) structs: `pub struct Task { ... }`, (2) fields: `pub id: u32`, `pub tasks: Vec<Task>`, "
            "(3) impl methods: `pub fn add(...)`, `pub fn complete(...)`. "
            "Without `pub`, types are module-private: `use pkg::*` in main.rs imports NOTHING, causing E0412. "
            "Private fields cause E0616. Rule: when writing lib.rs, mark ALL structs, ALL fields, ALL methods as `pub`. "
            "Example of correct lib.rs:\n"
            "  `pub struct Task { pub id: u32, pub title: String, pub done: bool }`\n"
            "  `pub struct TaskList { pub tasks: Vec<Task> }`\n"
            "  `impl TaskList { pub fn add(&mut self, title: &str) -> u32 { ... } }`"
            "\n- FORBIDDEN: crates not in AVAILABLE CRATES."
            "\n- FORBIDDEN: lazy_static, once_cell, global state."
        )
        # Also check the original spec so that when the Architect produces a fallback
        # generic instruction, the spec's concurrency requirements still unlock this block.
        _spec_text = ""
        if session.md_spec_path:
            try:
                _spec_path = Path(session.md_spec_path)
                if _spec_path.exists():
                    _spec_text = _spec_path.read_text(encoding="utf-8")[:600]
            except OSError:
                pass
        if _instruction_requires_concurrency(
            step.instruction + " " + (step.dsl_context or "") + " " + _spec_text
        ):
            system_msg += (
                "\n- CONCURRENCY ALLOWED: This step requires threading/synchronisation."
                "\n- USE THIS EXACT PATTERN for a shared counter:\n"
                "```rust\n"
                "use std::sync::{Arc, Mutex};\n"
                "fn main() {\n"
                "    let counter = Arc::new(Mutex::new(0u64));  // bare u64, NOT a struct\n"
                "    let mut handles = vec![];\n"
                "    for _ in 0..4 {\n"
                "        let c = Arc::clone(&counter);\n"
                "        handles.push(std::thread::spawn(move || {\n"
                "            for _ in 0..250 {\n"
                "                *c.lock().unwrap() += 1;  // * dereferences MutexGuard\n"
                "            }\n"
                "        }));\n"
                "    }\n"
                "    for h in handles {\n"
                "        h.join().unwrap();  // NEVER h.join()? — not std::error::Error\n"
                "    }\n"
                '    println!("{}", *counter.lock().unwrap());\n'
                "}\n"
                "```\n"
                "CRITICAL RULES:\n"
                "- Counter MUST be `Mutex::new(0u64)` — a bare number, NOT a custom struct. "
                "A custom struct cannot use `+=` unless you implement AddAssign.\n"
                "- Use `h.join().unwrap()` NEVER `h.join()?`\n"
                "- `*c.lock().unwrap() += 1` — the `*` is required to deref the MutexGuard"
            )
        else:
            system_msg += (
                "\n- FORBIDDEN: Arc, Mutex, RwLock, thread::spawn, async, await, tokio "
                "— this step does not require concurrency. Do not import or use them."
            )
        if step.target_file and "main.rs" in step.target_file:
            system_msg += (
                "\n- CRITICAL: output MUST include fn main(). Without fn main(), rustc emits E0601."
            )
            # Only inject JSON boilerplate when the step actually needs it.
            _needs_json = any(
                kw in (step.instruction + " " + (step.dsl_context or "")).lower()
                for kw in (
                    "json",
                    "serde",
                    "persist",
                    "save",
                    "load",
                    "file",
                    "read_to_string",
                    "write(",
                )
            )
            if _needs_json and _serde_available:
                system_msg += (
                    "\n\nRUST SERDE JSON PATTERN — for reading JSON from a file:\n"
                    "```rust\n"
                    "use serde::Deserialize;  // add Serialize too ONLY if writing JSON\n"
                    "#[derive(Deserialize)]\n"
                    "struct Config { field1: String, field2: u32 }\n"
                    "fn main() -> Result<(), Box<dyn std::error::Error>> {\n"
                    "    let args: Vec<String> = std::env::args().collect();\n"
                    '    if args.len() < 2 { eprintln!("Usage: ... <file.json>"); std::process::exit(1); }\n'
                    "    let content = std::fs::read_to_string(&args[1])?;\n"
                    "    let config: Config = serde_json::from_str(&content)?;  // typed binding REQUIRED\n"
                    '    println!("field1: {}", config.field1);\n'
                    '    println!("field2: {}", config.field2);\n'
                    "    Ok(())\n"
                    "}\n"
                    "```\n"
                    "CRITICAL: `let config: Config = serde_json::from_str(&content)?` — "
                    "the `Config` type annotation is MANDATORY (E0282 without it). "
                    "Adapt struct name, field names, and println! lines to match the spec exactly. "
                    "Do NOT add command parsing (add/reset/show commands) unless the spec requires it. "
                    "Do NOT add Serialize unless the spec requires writing JSON."
                )
            elif _needs_json and not _serde_available:
                system_msg += (
                    "\n\nSTDLIB-ONLY JSON OUTPUT PATTERN — serde is NOT available, use format strings:\n"
                    "```rust\n"
                    "fn main() -> Result<(), Box<dyn std::error::Error>> {\n"
                    "    let args: Vec<String> = std::env::args().collect();\n"
                    '    if args.len() < 2 { eprintln!("Usage: ... <file>"); std::process::exit(1); }\n'
                    "    let content = std::fs::read_to_string(&args[1])?;\n"
                    "    let line_count = content.lines().count();\n"
                    "    let word_count = content.split_whitespace().count();\n"
                    "    let char_count = content.chars().count();\n"
                    "    // Manual JSON — no serde needed:\n"
                    '    println!("{{{}}}", format!("\\"line_count\\": {}, \\"word_count\\": {}, \\"char_count\\": {}", line_count, word_count, char_count));\n'
                    "    Ok(())\n"
                    "}\n"
                    "```\n"
                    "CRITICAL: Do NOT import serde, serde_json, or any external crate — they are not in Cargo.toml. "
                    "Use only std:: to produce the output. Adapt field names to match the spec exactly."
                )
    if step.write_mode == "append_to_file":
        system_msg += (
            "\nFor append_to_file: output ONLY the new code to append "
            "(new methods, functions, or attributes). "
            "Do NOT repeat existing class definitions or previously written code."
        )
    if step.write_mode == "replace_file":
        system_msg += (
            "\nFor replace_file: output the COMPLETE file. "
            "Copy ALL existing code shown in CURRENT FILE above, then add your new code. "
            "Do NOT omit or shorten any existing functions, methods, or classes. "
            "Use EXACT names from the step instruction — do not invent new function or class names."
        )

    # #12: Large-file constraint — small models cannot reliably produce
    # git-style diffs for files > MAX_LINES_BEFORE_FORCE_REPLACE lines.
    # Force replace_file semantics so the model always outputs the complete file.
    if step.target_file:
        target_path = workspace / step.target_file
        if target_path.exists():
            line_count = len(target_path.read_text(encoding="utf-8", errors="ignore").splitlines())
            if line_count > MAX_LINES_BEFORE_FORCE_REPLACE:
                system_msg += (
                    f"\n\nFILE SIZE WARNING: The target file is {line_count} lines. "
                    "You MUST output the ENTIRE file from top to bottom. "
                    "Do NOT use diff markers (<<<<, ====, >>>>) or partial replacements. "
                    "Output mode: replace_file (complete rewrite)."
                )

    if attempt > 0 and compiler_error:
        if compiler_error.startswith("[Correctness Test FAIL]"):
            system_msg += (
                f"\n\nRetry {attempt + 1}/{MAX_RETRIES_PER_STEP}. "
                "Previous attempt compiled but failed correctness tests. "
                "Use the CORRECTNESS TEST HARNESS in the user context as the exact behavior contract."
            )
        else:
            system_msg += (
                f"\n\nRetry {attempt + 1}/{MAX_RETRIES_PER_STEP}. "
                f"Previous attempt failed to compile. Fix the error shown below."
            )
        _derive_fix = _extract_missing_derives(compiler_error)
        if _derive_fix:
            system_msg += _derive_fix
        _type_fix = _extract_type_mismatch_fix(compiler_error)
        if _type_fix:
            system_msg += _type_fix
        _trait_fix = _extract_trait_scope_fix(compiler_error)
        if _trait_fix:
            system_msg += _trait_fix
        _serde_fix = _extract_serde_inference_fix(compiler_error)
        if _serde_fix:
            system_msg += _serde_fix
        if (
            not _serde_available
            and ("E0432" in compiler_error or "unresolved import" in compiler_error)
            and "serde" in compiler_error
        ):
            system_msg += (
                "\n\nCRITICAL FIX: serde and serde_json are NOT in Cargo.toml — they cannot be used. "
                "Remove ALL `use serde::...`, `use serde_json::...`, `#[derive(Serialize)]`, and `#[derive(Deserialize)]` lines. "
                "To output JSON, use `println!` with format strings — no external crates needed."
            )
    if prune_context and compiler_error:
        # #7: On pruned retry, make the error injection explicit so the
        # model knows exactly what it needs to fix without the noise of
        # previous failed attempts in the history.
        system_msg += (
            "\n\n[CONTEXT PRUNED: Prior failed attempts removed to restore attention focus.] "
            f"Latest compiler error:\n{compiler_error[:1500]}"
        )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": builder_ctx},
    ]


def _build_monitor_messages(
    session: ManifestSession,
    step: StepRecord,
    builder_output: str,
    compiler_passed: bool,
) -> list[dict]:
    """Assemble chat messages for Monitor verdict."""
    return [
        {
            "role": "system",
            "content": (
                f"You are a code review monitor for {session.lang.capitalize()} projects. "
                "Score the builder's output 0.0-1.0 on correctness, safety, and adherence "
                "to the step instruction. Reply with ONLY a JSON object: "
                '{"score": 0.0-1.0, "verdict": "one sentence", "issues": ["..."]}.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Step instruction: {step.instruction}\n\n"
                f"Builder output:\n```\n{builder_output[:3000]}\n```\n\n"
                f"Compiler result: {'PASS' if compiler_passed else 'FAIL'}"
            ),
        },
    ]


def _parse_monitor_verdict(response_text: str) -> tuple[float, str]:
    """Parse Monitor's JSON verdict. Returns (score, verdict_text).

    Parse priority:
    1. Instructor structured extraction (when instructor + pydantic installed):
       Sends the raw text through a Pydantic model extraction — no regex
       fragility, works even on malformed JSON or mixed format responses.
    2. JSON object extraction: {"score": 0.8, "verdict": "..."}
    3. JSON inside markdown fence: ```json\n{...}\n```
    4. DSL/plain text fallback (DSL-fine-tuned models output tags instead of JSON):
       e.g. [SCORE: 0.9] [VERDICT: looks good] — extract score if present, else 0.5
    """
    # ── Priority 1: Instructor structured extraction ──────────────────────────
    # Instructor wraps an LLM call to extract structured Pydantic objects from
    # raw text. Here we use it in a lightweight "extract from existing text" mode
    # (no extra API call) via instructor's text extraction utils.
    try:
        import instructor
        from pydantic import BaseModel, Field

        class _MonitorVerdict(BaseModel):
            score: float = Field(ge=0.0, le=1.0)
            verdict: str

        # instructor.from_dict / extract_from_text (v1.x API)
        # Tries to coerce the text into the Pydantic model without an LLM call
        extracted = instructor.utils.extract_json_from_string(response_text)
        if extracted and "score" in extracted:
            mv = _MonitorVerdict.model_validate(extracted)
            return max(0.0, min(1.0, mv.score)), mv.verdict[:200]
    except Exception:
        pass  # Fall through to existing parse paths

    # ── Priority 2 & 3: Existing JSON extraction (unchanged) ─────────────────
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", response_text).strip()

    # Try any JSON object in the text (greedy — finds the largest {...} block)
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(m.group())
            score = float(obj.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            verdict = str(obj.get("verdict", text[:200]))
            return score, verdict
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    # ── Priority 4: DSL tag extraction fallback ───────────────────────────────
    # [SCORE: 0.9] or CONFIDENCE: 0.85
    score_m = re.search(r"(?:SCORE|CONFIDENCE|score|confidence)[:\s]+([0-9.]+)", text)
    if score_m:
        try:
            score = max(0.0, min(1.0, float(score_m.group(1))))
            return score, text[:200]
        except ValueError:
            pass

    # G9: Plain text fallback — cannot extract a numeric score, return 0.5 (neutral).
    # Returning 0.7 was fabricated and masked Monitor failures as near-passing.
    if text.strip():
        return 0.5, text[:200]
    return 0.5, "no verdict"
