"""Long-lived JSON-RPC sidecar over stdio.

Speaks the contract in FRONTEND_PLAN.md 3.3.  It exists because spawning a CLI
per request would pay the torch import on every tolerance-slider tick; a
resident process pays it once, and only when recovery actually runs.

Transport rules, same as the CLI: one JSON object per line on stdout, logs on
stderr, never mixed.  Pixels travel as file paths through ``cache/``; they never
go into the JSON.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import (
    ExitCode,
    NotFoundError,
    UsageError,
    WorkshopError,
)
from .generate import ComfyUIProvider, GenerationProvider, GenerationRequest
from .jobs import JobContext, JobManager
from .model import Frame, FrameSet, Point, Rect, Size
from .project import SCHEMA_VERSION, Project

PROTOCOL_VERSION = 1

# A tolerance slider writes two PNGs per frame per distinct setting, and
# nothing ever read them back after the user moved on.  Cap the directory and
# evict the least recently used files.
PREVIEW_CACHE_FILES = 400


def log(message: str) -> None:
    sys.stderr.write(f"[sprite-workshop] {message}\n")
    sys.stderr.flush()


def _param_str(params: Mapping[str, Any], key: str, *, default=None) -> str | None:
    """Strict string param: missing/None means default, anything else is UsageError.

    JSON booleans, numbers and lists are rejected instead of being coerced,
    so a typo like ``"overwrite": "false"`` cannot silently flip a flag.
    """

    if key not in params or params[key] is None:
        return default
    value = params[key]
    if not isinstance(value, str):
        raise UsageError(f"{key} must be a string", **{key: value})
    return value


def _param_bool(params: Mapping[str, Any], key: str, *, default=None) -> bool | None:
    """Strict boolean param: JSON ``true``/``false`` only, never strings or 0/1."""

    if key not in params or params[key] is None:
        return default
    value = params[key]
    if not isinstance(value, bool):
        raise UsageError(f"{key} must be true or false", **{key: value})
    return value


def _param_int(params: Mapping[str, Any], key: str, *, default=None) -> int | None:
    """Strict integer param: a JSON number, never bool, float or string."""

    if key not in params or params[key] is None:
        return default
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageError(f"{key} must be an integer", **{key: value})
    return value


def _max_size_param(params: Mapping[str, Any]) -> Size:
    """Parse ``maxSize`` as the CLI's ``WxH`` string into a Size.

    Kept strict on purpose: a malformed string raises UsageError (code 2)
    instead of letting a bare ``int()`` escape as a code 4 failure.
    """

    raw = _param_str(params, "maxSize", default="2048x2048")
    parts = raw.split("x")
    if len(parts) != 2:
        raise UsageError("maxSize must be WxH", value=raw)
    try:
        width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise UsageError("maxSize must be WxH", value=raw) from exc
    return Size(width, height)


class Daemon:
    def __init__(
        self,
        *,
        generation_provider: GenerationProvider | None = None,
        notify: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.project: Project | None = None
        self._stdout_lock = threading.Lock()
        self._pending_jobs: list[str] = []
        self._candidates: dict[str, Any] = {}
        self.generation_provider = generation_provider or ComfyUIProvider(
            os.environ.get("SPRITE_WORKSHOP_COMFYUI_URL", "http://127.0.0.1:8188")
        )
        self.jobs = JobManager(notify or self._notify)
        self.methods: dict[str, Callable[[Mapping[str, Any]], Any]] = {
            "app.hello": self.app_hello,
            "doctor": self.doctor,
            "project.open": self.project_open,
            "project.create": self.project_create,
            "project.tree": self.project_tree,
            "asset.import": self.asset_import,
            "asset.frames": self.asset_frames,
            "export.apply": self.export_apply,
            "source.classify": self.source_classify,
            "recover.apply": self.recover_apply,
            "history.list": self.history_list,
            "history.undo": self.history_undo,
            "history.redo": self.history_redo,
            "background.analyze": self.background_analyze,
            "background.apply": self.background_apply,
            "outline.analyze": self.outline_analyze,
            "outline.apply": self.outline_apply,
            "pixelify.analyze": self.pixelify_analyze,
            "pixelify.apply": self.pixelify_apply,
            "generate.providers": self.generate_providers,
            "generate.submit": self.generate_submit,
            "generate.commit": self.generate_commit,
            "job.cancel": self.job_cancel,
        }

    # ------------------------------------------------------------- helpers

    def _require_project(self) -> Project:
        if self.project is None:
            raise NotFoundError("no project is open")
        return self.project

    def _cache_dir(self) -> Path:
        project = self._require_project()
        target = project.root / "cache" / "prev"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _write_message(self, payload: Mapping[str, Any]) -> None:
        with self._stdout_lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write_message({"method": method, "params": params})

    def _load_frames(self, name: str) -> FrameSet:
        project = self._require_project()
        if name in project.assets:
            return project.load_asset(name)
        from .image_io import load_rgba  # noqa: PLC0415

        image = load_rgba(project.find_source(name))
        size = image.size
        frame = Frame(
            id=name,
            image=image,
            source_size=size,
            trim_rect=Rect(0, 0, size.width, size.height),
            trim_offset=Point(0, 0),
            anchor=Point(size.width // 2, max(0, size.height - 1)),
            label=name,
        )
        return FrameSet(name, (frame,), size)

    @staticmethod
    def _outline_spec(params: Mapping[str, Any]):
        from .outline import OutlineSpec  # noqa: PLC0415

        color = tuple(int(v) for v in params.get("color", (0, 0, 0)))
        return OutlineSpec(
            position=str(params.get("position", "outer")),
            thickness=int(params.get("thickness", 1)),
            connectivity=int(params.get("connectivity", 8)),
            skip_diagonal=bool(params.get("skipDiagonal", True)),
            color_mode=str(params.get("colorMode", "fixed")),
            color=color,  # type: ignore[arg-type]
            darken=int(params.get("darken", 40)),
            inner_shadow=bool(params.get("innerShadow", False)),
        )

    @staticmethod
    def _pixelify_spec(params: Mapping[str, Any]):
        from .pixelify import PixelifySpec  # noqa: PLC0415

        return PixelifySpec(
            target_width=int(params.get("targetWidth", 64)),
            palette=str(params.get("palette", "auto")),
            colors=int(params.get("colors", 16)),
            dither=str(params.get("dither", "none")),
            sharpen=int(params.get("sharpen", 0)),
            seed=int(params.get("seed", 42)),
        )

    @staticmethod
    def _preview_key(spec: Any, *, asset: str, version: int, frame_id: str) -> str:
        """Fingerprint everything that can change a preview's pixels.

        Naming the fields by hand is how this drifted: the key carried mode,
        tolerance and connectivity while the RPC also accepted samples,
        borderOnly, minIslandArea, maxHoleArea, alpha and softRange.  Toggling
        any of those re-served a stale PNG.  Deriving the key from the whole
        dataclass means a new BackgroundSpec field cannot be forgotten here.
        The asset version is in the key too, so committing a new version does
        not keep showing the old one's preview.
        """

        payload = json.dumps(
            {"asset": asset, "version": version, "spec": dataclasses.asdict(spec)},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()
        # Keep the mode and tolerance human-readable for debugging; the digest
        # is what actually makes the name unique.
        return f"bg_{asset}_{frame_id}_{spec.mode}_{spec.tolerance:g}_{digest}"

    def _prune_cache(self, limit: int = PREVIEW_CACHE_FILES) -> int:
        """Drop the least recently used preview files. Returns the count removed."""

        target = self._require_project().root / "cache" / "prev"
        if not target.is_dir():
            return 0
        files = [p for p in target.glob("*.png") if p.is_file()]
        if len(files) <= limit:
            return 0
        files.sort(key=lambda p: p.stat().st_mtime)
        removed = 0
        for path in files[: len(files) - limit]:
            try:
                path.unlink()
                removed += 1
            except OSError:  # pragma: no cover - a racing reader on Windows
                pass
        return removed

    # ------------------------------------------------------------- methods

    def app_hello(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": PROTOCOL_VERSION,
            "backend": f"sprite_workshop (Python {sys.version.split()[0]})",
            "real_backend": True,
            "project_schema": SCHEMA_VERSION,
            "note": "",
        }

    def doctor(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        from .image_io import pillow_version  # noqa: PLC0415

        checks: list[dict[str, str]] = [
            {"name": "Python", "status": "ok", "detail": sys.version.split()[0]},
            {"name": "项目 schema", "status": "ok", "detail": f"v{SCHEMA_VERSION}"},
        ]

        pillow = pillow_version()
        checks.append(
            {
                "name": "Pillow",
                "status": "ok" if pillow else "error",
                "detail": pillow or "缺失：pip install -e .[workshop]",
            }
        )

        try:
            import numpy  # noqa: PLC0415

            checks.append(
                {"name": "NumPy", "status": "ok", "detail": numpy.__version__}
            )
        except ImportError:
            checks.append({"name": "NumPy", "status": "error", "detail": "缺失"})

        # Torch is imported lazily so that opening a project stays fast; doctor
        # is the one place where paying for it is the point.
        try:
            import torch  # noqa: PLC0415

            checks.append(
                {"name": "Torch", "status": "ok", "detail": torch.__version__}
            )
            from pixel_snapper_core import runtime_description  # noqa: PLC0415

            checks.append(
                {"name": "可见设备", "status": "ok", "detail": runtime_description()}
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            checks.append({"name": "Torch", "status": "error", "detail": str(exc)})
            checks.append({"name": "可见设备", "status": "error", "detail": "不可用"})

        for module, label in (
            ("rectpack", "atlas 后端 (rectpack)"),
            ("rembg", "rembg 后端"),
        ):
            try:
                __import__(module)
                checks.append({"name": label, "status": "ok", "detail": "可用"})
            except ImportError:
                checks.append(
                    {"name": label, "status": "skip", "detail": "可选依赖，未安装"}
                )

        checks.append(
            {
                "name": "RPC 契约",
                "status": "ok",
                "detail": f"v{PROTOCOL_VERSION} · stdio",
            }
        )
        return {"checks": checks}

    def project_open(self, params: Mapping[str, Any]) -> dict[str, Any]:
        path = params.get("path")
        if not path:
            raise UsageError("missing project path")
        self.project = Project.open(path)
        manifest = self.project.manifest
        return {
            "project_id": manifest["project_id"],
            "name": manifest["name"],
            "path": str(self.project.root),
            "schema_version": manifest["schema_version"],
            "head_revision": self.project.head_revision,
            "defaults": manifest.get("defaults", {}),
        }

    def project_create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        path = params.get("path")
        if not path:
            raise UsageError("missing project path")
        self.project = Project.init(
            path,
            project_id=params.get("id"),
            name=params.get("name"),
        )
        return self.project_open({"path": str(self.project.root)})

    def asset_import(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project = self._require_project()
        path = params.get("path")
        if not path:
            raise UsageError("missing import path")
        from .ids import validate_id  # noqa: PLC0415

        source_name = (
            str(params.get("as") or Path(str(path)).stem)
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        validate_id(source_name, what="source name")
        project.import_source(str(path), as_name=source_name)
        frames = self._load_frames(source_name)
        report = project.commit(
            "asset.import",
            params={"source": source_name, "original": Path(str(path)).name},
            assets={source_name: frames},
            inputs=(source_name,),
            changed_frames=tuple(frame.id for frame in frames.frames),
        )
        return {"asset": source_name, "kind": "source", "revision": report.revision}

    def source_classify(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .classify import classify_source  # noqa: PLC0415

        name = params.get("source") or params.get("asset")
        if not name:
            raise UsageError("missing source")
        return classify_source(self._load_frames(str(name)).frames[0].image).to_dict()

    def recover_apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .recovery import RecoverySpec, recover_frames  # noqa: PLC0415

        project = self._require_project()
        name = params.get("asset") or params.get("source")
        if not name:
            raise UsageError("missing asset")
        source = self._load_frames(str(name))
        target = str(params.get("as") or f"{name}_recovered")
        spec = RecoverySpec(
            algorithm=str(params.get("algorithm", "optimized")),  # type: ignore[arg-type]
            device=str(params.get("device", "auto")),
            k_colors=int(params.get("colors", params.get("kColors", 16))),
            pixel_size_override=float(
                params.get("detectedStep", params.get("pixelSize", 0.0))
            ),
        )
        result = recover_frames(
            [frame.image for frame in source.frames], spec, set_id=target
        )
        # Recovery mints metadata from images; retain labels/tags when counts match.
        recovered = result.frames
        if len(recovered.frames) == len(source.frames):
            recovered = replace(
                recovered,
                frames=tuple(
                    replace(new, label=old.label, tags=old.tags)
                    for old, new in zip(source.frames, recovered.frames)
                ),
            )
        report = project.commit(
            "recover.apply",
            params={
                "asset": name,
                "algorithm": spec.algorithm,
                "pixel_size": spec.pixel_size_override,
            },
            assets={target: recovered},
            inputs=(str(name),),
            changed_frames=tuple(frame.id for frame in recovered.frames),
            warnings=result.warnings,
            metrics=result.metrics,
            device=result.device,
        )
        return {
            "revision": report.revision,
            "outputs": list(report.outputs),
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def project_tree(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        project = self._require_project()

        sources = [
            {
                "id": path.stem,
                "label": path.name,
                "note": f"{path.stat().st_size // 1024} KB",
                "kind": "source",
                "frames": 1,
            }
            for path in sorted((project.root / "sources").glob("*"))
            if path.is_file()
        ]

        assets = []
        for name in project.asset_names():
            frame_set = project.load_asset(name)
            assets.append(
                {
                    "id": name,
                    "label": name,
                    "note": f"v{project.assets[name].version}",
                    "kind": "frameset" if len(frame_set) > 1 else "asset",
                    "frames": len(frame_set),
                }
            )

        return {
            "groups": [
                {"id": "sources", "label": "sources", "items": sources},
                {
                    "id": "assets",
                    "label": "assets",
                    "items": [a for a in assets if a["kind"] == "asset"],
                },
                {
                    "id": "framesets",
                    "label": "frame sets",
                    "items": [a for a in assets if a["kind"] == "frameset"],
                },
                {
                    "id": "clips",
                    "label": "clips",
                    "items": [
                        {"id": c, "label": c, "note": "", "kind": "clip", "frames": 0}
                        for c in project.manifest.get("clips", [])
                    ],
                },
            ]
        }

    def asset_frames(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project = self._require_project()
        name = params.get("asset")
        if not name:
            raise UsageError("missing asset name")

        if name in project.assets:
            return {"asset": name, "frames": self._frames_from_asset(project, name)}
        return {"asset": name, "frames": [self._frame_from_source(project, name)]}

    def _frames_from_asset(self, project: Project, name: str) -> list[dict[str, Any]]:
        version = project.assets[name].version
        frame_set = project.load_asset(name)
        directory = project.asset_dir(name, version)

        frames = []
        for index, frame in enumerate(frame_set.frames):
            # The committed PNG is already on disk; serving it directly beats
            # re-encoding a preview nobody asked for.
            frames.append(
                {
                    "id": frame.id,
                    "index": index,
                    "width": frame.size.width,
                    "height": frame.size.height,
                    "tags": [f"{k}={v}" for k, v in sorted(frame.tags.items())],
                    "durationMs": 100,
                    "path": str((directory / f"{frame.id}.png").resolve()),
                }
            )
        return frames

    def _frame_from_source(self, project: Project, name: str) -> dict[str, Any]:
        from .image_io import load_rgba, save_rgba  # noqa: PLC0415

        source_path = project.find_source(name)
        image = load_rgba(source_path)
        preview = self._cache_dir() / f"src_{name}.png"
        if (
            not preview.is_file()
            or preview.stat().st_mtime < source_path.stat().st_mtime
        ):
            save_rgba(image, preview, normalize=False)

        return {
            "id": name,
            "index": 0,
            "width": image.width,
            "height": image.height,
            "tags": [],
            "durationMs": 100,
            "path": str(preview.resolve()),
        }

    def export_apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Export one committed asset to a user-chosen directory.

        ``frames`` writes one PNG per frame; ``generic-json`` packs the frames
        into an atlas first.  Packing options are the same set the CLI exposes
        for ``export``.  Export never writes into the project and never bumps
        the revision history; the returned revision is the current head.
        """

        from .export import ExportSpec, export_atlas, export_frames  # noqa: PLC0415
        from .packing import PackSpec, pack_frames  # noqa: PLC0415

        project = self._require_project()
        asset = _param_str(params, "asset")
        if not asset:
            raise UsageError("missing asset")
        output = _param_str(params, "output")
        if not output:
            raise UsageError("missing output")

        fmt = _param_str(params, "format", default="generic-json")
        spec = ExportSpec(
            format=fmt,
            name=_param_str(params, "name", default="atlas"),
            overwrite=_param_bool(params, "overwrite", default=False),
        )
        frames = project.load_asset(asset)

        if fmt == "frames":
            bundle = export_frames(frames, output, spec)
        else:
            atlas = pack_frames(
                frames,
                PackSpec(
                    layout=_param_str(params, "layout", default="compact"),
                    columns=_param_int(params, "columns"),
                    padding=_param_int(params, "padding", default=0),
                    extrude=_param_int(params, "extrude", default=0),
                    trim=_param_bool(params, "trim", default=False),
                    max_size=_max_size_param(params),
                    multi_page=_param_bool(params, "multiPage", default=False),
                ),
            )
            bundle = export_atlas(atlas, output, spec)

        return {
            "asset": asset,
            "format": fmt,
            "directory": str(bundle.directory),
            "files": [
                {
                    "name": path.name,
                    "bytes": path.stat().st_size if path.is_file() else 0,
                }
                for path in bundle.files
            ],
            "revision": project.head_revision,
            "warnings": [w.to_dict() for w in bundle.warnings],
            "metrics": dict(bundle.metrics),
        }

    def _background_spec(self, params: Mapping[str, Any]):
        from .background import BackgroundSpec  # noqa: PLC0415

        return BackgroundSpec(
            mode=params.get("mode", "lab"),
            samples=params.get("samples", "corners"),
            tolerance=float(params.get("tolerance", 10.0)),
            connectivity=int(params.get("connectivity", 8)),
            border_only=bool(params.get("borderOnly", True)),
            min_island_area=int(params.get("minIslandArea", 0)),
            max_hole_area=int(params.get("maxHoleArea", 0)),
            alpha=params.get("alpha", "hard"),
            soft_range=float(params.get("softRange", 4.0)),
        )

    def background_apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Commit a background removal as a normal project revision."""

        from .background import remove_background  # noqa: PLC0415

        project = self._require_project()
        name = params.get("asset")
        if not name:
            raise UsageError("missing asset name")
        target = params.get("as") or f"{name}_clean"

        spec = self._background_spec(params)
        frames = project.load_asset(name)
        result = remove_background(frames, spec)

        report = project.commit(
            "background.remove",
            params={
                "asset": name,
                "mode": spec.mode,
                "tolerance": spec.tolerance,
                "connectivity": spec.connectivity,
                "alpha": spec.alpha,
                "as": target,
            },
            assets={target: result.frames, f"{target}_mask": result.masks},
            inputs=(name,),
            changed_frames=tuple(f.id for f in result.frames.frames),
            warnings=result.warnings,
            metrics=result.metrics,
        )
        return {
            "revision": report.revision,
            "outputs": list(report.outputs),
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def history_undo(self, params: Mapping[str, Any]) -> dict[str, Any]:
        report = self._require_project().undo(int(params.get("steps", 1)))
        return {
            "revision": report.revision,
            "changed": report.changed,
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def history_redo(self, params: Mapping[str, Any]) -> dict[str, Any]:
        report = self._require_project().redo(int(params.get("steps", 1)))
        return {
            "revision": report.revision,
            "changed": report.changed,
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def background_analyze(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Preview removal without writing anything.

        This is what a tolerance slider calls on every tick, so it renders the
        mask into ``cache/`` and hands back a path — the frontend never
        recomputes the mask itself (FRONTEND_PLAN.md 13.1).
        """

        from .background import remove_background  # noqa: PLC0415
        from .image_io import save_rgba  # noqa: PLC0415

        project = self._require_project()
        name = params.get("asset")
        if not name:
            raise UsageError("missing asset name")

        frames = project.load_asset(name)
        spec = self._background_spec(params)

        # remove_background already carries the analysis, so calling
        # analyze_background as well would compute every mask twice — on every
        # tick of a tolerance slider.
        result = remove_background(frames, spec)
        analysis = result.analysis

        version = project.assets[name].version if name in project.assets else 0
        previews = []
        for frame, mask in zip(result.frames.frames, result.masks.frames):
            # Cache keys cover the whole spec, so dragging a slider back and
            # forth reuses files instead of re-encoding, while changing any
            # other setting is guaranteed to miss.
            stem = self._preview_key(
                spec, asset=name, version=version, frame_id=frame.id
            )
            frame_path = self._cache_dir() / f"{stem}.png"
            mask_path = self._cache_dir() / f"{stem}_mask.png"
            if not frame_path.is_file():
                save_rgba(frame.image, frame_path)
            if not mask_path.is_file():
                save_rgba(mask.image, mask_path)
            previews.append(
                {
                    "id": frame.id,
                    "width": frame.image.size.width,
                    "height": frame.image.size.height,
                    "path": str(frame_path.resolve()),
                    "maskPath": str(mask_path.resolve()),
                }
            )

        self._prune_cache()

        return {
            "asset": name,
            "analysis": analysis.to_dict(),
            "frames": previews,
            "warnings": [w.to_dict() for w in result.warnings],
        }

    def outline_analyze(self, params: Mapping[str, Any]) -> dict[str, Any]:
        import numpy as np  # noqa: PLC0415

        from .image_io import save_rgba  # noqa: PLC0415
        from .model import RgbaImage  # noqa: PLC0415
        from .outline import apply_outline  # noqa: PLC0415

        name = params.get("asset")
        if not name:
            raise UsageError("missing asset")
        source = self._load_frames(str(name))
        result = apply_outline(source, self._outline_spec(params))
        previews = []
        fingerprint = hashlib.blake2b(
            json.dumps(dict(params), sort_keys=True, default=str).encode(),
            digest_size=8,
        ).hexdigest()
        for before, after in zip(source.frames, result.frames.frames):
            path = self._cache_dir() / f"outline_{name}_{after.id}_{fingerprint}.png"
            mask_path = (
                self._cache_dir() / f"outline_{name}_{after.id}_{fingerprint}_mask.png"
            )
            if not path.is_file():
                save_rgba(after.image, path)
            if not mask_path.is_file():
                changed = np.any(before.image.array != after.image.array, axis=2)
                mask = np.full((*changed.shape, 4), 255, dtype=np.uint8)
                mask[changed, 3] = 0
                save_rgba(RgbaImage(mask), mask_path, normalize=False)
            previews.append(
                {
                    "id": after.id,
                    "width": after.image.width,
                    "height": after.image.height,
                    "path": str(path.resolve()),
                    "maskPath": str(mask_path.resolve()),
                }
            )
        self._prune_cache()
        return {
            "asset": name,
            "analysis": dict(result.metrics),
            "frames": previews,
            "warnings": [w.to_dict() for w in result.warnings],
        }

    def outline_apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .outline import apply_outline  # noqa: PLC0415

        project = self._require_project()
        name = params.get("asset")
        if not name:
            raise UsageError("missing asset")
        target = str(params.get("as") or f"{name}_outlined")
        result = apply_outline(self._load_frames(str(name)), self._outline_spec(params))
        report = project.commit(
            "outline.apply",
            params=dict(params),
            assets={target: replace(result.frames, id=target)},
            inputs=(str(name),),
            changed_frames=tuple(frame.id for frame in result.frames.frames),
            warnings=result.warnings,
            metrics=result.metrics,
        )
        return {
            "revision": report.revision,
            "outputs": list(report.outputs),
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def pixelify_analyze(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .image_io import save_rgba  # noqa: PLC0415
        from .pixelify import pixelify_frames  # noqa: PLC0415

        name = params.get("asset") or params.get("source")
        if not name:
            raise UsageError("missing asset")
        result = pixelify_frames(
            self._load_frames(str(name)), self._pixelify_spec(params)
        )
        fingerprint = hashlib.blake2b(
            json.dumps(dict(params), sort_keys=True, default=str).encode(),
            digest_size=8,
        ).hexdigest()
        previews = []
        for frame in result.frames.frames:
            path = self._cache_dir() / f"pixelify_{name}_{frame.id}_{fingerprint}.png"
            if not path.is_file():
                save_rgba(frame.image, path)
            previews.append(
                {
                    "id": frame.id,
                    "width": frame.image.width,
                    "height": frame.image.height,
                    "path": str(path.resolve()),
                }
            )
        self._prune_cache()
        return {
            "asset": name,
            "analysis": dict(result.metrics),
            "frames": previews,
            "warnings": [w.to_dict() for w in result.warnings],
        }

    def pixelify_apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .pixelify import pixelify_frames  # noqa: PLC0415

        project = self._require_project()
        name = params.get("asset") or params.get("source")
        if not name:
            raise UsageError("missing asset")
        target = str(params.get("as") or f"{name}_px")
        result = pixelify_frames(
            self._load_frames(str(name)), self._pixelify_spec(params)
        )
        report = project.commit(
            "pixelify.apply",
            params=dict(params),
            assets={target: replace(result.frames, id=target)},
            inputs=(str(name),),
            changed_frames=tuple(frame.id for frame in result.frames.frames),
            warnings=result.warnings,
            metrics=result.metrics,
        )
        return {
            "revision": report.revision,
            "outputs": list(report.outputs),
            "warnings": [w.to_dict() for w in report.warnings],
            "metrics": dict(report.metrics),
        }

    def generate_providers(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        info = self.generation_provider.probe()
        return {
            "available": True,
            "provider": info.name,
            "models": [{"id": model, "label": model} for model in info.models],
            "styles": [
                {"id": style, "label": "像素画" if style == "pixel" else style}
                for style in info.styles
            ],
        }

    def generate_submit(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project = self._require_project()
        prompt = str(params.get("prompt", "")).strip()
        if not prompt:
            raise UsageError("generation prompt is empty")
        count = int(params.get("count", 4))
        if not 1 <= count <= 8:
            raise UsageError("generation count must be 1..8", count=count)
        request = GenerationRequest(
            prompt=prompt,
            negative=str(params.get("negative", "")),
            model=str(params.get("model", "default")),
            style=str(params.get("style", "pixel")),
            count=count,
            size=int(params.get("size", 512)),
            steps=int(params.get("steps", 20)),
            cfg=float(params.get("cfg", 7)),
            seed=int(params.get("seed", int(time.time()) & 0x7FFFFFFF)),
        )

        def worker(context: JobContext) -> dict[str, Any]:
            output_dir = project.root / "cache" / "generated" / context.job_id
            generated = self.generation_provider.generate(
                request, output_dir, context.progress, context.cancel_event.is_set
            )
            candidates = []
            for index, candidate in enumerate(generated):
                candidate_id = f"cand_{context.job_id}_{index}"
                stored = replace(candidate, id=candidate_id)
                self._candidates[candidate_id] = {
                    "candidate": stored,
                    "request": request,
                }
                candidates.append(
                    {
                        "id": candidate_id,
                        "seed": stored.seed,
                        "path": str(stored.path.resolve()),
                    }
                )
            return {
                "candidates": candidates,
                "prompt": request.prompt,
                "model": request.model,
            }

        job_id = self.jobs.prepare("生成", worker)
        self._pending_jobs.append(job_id)
        return {"job": job_id, "label": "生成"}

    def generate_commit(self, params: Mapping[str, Any]) -> dict[str, Any]:
        from .classify import classify_source  # noqa: PLC0415
        from .image_io import load_rgba  # noqa: PLC0415
        from .model import WorkshopWarning  # noqa: PLC0415
        from .pixelify import PixelifySpec, pixelify_frames  # noqa: PLC0415
        from .recovery import RecoverySpec, recover_frames  # noqa: PLC0415

        project = self._require_project()
        picked = [str(value) for value in params.get("candidates", [])]
        if not picked:
            raise UsageError("no generated candidates selected")
        missing = [
            candidate for candidate in picked if candidate not in self._candidates
        ]
        if missing:
            raise NotFoundError("generated candidate not found", candidates=missing)
        assets: dict[str, FrameSet] = {}
        warnings: list[WorkshopWarning] = []
        recovered_any = False
        provenance = []
        base = str(params.get("as") or f"generated_{project.head_revision + 1}")
        for index, candidate_id in enumerate(picked):
            entry = self._candidates[candidate_id]
            candidate = entry["candidate"]
            image = load_rgba(candidate.path)
            target = base if len(picked) == 1 else f"{base}_{index + 1}"
            size = image.size
            source_frame = Frame(
                target,
                image,
                size,
                Rect(0, 0, size.width, size.height),
                Point(0, 0),
                Point(size.width // 2, max(0, size.height - 1)),
                target,
            )
            source_set = FrameSet(target, (source_frame,), size)
            classification = classify_source(image)
            output = None
            if (
                bool(params.get("recover", True))
                and classification.kind == "pixel-art"
                and classification.detected_step > 1
            ):
                try:
                    recovered = recover_frames(
                        [image],
                        RecoverySpec(
                            pixel_size_override=float(classification.detected_step)
                        ),
                        set_id=target,
                    )
                    output = replace(
                        recovered.frames,
                        id=target,
                        frames=(replace(recovered.frames.frames[0], id=target),),
                    )
                    recovered_any = True
                    warnings.extend(recovered.warnings)
                except Exception as error:
                    # Recovery is an optional ROCm/Torch path.  A generated
                    # image must remain committable on CPU-only workstations.
                    reason = (
                        error.message
                        if isinstance(error, WorkshopError)
                        else str(error)
                    )
                    warnings.append(
                        WorkshopWarning(
                            "generate.recover_fallback",
                            "自动修复失败，已改用像素化",
                            {"reason": reason},
                        )
                    )
            if output is None:
                pixelified = pixelify_frames(
                    source_set,
                    PixelifySpec(
                        target_width=int(params.get("targetWidth", 64)),
                        colors=int(params.get("colors", 32)),
                    ),
                )
                output = replace(
                    pixelified.frames,
                    id=target,
                    frames=(replace(pixelified.frames.frames[0], id=target),),
                )
                warnings.extend(pixelified.warnings)
            raw_name = f"{target}_raw"
            project.import_source(candidate.path, as_name=raw_name)
            assets[target] = output
            provenance.append(
                {
                    "candidate": candidate_id,
                    "seed": candidate.seed,
                    "raw_source": raw_name,
                    "classification": classification.to_dict(),
                    "prompt": entry["request"].prompt,
                    "model": entry["request"].model,
                }
            )
        report = project.commit(
            "generate.commit",
            params={
                "candidates": provenance,
                "auto_recover": bool(params.get("recover", True)),
            },
            assets=assets,
            inputs=tuple(item["raw_source"] for item in provenance),
            changed_frames=tuple(
                frame.id for frames in assets.values() for frame in frames.frames
            ),
            warnings=warnings,
        )
        for candidate_id in picked:
            self._candidates.pop(candidate_id, None)
        return {
            "revision": report.revision,
            "outputs": list(report.outputs),
            "warnings": [w.to_dict() for w in report.warnings],
            "recovered": recovered_any,
        }

    def job_cancel(self, params: Mapping[str, Any]) -> dict[str, Any]:
        job_id = str(params.get("job", ""))
        if not job_id:
            raise UsageError("missing job id")
        cancelled = self.jobs.cancel(job_id)
        return {"job": job_id, "cancelled": cancelled}

    def history_list(self, params: Mapping[str, Any]) -> dict[str, Any]:
        project = self._require_project()
        limit = int(params.get("limit", 50))
        entries = [
            {
                "revision": record.revision,
                "parent": record.parent_revision,
                "operation": record.operation,
                "frames": len(record.changed_frames),
                "warnings": len(record.warnings),
                "at": record.created_at.replace("T", " ").replace("+00:00", ""),
            }
            for record in project.history(limit=limit)
        ]
        return {
            "head_revision": project.head_revision,
            "redo_stack": project.redo_stack,
            "entries": entries,
        }

    # ----------------------------------------------------------- transport

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        if method == "$cancel":
            job_id = str(params.get("job", ""))
            if job_id:
                self.jobs.cancel(job_id)
            return None

        impl = self.methods.get(method)
        if impl is None:
            return {
                "id": request_id,
                "ok": False,
                "command": method,
                "error": {
                    "code": ExitCode.USAGE,
                    "message": f"unknown method: {method}",
                    "details": None,
                },
            }

        started = time.perf_counter()
        try:
            result = impl(params)
        except WorkshopError as error:
            log(f"error {method} code={error.code} {error.message}")
            return {
                "id": request_id,
                "ok": False,
                "command": method,
                "error": error.to_dict(),
            }
        except Exception as error:  # unknown failures map to 4, never crash the daemon
            log(f"unhandled {method}: {error}\n{traceback.format_exc()}")
            return {
                "id": request_id,
                "ok": False,
                "command": method,
                "error": {
                    "code": ExitCode.FAILED,
                    "message": str(error),
                    "details": None,
                },
            }

        return {
            "id": request_id,
            "ok": True,
            "command": method,
            "project": str(self.project.root) if self.project else None,
            "revision": self.project.head_revision if self.project else None,
            "outputs": [],
            "warnings": [],
            "metrics": {"elapsed_ms": round((time.perf_counter() - started) * 1000, 2)},
            "result": result,
        }

    def serve(self) -> int:
        log(f"started pid={__import__('os').getpid()} python={sys.version.split()[0]}")
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                log("malformed line dropped")
                continue

            reply = self.handle(message)
            if reply is None:
                continue
            self._write_message(reply)
            # Submit replies must become observable before a fast worker can
            # emit progress/job.done; otherwise the renderer has no waiter yet.
            self.start_pending_jobs()

        log("stdin closed, exiting")
        self.jobs.shutdown()
        return 0

    def start_pending_jobs(self) -> None:
        pending, self._pending_jobs = self._pending_jobs, []
        for job_id in pending:
            self.jobs.start(job_id)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--stdio" not in args:
        sys.stderr.write("usage: python -m sprite_workshop.daemon --stdio\n")
        return ExitCode.USAGE
    # UTF-8 on both pipes: Windows would otherwise pick a legacy code page and
    # mangle Chinese project names.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    return Daemon().serve()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
