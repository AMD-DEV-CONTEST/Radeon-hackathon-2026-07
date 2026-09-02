"""Local ComfyUI generative backend — deterministic Phase 2/3 orchestration (no Codex).

Given a Phase 1 bridge manifest with route `realizable`/`hybrid`:

- **Phase 2 (FLUX.2 keyframes)**: for each realizable key moment, run a FLUX image edit using
  the moment's `clean` frame as structural reference plus a prompt built from its description
  and the world continuity list. Output: one realistic keyframe PNG per moment.
- **Phase 3 (LTX-2.3 video)**: build segments between consecutive keyframes, run LTX
  first/last-frame generation per segment, then ffmpeg-concat into the final model video.

Delegates the actual ComfyUI submission to the self-contained Re_0 tools
(`phase2/tools/run_flux_image.py`, `phase3/tools/run_ltx_flf.py`) via subprocess; the invocation
helper is injectable so tests can mock it. GPU jobs are serial (the tools refuse a non-empty
ComfyUI queue).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from app.config import COMFYUI_URL, JOBS_DIR, PHASE2_DIR, PHASE3_DIR


class GenerativeUnavailableError(RuntimeError):
    """Raised when the local ComfyUI model stack is unavailable."""


def _comfy_ok() -> dict[str, Any] | None:
    """Return ComfyUI /system_stats if reachable, else None."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _model_present(rel: str) -> bool:
    return (Path("/persistent/ComfyUI") / "models" / rel).is_file()


def probe() -> dict[str, Any]:
    """Availability probe used by /health."""
    stats = _comfy_ok()
    if stats is None:
        return {"available": False, "detail": f"ComfyUI unreachable at {COMFYUI_URL}"}
    devices = stats.get("devices", [{}])
    device = devices[0].get("name", "unknown") if devices else "unknown"
    flux = _model_present("diffusion_models/flux2_dev_fp8mixed.safetensors")
    ltx = _model_present("checkpoints/ltx-2.3-22b-dev-fp8.safetensors")
    return {
        "available": bool(flux and ltx),
        "detail": f"ComfyUI {device} · FLUX={flux} LTX={ltx}",
    }


def _build_flux_prompt(moment: dict[str, Any], world_continuity: list[str], request: str) -> str:
    preserve = "、".join(moment.get("preserve") or [])
    world = "；".join(world_continuity)
    lines = [
        "Realistic scientific teaching illustration that turns a programmatic diagram into a photoreal scene.",
        f"The frame must preserve these composition/structure relations: {preserve}." if preserve else "",
        f"Whole-video world continuity: {world}." if world else "",
        f"Teaching meaning of this moment: {moment.get('description') or ''}",
        f"Original content: {request[:300]}",
    ]
    return "\n".join(line for line in lines if line)


class LocalModelPipeline:
    """Deterministic Phase 2/3 orchestrator backed by the Re_0 ComfyUI tools."""

    def __init__(self, runner: Callable[[list[str], Path], None] | None = None):
        self._runner = runner or self._default_runner

    @staticmethod
    def _default_runner(cmd: list[str], cwd: Path) -> None:
        subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)

    def run_phase2(
        self, job_id: str, manifest: dict[str, Any], phase1_run_dir: Path, request: str
    ) -> list[dict[str, Path]]:
        """Generate realistic keyframes for the realizable key moments."""
        tool = PHASE2_DIR / "tools" / "run_flux_image.py"
        model_dir = JOBS_DIR / job_id / "model"
        (model_dir / "anchors").mkdir(parents=True, exist_ok=True)
        world = list(manifest.get("worldContinuity") or [])
        keyframes: list[dict[str, Path]] = []
        moments = manifest.get("keyMoments") or []
        for idx, moment in enumerate(moments):
            if not moment.get("realizable", True):
                continue
            clean_rel = (moment.get("assets") or {}).get("clean")
            if not clean_rel:
                continue
            clean = phase1_run_dir / "bridge" / clean_rel
            if not clean.is_file():
                raise FileNotFoundError(f"clean frame missing: {clean}")
            prompt_path = model_dir / "anchors" / f"{moment['id']}.prompt.txt"
            prompt_path.write_text(_build_flux_prompt(moment, world, request), encoding="utf-8")
            keyframe = model_dir / "anchors" / f"{moment['id']}.png"
            self._runner(
                [
                    sys.executable, str(tool),
                    "--reference", str(clean),
                    "--prompt", str(prompt_path),
                    "--output", str(keyframe),
                    "--server", COMFYUI_URL,
                ],
                model_dir,
            )
            keyframes.append({"id": moment["id"], "time": float(moment.get("time", 0) or 0), "image": keyframe})
        if not keyframes:
            raise GenerativeUnavailableError("manifest has no realizable key moments")
        keyframes.sort(key=lambda k: k["time"])
        return keyframes

    def run_phase3(
        self, job_id: str, keyframes: list[dict[str, Path]], manifest: dict[str, Any]
    ) -> Path:
        """Build segments between consecutive keyframes, run LTX per segment, concat."""
        tool = PHASE3_DIR / "tools" / "run_ltx_flf.py"
        model_dir = JOBS_DIR / job_id / "model"
        run_dir = model_dir / "phase3"
        (run_dir / "segments").mkdir(parents=True, exist_ok=True)

        if len(keyframes) < 2:
            raise GenerativeUnavailableError("model route needs at least 2 realizable key moments")

        meta = manifest.get("meta") or {}
        width = int(meta.get("width", 1536))
        height = int(meta.get("height", 864))
        fps = float(meta.get("fps", 30))

        segments: list[dict[str, Any]] = []
        for i in range(len(keyframes) - 1):
            seg_id = f"seg{i:02d}"
            seg_dir = run_dir / "segments" / seg_id
            seg_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(keyframes[i]["image"], seg_dir / "start.png")
            shutil.copy2(keyframes[i + 1]["image"], seg_dir / "end.png")
            positive = _build_flux_prompt(
                {"description": f"transition from the previous state to the key moment '{keyframes[i + 1]['id']}'"},
                list(manifest.get("worldContinuity") or []),
                "",
            )
            (seg_dir / "prompt.txt").write_text(
                f"POSITIVE\n{positive}\nNEGATIVE\nlow quality, blurry, distorted, text artifacts\n",
                encoding="utf-8",
            )
            segments.append({
                "id": seg_id,
                "sourceType": "generated",
                "outputPrefix": f"live_science_phase3/{job_id}/{seg_id}",
                "settings": {
                    "width": width, "height": height, "fps": fps,
                    "frameCount": 25,  # 8n+1, ~0.83s at 30fps
                    "loraStrength": 0.8, "imageCompression": 17,
                    "guideStrength": 1.0, "seed": 271828 + i,
                },
            })
        (run_dir / "timeline.json").write_text(
            json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        for seg in segments:
            self._runner(
                [sys.executable, str(tool), str(run_dir), "--segment-id", seg["id"], "--server", COMFYUI_URL],
                run_dir,
            )

        final_video = model_dir / "final_video.mp4"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            concat_list = run_dir / "segments.txt"
            concat_list.write_text(
                "\n".join(f"file '{run_dir / 'segments' / s['id'] / 'video.mp4'}'" for s in segments),
                encoding="utf-8",
            )
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(final_video)],
                check=True, capture_output=True, text=True,
            )
        else:
            # No ffmpeg on PATH: fall back to the first segment as a smoke result.
            shutil.copy2(run_dir / "segments" / segments[0]["id"] / "video.mp4", final_video)
        return final_video

    def run_model(
        self,
        job_id: str,
        manifest: dict[str, Any],
        request: str,
        phase1_run_dir: Path,
    ) -> dict[str, Any]:
        """Full Phase 2 + Phase 3 pipeline for one job; returns a renderer result dict."""
        keyframes = self.run_phase2(job_id, manifest, phase1_run_dir, request)
        final_video = self.run_phase3(job_id, keyframes, manifest)
        model_dir = JOBS_DIR / job_id / "model"
        outputs: dict[str, Any] = {"video": final_video}
        for kf in keyframes:
            outputs[f"keyframe_{kf['id']}"] = kf["image"]
        return {
            "id": job_id,
            "status": "completed",
            "renderer": "local_comfyui",
            "outputs": outputs,
            "metrics": {
                "route": manifest.get("route"),
                "keyframes": [kf["id"] for kf in keyframes],
                "model_dir": str(model_dir),
            },
            "error": None,
        }


def run_generative(
    job_id: str,
    manifest: dict[str, Any],
    text: str,
    phase1_run_dir: Path,
) -> dict[str, Any]:
    """Module-level entry used by the job manager."""
    return LocalModelPipeline().run_model(job_id, manifest, text, phase1_run_dir)
