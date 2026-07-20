# Platform Issues Found on ROCm 7.2.1 / RDNA3 (AMD Radeon PRO W7900)

Found while building VTE's Thesis V7 optimization work (see [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md#thesis-v7-real-hardware-counters-and-closing-the-no-profiler-on-this-cloud-instance-gap-2026-07)) on an AMD Radeon PRO W7900 instance accessed through AMD's official Radeon Cloud platform ([radeon-global.anruicloud.com](https://radeon-global.anruicloud.com/)), ROCm 7.2.1, Linux, `gfx1100`. Reported here in case they're useful upstream; none of these blocked the project (the affected work fell back to software-side measurement methodology already in use elsewhere in the codebase), but all three cost real debugging time before the workaround was found.

## 1. `rocprof-compute` (Omniperf) refuses to run on RDNA3 (`gfx1100`)

`rocprof-compute` ships with the ROCm 7.2.1 install and runs without error up to the point of actually profiling:

```bash
rocprof-compute profile -n test -- python3 -c "print(1)"
```

```
WARNING Cannot detect accelerator partition from amd-smi.
  ERROR Cannot find a supported arch in rocminfo
```

`rocprof-compute --list-metrics`/`--list-blocks` only ever list CDNA architectures (`gfx908, gfx90a, gfx940, gfx941, gfx942, gfx950`); no RDNA architecture is present in the supported-arch list at all, so this isn't a workload-specific failure, it's a hard gate on the GPU architecture. Given `rocprof-compute` is the AMD-recommended replacement for the deprecated `omniperf`/`rocprof --tool-version 2` roofline-analysis path, and RDNA3 is a fully first-party-supported ROCm target (`hipcc --offload-arch=gfx1100` compiles and runs correctly), this leaves no roofline/occupancy-analysis tool at all for RDNA3 workstation cards. Requesting: either official RDNA3 support in `rocprof-compute`, or a documented note that it's CDNA-only so this isn't discovered by trial and error.

## 2. `rocprofv3 --pmc` returns zero for most counters on this GPU/instance

`rocprofv3` (the current, non-deprecated low-level profiler) runs and produces output with no errors, but only two counters ever returned non-zero data across every kernel tested, in a real production HIP-Graph decode workload:

```bash
rocprofv3 --pmc SQ_WAVES SQ_BUSY_CYCLES -f csv -d out -- python3 my_workload.py
# real, non-zero data for both counters, every dispatch
```

Every other counter tested returned a hard zero for every single dispatch, with no error or warning from the tool:

```bash
rocprofv3 --pmc GRBM_COUNT GL2C_HIT GL2C_MISS GL2C_HIT_sum GL2C_MISS_sum \
  OccupancyPercent GL2C_EA_RDREQ_128B_sum SQ_WAIT_ANY WAVE_DEP_WAIT \
  WAVE_ISSUE_WAIT SQ_INSTS_VALU SQ_INSTS_SALU SQ_INSTS_TEX_LOAD \
  -f csv -d out -- python3 my_workload.py
# every value: 0.00, every dispatch, no error
```

The pattern (only `SQ_WAVES`/`SQ_BUSY_CYCLES` work; everything else, including the GRBM block, the GL2C/L2-cache block, and even most SQ-block counters like wait-states and instruction-mix, returns zero) is consistent with only dispatch-trace-derivable metadata (wave count from grid dimensions, busy-cycles from kernel start/end timestamps) actually being sampled, not real hardware performance-counter block reads. `rocprofv3-avail list --pmc` correctly lists all of these counters as available for `gfx1100`, and `rocprofv3-avail info --pmc <name>` returns correct-looking counter descriptions/dimensions for each: the counters are recognized, just not populated. Root cause not identified from the client side (driver/KFD limitation on this specific cloud instance vs. a broader RDNA3 gap, vs. a cloud-provider virtualization restriction on chip-wide performance-counter MMIO access; all three remain plausible). Requesting: either a fix, or documentation of which counter blocks are actually functional on RDNA3 today so this isn't discovered by testing every counter by hand.

## 3. Legacy `rocprof`/`rocprofv2` does not execute on this ROCm 7.2.1 install

```bash
rocprof --tool-version 2 -i pmc.txt -d out -- python3 my_workload.py
# and
rocprofv2 -i pmc.txt -d out -- python3 my_workload.py
```

Both invocations (tried with several documented argument orderings, matching the tool's own `--help` usage examples exactly) print the tool's help text and exit with code 1 instead of running the workload, regardless of syntax. `rocprof`'s own banner already states the intent to deprecate this path ("We are phasing out development and support for roctracer/rocprofiler/rocprof/rocprofv2 in favor of rocprofiler-sdk/rocprofv3"), so this may be expected/already-known breakage on the way out rather than a regression worth fixing. Flagging in case it isn't, since the tool still ships and advertises itself as usable.

## Environment

- GPU: AMD Radeon PRO W7900 (`gfx1100`, 96 CUs, 48GB VRAM)
- ROCm: 7.2.1
- OS: Linux (reported as "Platform: Linux Baremetal" by `amd-smi`)
- Access: AMD Radeon Cloud ([radeon-global.anruicloud.com](https://radeon-global.anruicloud.com/))
- `amd-smi`: `Version: 26.2.2+e1a6bc5663`
