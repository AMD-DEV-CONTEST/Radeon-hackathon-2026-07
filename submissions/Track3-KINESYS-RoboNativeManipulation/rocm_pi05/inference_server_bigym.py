"""bigym_plus eval-compatible inference adapter for the trained pi05 policy (INFERENCE-SIDE ONLY).

Speaks the ``/process_frame`` protocol that ``d/eval/eval_bigym.py`` expects, so the eval client needs
no change — the real policy replaces ``d/eval/mock_vla_server.py`` behind the same URL.

Protocol (identical to mock_vla_server.py):
  POST /process_frame
    form:  text   = language prompt
           states = json 16-dim state (pad_to_16)
    files: image  = 3 raw-resolution PNGs in CAMERAS order [head, left_wrist, right_wrist]
    -> JSON {"response": [[16 float], ...]}   # action chunk, server decides length

It reuses ``inference_server.build_policy`` (which builds the exact same Pi0Config as train_jax.py:
camera order, action_dim, action_horizon, lora variant) so inputs align with the trained checkpoint.
The PNGs are decoded BGR->RGB uint8 HWC; the openpi ``MultiCameraInputs`` transform expects
``data["images"][name]`` as HxWx3 uint8 and ``ResizeImages(224,224)`` resizes internally.

Usage (mirrors train_jax.py):
  python3 inference_server_bigym.py \
      --action-dim 16 --action-horizon 10 --model-action-dim 32 \
      --camera-names high l_wrist r_wrist \
      --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
      --wrist-names l_wrist r_wrist \
      --data-dir /workspace/bigym_plus/d/replay_generation/data/dishwasher_unload_cups_long \
      --checkpoint-dir checkpoints/dishwasher_unload_cups_long/run1_lora_b4/3999 \
      --lora --default-prompt "Unload cup from dishwasher in wall cabinet task." \
      --host 0.0.0.0 --port 7891
"""
import argparse
import json
import logging

import cv2
import numpy as np
from flask import Flask, request

import inference_server  # repo-root sibling: add_args + build_policy (symmetric with the trainers)

log = logging.getLogger("bigym_infer")
app = Flask(__name__)
_policy = None

# eval env_utils.CAMERAS order = [head, left_wrist, right_wrist] -> model camera-names [high, l_wrist, r_wrist].
# The client sends files in CAMERAS order; we map positionally to the trained camera names.
CAM_ORDER = ("high", "l_wrist", "r_wrist")


@app.post("/process_frame")
def process_frame():
    try:
        prompt = request.form.get("text", "")
        state16 = np.array(json.loads(request.form.get("states", "[]")), dtype=np.float32)
        files = request.files.getlist("image")
        if len(files) != 3:
            return json.dumps({"error": f"expected 3 images, got {len(files)}"}), 400
        images = {}
        for name, f in zip(CAM_ORDER, files):
            buf = np.frombuffer(f.read(), dtype=np.uint8)
            bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # HxWx3 BGR
            if bgr is None:
                return json.dumps({"error": f"failed to decode image for {name}"}), 400
            images[name] = bgr[:, :, ::-1].copy()  # HxWx3 RGB uint8
        obs = {"state": state16, "images": images, "prompt": prompt}
        out = _policy.infer(obs)
        actions = np.asarray(out["actions"], dtype=np.float32)  # (action_horizon, action_dim)
        chunk = actions.tolist()
        log.info(
            "/process_frame prompt=%r state_dim=%d n_images=%d -> chunk %dx%d",
            prompt, state16.shape[0], len(images), len(chunk), len(chunk[0]) if chunk else 0,
        )
        return json.dumps({"response": chunk})
    except Exception as e:  # noqa: BLE001 - surface inference errors to the eval client
        log.exception("process_frame failed")
        return json.dumps({"error": str(e)}), 500


@app.get("/health")
def health():
    return json.dumps({"status": "ok"})


def main() -> None:
    ap = argparse.ArgumentParser(description="bigym eval-compatible pi05 inference adapter (inference-side only).")
    inference_server.add_args(ap)  # model/data/checkpoint/host/port args, symmetric with train_jax.py
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    global _policy
    log.info("Building policy from checkpoint %s ...", args.checkpoint_dir)
    _policy = inference_server.build_policy(args)
    log.info("Policy ready. Serving /process_frame on http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
