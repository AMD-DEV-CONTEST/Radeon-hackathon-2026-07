# MeshSmith report — a-greek-amphora-vase-with-two-handles

**Prompt:** a Greek amphora vase with two handles  
**Preset:** draft · **Seed:** 1234  
**Backend:** NVIDIA CUDA 12.4 · **GPU:** Quadro RTX 8000 (48.0 GB)

## Printability
- Score: **90/100** — ready to slice
- Watertight: True
- Model height as requested: 80.0 mm · laid on the bed it stands 80.0 mm tall
- Bounding box on bed (mm): [75.6, 67.9, 80.0] · Volume: 30.0 cm³
- Overhang area needing support: 11.3%
- Auto-orientation saved 4.5% support material (up vector (0.0, 0.0, -1.0))
- Wall thickness: min 1.39 mm, 5th percentile 1.44 mm, 0.0% of samples under limit

## Bed fit
- ✅ Prusa MK4 / most FDM (250x210x220)
- ✅ Bambu A1 mini (180x180x180)
- ✅ Resin 4K (130x80x160)

## Mesh cleanup
- Faces: 977924 generated → 977910 repaired → 29998 in the GLB / 149998 in the STL
- Watertight: False → True
- Floater components removed: 0

## Stage timings
| Stage | Time (s) | Peak VRAM (GB) |
|---|---:|---:|
| Text → image (SDXL-Turbo) | 45.75 | 7.48 |
| Background removal (u2net) | 4.72 | 6.58 |
| Image → 3D (Hunyuan3D draft) | 67.41 | 10.71 |
| Mesh cleanup & repair | 5.40 | 10.35 |
| Decimate + UV unwrap | 6.00 | 10.35 |
| Print analysis + orientation | 18.79 | 10.35 |
| Export GLB/STL/OBJ | 0.21 | 10.35 |
| **Total** | **148.29** | |