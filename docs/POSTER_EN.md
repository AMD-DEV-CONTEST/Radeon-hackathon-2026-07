# 3DGenerateFlow Competition Poster

> Can be printed from browser or exported to PDF via `docs/generate_poster_pdf.py`.

---

## 3DGenerateFlow

### One Photo · One Sentence · Printable Full-Color 3D / 2.5D Model

**Track**: Multimodal AI Content Creation Tool Development  
**Deliverable**: Web UI  
**Platform**: AMD Radeon GPU + ROCm Open Software Stack

---

## Why This Project?

- 3D content creation has a high barrier: multi-view capture, modeling, stylization, and print checking are scattered across tools.
- Closed-source APIs are expensive and uncontrollable.
- There is a lack of end-to-end tools for "photo → 3D print."

**3DGenerateFlow = Photo + One Sentence + AMD GPU → Full-Color 3D Model / 2.5D Relief**

---

## Core Capabilities

| Feature | Description |
|---|---|
| **AI Director Agent** | One-sentence planning of style, parameters, and 6-step production flow |
| **Image-to-Image Stylization** | Stable Diffusion img2img, up to 1024px, ROCm local inference |
| **Multi-View Synthesis** | Zero123 generates front / right / back / left views |
| **Image-to-3D** | Hunyuan3D-2 / Hunyuan3D-2mv multi-view 3D generation |
| **2.5D Relief** | Depth Anything V2 + height map → colorful GLB + printable STL |
| **Texture Fallback** | Front-projection texturing when ROCm cannot compile CUDA extensions |
| **Print Check** | Real-time volume, bounding box, and watertight report |
| **Web UI Preview** | Embedded Three.js 3D viewer and download |

---

## System Architecture

```
Web UI (React + R3F)
    ↓
FastAPI + Celery (Eager Mode)
    ↓
┌─────────────┬──────────────┬─────────────┐
│  ROCm Adapter │ Hunyuan3D-2  │ 3D Director │
│  · SD img2img   │ · 2D → 3D    │ · Agent Plan│
│  · Zero123      │ · 2mv Multi-View│ · Memory/Chat│
│  · Depth V2     │ · Texture Fallback│            │
└─────────────┴──────────────┴─────────────┘
              ↓
        Print Check / Export (GLB / STL)
```

---

## Tech Stack

- **Frontend**: React 19 + TypeScript + Tailwind + Vite + R3F
- **Backend**: FastAPI + Celery + SQLAlchemy + SQLite
- **AI**: PyTorch 2.5.1 + ROCm 6.1 + Diffusers + Transformers
- **Models**: Stable Diffusion v1.5, Zero123-xl, Depth Anything V2, Hunyuan3D-2 / 2mv
- **Printing**: Trimesh mesh processing, UV texturing, volume / watertight check

---

## AMD ROCm Adaptation Highlights

- One-click scripts install ROCm environment + PyTorch for ROCm + Hunyuan3D-2.
- Core inference runs locally on AMD Radeon gfx1100 (48 GB VRAM).
- Fixed Hunyuan3D-2 `to()` returning `None` on ROCm.
- Automatic fallback to front-projection texturing when the texture module's CUDA extensions fail to compile.
- Celery memory backend, no Redis required for demo.

---

## Application Scenarios

- Pet / person 3D figures and mementos
- Fridge magnets, keychains, commemorative coins, relief medals
- Rapid 3D prototyping for products
- Education / makerspace AI + 3D printing teaching

---

## Demo Results

- **2.5D Relief**: 80×80×7 mm, watertight, 30 cm³ volume, colorful GLB + printable STL.
- **Full-Color 3D**: Multi-view input → 80 mm target height → colorful GLB with Web UI preview.
- **Diverse Styles**: Realistic, cartoon, low-poly, voxel, clay, sketch, lithophane, silhouette, and more.

---

## Open Source & Repository

- **GitHub**: `SuppartWang/3DGenerateFlow`
- **README**: ROCm startup guide, dependency list, Web UI instructions.
- **Docs**: `docs/PROJECT_INTRO_EN.md`, `docs/DEMO_SCRIPT.md`, `docs/POSTER_EN.md`

---

**3DGenerateFlow — Let everyone turn photos into printable 3D memories with AMD GPU.**
