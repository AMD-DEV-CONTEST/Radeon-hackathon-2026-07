# Video generation backend

FrameForge now drives [Replicate](https://replicate.com) instead of a local ComfyUI server. No local GPU, model downloads, or ComfyUI install is required.

## Setup

1. **Get a Replicate API token** — sign up at <https://replicate.com> (free tier available, pay-per-second billing after that), then visit <https://replicate.com/account/api-tokens> to create a token.

2. **Set the environment variable:**
   ```bash
   export REPLICATE_API_TOKEN="r8_..."    # Linux / macOS
   $env:REPLICATE_API_TOKEN = "r8_..."    # PowerShell
   ```
   You can also add this to a `.env` file in the backend directory.

3. **(Optional) Choose a different model** — by default FrameForge uses `lightricks/ltx-video`. To use another model:
   ```bash
   export REPLICATE_MODEL="owner/model-name:version_hash"
   ```
   Find available video models at <https://replicate.com/collections/video-generation>.

4. **Start the backend:**
   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

That's it — no local ComfyUI, no exported workflow templates, no GPU required.
