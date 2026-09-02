"""
Patch TripoSG to run without `diso` (CUDA-only, no HIP path).
Replaces DiffDMC surface extraction with scikit-image marching cubes on CPU.
Idempotent: safe to run twice. Writes a .bak on first run.
"""
import re
import shutil
import sys

PATH = "triposg/inference_utils.py"

src = open(PATH).read()

if "SPATIALFORGE_ROCM_PATCH" in src:
    print("Already patched. Nothing to do.")
    sys.exit(0)

shutil.copy(PATH, PATH + ".bak")
lines = src.splitlines()

# 1) Guard the diso import so it never hard-fails on ROCm.
for i, ln in enumerate(lines):
    if re.match(r"\s*from diso import DiffDMC\s*$", ln):
        indent = ln[: len(ln) - len(ln.lstrip())]
        lines[i] = (
            f"{indent}# SPATIALFORGE_ROCM_PATCH: diso is CUDA-only, import made optional\n"
            f"{indent}try:\n"
            f"{indent}    from diso import DiffDMC\n"
            f"{indent}except Exception:\n"
            f"{indent}    DiffDMC = None\n"
            f"{indent}from skimage import measure as _sk_measure"
        )
        print(f"Patched import at line {i+1}")
        break
else:
    sys.exit("ERROR: could not find the diso import line.")

# 2) Replace the DiffDMC extraction block.
start = end = None
for i, ln in enumerate(lines):
    if "dmc = DiffDMC(" in ln:
        start = i
    if start is not None and "faces.detach().cpu().numpy()" in ln:
        end = i
        break

if start is None or end is None:
    sys.exit("ERROR: could not locate the DiffDMC extraction block.")

indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
block = [
    f"{indent}# SPATIALFORGE_ROCM_PATCH: CPU marching cubes, no CUDA kernels required",
    f"{indent}sdf = -grid_logits / octree_resolution",
    f"{indent}sdf_np = sdf.to(torch.float32).cpu().numpy()",
    f"{indent}sdf_np = np.nan_to_num(sdf_np, nan=1.0, posinf=1.0, neginf=-1.0)",
    f"{indent}vertices, faces, _, _ = _sk_measure.marching_cubes(sdf_np, level=0.0)",
    f"{indent}faces = faces[:, ::-1]",
]
print(f"Replacing lines {start+1}-{end+1} with CPU marching cubes")
lines[start : end + 1] = block

open(PATH, "w").write("\n".join(lines) + "\n")
print("Done. Original saved to", PATH + ".bak")
