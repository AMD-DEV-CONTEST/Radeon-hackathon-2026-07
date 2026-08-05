#!/usr/bin/env python3
"""
amd_amplification_evidence.py — merge the AMD amplification runs into one evidence file.

Three separate measurements, all on AMD's Radeon Token Factory, all raw:

  1. the SATURATED set     seven tasks at p = 1.000, including four invented for this
                           measurement, with distinct completions confirmed
  2. the PRODUCTIVE MIDDLE one task at p = 0.0625 measured over 16 independent draws
  3. the TRIALS            verified search run at the CALIBRATED K, observed vs predicted

Kept as one artifact because the three only mean something together: (1) says a saturated
task needs K=1 and any K above it is waste, (2) says the equation has something to bite on,
and (3) says whether the equation held. Publishing (3) alone would be the interesting number
without the context that makes it checkable.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(
    "C:/Dev/Radeon-hackathon-2026-07/Determinex/amd_gpu_evidence/"
    "radeon_amplification_2026-08-03.json"
)


def main() -> int:
    sat = json.loads(Path("C:/tmp/amd_amp.json").read_text())
    hard = json.loads(Path("C:/tmp/amd_amp_hard.json").read_text())
    try:
        trials = json.loads(Path("C:/tmp/amd_amplify_trials.json").read_text())
    except FileNotFoundError:
        print("trials not finished yet -- rerun once C:/tmp/amd_amplify_trials.json exists")
        return 1

    ev = {
        "what": "correctness amplification measured on AMD Radeon (Token Factory)",
        "measured_at": hard.get("measured_at"),
        "provider": hard.get("provider"),
        "model": hard.get("model"),
        "endpoint": "https://radeon.anruicloud.com/api/v1",
        "claim_under_test": "P = 1 - (1-p)^K, with p MEASURED rather than assumed",
        "method": {
            "oracle": (
                "determinex_synthesize builds exact example-assertions from the task text; a "
                "vacuous oracle is refused, so every p below is measured against checks that "
                "can actually fail."
            ),
            "draws": (
                "the generator is called directly at temperature and each candidate is "
                "verified. NOT build_from_idea(k=1) repeated: VerifiedSearch's temperature "
                "ladder starts at 0.0, so k=1 is greedy and N such draws are ONE draw N "
                "times. The first version of this harness did exactly that and reported "
                "112/112 p=1.000 across seven tasks -- a bug, not a result. "
                "distinct_completions is recorded so the reader can check the draws differ."
            ),
            "sandbox": (
                "candidates are model-generated and untrusted: verification runs through "
                "intake.hardened_runner (workspace-bounded, env-scrubbed, network denied), "
                "never a raw subprocess."
            ),
        },
        "saturated_set": sat.get("tasks", {}),
        "productive_middle": hard.get("tasks", {}),
        "trials": trials,
    }

    t = trials
    ev["headline"] = (
        f"p={t['p']:.3f} measured over 16 draws; at the calibrated K={t['K']} the equation "
        f"predicts P={t['P_predicted']:.3f} and {t['solved']}/{t['trials']} trials solved "
        f"(P_observed={t['P_observed']:.3f})."
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes)")
    print("  " + ev["headline"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
