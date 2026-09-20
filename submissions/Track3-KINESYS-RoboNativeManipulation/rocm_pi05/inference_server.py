"""Customer-facing HTTP inference server for pi05 (self-contained).

Loads a trained policy from a checkpoint and serves:
    POST /infer   - msgpack request body (obs dict) -> msgpack response body (action dict)
    GET  /healthz - liveness probe
    GET  /metadata- the policy metadata json

All model/camera/data configuration is via CLI args — no edit to ``src/openpi/training/config.py``.
The CLI is symmetric with the trainers: the same camera/data fields (so camera order matches the
training run exactly). Weights and norm_stats both load from ``--checkpoint-dir``; the backend (JAX
``params/`` vs PyTorch ``model.safetensors``) is auto-detected, so the same command works for either.

Uses only the Python standard library for HTTP (no fastapi/flask/uvicorn dependency). For high
concurrency / async, swap _serve() for a fastapi app (would add a dependency).

NOTE: the model/data config construction here mirrors train_jax.py on purpose —
training and inference MUST build the same Pi0Config (camera order, action_dim, action_horizon) or
inputs will not align. If you change the config in the trainers, change it here identically.

Usage:
  python3 inference_server.py \
      --action-dim 16 --action-horizon 10 \
      --camera-names high l_wrist r_wrist \
      --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
      --wrist-names l_wrist r_wrist \
      --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
      --checkpoint-dir checkpoints/cupboards_close_all/run1/20000 \
      --host 0.0.0.0 --port 8000

Client side (encode images with openpi_client.msgpack_numpy, NOT json):
  import requests, openpi_client.msgpack_numpy as mn
  resp = requests.post("http://host:8000/infer", data=mn.packb(obs), headers={"Content-Type": "application/msgpack"})
  action = mn.unpackb(resp.content)
"""

import argparse
import http.server
import json
import logging
import pathlib

import inference_post  # sibling module at repo root
from openpi.models import pi0_config
from openpi.policies import policy_config
from openpi.training import config as _config
from openpi.training import optimizer as _optimizer
from openpi.training import weight_loaders as _weight_loaders

log = logging.getLogger("openpi")


def add_args(parser: argparse.ArgumentParser) -> None:
    """Model + data args (symmetric with the trainers) plus inference-only args."""
    parser.add_argument("--action-dim", type=int, required=True, help="Action dimension of THIS robot (must match training).")
    parser.add_argument(
        "--model-action-dim",
        type=int,
        default=32,
        help="Base checkpoint action_dim (pi05_base=32, must match training). Model action projection stays 32; "
             "dataset actions are padded to this and inference slices outputs back to --action-dim.",
    )
    parser.add_argument("--action-horizon", type=int, default=10, help="Action chunk horizon (must match training).")
    parser.add_argument(
        "--lora",
        action="store_true",
        help="LoRA variant of the trained checkpoint (must match training) so the model config aligns with the loaded weights.",
    )
    parser.add_argument("--camera-names", nargs="+", required=True, help="Model image-token order (must match training).")
    parser.add_argument(
        "--camera-sources",
        nargs="+",
        required=True,
        help="LeRobot flattened paths mapping to each camera name (same order as --camera-names).",
    )
    parser.add_argument(
        "--wrist-names", nargs="*", default=[], help="Subset of --camera-names that are wrist cameras."
    )
    parser.add_argument(
        "--data-dir", required=True, help="Local LeRobot dataset directory (contains meta/data/videos)."
    )
    parser.add_argument("--state-source", default="observation.state")
    parser.add_argument("--action-source", default="action")
    parser.add_argument(
        "--prompt-from-task",
        dest="prompt_from_task",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Must match training (affects data config). Prompt itself comes from each request.",
    )
    parser.add_argument("--default-prompt", default=None, help="Prompt injected when the request lacks one.")
    parser.add_argument("--config-name", default=None, help="Config name (drives the assets path). Defaults to the data-dir basename.")
    parser.add_argument("--checkpoint-dir", required=True, help="Checkpoint dir with weights and assets/<asset_id>/norm_stats.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)


def build_config(args) -> _config.TrainConfig:
    """Build the openpi TrainConfig for inference. Training-only fields use defaults (unused here)."""
    if len(args.camera_names) != len(args.camera_sources):
        raise SystemExit("--camera-names and --camera-sources must have the same length.")
    cameras = tuple(
        _config.CameraSpec(name=n, source=s, is_wrist=(n in args.wrist_names))
        for n, s in zip(args.camera_names, args.camera_sources)
    )
    paligemma_variant = "gemma_2b_lora" if args.lora else "gemma_2b"
    action_expert_variant = "gemma_300m_lora" if args.lora else "gemma_300m"
    model = pi0_config.Pi0Config(
        pi05=True,
        paligemma_variant=paligemma_variant,
        action_expert_variant=action_expert_variant,
        action_dim=args.model_action_dim,  # must match the base checkpoint (pi05_base=32)
        action_horizon=args.action_horizon,
        image_keys=tuple(args.camera_names),
        wrist_image_keys=tuple(args.wrist_names),
    )
    # data_dir is the local dataset path; the data pipeline loads it offline from disk (no HF Hub).
    data = _config.LeRobotMultiCameraDataConfig(
        data_dir=args.data_dir,
        cameras=cameras,
        state_source=args.state_source,
        action_source=args.action_source,
        prompt_from_task=args.prompt_from_task,
        default_prompt=args.default_prompt,
        action_dim=args.action_dim,
    )
    return _config.TrainConfig(
        name=args.config_name or pathlib.Path(args.data_dir).name,
        exp_name="infer",  # unused at inference (checkpoint_dir is passed directly)
        model=model,
        data=data,
        weight_loader=_weight_loaders.NoOpWeightLoader(),
        pytorch_weight_path=None,
        pytorch_training_precision="bfloat16",
        lr_schedule=_optimizer.CosineDecaySchedule(warmup_steps=1_000, peak_lr=2.5e-5, decay_steps=30_000, decay_lr=2.5e-6),
        optimizer=_optimizer.AdamW(weight_decay=1e-10, clip_gradient_norm=1.0),
        assets_base_dir="./assets",
        checkpoint_base_dir="./checkpoints",
        seed=42,
        batch_size=32,
        num_workers=2,
        num_train_steps=30_000,
        log_interval=100,
        save_interval=1_000,
        overwrite=False,
        resume=False,
        wandb_enabled=False,
        fsdp_devices=1,
    )


def build_policy(args):
    config = build_config(args)
    return policy_config.create_trained_policy(config, args.checkpoint_dir, default_prompt=args.default_prompt)


class _PolicyHandler(http.server.BaseHTTPRequestHandler):
    policy = None  # set on the class before serve_forever()
    metadata: dict | None = None

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, b'{"status":"ok"}')
        elif self.path == "/metadata":
            self._send(200, json.dumps(self.metadata or {}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        if self.path != "/infer":
            self._send(404, b'{"error":"not found"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        status, resp, ctype = inference_post.handle_post(self.policy, body)
        self._send(status, resp, ctype)

    def log_message(self, *args) -> None:  # silence the default stderr access log
        pass


def _serve(args, policy) -> None:
    _PolicyHandler.policy = policy
    _PolicyHandler.metadata = getattr(policy, "metadata", None) or {}
    httpd = http.server.ThreadingHTTPServer((args.host, args.port), _PolicyHandler)
    log.info(
        "Serving openpi inference on http://%s:%d (POST /infer, GET /healthz, GET /metadata)",
        args.host,
        args.port,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a trained pi05 policy over HTTP (no config.py edit).")
    add_args(parser)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    policy = build_policy(args)
    _serve(args, policy)


if __name__ == "__main__":
    main()
