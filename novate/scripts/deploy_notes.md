# Radeon Cloud Deployment Notes

Nova's inference server is deployed directly through Radeon Cloud's
**vLLM Dedicated Model API**, rather than a self-managed llama.cpp/HIP build.
This keeps the setup reproducible for evaluators: no custom GPU driver or
compilation steps, just the platform's own deploy flow.

## 1. Deploy the model (one-time per instance)

1. Log in at https://radeon-global.anruicloud.com/
2. Profile → **Add Template**
3. Set **Deploy Type = vLLM Model API** (this is currently the only deploy
   type Radeon Cloud supports for dedicated model serving)
4. Serve Command:
   ```bash
   vllm serve <model-name> --host 0.0.0.0 --port 8000
   ```
   Keep `--host 0.0.0.0 --port 8000` exactly as shown — the platform routes
   the public endpoint to port 8000 specifically.
5. **Add Template** → then **Launch** it from **My Templates**.
6. When the instance is ready, copy the **Base URL**, **Model** name, and
   **API Key** shown in the instance details / Active Instance panel.

## 2. Point Nova at it

In `.env` (copied from `.env.example`):
```bash
NOVA_LLM_BASE_URL=https://radeon-global.anruicloud.com/spaces/<id>/8000/v1
NOVA_LLM_MODEL_NAME=<model-name-you-passed-to-vllm-serve>
NOVA_LLM_API_KEY=<the-api-key-shown-in-instance-details>
```

## 3. Fast iteration option (development only)

Radeon Cloud's **Token Factory** (Public Free Model APIs) offers free shared
Qwen/DeepSeek endpoints with no instance to launch — handy while iterating on
agent logic. Switch back to your own Dedicated Model API instance before
recording the demo video: the hackathon rules require core inference to run
on your own AMD Radeon GPU deployment, not a shared community endpoint.

## 4. Running Nova itself

Any Radeon Cloud instance's **JupyterLab terminal** (Open Notebook →
Terminal) or an **SSH** session works as the environment to run
`ingest.py` / `app.py` from — see the platform's own Radeon Cloud User Guide
for login, template, and SSH-key setup steps.

## 5. Optional: expose the Gradio UI publicly

From inside a Notebook, Radeon Cloud's `rc-tunnel` tool can expose a local
port (e.g. Nova's `7860`) to a public HTTPS URL for live demoing:
```bash
/var/run/secrets/frp-self-service/install       # one-time install
"$HOME/.local/bin/rc-tunnel" expose --port 7860
```
This is optional — the required deliverable is a recorded demo video, not a
live public URL. Stop the tunnel (`rc-tunnel stop`) when you're done, and
destroy the instance from Profile → Active Instance when you're finished
working to stop consuming credits.
