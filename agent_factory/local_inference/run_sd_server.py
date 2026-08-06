from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.model_pool.schema import StableDiffusionCppInferenceConfig
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stable-diffusion.cpp sd-server for a model profile")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    load_agentfactory_dotenv()
    store = ModelPoolStore(setup=False)
    profile = store.require_profile(args.profile_id)
    artifact = store.require_artifact(profile.artifact_id)
    inference = profile.inference
    if profile.kind != "image_generation" or not isinstance(inference, StableDiffusionCppInferenceConfig):
        raise ValueError("profile is not a managed stable-diffusion.cpp image generation profile")
    model_path = artifact.resolved_path()
    for path in (model_path, Path(inference.vae_path), Path(inference.clip_l_path), Path(inference.t5xxl_path)):
        if not path.is_file():
            raise FileNotFoundError(path)
    binary = str(os.getenv("AGENTFACTORY_SD_SERVER_PATH") or "sd-server").strip()
    command = [
        binary,
        "--diffusion-model", str(model_path),
        "--vae", inference.vae_path,
        "--clip_l", inference.clip_l_path,
        "--t5xxl", inference.t5xxl_path,
        "--listen-ip", args.host,
        "--listen-port", str(args.port),
    ]
    if inference.diffusion_flash_attention:
        command.append("--diffusion-fa")
    if inference.eager_load:
        command.append("--eager-load")
    if inference.clip_on_cpu:
        command.append("--clip-on-cpu")
    if inference.vae_tiling:
        command.append("--vae-tiling")
    if inference.offload_to_cpu:
        command.append("--offload-to-cpu")
    if inference.max_vram_gib is not None:
        command.extend(("--max-vram", str(inference.max_vram_gib)))
    if inference.stream_layers is not None:
        command.extend(("--stream-layers", str(inference.stream_layers)))
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
