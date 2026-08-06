# Formal eval log (Env-A Sync + RTC + π0.5 optimization)

Frozen snapshot: **2026-08-06** (Env-A Sync/RTC/π0.5 + Env-B).

## Protocol

| Knob | Value |
|---|---|
| Task | `Pick up the fruit and place it in the basket.` |
| Dataset | 120 ep / 30k frames (Env-A train dist only) |
| Seed | 99 (paired Env-A / Env-B nominal poses) |
| Chunk H | 50 · Sync-full E=50 · RTC/Async E=10 |
| max_steps | 400 · control 30 Hz · smooth 0.15 |

### Env-B (held-out runtime perturbation)

Capability check under distribution shift — **not** mixed with the latency axis.

| Knob | Value |
|---|---|
| Nominal fruit init | Same RNG as Env-A (`seed=99`) → paired poses |
| Perturb RNG | Independent `seed+7919` |
| Shift | \|Δxy\| ∼ U[3, 5] cm, uniform angle; **basket fixed** |
| Train exposure | **None** (eval-only) |
| Mode | Sync-full E=50, native delay (isolates pose shift) |
| Policies | SmolVLA B0 + π0.5 B1d |
| Manifest | `artifacts/formal/env_b_manifest.json` |

**Why this design:** 3–5 cm is large enough to break memorized grasp points, small enough to stay reachable; pairing keeps seed confound out of the A→B delta; Sync-full (no injected delay) avoids confounding latency with generalization.

## Training

| Run | Recipe | Steps | Peak VRAM | Final loss |
|---|---|---:|---:|---:|
| SmolVLA B0 | workshop | 4000 | 2.30 GB | 0.0178 |
| π0.5 B1 | expert-only, freeze vision | 3000 | 11.29 GB | 0.022 |
| π0.5 B1c | continue B1, expert-only | 4000 | 11.29 GB | 0.0062 |
| **π0.5 B1d** | **full + unfreeze vision** from B1c | 2000 | **32.34 GB** | 0.035 |

**Key fix:** expert-only fine-tune never grasped (0/20); unfreezing SigLIP + training full model → **1/20 place**.

## Closed-loop results

### Capability (native Sync-full)

| Policy | Place | Lift | Notes |
|---|---:|---:|---|
| SmolVLA B0 | **2/20** | 3/20 | primary light baseline |
| π0.5 B1 / B1c | 0/20 | 0/20 | open-loop OK; no grasp |
| **π0.5 B1d** | **1/20** | 1/20 | vision unfreeze unlocks grasp |

### Latency story (SmolVLA)

| Mode | +delay | Place | Lift | freeze |
|---|---:|---:|---:|---|
| Sync-full | 0 | 2/20 | 3/20 | — |
| Sync-full | 200 | **0/20** | 2/20 | freezes |
| **Async E=10** | 200 | **1/20** | **4/20** | **0** |
| RTC E=10 | 200 | 0/20 | 1/20 | 0 |

**Takeaway:** under +200 ms, continuous action queue (Async) recovers place/lift vs Sync freeze. RTC guidance ≤ Async on place here — report honestly; lever is **not stalling**.

### π0.5 B1d under +200 ms (n=10)

| Mode | Place | Lift | freeze / move_infer |
|---|---:|---:|---|
| Sync-full E=50 | **1/10** | 1/10 | freezes on replan |
| Async E=10 | 0/10 | 0/10 | freeze=0 / 720 |
| RTC E=10 | 0/10 | 0/10 | freeze=0 / 810 |

Small-n caveat: Sync hit the same graspable seed as native; Async/RTC E=10 may reintroduce short-horizon issues. Prefer SmolVLA latency table for the system story; π0.5 table shows **B1d unlocks grasp**, delay ablations need larger n.

### Env-B generalization (Sync-full, native; seed=99 paired)

Mean \|Δxy\| = **3.7 cm** (range 3.0–4.9 cm). Same nominal fruit inits as Env-A; basket fixed.

| Policy | Env-A place | Env-B place | Env-A lift | Env-B lift | Paired flips |
|---|---:|---:|---:|---:|---|
| SmolVLA B0 | **2/20** | **0/20** | 3/20 | 1/20 | A✓B✗=2, A✗B✓=0 |
| π0.5 B1d | **1/20** | **0/20** | 1/20 | 1/20 | A✓B✗=1, A✗B✓=0 |

**Takeaway:** held-out 3–5 cm XY shift **zeros place success** for both checkpoints. Env-A place winners (SmolVLA ep5/ep16; π0.5 ep3) all fail under their paired shifts. Lift remains rare (1/20 each on Env-B). Story: policies are **pose-sensitive** on this small dataset; Env-B is a negative generalization result we report honestly — primary contribution stays the **latency / non-stall** axis, not open-world spatial robustness.

## Artifacts

| Item | Path |
|---|---|
| Latency story fig | `artifacts/figures/eval/env_a_latency_story.*` |
| RTC story figs | `artifacts/figures/eval/env_a_rtc_story_*` |
| π0.5 opt figs | `artifacts/figures/eval/env_a_pi05_opt_*` |
| SmolVLA demo | `output/demo/smolvla_sync_E50_reel.mp4` |
| RTC vs Sync demo | `output/demo/rtc_vs_sync_d200_reel.mp4` |
| π0.5 B1d demo | `output/demo/pi05_b1d_reel.mp4` |
| Env-A vs Env-B fig | `artifacts/figures/eval/env_a_vs_b.*` |
| Env-B demo reel | `output/demo/env_b_reel.mp4` |
| Env-B manifest | `artifacts/formal/env_b_manifest.json` |
| Success clip | `output/eval/pi05_sync_E50_b1d_n20/videos/ep003_ok_sbs.mp4` |
| **Contest technical report** | `artifacts/technical-report.pdf` |
| **Contest demo video** | `artifacts/demo-video.mp4` (~3:48, EN burn-in + `demo-video.en.srt`) |
| Rebuild scripts | `scripts/build_technical_report.py`, `scripts/build_demo_video.py` |
