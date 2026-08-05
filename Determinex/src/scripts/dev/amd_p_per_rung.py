#!/usr/bin/env python3
"""
amd_p_per_rung.py — why `1-(1-p)^K` over-predicted, measured instead of argued.

The submission reports an honest miss: p measured at 0.0625, K=8, the equation predicted
P=0.403 and six trials returned 1 solve (0.167). Two explanations were offered and neither
could be dismissed -- six trials is few, AND the draws are not i.i.d. because VerifiedSearch
spreads its K samples across a TEMPERATURE LADDER (0.0, 0.2, 0.4, 0.6, 0.8, 1.0) while `p` was
measured at a single temperature.

`1-(1-p)^K` assumes ONE p for all K draws. The implementation deliberately violates that to
buy diversity. So the honest fix is not a better excuse, it is the right equation:

    P(at least one passes) = 1 - PROD over rungs of (1 - p_rung)

which needs p measured AT EACH RUNG. That is what this does, on the Radeon, and then compares
three numbers on the same task: the naive single-p prediction, the per-rung prediction, and
what the search actually achieved.

If the per-rung number lands near the observed one, the equation was never wrong -- it was
being applied to draws it does not describe, and the architecture is vindicated by measuring
more carefully rather than by arguing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "dev"))

TASK = (
    'solution(s) evaluates an arithmetic expression string containing non-negative integers, '
    '+ - * /, and parentheses, using normal precedence, where / is integer division '
    'truncating toward zero. For example solution("2+3*4") returns 14, solution("(2+3)*4") '
    'returns 20, solution("7/2") returns 3, solution("-7/2") returns -3, '
    'solution("2*(3+4)-5") returns 9, and solution("10") returns 10.'
)

#: The exact ladder VerifiedSearch uses for its first 8 samples. Measuring the rungs the
#: implementation actually draws at is the whole point -- a ladder invented here would answer
#: a question nobody asked.
LADDER = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="vllm")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--n", type=int, default=10, help="draws PER RUNG")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    from amd_amplification_measure import _extract_code, _verifier_and_prompt
    from determinex_providers import get_generator

    gen = get_generator(a.provider, a.model)
    verify, prompt = _verifier_and_prompt(TASK)

    rungs: dict[str, dict] = {}
    print(f"measuring p at each rung of the ladder, {a.n} draws per rung\n")
    for temp in sorted(set(LADDER)):
        passes, errors, outs = 0, 0, []
        t0 = time.monotonic()
        for _ in range(a.n):
            try:
                code = _extract_code(gen(prompt, temp))
                outs.append(code[:200])
                if verify(code).ok:
                    passes += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                if errors == 1:
                    print(f"    first error at t={temp}: {type(e).__name__}: {str(e)[:80]}")
        p = passes / a.n if a.n else 0.0
        rungs[str(temp)] = {
            "draws": a.n,
            "passes": passes,
            "errors": errors,
            "p": round(p, 4),
            # A rung whose draws are identical is not sampling, and its p is one draw's verdict
            # wearing N hats. t=0.0 is EXPECTED to be degenerate -- that is the point.
            "distinct": len(set(outs)),
            "wall_s": round(time.monotonic() - t0, 1),
        }
        print(f"  t={temp:<4} p={p:.3f}  ({passes}/{a.n})  distinct={len(set(outs))}/{len(outs)}"
              f"  {rungs[str(temp)]['wall_s']}s", flush=True)

    # The three numbers, side by side.
    ps = [rungs[str(t)]["p"] for t in LADDER]
    per_rung = 1.0
    for p in ps:
        per_rung *= 1 - p
    per_rung = 1 - per_rung

    flat = sum(ps) / len(ps)
    naive = 1 - (1 - flat) ** len(LADDER)

    report = {
        "what": "p measured PER TEMPERATURE RUNG on the Radeon, and the corrected prediction",
        "task": "expression evaluator (6 sound checks)",
        "provider": a.provider,
        "model": a.model,
        "ladder": LADDER,
        "rungs": rungs,
        "mean_p": round(flat, 4),
        "naive_prediction_single_p": round(naive, 4),
        "per_rung_prediction": round(per_rung, 4),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "why_it_matters": (
            "1-(1-p)^K assumes one p for all K draws. VerifiedSearch draws across a temperature "
            "ladder, so the correct form is 1 - PROD(1 - p_rung). Where the two disagree, the "
            "equation was not wrong -- it was being applied to draws it does not describe."
        ),
    }
    print(f"\n  mean p across rungs      : {flat:.4f}")
    print(f"  naive  1-(1-p_mean)^8    : {naive:.4f}")
    print(f"  per-rung 1-PROD(1-p_i)   : {per_rung:.4f}")
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
