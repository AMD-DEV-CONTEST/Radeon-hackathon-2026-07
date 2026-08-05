"""
_add_go_curriculum.py — one-shot: append Go wrap_error curriculum to micro_curriculum.jsonl
Run: python scripts/_add_go_curriculum.py
"""

import json
from pathlib import Path

MICRO = Path(__file__).resolve().parent / "micro_curriculum.jsonl"

GO_WRAP_ERROR = {
    "category": "micro_go_wrap_error",
    "display_name": "Go: wrap_error fmt.Errorf %w",
    "system_prompt": (
        "You are an expert Go programmer. Write idiomatic Go. "
        "Output ONLY the Go function — no package declaration, no imports, "
        "no main function, no explanation, no prose. "
        "Use fmt.Errorf with %w for error wrapping."
    ),
    "prompt_templates": [
        'Write a Go function wrap_error(msg string, err error) error that returns fmt.Errorf("%s: %w", msg, err).',
        "Write a Go function wrap_error(msg string, err error) error using fmt.Errorf with the %w verb so that errors.Is works on the result.",
        "Write a Go function wrap_error(msg string, err error) error. The returned error must wrap err so that errors.Is(result, err) returns true.",
        "Write a Go function wrap_error(msg string, err error) error. The returned error message must contain both msg and the original error message.",
        "Write a Go function wrap_error(msg string, err error) error using fmt.Errorf %w so that errors.Unwrap returns the original err.",
        "Write a Go function named wrap_err(context string, cause error) error that wraps cause with context using fmt.Errorf %w.",
        'Write a Go function annotate_error(label string, err error) error that returns fmt.Errorf("%s: %w", label, err).',
        "Write a Go function chain_error(step string, err error) error that wraps err so that errors.Is still finds the original error.",
        "Write a Go function wrap_error(msg string, err error) error. Double-wrapping must still allow errors.Is to reach the base error.",
        "Write a Go function wrap_error(msg string, err error) error that is nil-safe: return nil if err is nil.",
        "Write a Go function wrap_error(msg string, err error) error. Show idiomatic Go error wrapping with fmt.Errorf and %w in a single line.",
        'Write a Go function wrap_error(msg string, err error) error that produces a message in the format "msg: original_error".',
        "Given a Go function signature `func wrap_error(msg string, err error) error`, write the body using fmt.Errorf and %w.",
        "Write a Go function wrap_op_error(op string, cause error) error that wraps cause so errors.Unwrap returns cause.",
        (
            "Write a Go error-wrapping function that accepts a context string and an underlying error, "
            "and returns a new error preserving the error chain using fmt.Errorf %w. Name it wrap_error."
        ),
    ],
    "validator": "go",
    "cot_requested": False,
    "output_format": "code",
    "task_category_weight": 1.5,
}

# Read existing categories to avoid duplicates
existing_cats: set[str] = set()
if MICRO.exists():
    for line in MICRO.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                existing_cats.add(json.loads(line)["category"])
            except Exception:
                pass

to_add = [GO_WRAP_ERROR]
added = 0
with MICRO.open("a", encoding="utf-8") as f:
    for entry in to_add:
        if entry["category"] in existing_cats:
            print(f"  SKIP  {entry['category']} (already present)")
        else:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"  ADD   {entry['category']}  ({len(entry['prompt_templates'])} prompts)")
            added += 1

total = sum(1 for ln in MICRO.read_text(encoding="utf-8").splitlines() if ln.strip())
print(f"\nmicro_curriculum.jsonl: {total} categories total  ({added} added)")
