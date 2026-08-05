# MeshSmith report — a-replacement-drawer-knob-fluted-cylinde

**Prompt:** a replacement drawer knob, fluted cylinder  
**Preset:** draft · **Seed:** 1234  
**Backend:** NVIDIA CUDA 12.4 · **GPU:** Quadro RTX 8000 (48.0 GB)

## Printability
- Score: **90/100** — ready to slice
- Watertight: True
- Model height as requested: 80.0 mm · laid on the bed it stands 80.0 mm tall
- Bounding box on bed (mm): [79.5, 79.1, 80.0] · Volume: 232.5 cm³
- Overhang area needing support: 10.4%
- Auto-orientation saved 13.7% support material (up vector (0.0, 0.0, -1.0))
- Wall thickness: min 1.3 mm, 5th percentile 2.9 mm, 0.0% of samples under limit

## Bed fit
- ✅ Prusa MK4 / most FDM (250x210x220)
- ✅ Bambu A1 mini (180x180x180)
- ✅ Resin 4K (130x80x160)

## Mesh cleanup
- Faces: 874776 generated → 874504 repaired → 30000 in the GLB / 149994 in the STL
- Watertight: False → True
- Floater components removed: 2

## Stage timings
| Stage | Time (s) | Peak VRAM (GB) |
|---|---:|---:|
| Text → image (SDXL-Turbo) | 46.45 | 7.48 |
| Background removal (u2net) | 5.10 | 6.58 |
| Image → 3D (Hunyuan3D draft) | 115.17 | 10.71 |
| Mesh cleanup & repair | 5.20 | 10.35 |
| Decimate + UV unwrap | 5.87 | 10.35 |
| Print analysis + orientation | 24.06 | 10.35 |
| Export GLB/STL/OBJ | 0.24 | 10.35 |
| **Total** | **202.10** | |