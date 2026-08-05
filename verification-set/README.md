# V1 Verification Set — SmolVLA industrial_sort_v2 ckpt20k

A **fixed-seed, fully reproducible** verification set for the three-box industrial
sorting policy. 25 episodes with every seed locked in `verification_seeds.json` —
same seed = same EnvRandomizer state = same episode, so anyone re-running this
directory reproduces the exact episodes we evaluated.

## Composition

- **25 fixed-seed episodes**: all seeds randomly generated with a fixed Python RNG
  (`random.Random(20260803)`) from `[3000, 9999)` (11 gear, 9 bolt, 5 nut).
- Fully reproducible: every seed is written in `verification_seeds.json`, and
  `EnvRandomizer.seed(seed)` fully determines the episode's part pose, lighting,
  and physics randomization.
- A runner (`run_verification.py`) that executes all 25 episodes through
  `eval_policy.py` and aggregates the score into `verification_results.json`.

## Our evaluation result (the submitted number)

All episodes run on 2025-08-02, W7900 / ROCm 7.2.1, 3-way parallel, 450-frame cap:

| Group | Result |
|---|---|
| **Overall** | **13/25 = 52.0 %** |
| Gear | 5/11 = 45.5 % |
| Bolt | 5/9 = 55.6 % |
| Nut | 3/5 = 60.0 % |

## Verification set composition (25 episodes)

| Part | Count | Seeds | Source |
|---|---|---|---|
| gear | 11 | 1000, 2000, 2003, 2007, 2009, 2012, 2015, 2018, 2024, 4163, 4975 | randomly generated |
| bolt | 9 | 2002, 2005, 2008, 2011, 2014, 2020, 2021, 7350, 8167 | randomly generated |
| nut | 5 | 2007, 2027, 2029, 3521, 5943 | randomly generated |

All seeds generated with `random.Random(20260803).sample(range(3000, 9999), 25)` —
fully reproducible.

## Our verification result (submitted)

**Ran 2025-08-02 on the W7900 host, ROCm 7.2.1, 3-way parallel:**

| Group | Success | Detail |
|---|---|---|
| **Overall** | **13/25 = 52.0%** | 0 errors |

**By part:**

| Part | OK/Total |
|---|---|
| gear | 5/11 (45%) |
| bolt | 5/9 (56%) |
| nut | 3/5 (60%) |

Full per-episode data in `verification_videos/verification_results.json`.

## Contents

```
verification-set/
├── README.md                  ← this file
├── verification_seeds.json    ← 25 episodes: pick, seed, expected outcome, provenance
├── run_verification.py        ← runs all episodes via eval_policy.py, aggregates score
└── verification_videos/       ← created on run: mp4 videos + verification_results.json
```

## How to run

Prerequisites:

```bash
source /persistent/track3-robot/rdna/bin/activate
cd /persistent/track3-robot/franka_industrial_pick_demo/industrial_pick/verification-set
# Or, if this directory is placed next to eval_policy.py:
# cd <path-to-this-verification-set-directory>
```

Run all 25 episodes (3-way parallel, safe on the W7900, ~20 min):

```bash
python -u run_verification.py --jobs 3
```

Each episode is a separate `eval_policy.py --episodes 1 --seed <s> --picks <p>`
invocation. Results land in `verification_videos/verification_results.json`; each
episode gets a subdirectory with world + wrist mp4s and a `summary.json`.

Useful flags: `--eval-script` (default `../eval_policy.py`),
`--checkpoint` (default `/persistent/track3-robot/models/smolvla_industrial_sort_v2_ckpt20k`),
`--out-dir` (default `./verification_videos`).

## Reproduce a single episode

```bash
python -u ../eval_policy.py \
    --checkpoint /persistent/track3-robot/models/smolvla_industrial_sort_v2_ckpt20k \
    --episodes 1 --seed 2003 --picks gear \
    --video-dir /workspace/verify_check/gear_s2003
```

## Seed reproducibility

```
verification_seeds.json → run_verification.py → eval_policy.py --seed <seed>
→ EnvRandomizer.reset(seed=<seed>) → np.random.default_rng(seed)
```

Same seed = identical part pose, lighting, and physics randomization = identical
episode. Any re-run with the same seeds reproduces our verification episodes.

## Monitoring progress

**Do not grep the log** (eval stdout is block-buffered). Count mp4 files instead:

```bash
find verification_videos -name '*.mp4' | wc -l   # expected final: 25×2 = 50
```
