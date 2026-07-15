# TwinForge ROCm Inference Server

PyTorch + ROCm FastAPI server that runs the core digital-human generation **locally on an
AMD Radeon GPU**. The TwinForge app tier calls this over the contract below.

## Requirements
- AMD Radeon GPU (Radeon Cloud) with ROCm
- Python 3.10+, PyTorch (ROCm build), FastAPI, uvicorn, OpenCV, FFmpeg, Pillow
- Open-source models: TTS/voice-clone, talking-head (SadTalker/Wav2Lip-style), Diffusers

## Contract (called by the app tier)
- `POST /twins/train` → `{ jobId }`
- `GET  /twins/:jobId/status` → `{ stage, progress, twinModelUrl? }`
- `POST /render` → `{ jobId }`
- `GET  /render/:jobId/status` → `{ stage, progress, videoUrl? }`
- `POST /render/batch` → `{ batchId, jobIds[] }`
- `GET  /system/gpu-status` → `{ gpuModel, rocmVersion, vramUsedGB, vramTotalGB, utilizationPct, activeJobs }`

## Start
```bash
pip install -r requirements.txt
python server.py            # serves on 0.0.0.0:8000 (Radeon Cloud routes port 8000)
```

> Full inference implementation is added once Radeon Cloud GPU access is provisioned.
