"""
T188 scope addition (JM 2026-07-24): INT6 vs MXFP6 (E3M2) as a DECODE
WEIGHT-QUANT format, head-to-head on REAL weight tensors. CPU-only
(safetensors mmap read, no torch/GPU).

Distinct question from the all-reduce codec: weights are MULTIPLIED, never
reduced across ranks -> the int-domain exact-add advantage does NOT apply
here. This is pure dynamic-range/precision competition: int6 (fp16 scale,
linear/uniform code spacing) vs e3m2 (e8m0 scale, float/log-ish code
spacing, heavier tail headroom). INT4 included as the low anchor.
"""
import os, glob
import json
import mmap
import struct
import numpy as np
import ml_dtypes  # CPU-only dtype registration (bfloat16), no GPU/torch involved

from int6_codec import round_trip as int_round_trip
from mxfp6_codec import round_trip_mxfp6, bytes_per_element as mxfp6_bpe
from int6_codec import bytes_per_element as int_bpe


class RawSafetensorsFile:
    """Minimal CPU-only mmap safetensors reader that handles BF16 without
    requiring the `safetensors` numpy backend (which raises on bf16 -- 'data
    type bfloat16 not understood' -- since it hands raw numpy dtype strings
    to np.dtype()). Parses the format directly: 8-byte LE header length,
    JSON header {name: {dtype, shape, data_offsets}}, then a flat byte blob.
    """
    _DTYPE_MAP = {
        "BF16": ml_dtypes.bfloat16,
        "F16": np.float16,
        "F32": np.float32,
    }

    def __init__(self, path):
        self.path = path
        self._f = open(path, "rb")
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        (hdr_len,) = struct.unpack("<Q", self._mm[0:8])
        header = json.loads(self._mm[8:8 + hdr_len].decode("utf-8"))
        self._data_start = 8 + hdr_len
        self.header = {k: v for k, v in header.items() if k != "__metadata__"}

    def keys(self):
        return self.header.keys()

    def get_tensor(self, name):
        meta = self.header[name]
        dtype = self._DTYPE_MAP[meta["dtype"]]
        shape = meta["shape"]
        start, end = meta["data_offsets"]
        buf = self._mm[self._data_start + start: self._data_start + end]
        arr = np.frombuffer(buf, dtype=dtype).reshape(shape)
        return arr

    def close(self):
        self._mm.close()
        self._f.close()


def rel_l1(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    return np.sum(np.abs(b - a)) / (np.sum(np.abs(a)) + 1e-30)


def cosine_sim(a, b):
    a = a.astype(np.float64).ravel(); b = b.astype(np.float64).ravel()
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


MODEL_DIR = os.environ.get("MODEL_DIR", "")
if not MODEL_DIR:
    raise SystemExit("set MODEL_DIR to a BF16 HF model directory, e.g. "
                     "MODEL_DIR=/path/to/model python test_weight_quant.py")

TARGET_TENSORS = [
    # standard attention (layer 3 -- the hybrid model's full-attn layers)
    "model.language_model.layers.3.self_attn.q_proj.weight",
    "model.language_model.layers.3.self_attn.k_proj.weight",
    "model.language_model.layers.3.self_attn.v_proj.weight",
    "model.language_model.layers.3.self_attn.o_proj.weight",
    # MoE experts, layer 0 -- a couple of experts, gate/up/down
    "model.language_model.layers.0.mlp.experts.0.gate_proj.weight",
    "model.language_model.layers.0.mlp.experts.0.up_proj.weight",
    "model.language_model.layers.0.mlp.experts.0.down_proj.weight",
    "model.language_model.layers.0.mlp.experts.5.gate_proj.weight",
    "model.language_model.layers.0.mlp.experts.5.up_proj.weight",
    "model.language_model.layers.0.mlp.experts.5.down_proj.weight",
]


def find_tensor(name):
    for f in sorted(glob.glob(f"{MODEL_DIR}/model-*.safetensors")):
        rf = RawSafetensorsFile(f)
        if name in rf.header:
            t = rf.get_tensor(name)
            rf.close()
            return t
        rf.close()
    return None


def bf16_to_fp32(arr):
    return np.asarray(arr).astype(np.float32)


def main():
    print(f"=== INT6 vs MXFP6(E3M2) vs INT4: real weight tensors, {MODEL_DIR} ===")
    print(f"{'tensor':<62}{'shape':<16}{'INT4 relL1':>11}{'INT6 relL1':>11}{'MXFP6 relL1':>12}"
          f"{'INT4 cos':>10}{'INT6 cos':>10}{'MXFP6 cos':>11}")
    agg = {"int4": [], "int6": [], "mxfp6": []}
    rows = []
    for name in TARGET_TENSORS:
        t = find_tensor(name)
        if t is None:
            print(f"  [MISSING] {name}")
            continue
        x = bf16_to_fp32(t)
        flat = x.reshape(-1)

        y4 = int_round_trip(flat, 4)
        y6 = int_round_trip(flat, 6)
        ym6 = round_trip_mxfp6(flat)

        r4, r6, rm6 = rel_l1(flat, y4), rel_l1(flat, y6), rel_l1(flat, ym6)
        c4, c6, cm6 = cosine_sim(flat, y4), cosine_sim(flat, y6), cosine_sim(flat, ym6)

        agg["int4"].append(r4); agg["int6"].append(r6); agg["mxfp6"].append(rm6)
        rows.append(dict(name=name, shape=x.shape, r4=r4, r6=r6, rm6=rm6, c4=c4, c6=c6, cm6=cm6))
        print(f"{name:<62}{str(x.shape):<16}{r4:>11.5f}{r6:>11.5f}{rm6:>12.5f}"
              f"{c4:>10.6f}{c6:>10.6f}{cm6:>11.6f}")

    print(f"\nbytes/elem: INT4={int_bpe(4):.4f} INT6={int_bpe(6):.4f} MXFP6={mxfp6_bpe():.4f}")
    print("\n=== AGGREGATE (mean over tensors) ===")
    for k in ("int4", "int6", "mxfp6"):
        v = agg[k]
        print(f"  {k}: mean rel_L1={np.mean(v):.5f}  max rel_L1={np.max(v):.5f}  n_tensors={len(v)}")

    mean_int6 = np.mean(agg["int6"]); mean_mxfp6 = np.mean(agg["mxfp6"])
    delta_pct = 100.0 * (mean_int6 - mean_mxfp6) / mean_mxfp6
    print(f"\n=== VERDICT (MEASURED, numpy, real ornith-35B weights) ===")
    if mean_int6 < mean_mxfp6:
        print(f"  INT6 BEATS MXFP6 by {-delta_pct:.1f}% rel-L1 on these weight tensors.")
    else:
        print(f"  INT6 LOSES to MXFP6 by {delta_pct:.1f}% rel-L1 on these weight tensors "
              f"(INT6 mean={mean_int6:.5f} vs MXFP6 mean={mean_mxfp6:.5f}).")
    return rows


if __name__ == "__main__":
    main()
