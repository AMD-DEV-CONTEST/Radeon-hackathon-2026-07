"""
T188 -- MEASURED numpy accuracy/exact-reduce gate for the INT6 all-reduce codec.
CPU-only. Run: conda activate inference && python3 test_accuracy.py
"""
import os, numpy as np
from int6_codec import (
    QK, pack, unpack, round_trip, quantize_codes, dequantize_codes,
    bytes_per_element,
)

def _need(var, what):
    raise SystemExit(f"set {var} to {what}")


def rel_l2(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    return np.linalg.norm(b - a) / (np.linalg.norm(a) + 1e-30)


def max_abs(a, b):
    return float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64))))


def snr_db(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    sig = np.sum(a * a)
    err = np.sum((b - a) ** 2) + 1e-30
    return 10 * np.log10(sig / err) if sig > 0 else float("nan")


# ---------------------------------------------------------------------------
# 1a. Round-trip accuracy on synthetic gaussian activations
# ---------------------------------------------------------------------------
def test_gaussian(bits_list=(4, 6, 8), shapes=((4096,), (2048, 4096)), seeds=(0, 1, 2)):
    print("=== 1a. Round-trip accuracy: gaussian activations (block=32) ===")
    rows = []
    for shape in shapes:
        for seed in seeds:
            rng = np.random.default_rng(seed)
            x = rng.standard_normal(shape).astype(np.float32)
            # realistic activation scale + occasional outliers (heavy-ish tail)
            x = x * 1.0
            outlier_mask = rng.random(shape) < 0.001
            x = np.where(outlier_mask, x * 8.0, x)
            for bits in bits_list:
                y = round_trip(x, bits)
                # also compare against fp16 cast (the "already lossy" baseline
                # a real reduce would be operating on)
                y_fp16 = x.astype(np.float16).astype(np.float32)
                r = dict(
                    shape=shape, seed=seed, bits=bits,
                    rel_l2=rel_l2(x, y), max_abs=max_abs(x, y), snr_db=snr_db(x, y),
                    fp16_rel_l2=rel_l2(x, y_fp16),
                    bpe=bytes_per_element(bits),
                )
                rows.append(r)
    for r in rows:
        print(f"  shape={str(r['shape']):>16} seed={r['seed']} bits={r['bits']} "
              f"rel_l2={r['rel_l2']:.6f} max_abs={r['max_abs']:.5f} snr={r['snr_db']:6.2f}dB "
              f"bytes/elem={r['bpe']:.3f} (fp16-cast rel_l2={r['fp16_rel_l2']:.6f})")
    return rows


# ---------------------------------------------------------------------------
# 1b. Round-trip accuracy on a REAL tensor slice (F16 GGUF, mmap-backed read)
# ---------------------------------------------------------------------------
def test_real_tensor(gguf_path, bits_list=(4, 6, 8), n_tensors=4, rows_per_tensor=64):
    print(f"\n=== 1b. Round-trip accuracy: REAL tensor slices from {gguf_path} ===")
    try:
        from gguf import GGUFReader
    except ImportError:
        print("  [SKIP] gguf python module not available in this env")
        return []
    reader = GGUFReader(gguf_path)
    picked = 0
    out_rows = []
    for t in reader.tensors:
        if picked >= n_tensors:
            break
        name = t.name
        if "weight" not in name and "blk" not in name:
            continue
        arr = t.data  # numpy view, mmap-backed (no full-file load)
        if arr.dtype == np.float16 or arr.dtype == np.float32:
            flat = arr.reshape(-1).astype(np.float32)
        else:
            continue  # skip already-quantized tensors, we want float source data
        if flat.size < QK * 8:
            continue
        n_take = min(flat.size, rows_per_tensor * 4096)
        x = flat[:n_take].copy()
        picked += 1
        for bits in bits_list:
            y = round_trip(x, bits)
            r = dict(name=name, n=x.size, bits=bits, rel_l2=rel_l2(x, y),
                      max_abs=max_abs(x, y), snr_db=snr_db(x, y))
            out_rows.append(r)
            print(f"  tensor={name:<40} n={x.size:>8} bits={bits} "
                  f"rel_l2={r['rel_l2']:.6f} max_abs={r['max_abs']:.5f} snr={r['snr_db']:6.2f}dB")
    if picked == 0:
        print("  [SKIP] no eligible float16/float32 tensors found (file may be all-quantized)")
    return out_rows


# ---------------------------------------------------------------------------
# 2. EXACT-REDUCE property
# ---------------------------------------------------------------------------
def test_exact_reduce_shared_scale(bits=6, n=8192, seed=0):
    """Task-literal spec: pack TWO tensors to a COMMON per-block scale, add in
    the INT domain (int16 accumulator), dequant, and show the result equals
    fp32(a)+fp32(b) to WITHIN the two operands' own quantization error only
    (i.e. the ADD step itself introduces zero additional drift)."""
    print(f"\n=== 2a. Exact-reduce (SHARED scale, common-scale int add), bits={bits} ===")
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(n).astype(np.float32)
    b = rng.standard_normal(n).astype(np.float32)

    block = QK
    pad = (-n) % block
    ap = np.pad(a, (0, pad)); bp = np.pad(b, (0, pad))
    nblk = ap.size // block
    ab = ap.reshape(nblk, block); bb = bp.reshape(nblk, block)

    lo, hi, mask = -(1 << (bits - 1)), (1 << (bits - 1)) - 1, (1 << bits) - 1
    # shared scale per block = joint absmax across BOTH operands' block
    joint_absmax = np.maximum(np.max(np.abs(ab), axis=-1), np.max(np.abs(bb), axis=-1))
    scale = (joint_absmax / hi).astype(np.float32)
    scale_safe = np.where(scale == 0, 1.0, scale)

    qa = np.clip(np.round(ab / scale_safe[:, None]), lo, hi).astype(np.int32)
    qb = np.clip(np.round(bb / scale_safe[:, None]), lo, hi).astype(np.int32)

    # int16 accumulator: bits=6 -> 7-bit sum, fits int16 trivially; general case
    q_sum = (qa.astype(np.int16) + qb.astype(np.int16))  # EXACT int add, no overflow for bits<=15
    assert q_sum.dtype == np.int16
    max_possible = hi + hi
    min_possible = lo + lo
    assert q_sum.max() <= max_possible and q_sum.min() >= min_possible, "int16 accumulator overflow check"

    reduced = (q_sum.astype(np.float32) * scale[:, None]).reshape(-1)[:n]
    naive_sum = (a + b)

    # dequantized single-operand values (what each side's own quant error is)
    da = (qa.astype(np.float32) * scale[:, None]).reshape(-1)[:n]
    db = (qb.astype(np.float32) * scale[:, None]).reshape(-1)[:n]
    predicted_reduced = da + db  # if the int-add step is truly exact & lossless,
                                  # reduced must equal da+db EXACTLY (bit-for-bit
                                  # modulo the one float multiply/add, no extra rounding)

    drift = np.max(np.abs(reduced - predicted_reduced))
    err_vs_naive = rel_l2(naive_sum, reduced)
    err_vs_naive_singlequant = rel_l2(naive_sum, da)  # error if you'd only quantized ONE operand once

    print(f"  n={n} block={block} bits={bits}")
    print(f"  max|reduced - (dequant(qa)+dequant(qb))| = {drift:.3e}  <- must be ~0 (float64 rounding floor)")
    print(f"  rel_l2(reduced, fp32(a)+fp32(b))          = {err_vs_naive:.6f}")
    print(f"  rel_l2(single-operand-quant, fp32 a alone) baseline = {err_vs_naive_singlequant:.6f}")
    print(f"  VERDICT: {'EXACT (drift is float64-eps only)' if drift < 1e-3 else 'DRIFT DETECTED -- BUG'}")
    return drift, err_vs_naive


def test_exact_reduce_independent_scale(bits=6, n=8192, seed=0):
    """REALISTIC two-shot case: a and b are on DIFFERENT ranks with
    INDEPENDENT local per-block scales (as a real GPU all-reduce would
    actually compute them -- neither side sees the other's data before
    quantizing). Cannot int-add directly across mismatched scales; realistic
    kernel does dequant(peer) + local_fp_add. Reported for honesty -- this is
    NOT literally int+int, and the error is correspondingly a bit different
    (each operand independently quantized, no joint-block calibration)."""
    print(f"\n=== 2b. 'Exact-reduce', INDEPENDENT per-operand scales (realistic 2-shot), bits={bits} ===")
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(n).astype(np.float32)
    b = rng.standard_normal(n).astype(np.float32)

    ya = round_trip(a, bits)   # rank0 quantizes+sends a with ITS OWN scale
    yb = round_trip(b, bits)   # rank1 quantizes+sends b with ITS OWN scale

    # realistic protocol: receiver dequantizes peer, fp-adds to own local
    # full-precision copy (this is what the HIP two-shot kernel implements)
    reduced_at_rank_receiving_a_from_peer = b + ya   # rank1's view: own b (fp) + dequant(peer a)
    reduced_at_rank_receiving_b_from_peer = a + yb   # rank0's view: own a (fp) + dequant(peer b)
    naive_sum = a + b

    err0 = rel_l2(naive_sum, reduced_at_rank_receiving_b_from_peer)
    err1 = rel_l2(naive_sum, reduced_at_rank_receiving_a_from_peer)
    asym = rel_l2(reduced_at_rank_receiving_a_from_peer, reduced_at_rank_receiving_b_from_peer)
    print(f"  rel_l2(rank0 result, true sum) = {err0:.6f}")
    print(f"  rel_l2(rank1 result, true sum) = {err1:.6f}")
    print(f"  rel_l2(rank0 result, rank1 result) [cross-rank asymmetry] = {asym:.6f}")
    print("  NOTE: this is the REAL protocol shape (independent scales, dequant+fp-add);")
    print("        it is NOT literally int+int and the two ranks' views are not bit-identical.")
    return err0, err1, asym


if __name__ == "__main__":
    g_rows = test_gaussian()
    real_rows = test_real_tensor(
        os.environ.get("GGUF") or _need("GGUF", "an f16 GGUF file"), n_tensors=4)
    test_exact_reduce_shared_scale(bits=6)
    test_exact_reduce_shared_scale(bits=4)
    test_exact_reduce_shared_scale(bits=8)
    test_exact_reduce_independent_scale(bits=6)

    print("\n=== SUMMARY: bits vs mean rel_l2 (gaussian, all shapes/seeds) ===")
    import collections
    agg = collections.defaultdict(list)
    for r in g_rows:
        agg[r["bits"]].append(r["rel_l2"])
    for bits in sorted(agg):
        vals = agg[bits]
        print(f"  bits={bits}: mean rel_l2={np.mean(vals):.6f} max rel_l2={np.max(vals):.6f} "
              f"bytes/elem={bytes_per_element(bits):.3f} compression={16/  (bytes_per_element(bits)*8):.2f}x-vs-fp16")
