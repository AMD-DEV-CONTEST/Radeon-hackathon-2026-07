"""ComfyUI HTTP adapter using only the Python standard library."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from ..errors import BackendUnavailableError, CancelledError, OperationError
from .base import GeneratedCandidate, GenerationRequest, ProviderInfo


class ComfyUIProvider:
    def __init__(
        self, endpoint: str = "http://127.0.0.1:8188", *, timeout: float = 5.0
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    def _json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.timeout
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BackendUnavailableError(
                "ComfyUI is unavailable", endpoint=self.endpoint, reason=str(exc)
            ) from exc

    def probe(self) -> ProviderInfo:
        self._json("/system_stats")
        objects = self._json("/object_info/CheckpointLoaderSimple")
        try:
            models = tuple(
                objects["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            )
        except (KeyError, TypeError):
            models = ()
        return ProviderInfo(f"ComfyUI · {self.endpoint}", models)

    @staticmethod
    def _workflow(
        request: GenerationRequest, model: str, seed: int, prefix: str
    ) -> dict[str, Any]:
        positive = request.prompt
        if request.style == "pixel":
            positive += ", centered full-body 2D game sprite, clean silhouette, limited color palette, plain background, no text"
        negative = (
            request.negative
            or "text, watermark, blurry, photorealistic, cropped, multiple characters"
        )
        # Turbo checkpoints are distilled for one to four evaluations.  The
        # frontend keeps generic sliders for ordinary checkpoints, so clamp
        # here instead of relying on every caller to know model-specific
        # sampling rules.
        is_turbo = "turbo" in model.lower()
        steps = min(request.steps, 4) if is_turbo else request.steps
        cfg = min(request.cfg, 1.0) if is_turbo else request.cfg
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": positive, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": negative, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": request.size,
                    "height": request.size,
                    "batch_size": 1,
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": prefix, "images": ["6", 0]},
            },
        }

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
        progress: Callable[[str, int, int], None],
        cancelled: Callable[[], bool],
    ) -> tuple[GeneratedCandidate, ...]:
        info = self.probe()
        if not info.models:
            raise BackendUnavailableError("ComfyUI has no checkpoint models")
        model = info.models[0] if request.model == "default" else request.model
        if model not in info.models:
            raise BackendUnavailableError(
                "requested model is not installed", model=model
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for index in range(request.count):
            if cancelled():
                self.interrupt()
                raise CancelledError("generation cancelled")
            seed = request.seed + index
            prefix = f"sprite-workshop-{uuid.uuid4().hex[:8]}"
            queued = self._json(
                "/prompt",
                {
                    "prompt": self._workflow(request, model, seed, prefix),
                    "client_id": self.client_id,
                },
                timeout=30,
            )
            prompt_id = queued.get("prompt_id")
            if not prompt_id:
                raise OperationError("ComfyUI rejected prompt", response=queued)
            image_info = self._wait_for_image(str(prompt_id), cancelled)
            query = urllib.parse.urlencode(
                {
                    "filename": image_info["filename"],
                    "subfolder": image_info.get("subfolder", ""),
                    "type": image_info.get("type", "output"),
                }
            )
            try:
                with urllib.request.urlopen(
                    f"{self.endpoint}/view?{query}", timeout=60
                ) as response:
                    data = response.read()
            except (urllib.error.URLError, TimeoutError) as exc:
                raise OperationError(
                    "failed to download ComfyUI output", reason=str(exc)
                ) from exc
            candidate_id = f"candidate-{index + 1}"
            path = output_dir / f"{candidate_id}.png"
            path.write_bytes(data)
            results.append(GeneratedCandidate(candidate_id, seed, path))
            progress("generating", index + 1, request.count)
        return tuple(results)

    def _wait_for_image(
        self, prompt_id: str, cancelled: Callable[[], bool]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            if cancelled():
                self.interrupt()
                raise CancelledError("generation cancelled")
            history = self._json(f"/history/{prompt_id}", timeout=30)
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise OperationError(
                        "ComfyUI generation failed", messages=status.get("messages", [])
                    )
                for output in entry.get("outputs", {}).values():
                    images = output.get("images", [])
                    if images:
                        return images[0]
            time.sleep(0.5)
        raise OperationError("ComfyUI generation timed out", prompt_id=prompt_id)

    def interrupt(self) -> None:
        try:
            self._json("/interrupt", {})
        except BackendUnavailableError:
            pass
