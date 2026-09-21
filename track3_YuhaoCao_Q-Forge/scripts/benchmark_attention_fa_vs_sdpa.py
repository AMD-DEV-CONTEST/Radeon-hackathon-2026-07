"""Benchmark FlashAttention-2 (ROCm/CK) against torch SDPA on gfx1100.

Sweeps sequence length 256..4096, measuring forward and backward throughput for
both implementations. Each implementation receives tensors in its native layout
(FA: B,S,H,D -- SDPA: B,H,S,D) so the numbers reflect kernel cost rather than
transpose overhead.

Writes a JSON blob to --out for downstream chart/report generation.
"""

import argparse
import json
import platform
import subprocess
import time

import torch
import torch.nn.functional as F

SEQ_LENS = [256, 512, 1024, 2048, 4096]


def flops(batch, heads, seqlen, head_dim, causal, backward):
    """Attention FLOPs using the convention from the flash-attention repo."""
    fwd = 4 * batch * heads * seqlen * seqlen * head_dim
    if causal:
        fwd *= 0.5
    return fwd * 2.5 if backward else fwd


def timeit(fn, warmup, iters):
    """Median-of-iters wall time per call, in seconds."""
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return samples[len(samples) // 2]


def gpu_state():
    """Sample clock/temperature so the report can flag thermal drift."""
    try:
        out = subprocess.run(
            ["rocm-smi", "--showtemp", "--showclocks"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return {}
    state = {}
    for line in out.splitlines():
        if "Temperature" in line and "junction" in line.lower():
            state["temp_junction_c"] = line.split(":")[-1].strip()
        elif "sclk" in line.lower() and "clock" in line.lower():
            state["sclk"] = line.split(":")[-1].strip()
    return state


def make_inputs(batch, heads, seqlen, head_dim, dtype, layout):
    shape = (batch, seqlen, heads, head_dim) if layout == "bshd" else (batch, heads, seqlen, head_dim)
    return [
        torch.randn(shape, device="cuda", dtype=dtype, requires_grad=True)
        for _ in range(3)
    ]


def bench_one(impl, batch, heads, seqlen, head_dim, dtype, causal, warmup, iters):
    """Return (fwd_s, bwd_s, step_s, peak_bytes) for one implementation.

    fwd/bwd are isolated passes; step is a realistic training iteration with the
    autograd graph rebuilt each time, used as an independent cross-check that the
    isolated numbers add up.
    """
    from flash_attn import flash_attn_func

    layout = "bhsd" if impl == "sdpa" else "bshd"
    q, k, v = make_inputs(batch, heads, seqlen, head_dim, dtype, layout)

    if impl == "sdpa":
        fwd = lambda: F.scaled_dot_product_attention(q, k, v, is_causal=causal)
    else:
        fwd = lambda: flash_attn_func(q, k, v, causal=causal)

    torch.cuda.reset_peak_memory_stats()
    fwd_s = timeit(fwd, warmup, iters)

    # Isolate backward: build the graph once, replay it with retain_graph.
    out = fwd()
    grad = torch.randn_like(out)

    def bwd():
        for t in (q, k, v):
            t.grad = None
        out.backward(grad, retain_graph=True)

    bwd_s = timeit(bwd, warmup, iters)

    def step():
        for t in (q, k, v):
            t.grad = None
        fwd().backward(grad)

    step_s = timeit(step, warmup, iters)
    peak = torch.cuda.max_memory_allocated()

    del q, k, v, out, grad
    torch.cuda.empty_cache()
    return fwd_s, bwd_s, step_s, peak


def check_parity(batch, heads, seqlen, head_dim, dtype, causal):
    """Max abs deviation of FA output from an SDPA reference at this config."""
    from flash_attn import flash_attn_func

    torch.manual_seed(0)
    q, k, v = make_inputs(batch, heads, seqlen, head_dim, dtype, "bshd")
    fa = flash_attn_func(q, k, v, causal=causal)
    ref = F.scaled_dot_product_attention(
        *[x.transpose(1, 2) for x in (q, k, v)], is_causal=causal
    ).transpose(1, 2)
    err = (fa.float() - ref.float()).abs().max().item()
    del q, k, v, fa, ref
    torch.cuda.empty_cache()
    return err


def sdpa_backends():
    """Which SDPA backends this build reports as usable."""
    from torch.nn.attention import SDPBackend, sdpa_kernel

    avail = {}
    q, k, v = make_inputs(2, 8, 512, 64, torch.float16, "bhsd")
    for name, backend in [
        ("flash", SDPBackend.FLASH_ATTENTION),
        ("mem_efficient", SDPBackend.EFFICIENT_ATTENTION),
        ("math", SDPBackend.MATH),
    ]:
        try:
            with sdpa_kernel(backend):
                F.scaled_dot_product_attention(q, k, v, is_causal=True)
            avail[name] = True
        except Exception as exc:
            avail[name] = f"unavailable: {type(exc).__name__}"
    del q, k, v
    torch.cuda.empty_cache()
    return avail


def precompile(impls, batch, heads, head_dim, settle=8.0):
    """Force JIT compilation of every kernel/shape before any timing starts.

    Triton compiles (and autotunes) lazily and partly on background threads. If that
    work overlaps the timing loop it inflates wall-clock for whichever implementation
    happens to be measured next -- which showed up as an 86% swing in the SDPA
    baseline between runs. Warming every shape first, then letting the machine settle,
    removes it.
    """
    from flash_attn import flash_attn_func

    t0 = time.perf_counter()
    for dtype in (torch.float16, torch.bfloat16):
        for causal in (True, False):
            for seqlen in SEQ_LENS:
                for impl in impls:
                    layout = "bhsd" if impl == "sdpa" else "bshd"
                    q, k, v = make_inputs(batch, heads, seqlen, head_dim, dtype, layout)
                    out = (
                        F.scaled_dot_product_attention(q, k, v, is_causal=causal)
                        if impl == "sdpa"
                        else flash_attn_func(q, k, v, causal=causal)
                    )
                    out.sum().backward()
                    del q, k, v, out
                    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print(f"precompile pass: {time.perf_counter() - t0:.1f}s, settling {settle:.0f}s", flush=True)
    time.sleep(settle)


def stability_probe(batch, heads, head_dim):
    """SDPA step time at a fixed reference config, used to bound drift within a run."""
    q, k, v = make_inputs(batch, heads, 2048, head_dim, torch.float16, "bhsd")
    grad = torch.randn_like(F.scaled_dot_product_attention(q, k, v, is_causal=True))

    def step():
        for t in (q, k, v):
            t.grad = None
        F.scaled_dot_product_attention(q, k, v, is_causal=True).backward(grad)

    ms = timeit(step, 5, 20) * 1e3
    del q, k, v, grad
    torch.cuda.empty_cache()
    return ms


def detect_fa_backend():
    """Which FlashAttention backend actually got imported.

    The Triton path is selected before import by FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE
    plus a PYTHONPATH pointing at a tree that bundles flash_attn_triton_amd, so the
    only reliable way to label a run is to ask the imported module.
    """
    import flash_attn
    from flash_attn import flash_attn_interface as FI

    triton = bool(getattr(FI, "USE_TRITON_ROCM", False))
    key = "flash_attn_triton" if triton else "flash_attn"
    return key, {
        "fa_key": key,
        "fa_backend": "triton" if triton else "ck",
        "fa_version": flash_attn.__version__,
        "fa_module": FI.flash_attn_gpu.__name__,
        "fa_path": flash_attn.__file__,
    }


def merge_into(base_path, meta, rows, fa_key):
    """Fold a second run's FlashAttention columns into an existing result file.

    Only the new backend's columns are added; the existing rows are left alone. The
    second run's SDPA numbers are kept under sdpa_rerun_* so run-to-run drift stays
    auditable instead of being silently averaged away.
    """
    with open(base_path) as fh:
        base = json.load(fh)

    index = {(r["dtype"], r["causal"], r["seqlen"]): r for r in base["rows"]}
    drifts = []
    for r in rows:
        tgt = index.get((r["dtype"], r["causal"], r["seqlen"]))
        if tgt is None:
            base["rows"].append(r)
            continue
        for k, v in r.items():
            if k.startswith(fa_key + "_") or k.endswith("_" + fa_key):
                tgt[k] = v
            elif k.startswith("sdpa_"):
                tgt["sdpa_rerun_" + k[len("sdpa_"):]] = v
        for p in ("fwd", "bwd", "step"):
            tgt[f"speedup_{p}_{fa_key}"] = tgt[f"sdpa_{p}_ms"] / tgt[f"{fa_key}_{p}_ms"]
        drifts.append(abs(r["sdpa_step_ms"] / tgt["sdpa_step_ms"] - 1.0) * 100.0)

    base["meta"].setdefault("runs", []).append(meta)
    if drifts:
        base["meta"]["sdpa_drift_pct_max"] = max(drifts)
        base["meta"]["sdpa_drift_pct_mean"] = sum(drifts) / len(drifts)
        print(
            f"\nSDPA run-to-run drift (step time): mean {sum(drifts)/len(drifts):.2f}%, "
            f"max {max(drifts):.2f}%"
        )
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--heads", type=int, default=16)
    ap.add_argument("--head-dim", type=int, default=64)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--out", default="reports/attention_bench_gfx1100.json")
    ap.add_argument(
        "--merge-into",
        help="Existing results file to fold this run's FlashAttention columns into.",
    )
    ap.add_argument(
        "--no-precompile", action="store_true",
        help="Skip the pre-timing JIT warm pass (only safe for the CK backend).",
    )
    args = ap.parse_args()

    fa_key, fa_info = detect_fa_backend()

    meta = {
        "gpu": torch.cuda.get_device_name(0),
        "gfx": torch.cuda.get_device_properties(0).gcnArchName,
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "flash_attn": fa_info["fa_version"],
        "python": platform.python_version(),
        "batch": args.batch,
        "heads": args.heads,
        "head_dim": args.head_dim,
        "warmup": args.warmup,
        "iters": args.iters,
        "sdpa_backends": sdpa_backends(),
        "gpu_state_start": gpu_state(),
        **fa_info,
    }
    print(json.dumps(meta, indent=2), flush=True)

    if not args.no_precompile:
        precompile((fa_key, "sdpa"), args.batch, args.heads, args.head_dim)
    probe_start = stability_probe(args.batch, args.heads, args.head_dim)
    print(f"stability probe (start): {probe_start:.3f} ms", flush=True)

    rows = []
    for dtype, dtype_name in [(torch.float16, "fp16"), (torch.bfloat16, "bf16")]:
        for causal in (True, False):
            for seqlen in SEQ_LENS:
                rec = {
                    "dtype": dtype_name,
                    "causal": causal,
                    "seqlen": seqlen,
                    f"parity_max_abs_err_{fa_key}": check_parity(
                        args.batch, args.heads, seqlen, args.head_dim, dtype, causal
                    ),
                }
                for impl in (fa_key, "sdpa"):
                    fwd_s, bwd_s, step_s, peak = bench_one(
                        impl, args.batch, args.heads, seqlen, args.head_dim,
                        dtype, causal, args.warmup, args.iters,
                    )
                    for pass_name, secs, is_bwd in [
                        ("fwd", fwd_s, False), ("bwd", bwd_s, True),
                    ]:
                        fl = flops(args.batch, args.heads, seqlen, args.head_dim, causal, is_bwd)
                        rec[f"{impl}_{pass_name}_ms"] = secs * 1e3
                        rec[f"{impl}_{pass_name}_tflops"] = fl / secs / 1e12
                    rec[f"{impl}_step_ms"] = step_s * 1e3
                    rec[f"{impl}_peak_mib"] = peak / 2**20
                for pass_name in ("fwd", "bwd", "step"):
                    rec[f"speedup_{pass_name}"] = (
                        rec[f"sdpa_{pass_name}_ms"] / rec[f"{fa_key}_{pass_name}_ms"]
                    )
                rows.append(rec)
                print(
                    f"{dtype_name} causal={int(causal)} S={seqlen:>5}  "
                    f"FA fwd {rec[f'{fa_key}_fwd_tflops']:6.1f} TF/s  "
                    f"SDPA fwd {rec['sdpa_fwd_tflops']:6.1f} TF/s  "
                    f"(x{rec['speedup_fwd']:.2f})   "
                    f"FA bwd {rec[f'{fa_key}_bwd_tflops']:6.1f}  "
                    f"SDPA bwd {rec['sdpa_bwd_tflops']:6.1f}  "
                    f"(x{rec['speedup_bwd']:.2f})   "
                    f"step x{rec['speedup_step']:.2f}",
                    flush=True,
                )

    meta["gpu_state_end"] = gpu_state()
    probe_end = stability_probe(args.batch, args.heads, args.head_dim)
    meta["stability_probe_ms"] = {"start": probe_start, "end": probe_end}
    meta["stability_drift_pct"] = abs(probe_end / probe_start - 1.0) * 100.0
    print(
        f"stability probe (end): {probe_end:.3f} ms  ->  intra-run drift "
        f"{meta['stability_drift_pct']:.2f}%",
        flush=True,
    )
    if args.merge_into:
        blob = merge_into(args.merge_into, meta, rows, fa_key)
    else:
        blob = {"meta": meta, "rows": rows}
    with open(args.out, "w") as fh:
        json.dump(blob, fh, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
