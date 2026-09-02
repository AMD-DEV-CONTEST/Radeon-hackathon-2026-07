#!/usr/bin/env python3
"""
amd_amplification_measure.py — the correctness claim, measured on an AMD Radeon GPU.

The submission's GPU evidence so far is about THROUGHPUT: the Kth candidate is nearly free.
That is only half the argument. The other half is that spending those candidates converts
into correctness, `P = 1 - (1-p)^K`, and that half has never been measured on AMD silicon —
only on local hardware.

So: synthesize a SOUND oracle from a task, draw N independent candidates from a model served
on the Radeon, verify every one against that oracle, and report

    p          measured, not assumed — passes / N
    P_pred     1 - (1-p)^K, the amplifier's own equation
    P_obs      the observed rate at which a batch of K contains a passing candidate

A task the model always solves proves nothing (the machinery does nothing) and a task it never
solves proves nothing either (p=0 is the one value amplification cannot rescue — see the
corpus entry `amplification_floor_p_must_exceed_zero`). The interesting regime is the middle,
so this sweeps candidate tasks and reports where each one lands rather than picking one and
hoping.

    python scripts/dev/amd_amplification_measure.py --n 24 --out C:/tmp/amp.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

#: Candidate tasks, ordered by expected difficulty for a small model. Each states its examples
#: explicitly so `determinex_synthesize` can build a SOUND oracle — a vacuous oracle would make
#: every measurement below meaningless, which is exactly the failure the synthesizer refuses.
TASKS = {
    "rle": (
        'solution(s) run-length encodes a string: each run of a repeated character becomes '
        'the character followed by the run length. For example solution("aaabbc") returns '
        '"a3b2c1", solution("abc") returns "a1b1c1", and solution("") returns "".'
    ),
    "second_largest": (
        "solution(nums) returns the second largest DISTINCT value in a list of integers, or "
        "None when there is no such value. For example solution([1, 2, 3]) returns 2, "
        "solution([5, 5, 4]) returns 4, solution([7]) returns None, and solution([3, 3]) "
        "returns None."
    ),
    "roman": (
        'solution(n) converts an integer from 1 to 3999 into a Roman numeral. For example '
        'solution(4) returns "IV", solution(9) returns "IX", solution(14) returns "XIV", '
        'solution(40) returns "XL", and solution(1994) returns "MCMXCIV".'
    ),
    "balanced": (
        'solution(s) returns True when every bracket in the string is closed in the right '
        'order and False otherwise, considering (), [] and {}. For example solution("([])") '
        'returns True, solution("([)]") returns False, solution("(") returns False, and '
        'solution("") returns True.'
    ),
    # NOVEL COMPOSITIONS, added after the textbook set came back 48/48 at p=1.000. That
    # result is real and worth stating -- a 1B model served on the Radeon one-shots RLE,
    # second-largest, Roman numerals and bracket matching, so on those tasks K is pure waste
    # and the calibrator's p=1 -> K=1 rule is the correct answer. But a saturated task cannot
    # demonstrate amplification, so these are deliberately compositions unlikely to be
    # memorised: each combines two ordinary rules in a way no exercise book pairs them.
    "vowel_cycle": (
        'solution(s) replaces every vowel with the NEXT vowel in the cycle a,e,i,o,u,a, '
        'keeping the original case and leaving every other character alone. For example '
        'solution("hello") returns "hillu", solution("Apple") returns "Eppli", '
        'solution("xyz") returns "xyz", and solution("") returns "".'
    ),
    "reset_running_max": (
        "solution(nums) returns the running maximum of a list of integers, except that any "
        "negative number resets the running maximum to 0 and contributes 0 at its own "
        "position. For example solution([1, 3, 2]) returns [1, 3, 3], "
        "solution([2, -1, 4]) returns [2, 0, 4], solution([-5]) returns [0], and "
        "solution([]) returns []."
    ),
    "twice_only": (
        'solution(s) returns the characters that appear exactly twice in the string, in the '
        'order of their FIRST appearance, as a string. For example solution("aabbc") returns '
        '"ab", solution("abcabc") returns "abc", solution("aaa") returns "", and '
        'solution("") returns "".'
    ),
    # HARD, added after every task above measured p=1.000 with genuinely distinct completions.
    # A 1B model saturating textbook tasks AND invented compositions is a real result, but a
    # saturated task cannot show amplification, so this one needs actual reasoning: operator
    # precedence, unary minus, and integer division that truncates toward zero.
    "expr_eval": (
        'solution(s) evaluates an arithmetic expression string containing non-negative '
        'integers, + - * /, and parentheses, using normal precedence, where / is integer '
        'division truncating toward zero. For example solution("2+3*4") returns 14, '
        'solution("(2+3)*4") returns 20, solution("7/2") returns 3, solution("-7/2") returns '
        '-3, solution("2*(3+4)-5") returns 9, and solution("10") returns 10.'
    ),
    "wrap_words": (
        'solution(s, width) greedily wraps text to a maximum line width, breaking only at '
        'spaces, and returns the lines joined by newlines; a word longer than width goes on '
        'its own line uncut. For example solution("a bb ccc", 5) returns "a bb\nccc", '
        'solution("hello world", 5) returns "hello\nworld", solution("abcdef", 3) returns '
        '"abcdef", and solution("", 5) returns "".'
    ),
    "digit_span": (
        "solution(s) returns the sum of the digits in the string minus the number of letters "
        "in it. For example solution(\"a1b2\") returns 1, solution(\"999\") returns 27, "
        "solution(\"abc\") returns -3, and solution(\"\") returns 0."
    ),
}


def _extract_code(text: str) -> str:
    """Pull the python block out of a completion; fall back to the whole thing."""
    import re

    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def _verifier_and_prompt(idea: str):
    """The SAME oracle and prompt `build_from_idea` uses, without its search loop."""
    from determinex_build_from_idea import build_from_idea  # noqa: F401  (kept for parity)
    from determinex_synthesize import parse_spec, synthesize_oracle_tests

    spec = parse_spec(idea, "python")
    tests = synthesize_oracle_tests(spec)
    prompt = (
        f"Write a complete Python module defining `{spec.name}`.\n\n"
        f"Specification:\n{spec.description}\n\n"
        f"Return ONLY the code in a ```python block. It must satisfy these behaviors exactly."
    )

    class _R:
        def __init__(self, ok: bool, detail: str = ""):
            self.ok, self.detail = ok, detail

    def verify(code: str) -> _R:
        import sys as _s
        import tempfile
        from pathlib import Path as _P

        with tempfile.TemporaryDirectory() as d:
            dp = _P(d)
            (dp / "solution.py").write_text(code, encoding="utf-8")
            (dp / "tests_gen.py").write_text(tests, encoding="utf-8")
            # Model-generated code is untrusted: the hardened runner, never a raw subprocess.
            from intake.hardened_runner import run as _hrun

            res = _hrun(
                [_s.executable, "-m", "pytest", "tests_gen.py", "-q", "-p", "no:cacheprovider"],
                workspace=dp, cwd=dp, timeout=30, allow_network=False,
            )
            return _R(res.exit_code == 0, (res.stdout + res.stderr)[-400:])

    return verify, prompt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="amd-token-factory")
    ap.add_argument("--model", default="MiniCPM5-1B")
    ap.add_argument("--n", type=int, default=24, help="independent draws per task")
    ap.add_argument("--temp", type=float, default=0.4)
    ap.add_argument("--tasks", default="", help="comma list; default all")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    from determinex_providers import get_generator
    from determinex_synthesize import oracle_is_vacuous, parse_spec, synthesize_oracle_tests

    gen = get_generator(a.provider, a.model)
    names = [t.strip() for t in a.tasks.split(",") if t.strip()] or list(TASKS)
    report: dict = {
        "what": "correctness amplification measured on an AMD Radeon GPU",
        "provider": a.provider, "model": a.model,
        "draws_per_task": a.n, "temperature": a.temp,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tasks": {},
    }

    for name in names:
        idea = TASKS[name]
        print(f"\n=== {name} ===", flush=True)
        spec = parse_spec(idea, "python")
        tests = synthesize_oracle_tests(spec)
        vacuous = oracle_is_vacuous(tests)
        n_checks = tests.count("def test_")
        sound = not vacuous
        print(f"  oracle: {n_checks} checks, sound={sound}", flush=True)
        if not sound or n_checks < 2:
            # Refuse to report a p measured against an oracle that cannot fail. This is the
            # whole soundness contract: garbage oracle in, confident garbage out.
            print("  SKIPPED -- oracle not sound enough to measure against", flush=True)
            report["tasks"][name] = {"skipped": "oracle not sound", "n_checks": n_checks}
            continue

        # DRAW AT TEMPERATURE, DIRECTLY.
        #
        # The first version of this called `build_from_idea(..., k=1)` N times and reported
        # 112/112 = p=1.000 across seven tasks, four of which were compositions invented for
        # this measurement. That was not a result, it was a bug in the harness: VerifiedSearch's
        # `_DEFAULT_TEMPS` begins at 0.0, so sample index 0 is GREEDY -- k=1 draws the same
        # deterministic completion every time. Sixteen identical draws is one draw, and calling
        # it p is exactly the kind of confident number this project exists to refuse.
        #
        # So the generator is called directly at a non-zero temperature and each candidate is
        # verified against the same synthesized oracle. That is a real independent sample.
        verify, prompt = _verifier_and_prompt(idea)
        passes, errors, t0 = 0, 0, time.monotonic()
        outputs: list[str] = []
        for i in range(a.n):
            try:
                code = _extract_code(gen(prompt, a.temp))
                ok = bool(verify(code).ok)
                outputs.append(code[:400])
            except Exception as e:
                ok, errors = False, errors + 1
                if errors == 1:
                    print(f"  first error: {type(e).__name__}: {str(e)[:90]}", flush=True)
            passes += 1 if ok else 0
            print(f"  draw {i + 1:>3}/{a.n}  {'PASS' if ok else 'fail'}   "
                  f"running p={passes / (i + 1):.3f}", flush=True)
        # A sampler that returns identical text at temperature is not sampling -- report it
        # rather than quoting a p derived from one completion wearing N hats.
        distinct = len(set(outputs))
        print(f"  distinct completions: {distinct}/{len(outputs)}", flush=True)

        el = time.monotonic() - t0
        p = passes / a.n if a.n else 0.0
        row = {
            "n_checks": n_checks, "draws": a.n, "passes": passes, "errors": errors,
            "distinct_completions": distinct,
            "p": round(p, 4), "wall_s": round(el, 1),
            "P_predicted": {k: round(1 - (1 - p) ** k, 4) for k in (1, 2, 4, 6, 8, 16)},
            "regime": ("saturated (K adds nothing)" if p >= 0.99 else
                       "floor (p=0 -- amplification cannot rescue this)" if p <= 0.0 else
                       "PRODUCTIVE MIDDLE"),
        }
        report["tasks"][name] = row
        print(f"  p = {passes}/{a.n} = {p:.3f}   {row['regime']}", flush=True)
        print("  1-(1-p)^K:  " + "  ".join(
            f"K={k}:{v:.3f}" for k, v in row["P_predicted"].items()), flush=True)

    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
