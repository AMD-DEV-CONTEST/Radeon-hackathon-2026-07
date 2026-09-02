# FlightGuard video plan

## 7-second paired Challenge Arena clip

**Recommended first view:** [`flightguard-challenge-arena-v1.mp4`](flightguard-challenge-arena-v1.mp4)

| Time | Screen action | Caption meaning |
|---:|---|---|
| 0–3.35 s | Same Genesis scene and paired initial state. Left: nominal PD. Right: `robust_z`. Both approach the same three gates. | One controller change: `kp_z` 2.5→8.0 and `kd_z` 2.0→3.6. |
| 3.35–7.00 s | Freeze the left arm at collision while the right arm continues through all three gates. | Nominal: collision, 0/3 gates, step 167. `robust_z`: success, 3/3 gates, step 479. |

The footer reports the measured primary result: **194/384 = 50.5% → 371/384 = 96.6% (+46.1 pp), zero nominal-only wins**. The displayed pair is seed 144856705, pair 0. This clip is a simulation replay; aggregate metrics come from all paired contexts.

- Frames: 140
- Resolution: 1280×720
- FPS: 20
- Duration: 7.0 seconds
- Size: 2,146,360 bytes
- Aggregate: `evidence/challenge-arena/challenge-arena-summary.json`

---

## 210-second workflow video

**Historical production notes; not a reviewer entry.**

**Story:** FlightGuard turns a visible Genesis mission failure into a matched controller-qualification result on one AMD Radeon.

| Time | Screen action | Burned English caption |
|---:|---|---|
| 0–7 s | Play the paired Challenge Arena clip. | “Same scene and random stream: nominal collides; `robust_z` clears all three gates.” |
| 7–20 s | FlightGuard product card. | “FlightGuard turns a visible Genesis failure into a reproducible controller decision on one AMD Radeon.” |
| 20–38 s | Workflow: sample → pair → Genesis/ROCm → results. | “Pair every context, simulate on ROCm, and compare mission outcomes.” |
| 38–58 s | Show the no-op command and PASS output: Genesis 1.2.3, PyTorch ROCm, `cuda:0`, one visible AMD Radeon. | “The no-op reports Genesis 1.2.3, PyTorch ROCm, one visible AMD Radeon, and bit-exact PASS.” |
| 58–88 s | Primary bars: 194/384 → 371/384, +177, +46.1 pp, 93.16% failure reduction. | “On 384 primary adversarial pairs, mission success rises from 194 to 371 with zero nominal-only wins.” |
| 88–108 s | Retention: 121/192 → 192/192, zero nominal-only wins. | “On 192 separate heldout pairs, `robust_z` retains every nominal success and reaches 192 of 192.” |
| 108–128 s | Diagnostics: bit-exact no-op; zero action 0/8 success and 10.506417 m divergence. | “The unchanged path is exact; zero action produces zero successes and a 10.506417 meter divergence.” |
| 128–150 s | Isolated change: `kp_z` 2.5→8.0 and `kd_z` 2.0→3.6. | “Only `kp_z` and `kd_z` change; initial state, gates, domain parameters, and random streams stay paired.” |
| 150–175 s | One-Radeon scaling: 32, 128, 256, 512 environments and 2,227,200 transitions. | “The fixed one-Radeon workload scales from 32 to 512 parallel environments.” |
| 175–193 s | Show `python3 scripts/judge_smoke.py` and PASS headlines. | “A CPU-only judge command checks submitted metrics, diagnostics, figures, videos, and Radeon measurements.” |
| 193–205 s | Application: find failure, qualify change, review result. | “FlightGuard helps robotics teams choose which controller changes deserve hardware-test time.” |
| 205–210 s | Final claim-boundary card. | “Simulation-only and sampled: no physical-flight safety, sim-to-real, certification, or SOTA conclusion.” |

### Required on-screen numbers

- primary: 384 pairs, 194/384 → 371/384, +177, +46.1 pp, 93.16% failure reduction, zero nominal-only wins
- retention: 192 pairs, 121/192 → 192/192, +71, zero nominal-only wins
- self-checks: bit-exact no-op; zero action 0/8 success and 10.506417 m maximum divergence
- controller change: `kp_z` 2.5→8.0; `kd_z` 2.0→3.6
- Radeon scaling: 2,227,200 transitions; 32→512 environments; 16.027× intra-device speedup

### Recording notes

- Frames: 2,100
- Resolution: 1280×720
- FPS: 10
- Duration: 210.0 seconds
- Codec requested/reported: `mp4v` / `FMP4`
- Audio: none
- Size: 17,874,513 bytes
- Renderer: `scripts/render_challenge_arena_workflow_video_v3.py`
- The first 70 output frames consume all 140 frames of the 20 fps Challenge Arena clip by exact 2:1 downsampling.
- All narration is burned English text; the MP4 has no audio track.
