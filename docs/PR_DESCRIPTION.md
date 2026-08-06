# Pull Request Description

## Summary

This PR delivers the competition-ready version of **3DGenerateFlow**, a lightweight, high-performance AI multimodal content creation tool that runs entirely on **AMD Radeon GPU / ROCm**. It turns a single photo plus a text prompt into a ready-to-print 2.5D relief or full-color 3D model through a web UI and a 3D Director Agent.

## What’s New

- **3D Director Agent** (`services/api/agents/`): automatically plans the pipeline from reference analysis, style transfer, multi-view generation, 3D reconstruction, mesh post-processing, and printable export.
- **Multi-view generation** with Zero123 / Stable Diffusion on ROCm, feeding into Hunyuan3D-2mv for more coherent 3D shapes.
- **Texture fallback** for Hunyuan3D-2’s CUDA-only texture module: the reference image is projected and baked onto the GLB so the output is still colorful on ROCm.
- **Real print metrics** computed via trimesh (volume, watertight check, dimensions).
- **Web UI** with lazy-canvas workflow, GLB preview, download, and AMD ROCm status badge.
- **Competition deliverables**: README, project intro, demo script, poster, and video production guide.

## How to Test

1. Start the backend on an AMD ROCm instance:
   ```bash
   cd services/api
   source .venv/bin/activate
   export USE_ROCM=true USE_HUNYUAN3D=true HIP_VISIBLE_DEVICES=0
   CELERY_TASK_ALWAYS_EAGER=true \
   CELERY_RESULT_BACKEND=cache+memory:// \
   CELERY_TASK_EAGER_PROPAGATES=true \
   PYTHONPATH=../.. uvicorn main:app --host 0.0.0.0 --port 8000
   ```
2. Start the frontend:
   ```bash
   cd apps/web
   npm install && npm run dev
   ```
3. Open `http://<amd-instance>:5173/` (or the served URL).
4. Upload a photo, type a prompt such as **“realistic 3D full-body bride”** or **“2.5D relief coin, skateboard dog”**, click **Plan Style**, then **Generate Model**.
5. Verify the job finishes with `status: completed`, download `model.glb` / `relief.stl`, and check the print report.

## Evidence of AMD Radeon / ROCm Execution

- `amd-smi static` shows an AMD Radeon GPU with 48 GB VRAM and `gfx1100` target.
- `/health/gpu` returns `rocm_available: true`, `torch_cuda_available: true` (HIP mapped), and `gpu_memory_mb: 49136`.
- All key inference paths (style transfer, depth estimation, multi-view synthesis, 3D generation) run on the local AMD GPU without calling external paid APIs.

## Checklist

- [x] Web UI works end-to-end.
- [x] 2.5D relief and full-color 3D pipelines produce watertight, printable models.
- [x] No core feature relies solely on a closed-source online API.
- [x] Documentation (README, intro, demo script, poster, video guide) included.
- [x] `npm run build` passes locally.

## Notes for Reviewers

- The project targets the **Track 1: Multimodal AI Content Creation Tool** competition track.
- The demo video is the most important deliverable; see `docs/VIDEO_PRODUCTION.md` and `docs/DEMO_SCRIPT.md` for the 3–5 minute shooting script.
- The repository is ready to be cloned and run on the provided AMD Radeon GPU environment.
