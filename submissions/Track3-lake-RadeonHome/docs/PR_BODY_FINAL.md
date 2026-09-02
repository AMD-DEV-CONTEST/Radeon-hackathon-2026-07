## Track 3 Submission: RadeonHome

**Language-guided, failure-aware household mobile manipulation on AMD Radeon / ROCm.**

| Criterion | Wt | Evidence |
|---|---:|---|
| Robot capability | 30 | **15/17** physical · **10/10** batch · **5/5** smoke · **11.5mm** error · **Learned policy** (Spearman r=0.999) · **5 tasks** · Friction robustness 4/4 |
| Radeon / ROCm | 20 | gfx1100 48GB · ROCm/HIP 7.2 · Genesis 1.3.0 `gs.amdgpu` · **1,393 phys/s** · 99% peak GPU |
| Innovation | 20 | Language→execution (Qwen3-4B local) · MJCF mobile migration · Slip recovery · Learned policy on GPU |
| Application value | 20 | 5 household tasks: NL → A* nav → grasp → carry → verify |
| Upstream | 10 | **[Genesis PR #3186](https://github.com/Genesis-Embodied-AI/genesis-world/pull/3186)** (URDF EPS fix) · **[LeRobot PR #4336](https://github.com/huggingface/lerobot/pull/4336)** (ROCm guard) · [#3182](https://github.com/Genesis-Embodied-AI/genesis-world/issues/3182) · [franka PR #2](https://github.com/wangxunx/franka_fruit_pick_demo/pull/2) |

### Learning Component (AMD GPU)

**LearnedGraspPolicy** — MLP 128→64→32→1, 11,265 params
- Trained **18.1s** on gfx1100, 3,620 samples
- Spearman r=**0.9993** vs heuristic expert on 1,296 candidates
- Drop-in replacement for HeuristicGraspPolicy — same score()/rank() interface
- All training and inference on single AMD Radeon GPU

### Off-Distribution Robustness

Friction sweep on parcel_small (desk→trash_bin), all conditions **no failures**:

| Friction × | Mass × | Steps | Transport | Analysis |
|---|---|---|---|---|
| 0.5 | 1.0 | 6,137 | ✅ Success | +19% steps vs baseline |
| 1.0 | 1.0 | 5,137 | ✅ Success | Baseline |
| 1.5 | 1.0 | 5,537 | ✅ Success | +8% steps vs baseline |
| 2.0 | 1.0 | 6,337 | ✅ Success | +23% steps vs baseline |

**Conclusion**: Deterministic position-force controller survives **4× friction variation** (0.5×–2.0×) with zero transport failures. Step count increases monotonically with friction deviation — the slip detection loop actively compensates at the cost of throughput.

### Multi-Task Expansion (5 household tasks)

| Task | Object | Source | Target | Type |
|---|---|---|---|---|
| Take out trash | trash | desk/bedside | trash_bin | pick_and_place |
| Put away keys | keys | desk/bedside | door_tray | pick_and_place |
| Medicine near cup | medicine | desk/coffee | bedside_table | place_near |
| Cup to table | cup | coffee/desk | dining_table | pick_and_place |
| Book to shelf | book | desk/bedside | bookshelf | pick_and_place |

All parsed by deterministic `language.py` + optional Qwen3-4B via local ROCm inference.

### AMD GPU Benchmark (verified on gfx1100)

| Metric | Value |
|---|---|
| Physics throughput | 1,393 steps/s |
| Full loop (step + state read) | 1,144 steps/s |
| Peak GPU utilization | 99% |
| Peak VRAM | 9.3 GB |
| Platform | AMD Radeon gfx1100, 48 GB, Genesis 1.3.0 `gs.amdgpu` |

### Upstream Open-Source Contributions

| # | Link | Type | Description |
|---|---|---|---|
| 1 | [Genesis PR #3186](https://github.com/Genesis-Embodied-AI/genesis-world/pull/3186) | PR (+26/-3) | Fix URDF `panda_slider_mobile.urdf` missing inertial blocks (EPS mass bug) |
| 2 | [LeRobot PR #4336](https://github.com/huggingface/lerobot/pull/4336) | PR (+13) | Fix optional-dependency import guard for ROCm cloud images |
| 3 | [Genesis #3182](https://github.com/Genesis-Embodied-AI/genesis-world/issues/3182) | Issue | Document scikit-image/NumPy 2.x ROCm incompatibility |
| 4 | [franka demo PR #2](https://github.com/wangxunx/franka_fruit_pick_demo/pull/2) | PR | Add Wilson CI multi-seed batch runner to Track 3 starter |

### Judge Quick Path
1. `python3 judge_smoke.py` → `EVIDENCE_OK`  
2. [Interactive Evidence Page](https://htmlpreview.github.io/?https://raw.githubusercontent.com/520lake/Radeon-hackathon-2026-07/submission/track3-radeonhome/submissions/Track3-lake-RadeonHome/evidence.html)
3. `docker build -t radeonhome . && docker run --device=/dev/kfd --device=/dev/dri radeonhome`
4. [4:17 demo video](https://github.com/520lake/RadeonHome/blob/main/output/video/RadeonHome_Track3_Demo_20260802.mp4)

Team: **lake** · **Wang Suhu** · Solo · Track 3 — AMD AI DevMaster 2026
