# MeshSmith report — a-low-poly-fox-figurine

**Prompt:** a low-poly fox figurine  
**Preset:** draft · **Seed:** 1234  
**Backend:** NVIDIA CUDA 12.4 · **GPU:** Quadro RTX 8000 (48.0 GB)

## Printability
- Score: **90/100** — ready to slice
- Watertight: True
- Model height as requested: 80.0 mm · laid on the bed it stands 41.4 mm tall
- Bounding box on bed (mm): [80.0, 82.6, 41.4] · Volume: 53.8 cm³
- Overhang area needing support: 18.9%
- Auto-orientation saved 9.3% support material (up vector (0.0, 1.0, 0.0))
- Wall thickness: min 1.08 mm, 5th percentile 4.99 mm, 0.1% of samples under limit

## Bed fit
- ✅ Prusa MK4 / most FDM (250x210x220)
- ✅ Bambu A1 mini (180x180x180)
- ❌ Resin 4K (130x80x160)

## Mesh cleanup
- Faces: 362496 generated → 362496 repaired → 29998 in the GLB / 150000 in the STL
- Watertight: True → True
- Floater components removed: 0

## Stage timings
| Stage | Time (s) | Peak VRAM (GB) |
|---|---:|---:|
| Text → image (SDXL-Turbo) | 53.61 | 7.48 |
| Background removal (u2net) | 5.12 | 6.58 |
| Image → 3D (Hunyuan3D draft) | 95.39 | 10.71 |
| Mesh cleanup & repair | 2.23 | 10.35 |
| Decimate + UV unwrap | 6.05 | 10.35 |
| Print analysis + orientation | 20.97 | 10.35 |
| Export GLB/STL/OBJ | 0.19 | 10.35 |
| **Total** | **183.56** | |