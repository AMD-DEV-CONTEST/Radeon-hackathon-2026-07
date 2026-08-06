# Pi0 Sidecar (Plan B: dual-venv local Pi0 inference)

This is an **independent** Python 3.12 FastAPI service that hosts a LeRobot
Pi0 policy, completely isolated from the main `apps/realtime` service
(which stays on Python 3.11 + ROCm for camera / teleop / record).

Why a separate venv
-------------------
LeRobot's Pi0 code imports a **patched** `transformers` fork
(`transformers.models.siglip.check`) and the upstream recipe
`pip install "lerobot[pi]"` requires **Python 3.12+**. Mixing that into
the ROCm 3.11 venv breaks the already-stable teleop/record stack, so we
keep it in its own process and talk to it over `127.0.0.1:8010`.

Qualia alignment
----------------
Qualia's inference guide recommends **Python 3.12**, **uv**, **`lerobot==0.4.4`**,
**ffmpeg** (system package), and **Hugging Face Hub login** — see
[Inference | Qualia Docs](https://docs.qualiastudios.dev/global/guides/inference/).
This sidecar follows the same *environment style* (uv + py3.12 + HF login).
For **Pi0** we install `lerobot[pi]` from PyPI at **0.5.1** because the `pi`
extra is not present on the `0.4.4` wheel metadata; if your checkpoint fails
to load, use Qualia's `lerobot-record ... --policy.path=...` on a pure 0.4.4
venv once to confirm export compatibility, then we can pin the sidecar to
match.

Architecture
------------

```
┌─────────────────────────┐    HTTP /predict    ┌────────────────────────┐
│ apps/realtime (py311)   │ ──────────────────► │ apps/pi0_sidecar (3.12)│
│  camera + joint_state   │ ◄────────────────── │  PI0Policy.select_action│
│  SafetyGate + broadcast │      action[6]      │  CPU (or CUDA later)   │
└─────────────────────────┘                     └────────────────────────┘
```

Endpoints
---------

- `GET  /healthz`                    → `{"ok": true, "model_key": "..."}`
- `POST /load`                       → load / switch model (reads Hub ``config.json`` ``type``: **act** or **pi0**)
    body: `{"model_key": "<hf repo id>", "prefer_device": "cpu|cuda", "task_prompt": "..."}`
    returns include ``policy_family`` and ``image_hw`` for the chosen checkpoint.
- `POST /predict`                    → run one Pi0 step
    body:
    ```json
    {
      "joint_state": [j1, j2, j3, j4, j5, j6],
      "image_b64": "<base64 JPEG/PNG bytes>",
      "task_prompt": "pick up the yellow block"
    }
    ```
    returns:
    ```json
    {
      "action": [a1, a2, a3, a4, a5, a6],
      "latency_ms": 1234.5,
      "device": "cpu"
    }
    ```

Quick start
-----------

```bash
# 1) one-off: create the isolated venv + install LeRobot deps (~3-5 GB)
bash apps/pi0_sidecar/setup_env.sh

# 2) run the service (listens on 127.0.0.1:8010)
bash apps/pi0_sidecar/run.sh

# 3a) load Qualia ACT (fast path to validate the stack)
curl -X POST http://127.0.0.1:8010/load \
  -H 'Content-Type: application/json' \
  -d '{"model_key":"qualia-robotics/act-so101-20260422-0445-1b35f73c",
       "prefer_device":"cpu",
       "task_prompt":"perform the task"}'

# 3b) or load Qualia Pi0
curl -X POST http://127.0.0.1:8010/load \
  -H 'Content-Type: application/json' \
  -d '{"model_key":"qualia-robotics/pi0-so101-20260422-445-ba20f12d",
       "prefer_device":"cpu",
       "task_prompt":"pick up the yellow block"}'

# 4) smoke test /predict (with any JPEG):
curl -s -X POST http://127.0.0.1:8010/predict \
  -H 'Content-Type: application/json' \
  -d "{\"joint_state\":[0,0,0,0,0,0],
       \"image_b64\":\"$(base64 -w0 < /some/frame.jpg)\",
       \"task_prompt\":\"pick up the yellow block\"}"
```

Once `/load` succeeds, the BotverseX Inference page loads the same repo via
``apps/realtime`` (``POST /api/vision_inference/load``), which proxies
inference to this sidecar (see ``apps/realtime/api/pi0_runtime.py``).
