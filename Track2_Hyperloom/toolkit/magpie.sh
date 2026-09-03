#!/usr/bin/env bash
# Rocky's kernel evaluator = AMD Magpie (amd/skills -> magpie-kernel-evaluator, MIT).
# Correctness + performance eval + RANK multiple kernel implementations vs a baseline.
# USE THIS INSTEAD OF HAND-ROLLING A BENCHMARK HARNESS.
#
#   magpie.sh analyze kernel.hip --testcase "./run_test.sh"     # correctness+perf, one kernel
#   magpie.sh compare a.hip b.hip --testcase "./run_test.sh"    # rank impls vs baseline (idx 0)
#   magpie.sh compare -k compare.yaml                           # config-driven
#   magpie.sh --gpu-info                                        # arch/profiler probe
#
# VERIFIED on this box: Magpie recognizes Architecture: gfx1201.
# RDNA4 CLOSED-LOOP RECIPE (measured 2026-07-24, cross-validated dot8-vs-dp4a ~2.2x by
# self-timing AND metrix):
#   PERF BACKEND = metrix (NOT the default rocprof-compute, which is CDNA-only/dead here).
#   metrix HAS a gfx1201 backend and wraps rocprofv3 -> gives duration + HBM BW util + L2 hit.
#   Install: pip install "metrix @ git+https://github.com/AMDResearch/intellikit.git@<sha>#subdirectory=metrix"
#   GOTCHA (fixed): the SDK rocprofv3 shebang is `#!/usr/bin/env python3` -> resolves to
#     /home/jmonk/miniforge3/bin/python3 which lacked pyyaml. Fix once:
#     /home/jmonk/miniforge3/bin/python3 -m pip install --no-user pyyaml
#   USE: magpie compare -k cfg.yaml  (config has `performance: {backend: metrix, metrix: {profile: quick}}`)
#     -> Magpie gives compile + CORRECTNESS (works). But Magpie's AUTO-WINNER scoring weights
#        CDNA metrics (MFMA_FLOPs/LDS_BW = 0 on RDNA4) -> both score 0 -> it wrongly labels the
#        baseline the winner. IGNORE Magpie's winner label; RANK BY METRIX DURATION:
#        metrix profile --profile quick -- ./binaryA  | grep -oE 'avg=[0-9.]+'  (mean the dispatches)
#   Counters beyond duration: ~/rocky/toolkit/profile-datapath-gfx.sh (rocprofv3 + STABLE_STD).
# Compute runs on GPU0 (HIP_VISIBLE_DEVICES=0) per charter.
source /home/jmonk/rocky/quark-env.sh 2>/dev/null
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"; unset ROCR_VISIBLE_DEVICES
exec "$QPY" -m Magpie "$@"
