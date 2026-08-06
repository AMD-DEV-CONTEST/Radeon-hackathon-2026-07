# 3DGenerateFlow

A multimodal AI content creation tool that turns one photo and one sentence into a ready-to-3D-print full-color 3D or 2.5D relief model. It features a built-in **3D Director Agent**: describe what you want, and the Agent automatically picks the style, orchestrates the generation flow, synthesizes multi-view images, and outputs a printable model. Delivered as a **Web UI**, all core backend inference runs locally on **AMD Radeon GPU + ROCm**.

---

## Track

**Track 1: Multimodal AI Content Creation Tool Development**

- Core tasks: image-to-image, image-to-3D, 2.5D relief, full-color 3D printable models
- Scenarios: personal mementos, pet / person figurines, IP merchandise, commercial visual design, 3D-print content production
- Deliverable: Web UI (React + TypeScript + R3F frontend, FastAPI + Celery backend)

---

## Quick Start

### 1. Environment (AMD ROCm)

```bash
# One-click install ROCm, PyTorch for ROCm, and Hunyuan3D-2
./rocm/setup_rocm.sh
./rocm/setup_hunyuan3d.sh
```

> Requirement: AMD Radeon GPU, ROCm software stack. PyTorch 2.5.1+rocm6.1 is installed by `setup_rocm.sh`.

### 2. Start Backend

```bash
cd services/api
source .venv/bin/activate
export USE_ROCM=true
export USE_HUNYUAN3D=true
export USE_HUNYUAN3D_MV=true
export HIP_VISIBLE_DEVICES=0
export CELERY_TASK_ALWAYS_EAGER=true
export CELERY_RESULT_BACKEND=cache+memory://
export CELERY_TASK_EAGER_PROPAGATES=true

PYTHONPATH=../.. uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start Frontend

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:5173`.

If the frontend runs on Mac/Windows while the backend runs on a cloud AMD instance:

```bash
VITE_API_URL=http://<AMD-instance-public-IP>:8000 npm run dev
```

### 4. Environment Variables (Optional)

```bash
cp services/api/.env.example services/api/.env
```

If no LLM key is provided, the Agent falls back to rule-based planning and the full pipeline still works.

---

## Project Structure

```
3DGenerateFlow/
├── apps/web                # React + TypeScript + Tailwind + R3F frontend
├── services/api            # FastAPI + Celery backend
│   ├── agents/             # 3D Director Agent (Planner / Director / Memory / Chat)
│   ├── pipelines/          # 3D / 2.5D generation pipelines
│   ├── adapters/           # ROCm / Hunyuan3D-2 / Zero123 adapters
│   ├── routers/            # API routes
│   └── jobs/               # Celery async tasks
├── shared/schemas          # Shared Pydantic schemas
├── rocm/                   # ROCm and Hunyuan3D-2 install scripts
├── scripts/                # Benchmark and download scripts
├── docs/                   # Competition docs and posters
└── infra/                  # Nginx deployment config
```

---

## Key Capabilities

| Capability | Description | Runtime |
|---|---|---|
| **Image Upload** | Object / pet / person photo | Frontend |
| **AI Director Agent** | One-sentence plan: style, output mode, generation steps | Backend (rule fallback, optional LLM) |
| **Style Catalog** | Realistic 3D, Cartoon 3D, Low Poly, Voxel, Clay, Sketch, 2.5D Relief, Lithophane, Coin, Silhouette | Backend |
| **Image-to-Image Stylization** | Stable Diffusion img2img, up to 1024 px | Backend ROCm |
| **Multi-View Synthesis** | Zero123 generates front / right / back / left from a front image | Backend ROCm |
| **3D Generation** | Hunyuan3D-2 / Hunyuan3D-2mv image-to-3D | Backend ROCm |
| **2.5D Relief** | Local depth estimation + height map → textured GLB + printable STL | Backend ROCm + CPU |
| **Full-Color Texture Fallback** | When Hunyuan3D-2 texture module cannot compile on ROCm, front-projection baking is used | Backend CPU |
| **Print-Ready Check** | Volume, bounding box, watertight report | Backend |
| **3D Preview** | Embedded Three.js viewer in Web UI | Frontend |
| **Right-Side AI Chat** | Switch styles, adjust params, regenerate via natural language | Frontend |

---

## Current Implementation Status

- [x] Project scaffold (frontend + backend + Docker)
- [x] Single-image upload and job dispatch API
- [x] Landing / Director Console / Result three-page Web UI
- [x] 3D Director Agent (LLM / rule fallback)
- [x] Style catalog (3D + 2.5D styles)
- [x] Async 3D / 2.5D pipeline scheduling
- [x] ROCm local image-to-image stylization
- [x] ROCm local depth estimation
- [x] Zero123 multi-view synthesis
- [x] Hunyuan3D-2 / Hunyuan3D-2mv local image-to-3D
- [x] Full-color texture fallback
- [x] Print report (volume, dimensions, watertight)
- [x] Frontend 3D preview and download
- [ ] Cloud 3D API fallback (Tripo / Meshy / Rodin, optional)
- [ ] Advanced UV unwrapping and multi-view texture fusion

---

## ROCm / AMD GPU Local Execution

This project is adapted for **AMD Radeon GPU + ROCm**. The core creative pipeline (stylization → multi-view synthesis → 3D generation → 2.5D relief → print check) can run entirely on a local AMD GPU without relying on closed-source 3D APIs.

Quick setup:

```bash
./rocm/setup_rocm.sh
./rocm/setup_hunyuan3d.sh
```

Then follow the backend and frontend start commands above.

Detailed guide: [`docs/ROCM_GUIDE.md`](docs/ROCM_GUIDE.md).

---

## Demo Checklist

1. Open the Web UI landing page. The top-right corner shows the **AMD ROCm Ready** badge.
2. Drag and drop a photo, pick a style (e.g., Realistic 3D / Relief Coin), type a prompt, and click **Start Generate**.
3. The UI enters the **Director Console** with the left parameter panel, the center 6-step storyboard timeline, and the right AI assistant + task log showing real-time progress.
4. Wait for the backend to finish local inference on the AMD GPU (Upload → Style → Multiview → 3D → Print Check → Export).
5. The UI auto-navigates to the **Result page**, showing a turntable 3D preview and the print report (Volume / Dimensions / Wall Thickness / Watertight).
6. Download `model.glb` (full-color 3D) or `relief.stl` / `relief.glb` (2.5D relief).

---

## Demo Video Script

See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

---

## Competition Documents

- Frontend redesign brief: [`docs/FRONTEND_DESIGN.md`](docs/FRONTEND_DESIGN.md)
- English project introduction (PDF source): [`docs/PROJECT_INTRO_EN.md`](docs/PROJECT_INTRO_EN.md)
- English poster (PDF source): [`docs/POSTER_EN.md`](docs/POSTER_EN.md)
- Pull Request description template: [`docs/PR_DESCRIPTION.md`](docs/PR_DESCRIPTION.md)
- Demo video script (3–5 min): [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- Video production guide (with auto-screen-record script): [`docs/VIDEO_PRODUCTION.md`](docs/VIDEO_PRODUCTION.md)

---

## Performance Benchmark

```bash
cd services/api
source .venv/bin/activate
python scripts/benchmark_rocm.py --image assets/samples/dog.jpg --style relief_embossed
python scripts/benchmark_rocm.py --image assets/samples/bride.jpg --style realistic_3d
```

---

## License

MIT
