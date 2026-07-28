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

# Platform Issues Found on HIP SDK 7.1 / RDNA3 (AMD Radeon RX 7600, Windows)

Found while validating VTE's batched-prefill WMMA kernel (`gemm_q4k_wmma.hip.template`, see [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#batching-and-prefill)) back on the RX 7600, the project's original Windows development card, after it had only ever been built and measured on the Linux/W7900 cloud instance above. VTE's own existing fallback (try the WMMA path, fall back to the always-correct sequential kernel on any failure) caught both issues below cleanly: neither crashed or produced wrong output, so this cost debugging time to characterize, not a broken demo.

## 4. `rocwmma/rocwmma.hpp` is not shipped with the Windows HIP SDK at all

Confirmed by direct filesystem search, not assumed: no file matching `rocwmma*` exists anywhere under the HIP SDK install (`D:\AMD\7.1`) or `C:\Program Files\AMD`, on a machine where the HIP SDK was installed through AMD's own standard Windows installer. On a full Linux ROCm install, rocWMMA ships as a standard package (`rocwmma-dev` and similar, matching the pattern already documented for `rocprof-compute`/`rocprofv3` above being genuinely present there). A HIP kernel that does `#include <rocwmma/rocwmma.hpp>` fails at the `hipcc`/`clang` level with a plain "file not found", not a GPU/architecture-support error: `rocwmma`'s own upstream README lists `gfx1102` (this exact card) as an explicitly supported target, so this isn't a hardware-capability gap, it's a Windows packaging gap. Worked around locally by vendoring rocWMMA's header-only `library/include/rocwmma/` tree directly into the consuming project (see issue below for why that alone wasn't sufficient). Requesting: either the Windows HIP SDK installer bundles rocWMMA's headers (it's header-only, so this is a handful of files, not a new binary dependency), or the SDK's own documentation states plainly that WMMA/matrix-core kernel development on Windows requires manually sourcing this header from the separate `ROCm/rocWMMA` (or its stated successor, `ROCm/rocm-libraries`) repository, so this isn't discovered by a `file not found` error with no further guidance.

## 5. rocWMMA's own header-only templates (tag `rocm-7.1.0`) fail to compile against the Windows HIP SDK's bundled Clang, with real `constexpr`-evaluation errors

After vendoring the headers above (confirmed to resolve the `file not found` from issue 4: the include path is found and processed), compilation still fails, now inside rocWMMA's own template metaprogramming, not in any VTE code:

```
D:\...\rocwmma\internal\layout\register_layout_traits_impl.hpp:455:28: error: constexpr variable 'TestCompatibleParams' must be initialized by a constant expression
D:\...\rocwmma\internal\layout\register_layout_traits_impl.hpp:573:19: error: non-type template argument is not a constant expression
fatal error: too many errors emitted, stopping now [-ferror-limit=]
288 warnings and 20 errors generated when compiling for gfx1102.
```

Both errors point into `rocwmma::LayoutTraits_impl::testCompatibleRegisterParams`/`testRegisterLayoutSame`, deep in rocWMMA's own `RegisterLayout::MmaAcc` trait-comparison code, never touched by VTE's kernel source (`gemm_q4k_wmma.hip.template` only calls the public `rocwmma::mma_sync`/`fragment`/`load_matrix_sync` API). The Windows HIP SDK 7.1's bundled compiler reports as `clang version 21.0.0git`, a notably recent/development-snapshot version string. **Not independently confirmed** (would need a matching Linux ROCm 7.1 install to check `amdclang++ --version` directly against): the leading hypothesis is that this Clang build is meaningfully newer than whatever compiler Linux ROCm 7.1 validates the `rocm-7.1.0` rocWMMA tag against, and something in that gap changed `constexpr` evaluation strictness enough to break code that presumably compiles cleanly in rocWMMA's own Linux CI. Also worth noting for anyone trying to reproduce or fix this: the `ROCm/rocWMMA` repository itself carries a retirement notice pointing to a new consolidated `ROCm/rocm-libraries` monorepo, and its own release tags (`rocm-7.1.0` vs. `rocm-7.2.4`) share no common git ancestor, an unusual repository state that makes bisecting for a compatible combination harder than a normal single-history project. Requesting: either a Windows HIP SDK release with a Clang version actually validated against a matching rocWMMA release, or documentation of which Clang/rocWMMA version pairs are known to work together on Windows specifically.

## Environment

- GPU: AMD Radeon RX 7600 (`gfx1102`, 32 CUs, 8GB VRAM)
- HIP SDK: 7.1 (Windows standalone installer, not a full ROCm/Linux install)
- Compiler: `clang version 21.0.0git` (bundled with the HIP SDK, `D:\AMD\7.1\bin\clang.exe`)
- OS: Windows 11
- rocWMMA: vendored from the `rocm-7.1.0` tag of `ROCm/rocWMMA` (chosen to match the installed HIP SDK's stated ROCm version)
