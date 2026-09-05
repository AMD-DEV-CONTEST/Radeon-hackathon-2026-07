import json, shutil, re, subprocess

def _rocm_line():
    """Return (vram_used_gib, vram_pct) from rocm-smi, or (None, None).

    NOTE: the Radeon AI PRO R9700 (RDNA4 / Navi 48, gfx1201) ships no GPU-busy
    counter in the kernel driver -- `rocm-smi` GPU-use% stays flat at 0/7 and
    `gpu_busy_percent` returns 'Operation not supported'. VRAM residency is the
    reliable live signal, so we read `--showmeminfo vram` (used) and
    `--showmemuse` (allocated %).
    """
    if not shutil.which("rocm-smi"):
        return None, None
    try:
        out = subprocess.run(["rocm-smi", "-u", "--showmeminfo", "vram"],
                             capture_output=True, text=True, timeout=5).stdout
        used_b = next((int(m.group(1)) for m in
                       re.finditer(r"VRAM Total Used Memory \(B\):\s*(\d+)", out)), 0)
        used_gib = used_b / (1024 ** 3)
    except Exception:
        used_gib = None
    pct = None
    try:
        mu = subprocess.run(["rocm-smi", "--showmemuse"],
                            capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"GPU Memory Allocated \(VRAM%\):\s*(\d+)", mu)
        pct = int(m.group(1)) if m else None
    except Exception:
        pass
    return used_gib, pct

d = json.load(open('/home/admin00/Projectos/MedGlass/benchmarks/cpu_vs_gpu.json'))
g = d.get("gpu", {})
print("MedGlass - GPU acceleration (ROCm)         ")
print("GPU: %s | %s GiB VRAM" % (g.get("name"), g.get("vram_gb")))
print("ROCM: %s" % g.get("rocm_version"))
vram_used, vram_pct = _rocm_line()
used_str = ("%.2f GiB" % vram_used) if vram_used else "?"
pct_str = ("%d%%" % vram_pct) if vram_pct is not None else "?"
print("VRAM now: " + used_str + " used (" + pct_str + " alloc.)  [GPU use% unavailable on Navi 48]")
print("-" * 62)
stages = d.get("stages", {})
for stage in ["whisper", "llm", "yolo", "ocr"]:
    pair = stages.get(stage)
    if not pair:
        continue
    cpu, gpu = pair.get("cpu", {}), pair.get("gpu", {})
    cs, gs = cpu.get("status"), gpu.get("status")
    if cs == "ok" and gs == "ok":
        c = cpu.get("wall_ms") or cpu.get("ms_per_frame")
        gg = gpu.get("wall_ms") or gpu.get("ms_per_frame")
        if c and gg:
            sp = c / gg
            print("  %-7s CPU %9.0f ms  -> GPU %9.0f ms   %4.1fx faster"
                  % (stage, c, gg, sp))
        else:
            print("  %-7s CPU %-4s     GPU %-4s" % (stage, cs, gs))
    else:
        why = str(gpu.get("reason", ""))[:34] if gs != "ok" else ""
        print("  %-7s CPU %s | GPU %s %s" % (stage, cs, gs, why))
print("-" * 62)
print("whisper.cpp (ROCm) + CLILLM (ggml, 100% layers)")
