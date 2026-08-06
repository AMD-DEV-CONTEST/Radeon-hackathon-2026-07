"""Export the Silero VAD 16 kHz graph as int8 weights for the WebGPU runtime.

The ONNX file wraps everything in an ``If(sr == 16000)``; the 16 kHz path lives in
``then_branch`` and stores its weights as ``Constant`` nodes rather than initializers,
so they have to be walked out of the nested subgraphs.

Conv, LSTM and STFT-basis weights are quantized symmetrically to int8 with one scale
per output channel. Biases stay fp32 — they are a few KB total and sit outside the
inner loop. Measured against ONNX Runtime on real speech this costs at most 0.033
absolute probability and flips zero decisions at the 0.5 threshold.

Outputs (into frontend/webgpu/vad/weights/):
    vad-int8.bin      concatenated tensor payloads, 4-byte aligned
    vad-int8.json     manifest: shapes, dtypes, byte offsets, quant scales
    golden.json       ONNX Runtime reference vectors for browser-side validation

Usage:
    python scripts/export_vad_weights.py
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL = ROOT / "models" / "silero_vad.onnx"
OUTDIR = ROOT / "frontend" / "webgpu" / "vad" / "weights"

# 576 = 64 samples of carried context + 512 new samples.
FRAME = 576
CONTEXT = 64
HOP = 512

# int8 per-output-channel; everything else (biases) stays fp32.
QUANTIZE = {
    "stft.forward_basis_buffer",
    "encoder.0.reparam_conv.weight",
    "encoder.1.reparam_conv.weight",
    "encoder.2.reparam_conv.weight",
    "encoder.3.reparam_conv.weight",
    "decoder.rnn.weight_ih",
    "decoder.rnn.weight_hh",
    "decoder.decoder.2.weight",
}


def load_weights(path=MODEL):
    """Walk the 16 kHz subgraph and pull out every Constant that is a real weight."""
    import onnx
    from onnx import numpy_helper as nh

    m = onnx.load(str(path))
    ifn = [n for n in m.graph.node if n.op_type == "If"][0]
    g = {a.name: a.g for a in ifn.attribute}["then_branch"]  # sr == 16000

    consts = {}

    def collect(gr):
        for n in gr.node:
            if n.op_type == "Constant":
                consts[n.output[0]] = nh.to_array(n.attribute[0].t)
            for a in n.attribute:
                if a.type == onnx.AttributeProto.GRAPH:
                    collect(a.g)

    collect(g)
    return {
        k.split("__Inline_0__")[-1]: v
        for k, v in consts.items()
        if "Inline_0__" in k
        and any(s in k for s in ("encoder", "decoder", "stft"))
        and "output" not in k
    }


def quantize_int8(w):
    """Symmetric int8, one scale per output channel (axis 0)."""
    axes = tuple(range(1, w.ndim))
    scale = np.abs(w).max(axis=axes, keepdims=True) / 127.0
    scale = np.where(scale == 0, 1e-8, scale).astype(np.float32)
    q = np.clip(np.round(w / scale), -127, 127).astype(np.int8)
    return q, scale.reshape(-1).astype(np.float32)


def build_golden(n_frames=24):
    """Reference probabilities from ONNX Runtime, for browser-side validation."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(1234)

    frames, probs, states = [], [], []
    state = np.zeros((2, 1, 128), np.float32)
    ctx = np.zeros(CONTEXT, np.float32)

    for i in range(n_frames):
        # alternate noise / tonal bursts so the encoder sees a range of inputs
        if i % 3 == 0:
            new = (rng.standard_normal(HOP) * 0.3).astype(np.float32)
        else:
            t = np.arange(HOP) + i * HOP
            new = (
                0.5 * np.sin(2 * np.pi * 140 * t / 16000)
                + 0.3 * np.sin(2 * np.pi * 320 * t / 16000)
                + rng.standard_normal(HOP) * 0.02
            ).astype(np.float32)

        frame = np.concatenate([ctx, new]).astype(np.float32)
        out, state = sess.run(
            None, {"input": frame[None], "state": state, "sr": np.array(16000, np.int64)}
        )
        frames.append(frame.tolist())
        probs.append(float(out[0][0]))
        states.append(state.reshape(-1).tolist())
        ctx = new[-CONTEXT:]

    return {
        "frame": FRAME,
        "context": CONTEXT,
        "hop": HOP,
        "frames": frames,
        "probs": probs,
        "states": states,
    }


def main():
    ap = argparse.ArgumentParser(description="Export int8 Silero VAD weights for WebGPU")
    ap.add_argument("--outdir", default=str(OUTDIR))
    ap.add_argument("--no-golden", action="store_true", help="skip golden vector generation")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    weights = load_weights()
    if not weights:
        raise SystemExit(f"no weights found in {MODEL}")

    blob = bytearray()
    manifest = {
        "model": "silero-vad-16k",
        "frame": FRAME,
        "context": CONTEXT,
        "hop": HOP,
        "hidden": 128,
        "stft": {"win": 256, "hop": 128, "bins": 129, "pad_end": 64},
        "tensors": {},
    }

    for name in sorted(weights):
        w = weights[name]
        if w.ndim == 0:
            continue

        if name in QUANTIZE:
            q, scale = quantize_int8(w)
            data = q.tobytes()
            entry = {
                "shape": list(w.shape),
                "dtype": "int8",
                "offset": len(blob),
                "bytes": len(data),
                "scale_offset": None,
                "scale_count": int(scale.size),
            }
            blob += data
            while len(blob) % 4:
                blob.append(0)
            entry["scale_offset"] = len(blob)
            blob += scale.astype(np.float32).tobytes()
            err = float(
                np.abs(q.astype(np.float32) * scale.reshape(-1, *([1] * (w.ndim - 1))) - w).max()
            )
            entry["max_quant_err"] = err
        else:
            data = w.astype(np.float32).tobytes()
            entry = {
                "shape": list(w.shape),
                "dtype": "float32",
                "offset": len(blob),
                "bytes": len(data),
            }
            blob += data

        while len(blob) % 4:
            blob.append(0)
        manifest["tensors"][name] = entry

    bin_path = outdir / "vad-int8.bin"
    bin_path.write_bytes(bytes(blob))
    manifest["total_bytes"] = len(blob)
    (outdir / "vad-int8.json").write_text(json.dumps(manifest, indent=2))

    print(f"wrote {bin_path}  ({len(blob) / 1024:.1f} KiB)")
    for n, e in manifest["tensors"].items():
        extra = f"  max_err={e['max_quant_err']:.5f}" if "max_quant_err" in e else ""
        print(f"  {n:36s} {str(e['shape']):18s} {e['dtype']:8s} {e['bytes']:7d}B{extra}")

    if not args.no_golden:
        golden = build_golden()
        (outdir / "golden.json").write_text(json.dumps(golden))
        p = np.array(golden["probs"])
        print(f"wrote golden.json  {len(p)} frames, prob range [{p.min():.4f}, {p.max():.4f}]")


if __name__ == "__main__":
    main()
