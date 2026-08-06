"""Export the Whisper-tiny **encoder** as float16 weights for the WebGPU runtime.

Unlike ``export_vad_weights.py``, this does **not** quantize. The checkpoint OpenAI
ships is already float16, so storing float16 is bit-exact — the browser reproduces the
reference model rather than an approximation of it, and validation needs no
quantization budget at all.

int8 was measured first and rejected. Symmetric per-output-channel int8 halves the
download to 7.3 MiB but costs max|d| 11.0 on encoder hidden states whose range is
+/-19, and flips one of 64 argmax channels. Nearly all of that comes from one group:
quantizing only ``attn.out.weight`` accounts for 6.6 of the 11.0. Weight matrices go
to float16 and everything else (biases, LayerNorm gain and shift) stays float32,
because those are ~50 KB in total and sit outside the inner loop.

Two things are deliberately *not* shipped in the blob:

* **Positional embeddings.** They are sinusoids of the position index — a closed form,
  not learned data. Shipping the 1500x384 table would cost 2.3 MB, more than a quarter
  of the whole download, to store something the client can compute in a loop. The
  export verifies the formula reproduces the checkpoint's buffer before omitting it.
* **The mel filterbank**, for the same reason it is downloaded rather than derived:
  it is 80x201 of mostly zeros and compresses to a sparse triplet list.

Outputs (into frontend/webgpu/whisper/weights/):
    whisper-f16.bin     concatenated tensor payloads, 4-byte aligned
    whisper-f16.json    manifest: shapes, dtypes, byte offsets
    golden.json         reference activations for browser-side validation

Golden vectors run a **truncated context** (``--ctx``, default 64 of the model's 1500
positions). The reference truncates identically — it slices the positional embedding
and runs attention over the shorter sequence — so the comparison is exact rather than
approximate. A full 30 s context would make golden.json ~24x larger while exercising
precisely the same kernels.

Usage:
    python scripts/download_whisper_model.py
    python scripts/export_whisper_weights.py
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHECKPOINT = ROOT / "models" / "whisper-tiny.pt"
MEL_FILTERS = ROOT / "models" / "whisper_mel_filters.npz"
OUTDIR = ROOT / "frontend" / "webgpu" / "whisper" / "weights"

# Whisper's fixed audio frontend. Not configurable — the weights assume them.
SAMPLE_RATE = 16000
N_FFT = 400
HOP_LENGTH = 160
N_MELS = 80

# Half of one ulp at 1.0 in float16 — the resolution of the stored positional table.
FP16_EPS = 2.0**-11

# The matrices, which are 99.4% of the payload and the only tensors inside a MAC loop.
# LayerNorm gain/shift and every bias stay float32: narrowing them saves ~25 KB.
HALF_SUFFIXES = (
    "conv1.weight",
    "conv2.weight",
    "attn.query.weight",
    "attn.key.weight",
    "attn.value.weight",
    "attn.out.weight",
    "mlp.0.weight",
    "mlp.2.weight",
)


def sinusoids(length, channels, max_timescale=10000):
    """Whisper's positional embedding, as a formula. Mirrors `whisper.model.sinusoids`."""
    log_increment = np.log(max_timescale) / (channels // 2 - 1)
    inv_timescales = np.exp(-log_increment * np.arange(channels // 2, dtype=np.float64))
    scaled = np.arange(length, dtype=np.float64)[:, None] * inv_timescales[None, :]
    return np.concatenate([np.sin(scaled), np.cos(scaled)], axis=1).astype(np.float32)


def load_state_dict(path=CHECKPOINT):
    """Encoder tensors as float32.

    The checkpoint ships float16. Widening once here keeps the reference pass in f32
    rather than half precision, so golden.json carries no rounding noise the WebGPU
    path would have to reproduce. Narrowing the matrices back on the way out is
    therefore a round trip, not a loss — see `add`.
    """
    import torch

    if not path.exists():
        raise SystemExit(f"{path} not found — run scripts/download_whisper_model.py first")
    ck = torch.load(str(path), map_location="cpu")
    sd = {k: v.float() for k, v in ck["model_state_dict"].items() if k.startswith("encoder.")}
    return ck["dims"], sd


def log_mel(audio, filters):
    """Whisper's log-mel frontend, in numpy so the WGSL port has a line-by-line reference.

    `torch.stft(center=True)` reflect-pads N_FFT//2 on both sides; whisper then drops
    the final frame. The normalization is global: the 8 dB floor is relative to the
    loudest bin in the whole clip, not per frame.
    """
    pad = N_FFT // 2
    padded = np.pad(audio, (pad, pad), mode="reflect")
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float64)  # periodic, == torch.hann_window

    n_frames = 1 + (len(padded) - N_FFT) // HOP_LENGTH
    frames = np.stack(
        [padded[i * HOP_LENGTH : i * HOP_LENGTH + N_FFT] * window for i in range(n_frames)]
    )
    spec = np.fft.rfft(frames, axis=-1)  # (frames, 201)
    magnitudes = (np.abs(spec) ** 2)[:-1].T  # drop last frame -> (201, frames)

    mel = filters @ magnitudes
    log_spec = np.log10(np.clip(mel, 1e-10, None))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)


def reference_encoder(sd, dims, mel, n_ctx, positional):
    """Whisper-tiny encoder forward pass in torch, on a truncated context.

    `positional` is passed in rather than read from the checkpoint so the reference
    adds exactly the values the browser computes — see the note in `main`.

    Returns the final hidden states plus a couple of intermediates, so a validation
    failure points at a stage instead of just "the encoder is wrong".
    """
    import torch
    import torch.nn.functional as F

    d = dims["n_audio_state"]
    heads = dims["n_audio_head"]
    x = torch.from_numpy(mel)[None]  # (1, 80, 2*n_ctx)

    x = F.gelu(F.conv1d(x, sd["encoder.conv1.weight"], sd["encoder.conv1.bias"], padding=1))
    x = F.gelu(
        F.conv1d(x, sd["encoder.conv2.weight"], sd["encoder.conv2.bias"], stride=2, padding=1)
    )
    x = x.permute(0, 2, 1)  # (1, n_ctx, d)
    assert x.shape[1] == n_ctx, f"expected {n_ctx} positions, got {x.shape[1]}"

    post_conv = x.clone()
    x = x + torch.from_numpy(positional[:n_ctx])
    stages = {}

    def ln(t, prefix):
        return F.layer_norm(t, (d,), sd[f"{prefix}.weight"], sd[f"{prefix}.bias"], eps=1e-5)

    for b in range(dims["n_audio_layer"]):
        p = f"encoder.blocks.{b}"
        h = ln(x, f"{p}.attn_ln")

        q = F.linear(h, sd[f"{p}.attn.query.weight"], sd[f"{p}.attn.query.bias"])
        k = F.linear(h, sd[f"{p}.attn.key.weight"])  # no bias, by design
        v = F.linear(h, sd[f"{p}.attn.value.weight"], sd[f"{p}.attn.value.bias"])

        # scale**2 == 1/sqrt(head_dim); whisper splits it across q and k so the
        # products stay in range in fp16. Kept identical here for bit-comparability.
        scale = (d // heads) ** -0.25
        shape = (1, -1, heads, d // heads)
        q = q.view(*shape).permute(0, 2, 1, 3) * scale
        k = k.view(*shape).permute(0, 2, 1, 3) * scale
        v = v.view(*shape).permute(0, 2, 1, 3)

        w = torch.softmax(q @ k.transpose(-1, -2), dim=-1)
        attn = (w @ v).permute(0, 2, 1, 3).flatten(start_dim=2)
        x = x + F.linear(attn, sd[f"{p}.attn.out.weight"], sd[f"{p}.attn.out.bias"])

        h = ln(x, f"{p}.mlp_ln")
        h = F.gelu(F.linear(h, sd[f"{p}.mlp.0.weight"], sd[f"{p}.mlp.0.bias"]))
        x = x + F.linear(h, sd[f"{p}.mlp.2.weight"], sd[f"{p}.mlp.2.bias"])
        stages[f"block{b}"] = x.clone()

    out = ln(x, "encoder.ln_post")
    return post_conv, stages, out


def make_audio(seconds, seed=1234):
    """Synthetic speech-ish audio: alternating tonal bursts and noise.

    Real speech would be better but cannot be committed; what matters for kernel
    validation is that every stage sees a non-degenerate range of magnitudes.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    audio = np.zeros(n, dtype=np.float64)

    for start in range(0, n, SAMPLE_RATE // 4):
        end = min(start + SAMPLE_RATE // 5, n)
        f0 = rng.uniform(90, 220)
        seg = t[start:end]
        audio[start:end] = (
            0.5 * np.sin(2 * np.pi * f0 * seg)
            + 0.25 * np.sin(2 * np.pi * 2 * f0 * seg)
            + 0.12 * np.sin(2 * np.pi * 3 * f0 * seg)
        )
    audio += rng.standard_normal(n) * 0.01
    return audio.astype(np.float32)


def build_golden(sd, dims, n_ctx, positional, clips=2):
    """Reference activations for a couple of fixture clips."""
    with np.load(MEL_FILTERS) as z:
        filters = z["mel_80"].astype(np.float64)

    mel_frames = 2 * n_ctx
    n_samples = mel_frames * HOP_LENGTH

    entries = []
    for c in range(clips):
        audio = make_audio(n_samples / SAMPLE_RATE, seed=1234 + c)[:n_samples]
        mel = log_mel(audio.astype(np.float64), filters)[:, :mel_frames]
        post_conv, stages, out = reference_encoder(sd, dims, mel, n_ctx, positional)

        # Audio is the only input; everything else is a checkpoint the GPU has to hit.
        # `mel` and `post_conv` are kept because a mismatch in the final hidden states
        # alone cannot tell a broken frontend from a broken transformer block.
        entries.append(
            {
                "audio": [round(float(v), 6) for v in audio],
                "mel": [round(float(v), 5) for v in mel.reshape(-1)],
                "post_conv": [round(float(v), 5) for v in post_conv.numpy().reshape(-1)],
                "hidden": [round(float(v), 5) for v in out.numpy().reshape(-1)],
                # Which channel dominates each position. A numeric drift small enough
                # to pass an MSE budget but large enough to reorder channels shows up
                # here and nowhere else.
                "argmax": [int(i) for i in out.numpy()[0].argmax(axis=-1)],
            }
        )

    return {
        "n_ctx": n_ctx,
        "n_mels": N_MELS,
        "mel_frames": mel_frames,
        "n_samples": n_samples,
        "n_state": dims["n_audio_state"],
        "sample_rate": SAMPLE_RATE,
        "n_fft": N_FFT,
        "hop_length": HOP_LENGTH,
        "clips": entries,
    }


def sparse_mel_filters():
    """The filterbank as (bin, weight) runs — each mel row is a short triangle."""
    with np.load(MEL_FILTERS) as z:
        f = z["mel_80"].astype(np.float32)
    starts, lengths, values = [], [], []
    for row in f:
        nz = np.nonzero(row)[0]
        if len(nz) == 0:
            starts.append(0)
            lengths.append(0)
            continue
        lo, hi = int(nz[0]), int(nz[-1]) + 1
        starts.append(lo)
        lengths.append(hi - lo)
        values.append(row[lo:hi])
    return np.array(starts, np.int32), np.array(lengths, np.int32), np.concatenate(values)


def main():
    ap = argparse.ArgumentParser(description="Export float16 Whisper-tiny encoder weights")
    ap.add_argument("--outdir", default=str(OUTDIR))
    ap.add_argument(
        "--ctx",
        type=int,
        default=64,
        help="encoder positions used for golden vectors (default 64 of 1500)",
    )
    ap.add_argument("--no-golden", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    dims, sd = load_state_dict()

    # The positional table is sinusoidal. Confirm the formula before dropping 2.2 MiB
    # of it from the download — a mismatch here would silently skew every block.
    #
    # The tolerance is fp16 resolution, not fp32: the checkpoint stores the table as
    # float16, so the largest entries (|v| <= 1) are quantized to a 2^-12 grid. The
    # formula is the *more* accurate of the two; agreement to fp16 is all that can be
    # asked of it. The reference encoder below then adds the computed values rather
    # than the stored ones, so golden.json describes what the browser will compute.
    pos_ref = sd["encoder.positional_embedding"].numpy().astype(np.float32)
    positional = sinusoids(*pos_ref.shape)
    pos_err = float(np.abs(positional - pos_ref).max())
    if pos_err > FP16_EPS:
        raise SystemExit(
            f"positional embedding formula disagrees with the checkpoint by {pos_err:.2e}, "
            f"more than fp16 resolution ({FP16_EPS:.2e}); ship the table instead"
        )

    blob = bytearray()
    manifest = {
        "model": "whisper-tiny-encoder",
        "n_mels": N_MELS,
        "n_audio_ctx": dims["n_audio_ctx"],
        "n_state": dims["n_audio_state"],
        "n_head": dims["n_audio_head"],
        "n_layer": dims["n_audio_layer"],
        "n_fft": N_FFT,
        "hop_length": HOP_LENGTH,
        "sample_rate": SAMPLE_RATE,
        "positional": {"kind": "sinusoid", "max_timescale": 10000, "max_err": pos_err},
        "tensors": {},
    }

    def add(name, array, half):
        """Append one tensor. `half` picks float16 storage over float32.

        Every payload is padded to 4 bytes because the shaders read the blob as
        `array<u32>` — two halves per word, unpacked with `unpack2x16float`.
        """
        nonlocal blob
        if half:
            narrowed = array.astype(np.float16)
            if narrowed.size % 2:
                raise SystemExit(f"{name}: odd element count {narrowed.size}, cannot pair into u32")
            entry = {
                "shape": list(array.shape),
                "dtype": "float16",
                "offset": len(blob),
                "bytes": narrowed.nbytes,
                # Zero for every tensor here: the checkpoint is natively float16, so
                # this is a round trip. Recorded anyway so a future checkpoint that
                # ships float32 cannot silently start losing precision.
                "max_half_err": float(np.abs(narrowed.astype(np.float32) - array).max()),
            }
            blob += narrowed.tobytes()
        else:
            widened = array.astype(np.float32)
            entry = {
                "shape": list(array.shape),
                "dtype": "float32",
                "offset": len(blob),
                "bytes": widened.nbytes,
            }
            blob += widened.tobytes()
        while len(blob) % 4:
            blob.append(0)
        manifest["tensors"][name] = entry

    for name in sorted(sd):
        if name == "encoder.positional_embedding":
            continue  # computed from the formula, verified above
        w = sd[name].numpy().astype(np.float32)
        add(name, w, half=name.endswith(HALF_SUFFIXES))

    starts, lengths, values = sparse_mel_filters()
    add("mel_filters.start", starts.astype(np.float32), half=False)
    add("mel_filters.length", lengths.astype(np.float32), half=False)
    add("mel_filters.value", values, half=False)
    manifest["mel_filters"] = {"rows": N_MELS, "bins": N_FFT // 2 + 1, "nnz": int(values.size)}

    # The STFT basis is omitted for the same reason as the positional table: it is
    # `cos/sin(2*pi*f*n/N) * hann(n)`, a formula, and shipping it would add 0.6 MiB.
    # The client materializes it once at load time — see whisper-webgpu.js. It is not
    # recomputed per frame, which would put a transcendental inside every MAC.
    manifest["stft"] = {
        "n_fft": N_FFT,
        "hop": HOP_LENGTH,
        "bins": N_FFT // 2 + 1,
        "window": "hann-periodic",
    }

    bin_path = outdir / "whisper-f16.bin"
    bin_path.write_bytes(bytes(blob))
    manifest["total_bytes"] = len(blob)
    (outdir / "whisper-f16.json").write_text(json.dumps(manifest, indent=2))

    print(f"wrote {bin_path}  ({len(blob) / 1024 / 1024:.2f} MiB)")
    worst = max(
        (e["max_half_err"], n) for n, e in manifest["tensors"].items() if "max_half_err" in e
    )
    saved = pos_ref.size * 4 / 1024 / 1024
    print(f"  positional embedding vs fp16 table: {pos_err:.2e} (omitted, saved {saved:.1f} MiB)")
    print(f"  worst float16 storage error: {worst[0]:.2e} ({worst[1]})")

    if not args.no_golden:
        golden = build_golden(sd, dims, args.ctx, positional)
        (outdir / "golden.json").write_text(json.dumps(golden))
        h = np.array(golden["clips"][0]["hidden"])
        size = (outdir / "golden.json").stat().st_size
        print(
            f"wrote golden.json  {len(golden['clips'])} clips x {args.ctx} positions, "
            f"{size / 1024:.0f} KiB, hidden range [{h.min():.3f}, {h.max():.3f}]"
        )


if __name__ == "__main__":
    main()
