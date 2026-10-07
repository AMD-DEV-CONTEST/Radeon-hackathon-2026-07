# Look Twice V8

**Track:** Track 3 — Physical AI Challenge · **Team:** Liu Liang (solo entrant)

**GitHub:** [@eason4kim-rocket](https://github.com/eason4kim-rocket) · **Project:** Active Evidence Assurance for Physical AI on AMD Radeon GPU

[![Look Twice V8 — contract-aware active perception on AMD GPU](Look-Twice-V8-Social-Card.png)](https://eason4kim-rocket.github.io/#full-demo)

## Start here

| Entry | What opens |
| --- | --- |
| **[Live Evidence Console](https://eason4kim-rocket.github.io/console)** | An interactive, English-first walkthrough of the system and recorded evidence |
| **[13-second 1080p proof](https://eason4kim-rocket.github.io/media/look-twice-repair-to-action-proof.mp4)** | A silent repair → dual-admission → direct-motion excerpt, including the final result, that plays directly in the browser |
| **[Watch the 3:59 Demo](https://eason4kim-rocket.github.io/#full-demo)** | The complete video in a browser player; no download is required |
| **[Technical Report](Look-Twice-V8-Technical-Report.pdf)** | The 19-page architecture, protocol, results, and evidence-boundary report |
| **[Reproduce](https://eason4kim-rocket.github.io/reproduce)** | The shortest path from a clean clone to the CPU audit, site, and Radeon replay |

<a href="https://eason4kim-rocket.github.io/#full-demo">
  <img src="look-twice-repair-to-action-proof.webp" width="960" alt="Thirteen-second native-resolution silent replay: independent evidence repairs the contract, Python and Purify admit, the carrier moves directly, and the final result appears">
</a>

The moving preview above is a 13.2-second native-resolution excerpt of the
recorded simulation replay—not a new experiment or physical-robot result.
Click it to jump straight to the complete
[3:59 demo](https://eason4kim-rocket.github.io/#full-demo) on the project site;
the excerpt also remains available as a [local 1080p MP4](look-twice-repair-to-action-proof.mp4).

The complete demo is also committed here as [Look-Twice-V8-Demo.mp4](Look-Twice-V8-Demo.mp4).
The [GitHub Release copy](https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/Look-Twice-V8-Demo.mp4) is a stable hash mirror. Both are the same 239-second, 1920×1080 H.264/AAC file:

```text
SHA256  70f0cb035498ed617421163b192a4c42856d0d8ede474582e550c1e3f9d81d05
```

The website link above is the simplest way to watch it without downloading.

## The problem

A warehouse AMR often has enough perception to propose a route, but not enough evidence to justify moving a loaded carrier through a narrow corridor.
Repeated crops of one frame can look like several observations. A stale clear view can outlive a changed scene. A model can also be uncertain even when its top class says “clear.”

Look Twice sits between perception and motion. It asks a practical question: *is the current evidence good enough for this particular action?*
If the answer is no, it explains what is missing, sends a low-risk scout to collect a useful view, and evaluates the same action again. The carrier either takes the direct corridor or completes the mission by a disclosed safe detour.

```text
live RGB-D
  → spatial clear/blocked claims
  → physical-root lineage
  → split-conformal prediction set
  → scoped Action Contract
  → Python decision AND Purify Go decision
  → direct motion, targeted scout observation, or safe detour
```

## What is new

### 1. Evidence keeps its physical lineage

Every claim carries a physical observation root. Derived crops, modalities, or transformations from the same capture cannot masquerade as independent support.
In the compound system, geometry and vision that came from one capture are unified under that same root before qualification.

### 2. Uncertainty is checked against the action

The RGB-D model produces a split-conformal prediction set, not just a winning class.
An `ActionContract` checks the conditions needed for the selected corridor: scope, freshness, independent roots, conflicts, calibration, and whether the set is decisive enough for travel.

### 3. A denial becomes a useful sensing request

A failed contract emits a finite, machine-readable `BeliefGap`. The active planner uses it to rank side views against a specific failed clause.
This is contract-aware next-best-view selection, rather than a generic rescan or an unconstrained exploration policy.

### 4. The motion gate has two implementations

Direct travel requires:

```text
effective_admit = python_admit AND purify_go_admit
```

The second path is the standalone, standard-library [Purify Robotics Go reference core](https://github.com/eason4kim-rocket/look-twice/tree/v8-contract-progress-nbv/purify_robotics).
It evaluates the same public contract independently. A disagreement cannot open the route; it fails closed.

### 5. Each decision is inspectable

Purify emits a deterministic `GateReceipt` containing accepted and discounted claims, root identities, clause outcomes, `BeliefGap`s, the final decision, and a canonical SHA256.
The replay can therefore show not only what the robot did, but which evidence made that action valid.

## Results

The permanent locked comparison used the same 12 warehouse worlds for active repair and passive denial:

| Locked full-chain outcome | Active repair | Passive baseline |
| --- | ---: | ---: |
| Direct route | **11 / 12** | **0 / 12** |
| Mission complete | 12 / 12 | 12 / 12 |
| Unsafe crossing | 0 / 12 | 0 / 12 |
| Unplanned fallback | 0 / 12 | 0 / 12 |

The locked offline set contained 3,200 samples. Metrics reported as perfect apply only to the 3,001 decisive samples; 199 samples remain explicitly inconclusive rather than being forced into a class.

A separate, public-before-run same-generator supplement fixed seeds `102500–102529`, execution order, endpoints, source identities, and validators before opening the worlds:

| 30-world paired supplement | Active repair | Passive baseline |
| --- | ---: | ---: |
| Full-chain direct | **29 / 30** | **0 / 30** |
| Mission complete | 30 / 30 | 30 / 30 |
| Unsafe / unplanned fallback | 0 / 30 | 0 / 30 |

The direct-route gain was +96.7 percentage points; exact two-sided McNemar `p=3.73e-9`.
Seed `102515` was the only world with both corridors blocked and completed by safe detour. The project verifier passed all 60 episodes with zero errors and no observed retry.

Across 268 contract evaluations, Python and Purify Go agreed on 250 (93.3%). All 18 differences were Python-admit/Go-deny, so every difference remained fail-closed and no selected crossing depended on a disagreement.

### Contract-progress efficiency

The next fixed 20-world comparison tested the complete compound change: shared frozen dual-ROI inference, physical-root unification, and contract-aware next-best-view ranking.
Both baseline and candidate remained 20/20 direct, while the candidate reduced:

| Resource | Relative reduction |
| --- | ---: |
| Scout path | **40.2563%** |
| Total team path | **15.0306%** |
| Physical captures | **27.5362%** |

All 20 paired scout-path and team-path deltas favored the candidate. Mission success was 40/40; unsafe, collision, fallback, and false-clear counts were zero.
This is a compound-system result and does not assign the gain to one component in isolation.

### Decision-bound wheel dynamics

The archived 30 route decisions were then bound to non-fixed Genesis robots with wheel-velocity actuation.
Thirty fresh three-body scenes instantiated 30 scouts, 30 active loaded carriers, and 30 passive loaded carriers. All 90 distinct bodies reached their targets.

- The run passed 30/30 fixed seeds.
- All 29 direct pairs saved at least 0.50 m of loaded-carrier path.
- Mean active/passive carrier path was 4.9435/6.2433 m, a 20.8183% reduction.
- The one dual-blocked case completed its safe outer detour.
- Counted blocker and active carrier/scout contact rows were zero.
- No script pose write occurred after `scene.build()`; motion used wheel speed.

A separate solver-scale check replayed the same fixed decisions in exactly two scenes: 60 co-resident robots for the first 20 seeds and 30 co-resident robots for the final 10.
Both shards passed independently. This means 90 cumulative distinct robots with a maximum of 60 co-resident robots, not one 90-body scene.

Machine-readable reports and validators are linked from [evidence/README.md](evidence/README.md).

## AMD Radeon and ROCm

The frozen environment used Genesis 1.1.2 on `gs.amdgpu`, PyTorch 2.9.1+gitff65f5b, HIP 7.2.53211-e1a6bc5663, and one Radeon Cloud `gfx1100` GPU.
Genesis simulation, RGB-D rendering, tensor preprocessing, and the 39.8M-parameter spatial RGB-D model ran on Radeon. Purify Go ran on CPU by design as the independent decision path.

The exact checkpoint produced 192.31 ms batch-1 p50 model-forward latency and 6.25 images/s at batch 8. These measurements cover model forward only.

For the 30-world full-chain supplement, 844 two-second `rocm-smi` samples cover the complete 1,685.5-second wall of 60 Genesis + checkpoint + Purify subprocesses, including idle.
The run recorded 268 live RGB-D observations, 134 vision proposals, and 268 Go invocations.

## Evidence boundary

**All reported robot outcomes are simulation-only.** The frozen policy uses Genesis kinematic simulation, where carrier and scout are logical roles and capture roots on one shared chassis. The separately labelled dynamics checks instantiate non-fixed rigid bodies and use wheel-velocity control, but consume archived decisions and are not a live perception-policy rerun. The entry does not claim a physical-robot trial, sim-to-real transfer, dynamic obstacle handling, safety certification, fleet throughput, physical energy, or end-to-end control latency. Same-generator supplements are not OOD evidence. These limits apply to every result above.

## Reproduce and verify

### Verify this submitted directory

From this directory on Linux:

```bash
sha256sum -c SHA256SUMS
jq -e '.passed == true and (.errors | length) == 0' \
  evidence/challenge_102500_102529/VERIFICATION.json
```

On macOS, replace the first command with:

```bash
shasum -a 256 -c SHA256SUMS
```

The package manifest is [SUBMISSION_PACKAGE.json](SUBMISSION_PACKAGE.json); the full demo sidecar is [Look-Twice-V8-Demo.manifest.json](Look-Twice-V8-Demo.manifest.json).

### Run the deterministic CPU audit

```bash
git clone --branch v8-contract-progress-nbv --single-branch \
  https://github.com/eason4kim-rocket/look-twice.git
cd look-twice
python3 scripts/build_competition_replays.py
python3 -m unittest tests.test_competition_replay -v
python3 scripts/derive_v8_task_utility.py
(cd purify_robotics && go test ./...)
```

This path needs Python 3.11+ and Go, but no GPU or Genesis installation.

The original source-SHA guard is bound to the immutable frozen-foundation tag:

```bash
git clone --branch v8-competition-final-2026-08-05 --single-branch \
  https://github.com/eason4kim-rocket/look-twice.git look-twice-frozen
cd look-twice-frozen
python3 scripts/verify_frozen_foundation.py
```

### Run the Evidence Console locally

```bash
docker compose up --build
# open http://localhost:3000
```

Or build the site directly:

```bash
cd showcase
npm ci
npm test
npm run build
```

### Run a new Radeon episode

The [V8 reproducibility guide](https://github.com/eason4kim-rocket/look-twice/blob/v8-contract-progress-nbv/docs/V8_REPRODUCTION.md#8-run-a-new-non-locked-radeon-episode) gives the complete copy-paste command, environment checks, archive audit, and dynamics validators. A new execution is labelled as a reproduction and does not overwrite the archived result.

[Download the frozen checkpoint](https://github.com/eason4kim-rocket/look-twice/releases/download/v8-competition-candidate/v8_seg_v3_selected_ep22_7b158726f9c0.pt) and verify:

```text
SHA256  7b158726f9c00e01eec7f995674001727be03b84ff684a0cb43cba8682cd5783
```

## Package map

- `Look-Twice-V8-Demo.mp4` — complete 3:59 workflow demonstration.
- `Look-Twice-V8-Evidence-Reel-30s.mp4` — short silent evidence preview.
- `Look-Twice-V8-Technical-Report.pdf` — complete 19-page report.
- `Look-Twice-V8-Social-Card.png` — project preview image.
- `SUBMISSION_PACKAGE.json` — machine-readable inventory and scope.
- `SHA256SUMS` — integrity index for the submitted directory.
- `evidence/challenge_102500_102529/` — 30-world paired result and verifier.
- `evidence/contract_progress_challenge_102530_102549/` — compound efficiency result.
- `evidence/dual_body_dynamics_160820_160839/` — two-body dynamics report.
- `evidence/decision_dynamics_*` — 30-seed replay and the independent 60-/30-body shards.
- `evidence/README.md` — detailed index of machine evidence and boundaries.

The source repository keeps the implementation under `src/`, the independent Go core under `purify_robotics/`, public schemas under `schemas/`, the website under `showcase/`, and deterministic builders and validators under `scripts/`.

## Open-source contribution

The project code, schemas, Purify Go reference core, replay builder, validators, and Evidence Console are open source.
A focused Genesis URDF inertial-origin fix is available as upstream [issue #3183](https://github.com/Genesis-Embodied-AI/genesis-world/issues/3183) and open, unmerged [PR #3184](https://github.com/Genesis-Embodied-AI/genesis-world/pull/3184). The identical required test failed on the tested upstream commit and passed with the two-file patch; a later bounded run passed 3/3 selected regression tests. This is not a full-suite or upstream-acceptance claim.

## License

Apache-2.0. `NOTICE` in the source repository defines the public Purify reference-core boundary.
