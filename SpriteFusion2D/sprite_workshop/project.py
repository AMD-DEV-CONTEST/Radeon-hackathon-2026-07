"""Project directory, revisions, and atomic commits.

A ``.spritework`` project is a readable directory, not a database.  The manifest
is the only pointer into it, so an interrupted write leaves unreachable files
rather than a corrupt project (BACKEND_CLI_PLAN.md 7).

Revisions form a tree: every record carries ``parent_revision`` and the manifest
carries a ``redo_stack``.  That is what makes "undo to 5, then do something new"
expressible instead of ambiguous (BACKEND_CLI_PLAN.md 7.2).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .errors import NotFoundError, OperationError, RefusedError, UsageError
from .ids import ID_PATTERN, validate_id
from .image_io import load_rgba, save_rgba
from .model import (
    AssetRef,
    Frame,
    FrameSet,
    OperationReport,
    Point,
    Rect,
    Size,
    WorkshopWarning,
)

SCHEMA_VERSION = 1
PROJECT_SUFFIX = ".spritework"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = ".lock"


def _process_is_alive(pid: int) -> bool:
    """Best-effort liveness check, used only to break abandoned locks."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Someone else's process: it exists, we just cannot signal it.
        return True
    except OSError:
        # Windows raises OSError for a dead pid; assume gone rather than
        # wedging the project behind a lock nobody holds.
        return False
    return True


class ProjectLock:
    """Exclusive writer lock over one project directory.

    `RefusedError` has documented "or the lock is held" since the first
    version, but nothing ever took a lock: the daemon and a CLI run could
    commit to one project concurrently and the second manifest write simply
    won.  `O_CREAT | O_EXCL` is the atomic primitive on both POSIX and
    Windows.  A lock whose owning process is gone is broken automatically,
    because the alternative is a project that stays unusable after a crash.
    """

    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_NAME
        self._fd: int | None = None

    def _holder(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def acquire(self) -> "ProjectLock":
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = self._holder()
            pid = int(holder.get("pid", 0) or 0)
            if _process_is_alive(pid):
                raise RefusedError(
                    "project is locked by another process",
                    path=str(self.path),
                    pid=pid,
                    since=holder.get("at", ""),
                ) from None
            # Stale: the owner died without releasing.
            self.path.unlink(missing_ok=True)
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise RefusedError(
                    "project is locked by another process",
                    path=str(self.path),
                ) from None

        from datetime import datetime, timezone  # noqa: PLC0415

        payload = json.dumps(
            {
                "pid": os.getpid(),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        os.write(self._fd, payload.encode("utf-8"))
        return self

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> "ProjectLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write UTF-8 JSON with fixed indent, atomically (BACKEND_CLI_PLAN.md 5.2).

    The temp name is unique rather than ``<name>.tmp``: the daemon and a CLI
    invocation can touch one project at the same time, and a shared temp name
    means one writer's partial content lands under the other's ``os.replace``.
    Data is fsynced before the rename so a crash cannot publish a truncated
    manifest.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise NotFoundError("file not found", path=str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperationError("invalid JSON", path=str(path), reason=str(exc)) from exc


def _check_relative(value: str) -> str:
    """Reject anything that could escape the project directory."""

    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive:
        raise RefusedError("path must be project-relative", path=value)
    if ".." in candidate.parts:
        raise RefusedError("path must not traverse upwards", path=value)
    return value


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision: int
    parent_revision: int | None
    operation: str
    params: Mapping[str, Any]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    changed_frames: tuple[str, ...]
    renames: Mapping[str, str]
    assets_after: Mapping[str, int]
    warnings: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]
    tool_version: str
    device: str
    dependencies: Mapping[str, str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": self.revision,
            "parent_revision": self.parent_revision,
            "operation": self.operation,
            "params": dict(self.params),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "changed_frames": list(self.changed_frames),
            "renames": dict(self.renames),
            "assets_after": dict(self.assets_after),
            "warnings": [dict(w) for w in self.warnings],
            "metrics": dict(self.metrics),
            "tool_version": self.tool_version,
            "device": self.device,
            "dependencies": dict(self.dependencies),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RevisionRecord":
        return cls(
            revision=int(data["revision"]),
            parent_revision=data.get("parent_revision"),
            operation=str(data["operation"]),
            params=data.get("params", {}),
            inputs=tuple(data.get("inputs", ())),
            outputs=tuple(data.get("outputs", ())),
            changed_frames=tuple(data.get("changed_frames", ())),
            renames=data.get("renames", {}),
            assets_after=data.get("assets_after", {}),
            warnings=tuple(data.get("warnings", ())),
            metrics=data.get("metrics", {}),
            tool_version=str(data.get("tool_version", "")),
            device=str(data.get("device", "")),
            dependencies=data.get("dependencies", {}),
            created_at=str(data.get("created_at", "")),
        )


class Project:
    """An opened ``.spritework`` directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / MANIFEST_NAME
        self.manifest: dict[str, Any] = _read_json(self.manifest_path)
        self._validate_manifest()

    # ------------------------------------------------------------------ setup

    @classmethod
    def plan_init(
        cls,
        path: str | os.PathLike[str],
        *,
        project_id: str | None = None,
    ) -> tuple[Path, str]:
        """Run every `init` check and return ``(root, project_id)``.

        Split out so ``--dry-run init`` can refuse exactly what a real init
        would refuse without creating anything.
        """

        root = Path(path)
        if root.exists() and any(root.iterdir()):
            raise RefusedError("target directory is not empty", path=str(root))

        derived_id = project_id or root.name
        if derived_id.endswith(PROJECT_SUFFIX):
            derived_id = derived_id[: -len(PROJECT_SUFFIX)]
        derived_id = derived_id.lower()
        # Chinese names are welcome as display names but never as identifiers,
        # because the id ends up in filenames and engine metadata.  Rather than
        # transliterate behind the user's back, ask for one explicitly.
        if not ID_PATTERN.match(derived_id):
            raise UsageError(
                "project id must be lowercase ascii; pass --id explicitly "
                "and keep the localized name in --name",
                derived_from=root.name,
                example="--id chouko --name 蝶子",
            )
        validate_id(derived_id, what="project id")
        return root, derived_id

    @classmethod
    def init(
        cls,
        path: str | os.PathLike[str],
        *,
        name: str | None = None,
        project_id: str | None = None,
    ) -> "Project":
        root, derived_id = cls.plan_init(path, project_id=project_id)

        for sub in ("sources", "assets", "revisions", "recipes", "cache", "exports"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_id": derived_id.lower(),
            "name": name or derived_id,
            "head_revision": 0,
            "redo_stack": [],
            "assets": {},
            "clips": [],
            "palette": None,
            "defaults": {
                "device": "auto",
                "algorithm": "optimized",
                "alpha_mode": "hard",
            },
        }
        _write_json(root / MANIFEST_NAME, manifest)
        return cls(root)

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "Project":
        root = Path(path)
        if not (root / MANIFEST_NAME).is_file():
            raise NotFoundError("not a Sprite Workshop project", path=str(root))
        return cls(root)

    def _validate_manifest(self) -> None:
        version = self.manifest.get("schema_version")
        if version != SCHEMA_VERSION:
            # Refuse rather than guess: silent migration is how projects rot.
            raise OperationError(
                "unsupported project schema version",
                found=version,
                supported=SCHEMA_VERSION,
            )

    # -------------------------------------------------------------- accessors

    @property
    def head_revision(self) -> int:
        return int(self.manifest["head_revision"])

    @property
    def redo_stack(self) -> list[int]:
        return list(self.manifest.get("redo_stack", []))

    @property
    def assets(self) -> dict[str, AssetRef]:
        return {
            name: AssetRef(name=name, version=int(entry["version"]))
            for name, entry in self.manifest.get("assets", {}).items()
        }

    def asset_names(self) -> list[str]:
        return sorted(self.manifest.get("assets", {}))

    def lock(self) -> ProjectLock:
        """Take the exclusive writer lock for this project."""

        return ProjectLock(self.root).acquire()

    def revision_path(self, revision: int) -> Path:
        return self.root / "revisions" / f"{revision:06d}.json"

    def read_revision(self, revision: int) -> RevisionRecord:
        return RevisionRecord.from_dict(_read_json(self.revision_path(revision)))

    def history(self, limit: int | None = None) -> list[RevisionRecord]:
        """Walk the ancestry chain from head backwards."""

        records: list[RevisionRecord] = []
        current: int | None = self.head_revision
        while current and current > 0:
            record = self.read_revision(current)
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
            current = record.parent_revision
        return records

    # ----------------------------------------------------------------- assets

    def asset_dir(self, name: str, version: int) -> Path:
        return self.root / "assets" / name / f"v{version:04d}"

    def load_asset(self, name: str, version: int | None = None) -> FrameSet:
        refs = self.assets
        if version is None:
            if name not in refs:
                raise NotFoundError(
                    "asset not found", asset=name, known=self.asset_names()
                )
            version = refs[name].version

        meta_path = self.asset_dir(name, version) / "meta.json"
        if not meta_path.is_file():
            raise NotFoundError("asset version not found", asset=name, version=version)

        meta = _read_json(meta_path)
        frames: list[Frame] = []
        for entry in meta["frames"]:
            # `file` is not the only field that becomes a path.  A frame id is
            # concatenated into a filename by _write_asset_version, by the
            # frames exporter, and by the daemon when it hands a preview path
            # to the frontend, so an id read back off disk has to clear the
            # same bar as one we minted.
            validate_id(entry["id"], what="frame id")
            image = load_rgba(
                self.asset_dir(name, version) / _check_relative(entry["file"])
            )
            frames.append(
                Frame(
                    id=entry["id"],
                    image=image,
                    source_size=Size(*entry["source_size"]),
                    trim_rect=Rect(*entry["trim_rect"]),
                    trim_offset=Point(*entry["trim_offset"]),
                    anchor=Point(*entry["anchor"]),
                    label=entry.get("label", ""),
                    tags=dict(entry.get("tags", {})),
                )
            )
        canvas = meta.get("canvas_size")
        return FrameSet(
            id=meta["id"],
            frames=tuple(frames),
            canvas_size=Size(*canvas) if canvas else None,
        )

    def _write_asset_version(
        self, name: str, frame_set: FrameSet, version: int
    ) -> None:
        target = self.asset_dir(name, version)
        target.mkdir(parents=True, exist_ok=True)

        entries: list[dict[str, Any]] = []
        for frame in frame_set.frames:
            file_name = f"{frame.id}.png"
            save_rgba(frame.image, target / file_name)
            entries.append(
                {
                    "id": frame.id,
                    "label": frame.label,
                    "file": file_name,
                    "size": list(frame.size.as_tuple()),
                    "source_size": list(frame.source_size.as_tuple()),
                    "trim_rect": list(frame.trim_rect.as_tuple()),
                    "trim_offset": list(frame.trim_offset.as_tuple()),
                    "anchor": list(frame.anchor.as_tuple()),
                    "tags": dict(frame.tags),
                }
            )

        _write_json(
            target / "meta.json",
            {
                "schema_version": SCHEMA_VERSION,
                "id": frame_set.id,
                "canvas_size": list(frame_set.canvas_size.as_tuple())
                if frame_set.canvas_size
                else None,
                "frames": entries,
            },
        )

    # ---------------------------------------------------------------- sources

    def import_source(self, path: str | os.PathLike[str], *, as_name: str) -> Path:
        """Copy a file into ``sources/`` byte-for-byte.

        Sources keep their original bytes; the transparent-RGB normalisation of
        5.1 happens when data enters ``assets/`` (BACKEND_CLI_PLAN.md 7.2).
        """

        validate_id(as_name, what="source name")
        origin = Path(path)
        if not origin.is_file():
            raise NotFoundError("source file not found", path=str(origin))

        target = self.root / "sources" / f"{as_name}{origin.suffix.lower()}"
        if target.exists():
            raise RefusedError("source already exists", name=as_name, path=str(target))
        target.write_bytes(origin.read_bytes())
        return target

    def find_source(self, as_name: str) -> Path:
        matches = sorted((self.root / "sources").glob(f"{as_name}.*"))
        if not matches:
            raise NotFoundError("source not found", name=as_name)
        return matches[0]

    # ----------------------------------------------------------------- commit

    def commit(
        self,
        operation: str,
        *,
        params: Mapping[str, Any] | None = None,
        assets: Mapping[str, FrameSet] | None = None,
        inputs: Sequence[str] = (),
        changed_frames: Sequence[str] = (),
        renames: Mapping[str, str] | None = None,
        warnings: Iterable[WorkshopWarning] = (),
        metrics: Mapping[str, Any] | None = None,
        device: str = "",
    ) -> OperationReport:
        """Write one revision atomically.

        Asset payloads land first; the manifest replace at the end is the single
        atomic act that makes them reachable.
        """

        all_warnings = list(warnings)
        assets = dict(assets or {})

        # New work while a redo branch exists abandons that branch, loudly.
        redo = self.redo_stack
        if redo:
            all_warnings.append(
                WorkshopWarning(
                    code="history.forked",
                    message=f"abandoned {len(redo)} redo step(s) by committing from history",
                    details={"abandoned": redo},
                )
            )

        # Everything from here on reads then writes shared state, so it runs
        # under the writer lock: two concurrent commits would otherwise pick
        # the same revision number and the loser's manifest would win.
        with ProjectLock(self.root):
            return self._commit_locked(
                operation,
                params=params,
                assets=assets,
                inputs=inputs,
                changed_frames=changed_frames,
                renames=renames,
                all_warnings=all_warnings,
                metrics=metrics,
                device=device,
            )

    def _commit_locked(
        self,
        operation: str,
        *,
        params: Mapping[str, Any] | None,
        assets: Mapping[str, FrameSet],
        inputs: Sequence[str],
        changed_frames: Sequence[str],
        renames: Mapping[str, str] | None,
        all_warnings: list[WorkshopWarning],
        metrics: Mapping[str, Any] | None,
        device: str,
    ) -> OperationReport:
        from datetime import datetime, timezone  # noqa: PLC0415

        next_revision = self._next_revision_number()
        asset_versions = {name: ref.version for name, ref in self.assets.items()}

        for name, frame_set in assets.items():
            validate_id(name, what="asset name")
            asset_versions[name] = self._next_asset_version(name)
            self._write_asset_version(name, frame_set, asset_versions[name])

        record = RevisionRecord(
            revision=next_revision,
            parent_revision=self.head_revision or None,
            operation=operation,
            params=dict(params or {}),
            inputs=tuple(inputs),
            outputs=tuple(sorted(assets)),
            changed_frames=tuple(changed_frames),
            renames=dict(renames or {}),
            assets_after=dict(asset_versions),
            warnings=tuple(w.to_dict() for w in all_warnings),
            metrics=dict(metrics or {}),
            tool_version=_tool_version(),
            device=device,
            dependencies=_dependency_versions(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        _write_json(self.revision_path(next_revision), record.to_dict())

        self.manifest["head_revision"] = next_revision
        self.manifest["redo_stack"] = []
        self.manifest["assets"] = {
            name: {"version": version}
            for name, version in sorted(asset_versions.items())
        }
        _write_json(self.manifest_path, self.manifest)

        return OperationReport(
            operation=operation,
            changed=True,
            revision=next_revision,
            outputs=tuple(sorted(assets)),
            warnings=tuple(all_warnings),
            metrics=dict(metrics or {}),
        )

    def _next_revision_number(self) -> int:
        existing = [
            int(p.stem)
            for p in (self.root / "revisions").glob("*.json")
            if p.stem.isdigit()
        ]
        return (max(existing) + 1) if existing else 1

    def _next_asset_version(self, name: str) -> int:
        """Return a version number no committed revision can already own.

        Revisions form a tree, so the manifest's current version is *not* a
        high-water mark: after an undo it points back at an older version and
        `manifest + 1` would land on a number a revision on the abandoned
        branch already wrote.  That silently rewrote the pixels an existing
        revision record still pointed at.  Versions are therefore allocated
        from what is on disk, which only ever grows.
        """

        directory = self.root / "assets" / name
        existing = [
            int(path.name[1:])
            for path in directory.glob("v*")
            if path.is_dir() and path.name[1:].isdigit()
        ]
        return (max(existing) + 1) if existing else 1

    # ------------------------------------------------------------ undo / redo

    def undo(self, steps: int = 1) -> OperationReport:
        if steps < 1:
            raise UsageError("steps must be at least one", steps=steps)

        with ProjectLock(self.root):
            redo = self.redo_stack
            moved = 0
            for _ in range(steps):
                head = self.head_revision
                if head <= 0:
                    break
                record = self.read_revision(head)
                redo.append(head)
                self.manifest["head_revision"] = record.parent_revision or 0
                moved += 1

            self._reapply_asset_state()
            self.manifest["redo_stack"] = redo
            _write_json(self.manifest_path, self.manifest)

        warnings: tuple[WorkshopWarning, ...] = ()
        if moved < steps:
            warnings = (
                WorkshopWarning(
                    code="history.at_start",
                    message=f"only {moved} step(s) could be undone",
                ),
            )
        return OperationReport(
            operation="history.undo",
            changed=moved > 0,
            revision=self.head_revision,
            warnings=warnings,
            metrics={"undone": moved},
        )

    def redo(self, steps: int = 1) -> OperationReport:
        if steps < 1:
            raise UsageError("steps must be at least one", steps=steps)

        with ProjectLock(self.root):
            redo = self.redo_stack
            moved = 0
            for _ in range(steps):
                if not redo:
                    break
                self.manifest["head_revision"] = redo.pop()
                moved += 1

            self._reapply_asset_state()
            self.manifest["redo_stack"] = redo
            _write_json(self.manifest_path, self.manifest)

        warnings: tuple[WorkshopWarning, ...] = ()
        if moved < steps:
            warnings = (
                WorkshopWarning(
                    code="history.at_end",
                    message=f"only {moved} step(s) could be redone",
                ),
            )
        return OperationReport(
            operation="history.redo",
            changed=moved > 0,
            revision=self.head_revision,
            warnings=warnings,
            metrics={"redone": moved},
        )

    def preview_undo(self, steps: int = 1) -> tuple[int, int]:
        """Return ``(target_revision, steps_possible)`` without moving the head."""

        if steps < 1:
            raise UsageError("steps must be at least one", steps=steps)
        head = self.head_revision
        moved = 0
        for _ in range(steps):
            if head <= 0:
                break
            head = self.read_revision(head).parent_revision or 0
            moved += 1
        return head, moved

    def preview_redo(self, steps: int = 1) -> tuple[int, int]:
        """Return ``(target_revision, steps_possible)`` without moving the head."""

        if steps < 1:
            raise UsageError("steps must be at least one", steps=steps)
        redo = self.redo_stack
        moved = min(steps, len(redo))
        if moved == 0:
            return self.head_revision, 0
        return redo[len(redo) - moved], moved

    def _reapply_asset_state(self) -> None:
        """Resolve asset versions for the current head.

        Each revision stores the full name->version map after it, so moving the
        head is a lookup rather than a replay.  The maps are tiny; diffing them
        would buy nothing and cost correctness.
        """

        head = self.head_revision
        if head <= 0:
            self.manifest["assets"] = {}
            return
        record = self.read_revision(head)
        self.manifest["assets"] = {
            name: {"version": version}
            for name, version in sorted(record.assets_after.items())
        }


def _tool_version() -> str:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("comfyui-spritefusion-pixel-snapper")
    except Exception:
        return "0.0.0+dev"


def _dependency_versions() -> dict[str, str]:
    """Record only dependencies that can actually change pixel results."""

    import numpy  # noqa: PLC0415

    versions: dict[str, str] = {"numpy": numpy.__version__}
    # Torch is genuinely optional at this layer: nothing but recovery needs it.
    try:
        import torch  # noqa: PLC0415

        versions["torch"] = torch.__version__
    except Exception:
        pass
    return versions
