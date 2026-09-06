# CRUX — Failure Discovery, Repair and Qualification for Contact-Rich Robot Manipulation on one AMD Radeon GPU

**Track 3: Physical AI Challenge · AMD AI DevMaster Hackathon 2026 · Solo — Enoch**

▶ **Demo video (3:56)** — narrated, every clip a fresh rollout; ends with an uncut real-time completed episode on a virgin seed:

https://github.com/user-attachments/assets/1b1171d1-84af-4129-8c86-1dce5f3f06e3

Also on YouTube: https://youtu.be/fLotIogPuSs
**Repository:** https://github.com/Enoch208/Crux · **Live evidence page:** https://enoch208.github.io/Crux/

---

## What CRUX is

Robotics can produce a new manipulation controller in an afternoon — and then cannot answer the question that matters: *is it actually better, and can you prove it to someone who wasn't there?* CRUX is that missing reliability layer, built end-to-end on one AMD Radeon PRO W7900 (gfx1100, ROCm 7.2.1, Genesis 1.3.1 on `gs.amdgpu`, `torch 2.13.0+rocm7.2`).

The task is contact-rich and unforgiving: a Franka arm grasps a 40 cm articulated cable, routes it through two clip gates, aligns its connector, and seats it in a channel retainer. CRUX runs that task across hundreds of matched, seeded environments in one batched scene, isolates each failure mechanism with experiments designed to falsify the alternatives, applies named repairs, qualifies the result with exact statistics on virgin seeds — and packages every number into a tamper-evident evidence bundle that re-verifies on a laptop CPU in about a minute.

## Headline results — every number recomputed from machine-readable evidence

| Result | Evidence |
|---|---|
| **Task success 0/128 → 47/128 on virgin seeds** (+36.7 pp, exact McNemar **p = 1.4e-14**; seating endpoint p = 4.1e-16) | 128 matched pairs, seeds asserted disjoint in code from all 192 previously used; 256 environments in one batched scene, 165 s |
| **Replicated on four further independent suites** — 13/32, 12/32, 9/32, and 6/32 on a second task defined in config alone | 256 matched pairs total across five suites, **zero discordant pairs against** — no seed anywhere the baseline completes and the candidate does not |
| **Release gate: APPROVED** on pre-registered rules (+36.7 pp generalization, −28.1 pp regression — better on both suites) | The same gate REJECTED the two candidates before this one; verdict, rule and raw episodes ship in the receipt |
| **~200k–293k environment-steps/s at 4,096 batched environments** on one GPU | Measured twice, ranges reported; live `rocm-smi` telemetry retained |
| **A learned policy qualified by the same harness — and correctly refused** | Behaviour-cloned MLP trained through ROCm, driven by the same batched driver, judged by the same seat-metric ruler: 0/32, with 9 episodes aborted by the shared safety envelope for arm collisions |
| **The harness caught its own success metric being geometrically impossible** | Five independent repair families converged on one impossible number; the corrected measurement is pinned by a CPU test and released the repair behind the headline |

**Verify without a GPU (~60 seconds):**

```bash
git clone --depth 1 https://github.com/Enoch208/Crux && cd Crux && uv sync
uv run pytest -q                                # 275 tests, ~1 s
uv run crux validate evidence/manifest.json     # 9/9 checks passed — sha256 + aggregates recomputed from raw episodes
```

Tamper with one byte of an episode file and the validator fails. That is the design.

## How AMD Radeon / ROCm is used

- **Batched physics at scale** — Genesis 1.3.1 resolves to the `gs.amdgpu` backend; the full task scene (articulated cable + Franka) steps at ~200k–293k env-steps/s at 4,096 environments. Qualification suites run live per-environment control and batched IK: 256 episodes in 165 s.
- **Training on the Radeon, twice** — a failure-risk model and a behaviour-cloned policy, both trained in PyTorch through ROCm (HIP 7.2.53211), with `assert_rocm()` refusing to run without a visible ROCm device. The cloned policy also runs **ROCm inference inside the control loop** during its qualification.
- **No silent CPU fallback anywhere** — core stages assert the resolved backend and fail loudly; the device evidence (GPU name, gfx1100, ROCm/HIP/torch versions) ships inside the hash-verified bundle.
- Discovery ran as ~4-minute matched-sweep cycles of 32–128 simultaneous episodes — the iteration speed that made 20 sweep rounds and ~1,400 batched episodes affordable in days.

## Innovations and key technical contributions

1. **Qualification as a first-class artifact.** Matched pairs on contamination-asserted virgin seeds, Wilson intervals, exact McNemar, and a pre-registered release gate that has rejected more candidates than it approved. Single episodes are never evidence — a decision backed by our own measurement of rollout divergence on this stack.
2. **A tamper-evident evidence bundle verified on CPU.** `crux bundle` writes hashed episodes, configs, the frozen controller spec, Radeon device evidence and replays under a manifest + receipt; `crux validate` recomputes the headline numbers from raw records with no GPU. 9/9 checks, tested against deliberate tampering.
3. **Failure discovery that falsifies.** 20 matched sweep rounds and two instrumented post-mortems produced 11 named mechanisms — including the discovery that the project's own success metric was mathematically unsatisfiable, found because five physically independent repairs converged on one impossible number.
4. **A measured noise floor, answered with sample size.** When a sweep showed the same controller swinging 9/32 → 13/32 between runs on identical seeds, the headline was re-proven at 4× the sample rather than left exposed — 0/128 vs 47/128, p = 1.4e-14.
5. **Controller-agnostic by demonstration.** The policy interface is a generator (observations in, control chunks out — the shape of a VLA/RL action loop). A ROCm-trained behaviour-cloned policy was dropped behind the same interface and qualified by identical machinery; the network only proposes bounded actions while the harness keeps the safety envelope and the seat-metric ruler. The gate's honest verdict — refusal, with 9 unsafe episodes caught — is the product working.
6. **Counterfactual physical search** — a captured mid-episode state restored into 32 parallel environments to evaluate 32 alternative futures of one decision in ~5 s on the GPU.
7. **Upstream contributions to Genesis** — three issues with minimal reproductions plus a pull request whose actuator-authority measurements the maintainers took for internal analysis.

## Datasets

All data is generated by the system and ships in the repository as machine-readable JSONL: ~2,000 retained episodes across discovery, ablation and qualification (12 reason codes × 11 task stages; failures never deleted), 11,375 expert state→action pairs for behaviour cloning, and 320 episodes of training/evaluation data for the ROCm failure predictor. Suites are seed-disjoint by assertion: evaluation seeds are checked in code against every seed selection ever touched.

## Deliverables

| Requirement | Location |
|---|---|
| Technical report | [`docs/technical-report.md`](https://github.com/Enoch208/Crux/blob/main/docs/technical-report.md) — application, architecture, datasets, AMD utilization, innovations, limitations, team |
| Source code | https://github.com/Enoch208/Crux — fully typed Python, `ruff`/`mypy --strict` clean, 275 CPU tests. Frozen submitted state: [release `v1.0-submission`](https://github.com/Enoch208/Crux/releases/tag/v1.0-submission) |
| Reproducibility README | [`README.md`](https://github.com/Enoch208/Crux/blob/main/README.md) — pinned `uv` environment, 60-second CPU verification path, and per-experiment GPU reproduction commands (numbered `gate*.py`, in the order they ran) |
| Demonstration video | https://youtu.be/fLotIogPuSs — narrated, every clip a fresh rollout; ends with an uncut real-time completed episode on a virgin seed |
| Supplementary | [Poster (PDF)](https://github.com/Enoch208/Crux/blob/main/docs/poster.pdf) · [live evidence page](https://enoch208.github.io/Crux/) · [gate-by-gate evidence log](https://github.com/Enoch208/Crux/blob/main/docs/acceptance-gates.md) including retractions |

Environment: prebuilt ROCm PyTorch wheels + `genesis-world` on the Radeon Cloud (setup documented in the README); the evaluation path needs only `uv` and a CPU. A Docker image is not included; the pinned `uv.lock` environment and the CPU-only verification path are the reproduction route.

## What is deliberately not claimed

The cable is a rigid articulated chain (Genesis 1.3.1 has no 1-D deformable — verified by introspection and disclosed everywhere). Task success is a minority of episodes and is not presented as a solved task. Contact rollouts on this stack are not reproducible episode-to-episode — measured, which is why every claim is suite-level. No sim-to-real claims are made. Failed experiments — a slip guard falsified on virgin seeds, a counterfactual search policy that did not transfer, the refused learned policy — are retained in the record with their data, not omitted.

## Team

**Enoch — solo.** System design, simulation and controller engineering, the discovery campaign, qualification statistics and release gate, evidence tooling, ROCm-trained models, upstream reports, documentation and video.
