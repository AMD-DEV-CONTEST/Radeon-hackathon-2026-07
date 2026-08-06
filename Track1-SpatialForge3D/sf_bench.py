"""
SpatialForge 3D - batch benchmark
Runs every image in a folder, records per-stage timings, writes gallery + tables.
All numbers measured. Nothing estimated.
"""
import os
import csv
import glob
import time
import argparse

import numpy as np
import torch
import rembg
from PIL import Image

from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground, to_gradio_3d_orientation

p = argparse.ArgumentParser()
p.add_argument("--input-dir", default="examples")
p.add_argument("--output-dir", default="/persistent/gallery")
p.add_argument("--resolution", type=int, default=256)
p.add_argument("--warmup", action="store_true", help="discard first run from stats")
args = p.parse_args()

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GPU_NAME = torch.cuda.get_device_name(0) if DEVICE == "cuda" else "CPU"
TOTAL_VRAM = torch.cuda.get_device_properties(0).total_memory / 1024**3 if DEVICE == "cuda" else 0

os.makedirs(args.output_dir, exist_ok=True)

print(f"Device: {DEVICE} | {GPU_NAME} | {TOTAL_VRAM:.1f} GB")

t0 = time.time()
model = TSR.from_pretrained(
    "stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt"
)
model.renderer.set_chunk_size(8192)
model.to(DEVICE)
load_ms = (time.time() - t0) * 1000
print(f"Model resident in {load_ms:.0f} ms")

rembg_session = rembg.new_session()


def sync():
    if DEVICE == "cuda":
        torch.cuda.synchronize()


def extract(scene_codes, resolution):
    try:
        return model.extract_mesh(scene_codes, has_vertex_color=True, resolution=resolution)
    except TypeError:
        return model.extract_mesh(scene_codes, resolution=resolution)


def run_one(path, resolution):
    if DEVICE == "cuda":
        torch.cuda.reset_peak_memory_stats()

    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    t = time.time()
    img = remove_background(img, rembg_session)
    img = resize_foreground(img, 0.85)
    a = np.array(img).astype(np.float32) / 255.0
    a = a[:, :, :3] * a[:, :, 3:4] + (1 - a[:, :, 3:4]) * 0.5
    img = Image.fromarray((a * 255.0).astype(np.uint8))
    sync()
    pre_ms = (time.time() - t) * 1000

    t = time.time()
    with torch.no_grad():
        codes = model([img], device=DEVICE)
    sync()
    inf_ms = (time.time() - t) * 1000

    t = time.time()
    meshes = extract(codes, resolution)
    mesh = to_gradio_3d_orientation(meshes[0])
    mesh_ms = (time.time() - t) * 1000

    name = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(args.output_dir, f"{name}.glb")
    t = time.time()
    mesh.export(out_path)
    exp_ms = (time.time() - t) * 1000

    peak = torch.cuda.max_memory_allocated() / 1024**3 if DEVICE == "cuda" else 0
    size_mb = os.path.getsize(out_path) / 1024**2

    return {
        "name": name,
        "pre_ms": round(pre_ms, 1),
        "inf_ms": round(inf_ms, 1),
        "mesh_ms": round(mesh_ms, 1),
        "exp_ms": round(exp_ms, 1),
        "total_ms": round(pre_ms + inf_ms + mesh_ms + exp_ms, 1),
        "verts": len(mesh.vertices),
        "faces": len(mesh.faces),
        "peak_vram_gb": round(peak, 2),
        "glb_mb": round(size_mb, 2),
    }


images = sorted(
    [f for ext in ("png", "jpg", "jpeg", "webp") for f in glob.glob(os.path.join(args.input_dir, f"*.{ext}"))]
)
if not images:
    raise SystemExit(f"No images found in {args.input_dir}")

print(f"Found {len(images)} images. Resolution grid {args.resolution}.\n")

if args.warmup:
    print("Warmup run (kernel compilation, discarded)...")
    run_one(images[0], args.resolution)
    print("Warmup done.\n")

rows = []
failed = []
for i, path in enumerate(images, 1):
    try:
        r = run_one(path, args.resolution)
        rows.append(r)
        print(
            f"[{i}/{len(images)}] {r['name']:<16} "
            f"inf {r['inf_ms']:>7.1f}ms  mesh {r['mesh_ms']:>7.1f}ms  "
            f"total {r['total_ms']:>7.1f}ms  {r['verts']:>7,}v  {r['peak_vram_gb']}GB"
        )
    except Exception as e:
        failed.append((os.path.basename(path), str(e)[:80]))
        print(f"[{i}/{len(images)}] {os.path.basename(path)} FAILED: {str(e)[:80]}")

if not rows:
    raise SystemExit("All runs failed.")

csv_path = os.path.join(args.output_dir, "benchmark.csv")
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)


def stats(key):
    v = [r[key] for r in rows]
    return min(v), sum(v) / len(v), max(v)


md = os.path.join(args.output_dir, "BENCHMARK.md")
with open(md, "w") as f:
    f.write("# SpatialForge 3D - Batch Benchmark\n\n")
    f.write(f"**Hardware:** {GPU_NAME} (gfx1100), {TOTAL_VRAM:.0f} GB VRAM\n\n")
    f.write(f"**Stack:** ROCm 7.2.1, PyTorch {torch.__version__}, TripoSR\n\n")
    f.write(f"**Config:** mesh grid {args.resolution}, foreground ratio 0.85, "
            f"background removal on\n\n")
    f.write(f"**Model load (one-time):** {load_ms:.0f} ms\n\n")
    f.write(f"**Assets generated:** {len(rows)}")
    if failed:
        f.write(f" ({len(failed)} failed)")
    f.write("\n\n## Per-asset results\n\n")
    f.write("| Asset | Preprocess | Inference (GPU) | Mesh (CPU) | Export | Total | Vertices | Peak VRAM |\n")
    f.write("|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        f.write(
            f"| {r['name']} | {r['pre_ms']:.0f} ms | **{r['inf_ms']:.0f} ms** | "
            f"{r['mesh_ms']:.0f} ms | {r['exp_ms']:.0f} ms | {r['total_ms']:.0f} ms | "
            f"{r['verts']:,} | {r['peak_vram_gb']} GB |\n"
        )
    lo, avg, hi = stats("total_ms")
    ilo, iavg, ihi = stats("inf_ms")
    _, vavg, vhi = stats("peak_vram_gb")
    f.write("\n## Summary\n\n")
    f.write(f"- End-to-end: min {lo:.0f} ms, mean {avg:.0f} ms, max {hi:.0f} ms\n")
    f.write(f"- GPU inference: min {ilo:.0f} ms, mean {iavg:.0f} ms, max {ihi:.0f} ms\n")
    f.write(f"- Peak VRAM: mean {vavg:.2f} GB, max {vhi:.2f} GB of {TOTAL_VRAM:.0f} GB "
            f"({vhi/TOTAL_VRAM*100:.1f}% utilization)\n")
    f.write(f"- Throughput: {1000/avg:.2f} assets/sec sustained\n")
    if failed:
        f.write("\n## Failures\n\n")
        for n, e in failed:
            f.write(f"- `{n}`: {e}\n")

lo, avg, hi = stats("total_ms")
ilo, iavg, ihi = stats("inf_ms")
print(f"\n{'='*60}")
print(f"{len(rows)} assets | mean E2E {avg:.0f} ms | mean inference {iavg:.0f} ms")
print(f"Gallery: {args.output_dir}")
print(f"Tables:  {md}")
print(f"         {csv_path}")
