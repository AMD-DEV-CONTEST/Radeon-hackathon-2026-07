# SparkFencer

SparkFencer is a private AI-agent system for fencing video review. It converts a training or competition
video into structured detections, tactical events, evidence clips, a multi-agent review record, and a
coaching report. The package is prepared for the AMD Radeon Track 2 submission.

## Radeon ROCm quick start

Requirements: Linux, Python 3.10+, FFmpeg, a ROCm-supported AMD Radeon GPU, and a local
OpenAI-compatible model service (Ollama or llama.cpp).

```bash
export PYTORCH_ROCM_INDEX=https://download.pytorch.org/whl/rocm7.2
bash scripts/setup_amd_rocm.sh
source .venv/bin/activate
python scripts/build_knowledge.py
python scripts/health_check.py
```

Pull a local VLM and embedding model with your chosen serving runtime, then configure
`config.yaml` or the `VLM_BASE_URL` / `VLM_MODEL` environment variables. The default endpoint is local,
and `privacy.local_only: true` keeps all video, inference, embeddings, and session records on the device.

The ROCm 7.2 installation is pinned in `requirements-rocm.txt` (`torch` and `torchvision`).
`triton-rocm` is installed automatically by the matching PyTorch wheel; `numpy` is listed in the portable
`requirements.txt` because it is used by the complete analysis pipeline.

## Run

```bash
# Export a reference frame and select the four piste corners.
python main.py --video-path videos/demo.mp4 --export-frame

# Run the visual pipeline and rule-based report.
python main.py --video-path videos/demo.mp4 \
  --corners "120,650 1800,640 1850,720 80,730" \
  --piste-length 14 --skip-agents

# Launch the graphical interface.
python webui/app.py
```

For full agent review, omit `--skip-agents` after a local VLM endpoint is ready. The WebUI includes separate
VLM and RAG-answer provider/model/service-URL controls, session-only password-type API-key inputs, review
results, RAG-enabled coach chat, and prior-session browsing. Empty API-key fields use only a server-side
private environment setting when one is configured.

## Radeon Cloud demonstration mode

SparkFencer supports both local-private deployment and an optional Radeon Cloud API deployment.
`scripts/start_radeon_cloud_webui.sh` is a launcher for an authenticated Radeon Cloud notebook. The operator
supplies an API key through a private environment file and explicitly enables the Radeon Cloud API mode. This
opt-in mode transmits selected review keyframes and prompts only; it never uploads a raw video stream. The
launcher binds the WebUI to `127.0.0.1` and requires `WEBUI_USER` / `WEBUI_PASSWORD`, suitable for publishing
through the platform's authenticated tunnel workflow.

## Included materials

- `fencing_analysis/`: perception, event analysis, evidence, agents, RAG, and report generation.
- `webui/`: Gradio analysis interface and blade-tip data workshop.
- `knowledge/`: local fencing knowledge-base documents.
- `scripts/`: ROCm setup, health check, benchmark, knowledge/index construction, and Radeon Cloud launcher.
- `tests/`: geometry, scorecard, evidence-window, and blade-pose tests.

See `../../README.md` and `../../Project_Specification_Document.md` for the reviewer-oriented submission
guide and complete project specification.
