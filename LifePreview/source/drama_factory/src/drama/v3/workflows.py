from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from shared_contracts import (
    FirstLastFrameRequest,
    GenerationMode,
    GenerationRequest,
    ImageToVideoRequest,
    TextToVideoRequest,
    stable_json_sha256,
)

from .prompt_compiler import CompiledWanPrompt


class WanWorkflowError(RuntimeError):
    pass


class WanQualityProfile(StrEnum):
    SMOKE = "smoke"
    DRAFT = "draft"
    QUALITY = "quality"


@dataclass(frozen=True, slots=True)
class WanWorkflowBuild:
    workflow_id: str
    workflow_version: str
    workflow: dict[str, Any]
    workflow_sha256: str
    frame_count: int
    fps: float
    model_files: tuple[str, ...]


_TI2V_MODEL = "wan2.2_ti2v_5B_fp16.safetensors"
_T2V_HIGH = "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
_T2V_LOW = "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"
_I2V_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
_I2V_LOW = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
_T2V_LORA_HIGH = (
    "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"
)
_T2V_LORA_LOW = (
    "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors"
)
_I2V_LORA_HIGH = (
    "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
)
_I2V_LORA_LOW = (
    "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
)
_TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
_WAN21_VAE = "wan_2.1_vae.safetensors"
_WAN22_VAE = "wan2.2_vae.safetensors"


def _safe_input_filename(value: str, field: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise WanWorkflowError(f"{field} must be a safe Comfy input filename")
    return path.as_posix()


def _frames(duration_seconds: float, fps: float = 16.0) -> int:
    # Wan temporal latents require 4n+1 frames. Supported R3 durations map to
    # 49, 81, and 129 frames at the native 16 fps cadence.
    requested = max(1, round(duration_seconds * fps))
    return ((requested + 3) // 4) * 4 + 1


def _node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def _output_nodes(
    *,
    decoded_images: tuple[str, int],
    fps: float,
    filename_prefix: str,
) -> dict[str, Any]:
    return {
        "90": _node("CreateVideo", images=list(decoded_images), fps=fps),
        "91": _node(
            "SaveVideo",
            video=["90", 0],
            filename_prefix=filename_prefix,
            format="mp4",
            codec="h264",
        ),
    }


class WanWorkflowBuilder:
    """Build native Comfy API prompts for the three locked R3 local modes."""

    VERSION = "wan-native-workflows.v1"

    def build(
        self,
        *,
        request: GenerationRequest,
        compiled: CompiledWanPrompt,
        quality: WanQualityProfile = WanQualityProfile.QUALITY,
        first_image_filename: str | None = None,
        last_image_filename: str | None = None,
    ) -> WanWorkflowBuild:
        self._validate_identity(request, compiled)
        if request.model_id == "wan2.2-ti2v-5b":
            workflow, files = self._build_ti2v(
                request=request,
                compiled=compiled,
                first_image_filename=first_image_filename,
            )
            workflow_id = (
                "wan22-ti2v-t2v"
                if request.mode is GenerationMode.T2V
                else "wan22-ti2v-i2v"
            )
        elif request.model_id == "wan2.2-t2v-a14b-fp8":
            workflow, files = self._build_dual_expert(
                request=request,
                compiled=compiled,
                quality=quality,
                first_image_filename=None,
                last_image_filename=None,
                high_model=_T2V_HIGH,
                low_model=_T2V_LOW,
                high_lora=_T2V_LORA_HIGH,
                low_lora=_T2V_LORA_LOW,
            )
            workflow_id = "wan22-t2v-a14b"
        elif request.model_id == "wan2.2-i2v-a14b-fp8":
            workflow, files = self._build_dual_expert(
                request=request,
                compiled=compiled,
                quality=quality,
                first_image_filename=first_image_filename,
                last_image_filename=last_image_filename,
                high_model=_I2V_HIGH,
                low_model=_I2V_LOW,
                high_lora=_I2V_LORA_HIGH,
                low_lora=_I2V_LORA_LOW,
            )
            workflow_id = (
                "wan22-i2v-a14b-flf"
                if request.mode is GenerationMode.FIRST_LAST_FRAME
                else "wan22-i2v-a14b"
            )
        else:
            raise WanWorkflowError("request model has no native Wan workflow")

        return WanWorkflowBuild(
            workflow_id=workflow_id,
            workflow_version=self.VERSION,
            workflow=workflow,
            workflow_sha256=stable_json_sha256(workflow),
            frame_count=_frames(request.duration_seconds),
            fps=16.0,
            model_files=files,
        )

    @staticmethod
    def _validate_identity(
        request: GenerationRequest,
        compiled: CompiledWanPrompt,
    ) -> None:
        if (
            compiled.run_id != request.run_id
            or compiled.clip_id != request.clip_id
            or compiled.prompt_snapshot_id != request.prompt_snapshot_id
            or compiled.mode is not request.mode
            or compiled.model_id != request.model_id
            or compiled.workflow.seed != request.resolved_seed
            or compiled.workflow.resolution != request.resolution
            or compiled.workflow.duration_seconds != request.duration_seconds
        ):
            raise WanWorkflowError(
                "compiled prompt does not match generation request"
            )

    def _build_ti2v(
        self,
        *,
        request: GenerationRequest,
        compiled: CompiledWanPrompt,
        first_image_filename: str | None,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if request.mode not in {GenerationMode.T2V, GenerationMode.I2V}:
            raise WanWorkflowError("TI2V-5B cannot run first/last-frame mode")
        if request.resolution.width % 32 or request.resolution.height % 32:
            raise WanWorkflowError("TI2V-5B resolution must be divisible by 32")
        if isinstance(request, TextToVideoRequest):
            if first_image_filename is not None:
                raise WanWorkflowError("T2V cannot receive an input image")
        elif isinstance(request, ImageToVideoRequest):
            if first_image_filename is None:
                raise WanWorkflowError("I2V requires a first image filename")
        else:
            raise WanWorkflowError("unsupported TI2V request shape")

        workflow: dict[str, Any] = {
            "10": _node(
                "UNETLoader",
                unet_name=_TI2V_MODEL,
                weight_dtype="default",
            ),
            "11": _node(
                "CLIPLoader",
                clip_name=_TEXT_ENCODER,
                type="wan",
                device="default",
            ),
            "12": _node("VAELoader", vae_name=_WAN22_VAE),
            "13": _node(
                "CLIPTextEncode",
                text=compiled.positive_prompt,
                clip=["11", 0],
            ),
            "14": _node(
                "CLIPTextEncode",
                text=compiled.negative_prompt,
                clip=["11", 0],
            ),
            "15": _node(
                "ModelSamplingSD3",
                shift=8.0,
                model=["10", 0],
            ),
        }
        latent_inputs: dict[str, Any] = {
            "vae": ["12", 0],
            "width": request.resolution.width,
            "height": request.resolution.height,
            "length": _frames(request.duration_seconds),
            "batch_size": 1,
        }
        if first_image_filename is not None:
            workflow["16"] = _node(
                "LoadImage",
                image=_safe_input_filename(
                    first_image_filename,
                    "first image",
                ),
            )
            latent_inputs["start_image"] = ["16", 0]
        workflow["17"] = _node("Wan22ImageToVideoLatent", **latent_inputs)
        workflow["18"] = _node(
            "KSampler",
            seed=request.resolved_seed,
            steps=compiled.workflow.steps,
            cfg=compiled.workflow.cfg,
            sampler_name="uni_pc",
            scheduler="simple",
            denoise=1.0,
            model=["15", 0],
            positive=["13", 0],
            negative=["14", 0],
            latent_image=["17", 0],
        )
        workflow["19"] = _node(
            "VAEDecode",
            samples=["18", 0],
            vae=["12", 0],
        )
        workflow.update(
            _output_nodes(
                decoded_images=("19", 0),
                fps=16.0,
                filename_prefix=f"factory/{request.run_id}",
            )
        )
        return workflow, (_TI2V_MODEL, _TEXT_ENCODER, _WAN22_VAE)

    def _build_dual_expert(
        self,
        *,
        request: GenerationRequest,
        compiled: CompiledWanPrompt,
        quality: WanQualityProfile,
        first_image_filename: str | None,
        last_image_filename: str | None,
        high_model: str,
        low_model: str,
        high_lora: str,
        low_lora: str,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        self._validate_dual_mode_inputs(
            request=request,
            first_image_filename=first_image_filename,
            last_image_filename=last_image_filename,
        )
        accelerated = quality in {
            WanQualityProfile.SMOKE,
            WanQualityProfile.DRAFT,
        }
        if accelerated and (
            compiled.workflow.steps != 4
            or compiled.workflow.cfg != 1.0
        ):
            raise WanWorkflowError(
                "accelerated workflow requires a frozen 4-step/cfg-1 prompt"
            )
        if not accelerated and compiled.workflow.steps < 20:
            raise WanWorkflowError(
                "quality workflow requires at least 20 frozen steps"
            )
        steps = compiled.workflow.steps
        split = 2 if accelerated else steps // 2
        cfg = compiled.workflow.cfg
        shift = 5.0 if accelerated else 8.0

        workflow: dict[str, Any] = {
            "20": _node(
                "UNETLoader",
                unet_name=high_model,
                weight_dtype="default",
            ),
            "21": _node(
                "UNETLoader",
                unet_name=low_model,
                weight_dtype="default",
            ),
            "22": _node(
                "CLIPLoader",
                clip_name=_TEXT_ENCODER,
                type="wan",
                device="default",
            ),
            "23": _node("VAELoader", vae_name=_WAN21_VAE),
            "24": _node(
                "CLIPTextEncode",
                text=compiled.positive_prompt,
                clip=["22", 0],
            ),
            "25": _node(
                "CLIPTextEncode",
                text=compiled.negative_prompt,
                clip=["22", 0],
            ),
        }
        high_source: list[Any] = ["20", 0]
        low_source: list[Any] = ["21", 0]
        model_files = [
            high_model,
            low_model,
            _TEXT_ENCODER,
            _WAN21_VAE,
        ]
        if accelerated:
            workflow["26"] = _node(
                "LoraLoaderModelOnly",
                model=high_source,
                lora_name=high_lora,
                strength_model=1.0,
            )
            workflow["27"] = _node(
                "LoraLoaderModelOnly",
                model=low_source,
                lora_name=low_lora,
                strength_model=1.0,
            )
            high_source = ["26", 0]
            low_source = ["27", 0]
            model_files.extend((high_lora, low_lora))
        workflow["28"] = _node(
            "ModelSamplingSD3",
            shift=shift,
            model=high_source,
        )
        workflow["29"] = _node(
            "ModelSamplingSD3",
            shift=shift,
            model=low_source,
        )
        positive_ref: list[Any] = ["24", 0]
        negative_ref: list[Any] = ["25", 0]

        if isinstance(request, TextToVideoRequest):
            workflow["30"] = _node(
                "EmptyHunyuanLatentVideo",
                width=request.resolution.width,
                height=request.resolution.height,
                length=_frames(request.duration_seconds),
                batch_size=1,
            )
            latent_ref: list[Any] = ["30", 0]
        else:
            workflow["31"] = _node(
                "LoadImage",
                image=_safe_input_filename(
                    first_image_filename or "",
                    "first image",
                ),
            )
            conditioner_inputs: dict[str, Any] = {
                "positive": positive_ref,
                "negative": negative_ref,
                "vae": ["23", 0],
                "width": request.resolution.width,
                "height": request.resolution.height,
                "length": _frames(request.duration_seconds),
                "batch_size": 1,
                "start_image": ["31", 0],
            }
            conditioner = "WanImageToVideo"
            if isinstance(request, FirstLastFrameRequest):
                workflow["32"] = _node(
                    "LoadImage",
                    image=_safe_input_filename(
                        last_image_filename or "",
                        "last image",
                    ),
                )
                conditioner = "WanFirstLastFrameToVideo"
                conditioner_inputs["end_image"] = ["32", 0]
            workflow["33"] = _node(conditioner, **conditioner_inputs)
            positive_ref = ["33", 0]
            negative_ref = ["33", 1]
            latent_ref = ["33", 2]

        workflow["40"] = _node(
            "KSamplerAdvanced",
            add_noise="enable",
            noise_seed=request.resolved_seed,
            steps=steps,
            cfg=cfg,
            sampler_name="euler",
            scheduler="simple",
            start_at_step=0,
            end_at_step=split,
            return_with_leftover_noise="enable",
            model=["28", 0],
            positive=positive_ref,
            negative=negative_ref,
            latent_image=latent_ref,
        )
        workflow["41"] = _node(
            "KSamplerAdvanced",
            add_noise="disable",
            noise_seed=request.resolved_seed,
            steps=steps,
            cfg=cfg,
            sampler_name="euler",
            scheduler="simple",
            start_at_step=split,
            end_at_step=10000,
            return_with_leftover_noise="disable",
            model=["29", 0],
            positive=positive_ref,
            negative=negative_ref,
            latent_image=["40", 0],
        )
        workflow["42"] = _node(
            "VAEDecode",
            samples=["41", 0],
            vae=["23", 0],
        )
        workflow.update(
            _output_nodes(
                decoded_images=("42", 0),
                fps=16.0,
                filename_prefix=f"factory/{request.run_id}",
            )
        )
        return workflow, tuple(model_files)

    @staticmethod
    def _validate_dual_mode_inputs(
        *,
        request: GenerationRequest,
        first_image_filename: str | None,
        last_image_filename: str | None,
    ) -> None:
        if isinstance(request, TextToVideoRequest):
            if request.model_id != "wan2.2-t2v-a14b-fp8":
                raise WanWorkflowError("I2V model cannot execute T2V")
            if first_image_filename is not None or last_image_filename is not None:
                raise WanWorkflowError("T2V cannot receive endpoint images")
            return
        if request.model_id != "wan2.2-i2v-a14b-fp8":
            raise WanWorkflowError("T2V model cannot execute image-conditioned mode")
        if not first_image_filename:
            raise WanWorkflowError(
                "image-conditioned mode requires a first image"
            )
        if isinstance(request, ImageToVideoRequest):
            if last_image_filename is not None:
                raise WanWorkflowError("I2V cannot receive a last image")
            return
        if isinstance(request, FirstLastFrameRequest):
            if not last_image_filename:
                raise WanWorkflowError("first/last-frame mode requires last image")
            return
        raise WanWorkflowError("unsupported generation request shape")
