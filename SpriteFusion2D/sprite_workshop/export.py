"""Write finished assets outside the project.

Everything is staged first and committed at the end, so a failure halfway
through cannot leave a half-written atlas next to a valid JSON
(BACKEND_CLI_PLAN.md 8.9).

Scope note: only ``generic-json`` and ``frames`` are implemented.  The godot /
unity / rpgmaker presets from the plan are *not* here — a preset that emits
plausible-looking but untested files is worse than an honest "not yet", so
``ExportSpec`` rejects them by name.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .errors import RefusedError, UsageError
from .image_io import save_rgba
from .model import FrameSet, WorkshopWarning
from .packing import AtlasBundle

ExportFormat = Literal["generic-json", "frames"]

FORMATS: tuple[ExportFormat, ...] = ("generic-json", "frames")
PLANNED_PRESETS = ("godot", "unity", "rpgmaker")


def _check_plain_name(name: str) -> None:
    """Reject export names that could escape the destination directory.

    The name becomes part of a file name inside the target directory
    (``{name}.json``), so it must be a single path component: no ``/`` or
    ``\\`` separators, no ``..``, no drive, no absolute path.  Both separator
    characters are rejected explicitly so the behaviour is the same on Windows
    and POSIX.
    """

    candidate = Path(name)
    if (
        candidate.is_absolute()
        or candidate.drive
        or ".." in candidate.parts
        or "/" in name
        or "\\" in name
    ):
        raise UsageError("export name must be a plain file name", name=name)


@dataclass(frozen=True, slots=True)
class ExportSpec:
    format: ExportFormat = "generic-json"
    name: str = "atlas"
    overwrite: bool = False

    def __post_init__(self) -> None:
        if self.format in PLANNED_PRESETS:
            raise UsageError(
                f"the {self.format} preset is not implemented yet; "
                "export generic-json and convert, or ask for it to be built",
                available=list(FORMATS),
            )
        if self.format not in FORMATS:
            raise UsageError(
                "unknown export format", format=self.format, available=list(FORMATS)
            )
        if not isinstance(self.name, str) or not self.name:
            raise UsageError("export name must be a non-empty string", name=self.name)
        _check_plain_name(self.name)


@dataclass(frozen=True, slots=True)
class ExportBundle:
    directory: Path
    files: tuple[Path, ...]
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "files": [
                {"name": p.name, "bytes": p.stat().st_size if p.is_file() else 0}
                for p in self.files
            ],
            "warnings": [w.to_dict() for w in self.warnings],
            "metrics": dict(self.metrics),
        }


def _atlas_files(atlas: AtlasBundle, spec: ExportSpec) -> list[str]:
    return [f"{spec.name}.json"] + [f"page_{p.index}.png" for p in atlas.pages]


def _frame_files(frames: FrameSet) -> list[str]:
    return [f"{frame.id}.png" for frame in frames.frames]


def export_atlas(
    atlas: AtlasBundle,
    destination: str | os.PathLike[str],
    spec: ExportSpec = ExportSpec(),
) -> ExportBundle:
    """Write atlas pages plus the generic JSON description."""

    if spec.format != "generic-json":
        raise UsageError("export_atlas only writes generic-json", format=spec.format)
    return _write(destination, spec, _atlas_files(atlas, spec), _emit_atlas, atlas)


def export_frames(
    frames: FrameSet,
    destination: str | os.PathLike[str],
    spec: ExportSpec = ExportSpec(format="frames"),
) -> ExportBundle:
    """Write one PNG per frame."""

    if spec.format != "frames":
        raise UsageError(
            "export_frames only writes a frame sequence", format=spec.format
        )
    if len(frames) == 0:
        raise UsageError("frame set is empty", frame_set=frames.id)
    return _write(destination, spec, _frame_files(frames), _emit_frames, frames)


def _write(
    destination: str | os.PathLike[str],
    spec: ExportSpec,
    planned: Sequence[str],
    emit,
    payload,
) -> ExportBundle:
    target = Path(destination)

    # Refuse before doing any work, and only for the files this run would
    # actually write — an unrelated file in the directory is not our business
    # (BACKEND_CLI_PLAN.md 8.9).
    if not spec.overwrite:
        clashes = [name for name in planned if (target / name).exists()]
        if clashes:
            raise RefusedError(
                "refusing to overwrite existing output; pass overwrite",
                directory=str(target),
                files=clashes,
            )

    staging = target.parent / f".{target.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        written = emit(payload, staging, spec)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    target.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for path in written:
        final = target / path.name
        os.replace(path, final)
        files.append(final)
    shutil.rmtree(staging, ignore_errors=True)

    return ExportBundle(
        directory=target,
        files=tuple(files),
        metrics={"format": spec.format, "files": len(files)},
    )


def _emit_atlas(atlas: AtlasBundle, staging: Path, spec: ExportSpec) -> list[Path]:
    written: list[Path] = []
    for page in atlas.pages:
        written.append(save_rgba(page.image, staging / f"page_{page.index}.png"))

    payload = atlas.to_dict()
    json_path = staging / f"{spec.name}.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(json_path)
    return written


def _emit_frames(frames: FrameSet, staging: Path, _spec: ExportSpec) -> list[Path]:
    return [
        save_rgba(frame.image, staging / f"{frame.id}.png") for frame in frames.frames
    ]
