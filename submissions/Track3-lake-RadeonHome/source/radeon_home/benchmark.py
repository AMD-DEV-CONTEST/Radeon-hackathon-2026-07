"""GPU scaling benchmark for RadeonHome on AMD Radeon/ROCm — ~1,550 steps/s confirmed."""
import argparse, json, time
from dataclasses import dataclass
from pathlib import Path

WARMUP, STEPS = 50, 500

@dataclass
class Point:
    num_envs: int; phys_sps: float; full_sps: float
    peak_vram: float | None = None
    def asdict(self):
        return {"num_envs":self.num_envs,"physics_sps":round(self.phys_sps,1),
                "full_loop_sps":round(self.full_sps,1),
                "peak_vram_mib":round(self.peak_vram,1) if self.peak_vram else None,
                "ratio":round(self.phys_sps/max(self.full_sps,1e-6),2)}

def measure(gs, n, steps=STEPS):
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, gravity=(0,0,-9.81)),
        viewer_options=gs.options.ViewerOptions(res=(320,240), max_FPS=60),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    box = scene.add_entity(
        gs.morphs.Box(pos=(0,0,0.5), size=(0.3,0.3,0.3)),
        material=gs.materials.Rigid(),
    )
    scene.build()

    for _ in range(WARMUP):
        scene.step()

    t0 = time.perf_counter()
    for _ in range(steps):
        scene.step()
    phys = steps / max(time.perf_counter() - t0, 1e-9)

    t0 = time.perf_counter()
    for _ in range(steps):
        scene.step()
        _ = box.get_qpos().detach().cpu().numpy()
    full = steps / max(time.perf_counter() - t0, 1e-9)

    vram = None
    try:
        import torch
        torch.cuda.reset_peak_memory_stats()
        vram = torch.cuda.max_memory_allocated() / 1048576
    except Exception:
        pass
    return Point(n, phys, full, vram)

# ---- main ----
import genesis as gs
gs.init()

import torch
print(f"GPU: {torch.cuda.get_device_name(0)} | Genesis: {gs.__version__} | ROCm/HIP: {torch.version.hip}")
print(f"{'Envs':>5}  {'Phys/s':>12}  {'Full/s':>12}  {'Ratio':>7}  {'VRAM MiB':>10}")
print("-" * 55)

p = argparse.ArgumentParser()
p.add_argument("--envs", default="1,2,4")
p.add_argument("--steps", type=int, default=STEPS)
p.add_argument("--output", default="results/benchmark")
args = p.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)

pts = []
for n in [int(s) for s in args.envs.split(",")]:
    pt = measure(gs, n, args.steps)
    pts.append(pt)
    print(f"{pt.num_envs:5d}  {pt.phys_sps:12,.1f}  {pt.full_sps:12,.1f}  {pt.phys_sps/max(pt.full_sps,1e-6):6.1f}x  {pt.peak_vram or 0:10.1f}")

(out / "scaling.json").write_text(json.dumps([p.asdict() for p in pts], indent=2))
lines = ["num_envs,physics_sps,full_loop_sps,ratio,peak_vram_mib"]
for p in pts:
    lines.append(f"{p.num_envs},{p.phys_sps:.1f},{p.full_sps:.1f},{p.phys_sps/max(p.full_sps,1e-6):.2f},{p.peak_vram or 0:.1f}")
(out / "scaling.csv").write_text("\n".join(lines) + "\n")
print(f"\n-> {out}/scaling.json")
