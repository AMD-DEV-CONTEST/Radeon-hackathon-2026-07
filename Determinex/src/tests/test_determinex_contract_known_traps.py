"""Tests for determinex_contract.py's known-traps scan + two-strike gate (2026-07-16).

Design (Ryan): a heuristic pattern match is not a sound oracle, so a first occurrence of a
known trap must NOT hard-reject a candidate -- only a SECOND occurrence of the SAME trap in a
later candidate from the same generation sequence (meaning the model was warned and ignored it)
gates before the candidate reaches the real compiler/test oracle.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_contract as C  # noqa: E402

# ---------- known_traps_scan: real positive/negative cases per language ----------


def test_rust_unwrap_expect_detected():
    hits = C.known_traps_scan("let f = File::open(path).unwrap();", "rust")
    assert any(h.trap_id == "rust_unwrap_expect" for h in hits)


def test_rust_question_mark_not_flagged():
    hits = C.known_traps_scan("let f = File::open(path)?;", "rust")
    assert not any(h.trap_id == "rust_unwrap_expect" for h in hits)


def test_rust_debug_error_print_detected():
    hits = C.known_traps_scan('eprintln!("Error: {:?}", err);', "rust")
    assert any(h.trap_id == "rust_debug_error_print" for h in hits)


def test_rust_display_error_print_not_flagged():
    hits = C.known_traps_scan('eprintln!("Error: {}", err);', "rust")
    assert not any(h.trap_id == "rust_debug_error_print" for h in hits)


def test_go_ignored_error_detected():
    hits = C.known_traps_scan("data, _ := os.ReadFile(path)", "go")
    assert any(h.trap_id == "go_ignored_error" for h in hits)


def test_go_checked_error_not_flagged():
    hits = C.known_traps_scan("data, err := os.ReadFile(path)", "go")
    assert not any(h.trap_id == "go_ignored_error" for h in hits)


def test_go_len_on_string_detected():
    hits = C.known_traps_scan("n := len(s)", "go")
    assert any(h.trap_id == "go_len_on_string" for h in hits)


def test_go_len_on_slice_not_flagged():
    hits = C.known_traps_scan("n := len(items)", "go")
    assert not any(h.trap_id == "go_len_on_string" for h in hits)


def test_c_unbounded_strcpy_detected():
    hits = C.known_traps_scan("strcpy(buf, argv[1]);", "c")
    assert any(h.trap_id == "c_unbounded_strcpy" for h in hits)


def test_c_snprintf_not_flagged():
    hits = C.known_traps_scan('snprintf(buf, sizeof(buf), "%s", argv[1]);', "c")
    assert not any(h.trap_id == "c_unbounded_strcpy" for h in hits)


def test_c_unchecked_malloc_detected():
    hits = C.known_traps_scan("char *buf = malloc(100);", "c")
    assert any(h.trap_id == "c_unchecked_malloc" for h in hits)


def test_c_checked_malloc_not_flagged():
    hits = C.known_traps_scan("char *buf = malloc(100); if (!buf) return 1;", "c")
    assert not any(h.trap_id == "c_unchecked_malloc" for h in hits)


def test_cpp_raw_new_detected():
    hits = C.known_traps_scan("int *p = new int[10];", "cpp")
    assert any(h.trap_id == "cpp_raw_new_no_raii" for h in hits)


def test_cpp_make_unique_not_flagged():
    hits = C.known_traps_scan("auto p = std::make_unique<int[]>(10);", "cpp")
    assert not any(h.trap_id == "cpp_raw_new_no_raii" for h in hits)


def test_known_traps_scan_python_returns_empty():
    """python has no known-traps table -- always empty, never a false positive."""
    assert C.known_traps_scan("f.unwrap()  # not real python, but still", "python") == []


def test_known_traps_scan_unregistered_language_returns_empty():
    assert C.known_traps_scan("anything", "cobol") == []


def test_known_traps_scan_clean_code_returns_no_hits():
    clean_rust = """
fn main() {
    let path = std::env::args().nth(1);
    match path {
        Some(p) => match std::fs::read_to_string(&p) {
            Ok(contents) => println!("{}", contents),
            Err(e) => { eprintln!("error: {}", e); std::process::exit(1); }
        },
        None => { eprintln!("usage: tool <path>"); std::process::exit(2); }
    }
}
"""
    assert C.known_traps_scan(clean_rust, "rust") == []


def test_known_traps_scan_reports_line_number():
    code = 'fn main() {\n    let x = 1;\n    let f = File::open("p").unwrap();\n}'
    hits = C.known_traps_scan(code, "rust")
    hit = next(h for h in hits if h.trap_id == "rust_unwrap_expect")
    assert hit.line == 3


def test_known_traps_scan_strips_code_fence():
    fenced = "```rust\nlet f = File::open(path).unwrap();\n```"
    hits = C.known_traps_scan(fenced, "rust")
    assert any(h.trap_id == "rust_unwrap_expect" for h in hits)


# ---------- trap_guard: the two-strike state machine ----------


def test_trap_guard_first_occurrence_passes_through_untouched():
    """The real oracle is still the only judge of a FIRST attempt -- no gating, no resample."""
    calls = []

    def fake_generate(prompt, temp):
        calls.append((prompt, temp))
        return "let f = File::open(path).unwrap();"

    wrapped = C.trap_guard(fake_generate, "rust")
    result = wrapped("original prompt", 0.5)
    assert result == "let f = File::open(path).unwrap();"
    assert len(calls) == 1  # no resample on first offense
    assert calls[0][0] == "original prompt"  # prompt unmodified


def test_trap_guard_second_occurrence_of_same_trap_gates_and_resamples():
    """Second candidate with the SAME trap (after the first was silently recorded) must be
    gated: resampled with an escalated note, not returned as-is."""
    responses = iter(
        [
            "let f = File::open(path).unwrap();",  # 1st call: trap present, recorded, passed through
            "let f = File::open(path).unwrap();",  # 2nd call: SAME trap again -> must gate+resample
            "let f = File::open(path)?;",  # 3rd call (after resample): clean
        ]
    )
    prompts_seen = []

    def fake_generate(prompt, temp):
        prompts_seen.append(prompt)
        return next(responses)

    wrapped = C.trap_guard(fake_generate, "rust", max_retries=3)
    first = wrapped("prompt A", 0.5)
    assert first == "let f = File::open(path).unwrap();"

    second = wrapped("prompt B", 0.5)
    assert second == "let f = File::open(path)?;"  # resampled to the clean 3rd response
    # the SECOND wrapped() call must have triggered a resample -- prompts_seen has the
    # original "prompt B" call, then an escalated retry prompt
    assert len(prompts_seen) == 3  # 1 (first()) + 2 (second()'s own retry)
    escalated_prompt = prompts_seen[2]
    assert "prompt B" in escalated_prompt
    assert "already warned" in escalated_prompt.lower()
    assert "rust_unwrap_expect" not in escalated_prompt  # message text, not the raw trap id
    assert "unwrap" in escalated_prompt.lower()


def test_trap_guard_different_traps_do_not_trigger_gate():
    """Trap A on the first call and trap B on the second call are DIFFERENT traps -- neither
    has been repeated, so neither gates."""
    responses = iter(
        [
            "let f = File::open(path).unwrap();",  # trap: rust_unwrap_expect
            'eprintln!("Error: {:?}", err);',  # trap: rust_debug_error_print (different)
        ]
    )

    def fake_generate(prompt, temp):
        return next(responses)

    wrapped = C.trap_guard(fake_generate, "rust")
    r1 = wrapped("p1", 0.5)
    r2 = wrapped("p2", 0.5)
    assert r1 == "let f = File::open(path).unwrap();"
    assert r2 == 'eprintln!("Error: {:?}", err);'  # passed through, no gate (different trap)


def test_trap_guard_exhausts_retries_and_returns_last_candidate():
    """If every resample still repeats the trap, trap_guard gives up after max_retries and
    returns the last candidate anyway -- it never silently blocks the pipeline; the real
    oracle still gets the final say."""

    def always_bad_generate(prompt, temp):
        return "let f = File::open(path).unwrap();"

    wrapped = C.trap_guard(always_bad_generate, "rust", max_retries=2)
    wrapped("first call", 0.5)  # records the trap as warned
    result = wrapped("second call", 0.5)  # every resample repeats it -> exhausts retries
    assert result == "let f = File::open(path).unwrap();"


def test_trap_guard_clean_code_never_gates():
    def clean_generate(prompt, temp):
        return "fn main() { std::process::exit(0); }"

    wrapped = C.trap_guard(clean_generate, "rust")
    for _ in range(5):
        assert wrapped("p", 0.5) == "fn main() { std::process::exit(0); }"


def test_trap_guard_state_is_isolated_per_instance():
    """Two separate trap_guard-wrapped generators (e.g. two different model-ladder entries)
    must not share warned-trap state."""

    def bad_generate(prompt, temp):
        return "let f = File::open(path).unwrap();"

    wrapped_a = C.trap_guard(bad_generate, "rust")
    wrapped_b = C.trap_guard(bad_generate, "rust")
    wrapped_a("p", 0.5)  # records warning in A's state only
    # B has never seen this trap before -- must pass through untouched, not gate
    result = wrapped_b("p", 0.5)
    assert result == "let f = File::open(path).unwrap();"
