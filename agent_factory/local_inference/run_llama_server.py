from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

from agent_factory.local_inference.context_allocation import resolve_llama_context_plan
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.model_pool.schema import LlamaCppInferenceConfig
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a registered chat model with llama.cpp on AMD ROCm")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()

    inspect_rocm_runtime(require_available=True)
    store = ModelPoolStore(setup=False)
    profile = store.require_profile(args.profile_id)
    artifact = store.require_artifact(profile.artifact_id)
    if profile.kind != "chat" or profile.engine != "llama_cpp_rocm":
        raise ValueError(f"profile {profile.profile_id} is not a llama.cpp chat profile")
    if not isinstance(profile.inference, LlamaCppInferenceConfig):
        raise ValueError(f"profile {profile.profile_id} does not contain llama.cpp inference settings")
    if not profile.enabled or not artifact.enabled:
        raise ValueError("profile and model artifact must be enabled before loading")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    model_path = artifact.resolved_path()
    if not model_path.is_file():
        raise ValueError(f"llama.cpp model file does not exist: {model_path}")
    configured_binary = str(os.environ.get("AGENTFACTORY_LLAMA_SERVER_PATH") or "llama-server").strip()
    binary = shutil.which(configured_binary)
    if binary is None:
        raise FileNotFoundError(
            "llama-server executable was not found; set AGENTFACTORY_LLAMA_SERVER_PATH "
            "to the compiled llama-server binary"
        )
    command = [
        binary,
        "--model",
        str(model_path),
        "--alias",
        profile.served_model_name,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--n-gpu-layers",
        str(profile.inference.gpu_layers),
        "--parallel",
        str(profile.inference.parallel_slots),
        "--cache-type-k",
        profile.inference.cache_type_k,
        "--cache-type-v",
        profile.inference.cache_type_v,
        "--jinja",
        "--metrics",
        "--slots",
    ]
    command.extend(["--flash-attn", "on" if profile.inference.flash_attention else "off"])
    speculative = profile.inference.speculative_decoding
    if speculative.method == "mtp":
        command.extend(
            [
                "--spec-type",
                "draft-mtp",
                "--spec-draft-n-max",
                str(speculative.max_draft_tokens),
                "--spec-draft-n-min",
                str(speculative.min_draft_tokens),
                "--spec-draft-p-min",
                format(speculative.min_acceptance_probability, ".9g"),
                (
                    "--spec-draft-backend-sampling"
                    if speculative.backend_sampling
                    else "--no-spec-draft-backend-sampling"
                ),
            ]
        )
    if profile.inference.mmproj_path:
        mmproj_path = Path(profile.inference.mmproj_path).expanduser().resolve()
        if not mmproj_path.is_file():
            raise ValueError(f"llama.cpp multimodal projector does not exist: {mmproj_path}")
        command.extend(["--mmproj", str(mmproj_path)])
    context_plan = resolve_llama_context_plan(artifact, profile.limits, profile.inference)
    if context_plan is not None:
        command.extend(["--ctx-size", str(context_plan.allocation.server_context_tokens)])
        rope_scaling = context_plan.rope_scaling
        if rope_scaling is not None:
            command.extend(
                [
                    "--rope-scaling",
                    rope_scaling.method,
                    "--rope-scale",
                    format(rope_scaling.factor, ".9g"),
                    "--yarn-orig-ctx",
                    str(rope_scaling.original_context_tokens),
                ]
            )
    os.execv(binary, command)


if __name__ == "__main__":
    main()
