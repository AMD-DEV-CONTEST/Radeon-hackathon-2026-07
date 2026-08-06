from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from colorgraph.config import settings
from colorgraph.domain.grade_graph import GradeGraph


def _safe_stem(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return normalized[:48] or "project"


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    id: str
    root: Path
    input_dir: Path
    frames_dir: Path
    masks_dir: Path
    previews_dir: Path
    outputs_dir: Path
    graph_path: Path


@dataclass(frozen=True, slots=True)
class ImportedSource:
    path: Path
    mode: str


def _relocated_project_path(
    project: ProjectPaths,
    value: str,
    *,
    fallback_directory: Path,
) -> str:
    recorded = Path(value)
    if recorded.exists():
        return str(recorded.resolve())

    portable = PureWindowsPath(value)
    candidates: list[Path] = []
    if not recorded.is_absolute():
        candidates.extend(
            [
                project.root / recorded,
                fallback_directory / recorded,
            ]
        )
    matching_indices = [
        index
        for index, part in enumerate(portable.parts)
        if part.casefold() == project.id.casefold()
    ]
    if matching_indices:
        suffix = portable.parts[matching_indices[-1] + 1 :]
        if suffix:
            candidates.append(project.root.joinpath(*suffix))
    if portable.name:
        candidates.append(fallback_directory / portable.name)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return value


def _relocate_loaded_graph(project: ProjectPaths, graph: GradeGraph) -> GradeGraph:
    media = graph.media.model_copy(
        update={
            "path": _relocated_project_path(
                project,
                graph.media.path,
                fallback_directory=project.input_dir,
            )
        }
    )
    shots = [
        shot.model_copy(
            update={
                "representative_frame": _relocated_project_path(
                    project,
                    shot.representative_frame,
                    fallback_directory=project.frames_dir,
                )
            }
        )
        if shot.representative_frame
        else shot
        for shot in graph.shots
    ]
    masks = []
    for asset in graph.masks:
        metadata = dict(asset.metadata)
        for key, fallback_directory in (
            ("video_path", project.masks_dir),
            ("source_path", project.input_dir),
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                metadata[key] = _relocated_project_path(
                    project,
                    value,
                    fallback_directory=fallback_directory,
                )
        masks.append(
            asset.model_copy(
                update={
                    "path": _relocated_project_path(
                        project,
                        asset.path,
                        fallback_directory=project.masks_dir,
                    ),
                    "metadata": metadata,
                },
                deep=True,
            )
        )
    return graph.model_copy(
        update={"media": media, "shots": shots, "masks": masks},
        deep=True,
    )


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.projects_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str) -> ProjectPaths:
        project_id = f"{_safe_stem(name)}-{uuid4().hex[:10]}"
        root = self.root / project_id
        paths = ProjectPaths(
            id=project_id,
            root=root,
            input_dir=root / "input",
            frames_dir=root / "frames",
            masks_dir=root / "masks",
            previews_dir=root / "previews",
            outputs_dir=root / "outputs",
            graph_path=root / "grade_graph.json",
        )
        for directory in (
            paths.input_dir,
            paths.frames_dir,
            paths.masks_dir,
            paths.previews_dir,
            paths.outputs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=False)
        return paths

    def get(self, project_id: str) -> ProjectPaths:
        if not re.fullmatch(r"[a-z0-9_-]+", project_id):
            raise ValueError("invalid project id")
        root = (self.root / project_id).resolve()
        if root.parent != self.root or not root.is_dir():
            raise FileNotFoundError(project_id)
        return ProjectPaths(
            id=project_id,
            root=root,
            input_dir=root / "input",
            frames_dir=root / "frames",
            masks_dir=root / "masks",
            previews_dir=root / "previews",
            outputs_dir=root / "outputs",
            graph_path=root / "grade_graph.json",
        )

    def copy_source(self, project: ProjectPaths, source: Path) -> Path:
        suffix = source.suffix.lower()[:12]
        destination = project.input_dir / f"source{suffix}"
        shutil.copy2(source, destination)
        return destination

    def import_local_source(self, project: ProjectPaths, source: Path) -> ImportedSource:
        resolved = source.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        suffix = resolved.suffix.lower()[:12]
        destination = project.input_dir / f"source{suffix}"
        try:
            os.link(resolved, destination)
            return ImportedSource(path=destination, mode="hardlink")
        except OSError:
            reference_path = project.input_dir / "source-reference.json"
            reference_path.write_text(
                json.dumps({"path": str(resolved)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return ImportedSource(path=resolved, mode="external_reference")

    def resolve_source(self, project: ProjectPaths) -> Path:
        sources = sorted(path for path in project.input_dir.glob("source.*") if path.is_file())
        if sources:
            return sources[0].resolve()
        reference_path = project.input_dir / "source-reference.json"
        if reference_path.is_file():
            payload = json.loads(reference_path.read_text(encoding="utf-8"))
            source = Path(str(payload.get("path", ""))).resolve()
            if source.is_file():
                return source
        raise FileNotFoundError("project source video is missing")

    def save_graph(self, project: ProjectPaths, graph: GradeGraph) -> None:
        temporary = project.graph_path.with_suffix(".json.tmp")
        temporary.write_text(
            graph.model_dump_json(indent=2),
            encoding="utf-8",
        )
        temporary.replace(project.graph_path)

    def save_graph_revision(
        self,
        project: ProjectPaths,
        graph: GradeGraph,
        *,
        label: str,
    ) -> Path:
        safe_label = _safe_stem(label)
        revision = project.root / f"grade_graph.{safe_label}.json"
        if revision.exists():
            return revision
        temporary = revision.with_suffix(".json.tmp")
        temporary.write_text(
            graph.model_dump_json(indent=2),
            encoding="utf-8",
        )
        try:
            temporary.replace(revision)
        finally:
            temporary.unlink(missing_ok=True)
        return revision

    def load_graph(self, project_id: str) -> GradeGraph:
        project = self.get(project_id)
        if not project.graph_path.is_file():
            raise FileNotFoundError(project.graph_path)
        payload = json.loads(project.graph_path.read_text(encoding="utf-8"))
        graph = GradeGraph.model_validate(payload)
        return _relocate_loaded_graph(project, graph)

    def list_graphs(self) -> list[GradeGraph]:
        graphs: list[GradeGraph] = []
        for graph_path in self.root.glob("*/grade_graph.json"):
            try:
                payload = json.loads(graph_path.read_text(encoding="utf-8"))
                graphs.append(GradeGraph.model_validate(payload))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(graphs, key=lambda graph: graph.updated_at, reverse=True)
