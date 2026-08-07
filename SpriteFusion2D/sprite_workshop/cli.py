"""Command line entry point.

This layer contains no image logic.  It parses arguments, calls the same public
backend functions the tests and any future frontend call, formats a report, and
maps errors to exit codes (BACKEND_CLI_PLAN.md 4.1, 9).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ExitCode, UsageError, WorkshopError
from .model import OperationReport, Rect, WorkshopWarning
from .project import SCHEMA_VERSION, Project

PROG = "sprite-workshop"


# --------------------------------------------------------------------- output


class Output:
    """Human text on stdout, progress and warnings on stderr.

    Under ``--json`` stdout carries exactly one JSON object and nothing else
    (BACKEND_CLI_PLAN.md 9.2).
    """

    def __init__(self, as_json: bool, quiet: bool) -> None:
        self.as_json = as_json
        self.quiet = quiet

    def note(self, message: str) -> None:
        if not self.quiet and not self.as_json:
            print(message)

    def warn(self, message: str) -> None:
        if not self.quiet:
            print(message, file=sys.stderr)

    def envelope(
        self,
        command: str,
        *,
        ok: bool = True,
        project: str | None = None,
        revision: int | None = None,
        outputs: Sequence[str] = (),
        warnings: Sequence[WorkshopWarning] = (),
        metrics: Mapping[str, Any] | None = None,
        result: Any = None,
        error: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.as_json:
            return
        payload: dict[str, Any] = {
            "ok": ok,
            "command": command,
            "project": project,
            "revision": revision,
            "outputs": list(outputs),
            "warnings": [w.to_dict() for w in warnings],
            "metrics": dict(metrics or {}),
        }
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = dict(error)
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    def report(
        self, command: str, project: Project | None, report: OperationReport
    ) -> None:
        for warning in report.warnings:
            self.warn(f"warning[{warning.code}]: {warning.message}")
        self.note(
            f"{command}: revision {report.revision}"
            + (f", outputs: {', '.join(report.outputs)}" if report.outputs else "")
        )
        self.envelope(
            command,
            project=str(project.root) if project else None,
            revision=report.revision,
            outputs=report.outputs,
            warnings=report.warnings,
            metrics=report.metrics,
        )


# ------------------------------------------------------------------- commands


def _require_project(args: argparse.Namespace) -> Project:
    if not args.project:
        raise UsageError("this command needs --project PATH")
    return Project.open(args.project)


def cmd_init(args: argparse.Namespace, out: Output) -> int:
    if args.dry_run:
        # Same refusals as a real init, no directory.
        root, project_id = Project.plan_init(args.path, project_id=args.id)
        out.note(f"would create {root} (id {project_id})")
        out.envelope(
            "init",
            project=str(root),
            revision=0,
            result={"project_id": project_id, "name": args.name or project_id},
        )
        return ExitCode.OK

    project = Project.init(args.path, name=args.name, project_id=args.id)
    out.note(f"created {project.root}")
    out.envelope(
        "init",
        project=str(project.root),
        revision=project.head_revision,
        result={
            "project_id": project.manifest["project_id"],
            "name": project.manifest["name"],
        },
    )
    return ExitCode.OK


def cmd_import(args: argparse.Namespace, out: Output) -> int:
    project = _require_project(args)
    if args.dry_run:
        out.note(f"would import {args.path} as {args.as_name}")
        out.envelope(
            "import", project=str(project.root), revision=project.head_revision
        )
        return ExitCode.OK

    target = project.import_source(args.path, as_name=args.as_name)

    assets = {}
    if args.adopt:
        # Already-1x pixel art has no upscaled grid to detect, so forcing it
        # through recovery would resample it for nothing.  Adopt takes the
        # image as an asset verbatim.
        from .image_io import load_rgba  # noqa: PLC0415
        from .model import Frame, FrameSet, Point, Rect  # noqa: PLC0415

        image = load_rgba(target)
        frame = Frame(
            id=args.as_name,
            image=image,
            source_size=image.size,
            trim_rect=Rect(0, 0, image.width, image.height),
            trim_offset=Point(0, 0),
            anchor=Point(*args.anchor)
            if args.anchor
            else Point(image.width // 2, image.height),
        )
        assets[args.as_name] = FrameSet(id=args.as_name, frames=(frame,))

    report = project.commit(
        "import",
        params={"path": str(args.path), "as": args.as_name, "adopt": args.adopt},
        assets=assets,
        inputs=(str(args.path),),
        metrics={"bytes": target.stat().st_size},
    )
    out.report("import", project, report)
    return ExitCode.OK


def cmd_inspect(args: argparse.Namespace, out: Output) -> int:
    project = _require_project(args)
    assets: list[dict[str, Any]] = []
    for name in project.asset_names():
        frame_set = project.load_asset(name)
        assets.append(
            {
                "name": name,
                "version": project.assets[name].version,
                "frames": len(frame_set),
                "frame_ids": [f.id for f in frame_set.frames],
                "tags": sorted({k for f in frame_set.frames for k in f.tags}),
            }
        )

    sources = sorted(
        p.name for p in (project.root / "sources").glob("*") if p.is_file()
    )
    out.note(f"project: {project.manifest['name']} (revision {project.head_revision})")
    for source in sources:
        out.note(f"  source: {source}")
    for asset in assets:
        out.note(
            f"  asset:  {asset['name']} v{asset['version']} · {asset['frames']} frames"
        )

    out.envelope(
        "inspect",
        project=str(project.root),
        revision=project.head_revision,
        result={
            "sources": sources,
            "assets": assets,
            "clips": project.manifest.get("clips", []),
        },
    )
    return ExitCode.OK


def cmd_recover(args: argparse.Namespace, out: Output) -> int:
    from .image_io import load_rgba  # noqa: PLC0415
    from .recovery import RecoverySpec, recover_frames  # noqa: PLC0415

    project = _require_project(args)
    source_path = project.find_source(args.source)
    image = load_rgba(source_path)

    spec = RecoverySpec(
        algorithm=args.algorithm,
        device=args.device,
        ignore_alpha=args.ignore_alpha,
    )
    result = recover_frames([image], spec, set_id=args.as_name)
    grid = result.grids[0]

    metrics = {
        "algorithm": result.algorithm,
        "device": result.device,
        "input_size": f"{image.width}x{image.height}",
        "output_size": f"{result.frames.frames[0].size.width}x{result.frames.frames[0].size.height}",
        "grid_columns": grid.columns,
        "grid_rows": grid.rows,
        "elapsed_ms": round(result.elapsed_ms, 2),
    }

    if args.dry_run:
        out.note(
            f"would recover {args.source} -> {args.as_name} ({metrics['output_size']})"
        )
        out.envelope(
            "recover",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=metrics,
            result={"grid": grid.to_dict()},
        )
        return ExitCode.OK

    report = project.commit(
        "recover",
        params={
            "source": args.source,
            "algorithm": args.algorithm,
            "device": args.device,
            "ignore_alpha": args.ignore_alpha,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=(f"sources/{source_path.name}",),
        changed_frames=tuple(f.id for f in result.frames.frames),
        warnings=result.warnings,
        metrics={**metrics, "grid": grid.to_dict()},
        device=result.device,
    )
    out.report("recover", project, report)
    return ExitCode.OK


def _background_spec(args: argparse.Namespace):
    from .background import BackgroundSpec  # noqa: PLC0415

    colors: list[tuple[int, int, int]] = []
    for text in args.color or ():
        value = text.lstrip("#")
        if len(value) != 6:
            raise UsageError("colour must be #RRGGBB", value=text)
        colors.append(tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)))

    points: list[tuple[int, int]] = []
    for text in args.at or ():
        try:
            x, y = (int(part) for part in text.split(","))
        except ValueError as exc:
            raise UsageError("sample point must be X,Y", value=text) from exc
        points.append((x, y))

    samples = args.samples
    if (colors or points) and samples not in ("colors",):
        samples = "colors"

    return BackgroundSpec(
        mode=args.mode,
        samples=samples,
        colors=tuple(colors),
        points=tuple(points),
        tolerance=args.tolerance,
        connectivity=args.connectivity,
        border_only=not args.no_border_only,
        min_island_area=args.min_island_area,
        max_hole_area=args.max_hole_area,
        alpha=args.alpha,
        soft_range=args.soft_range,
        despill=args.despill,
        shared_background=not args.per_frame_samples,
        mask_only=getattr(args, "mask_only", False),
    )


def cmd_background(args: argparse.Namespace, out: Output) -> int:
    from .background import (  # noqa: PLC0415
        analyze_background,
        apply_mask,
        remove_background,
    )

    project = _require_project(args)
    command = f"background.{args.background_action}"

    if args.background_action == "apply-mask":
        frames = project.load_asset(args.asset)
        masks = project.load_asset(args.mask)
        result = apply_mask(frames, masks, invert=args.invert)
        if args.dry_run:
            out.note(f"would apply {args.mask} to {args.asset}")
            out.envelope(
                command, project=str(project.root), revision=project.head_revision
            )
            return ExitCode.OK
        report = project.commit(
            command,
            params={"asset": args.asset, "mask": args.mask, "invert": args.invert},
            assets={args.as_name: result},
            inputs=(args.asset, args.mask),
            changed_frames=tuple(f.id for f in result.frames),
        )
        out.report(command, project, report)
        return ExitCode.OK

    frames = project.load_asset(args.asset)
    spec = _background_spec(args)

    if args.background_action == "analyze":
        analysis = analyze_background(frames, spec)
        chosen = analysis.chosen
        out.note(
            f"suggested background: {chosen.color if chosen else '(none)'}"
            f"  covers {chosen.border_coverage:.0%} of the border"
            if chosen
            else "no background candidate found"
        )
        out.note(
            f"would erase {analysis.erased_pixels}/{analysis.total_pixels} pixels "
            f"({analysis.erased_pixels / max(analysis.total_pixels, 1):.1%})"
        )
        out.envelope(
            command,
            project=str(project.root),
            revision=project.head_revision,
            metrics={"elapsed_ms": round(analysis.elapsed_ms, 2)},
            result=analysis.to_dict(),
        )
        return ExitCode.OK

    result = remove_background(frames, spec)
    if args.dry_run:
        out.note(f"would erase {result.analysis.erased_pixels} pixels")
        out.envelope(
            command,
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
            result=result.analysis.to_dict(),
        )
        return ExitCode.OK

    assets = {}
    if not spec.mask_only:
        assets[args.as_name] = result.frames
    mask_name = args.mask_as or f"{args.as_name}_mask"
    assets[mask_name] = result.masks

    report = project.commit(
        command,
        params={
            "asset": args.asset,
            "mode": spec.mode,
            "tolerance": spec.tolerance,
            "alpha": spec.alpha,
            "connectivity": spec.connectivity,
            "as": args.as_name,
        },
        assets=assets,
        inputs=(args.asset,),
        changed_frames=tuple(f.id for f in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.report(command, project, report)
    return ExitCode.OK


def cmd_outline(args: argparse.Namespace, out: Output) -> int:
    from .outline import OutlineSpec, apply_outline  # noqa: PLC0415

    project = _require_project(args)
    value = args.color.lstrip("#")
    if len(value) != 6:
        raise UsageError("colour must be #RRGGBB", value=args.color)
    color = tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    spec = OutlineSpec(
        position=args.position,
        thickness=args.thickness,
        connectivity=args.connectivity,
        skip_diagonal=not args.keep_diagonal,
        color_mode=args.color_mode,
        color=color,
        darken=args.darken,
        inner_shadow=args.inner_shadow,
    )
    result = apply_outline(project.load_asset(args.asset), spec)
    if args.dry_run:
        out.envelope(
            "outline",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
        )
        return ExitCode.OK
    report = project.commit(
        "outline",
        params={
            "asset": args.asset,
            "position": spec.position,
            "thickness": spec.thickness,
            "color_mode": spec.color_mode,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=(args.asset,),
        changed_frames=tuple(frame.id for frame in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.report("outline", project, report)
    return ExitCode.OK


def cmd_pixelify(args: argparse.Namespace, out: Output) -> int:
    from .pixelify import PixelifySpec, pixelify_frames  # noqa: PLC0415

    project = _require_project(args)
    spec = PixelifySpec(
        target_width=args.width,
        palette=args.palette,
        colors=args.colors,
        dither=args.dither,
        sharpen=args.sharpen,
        seed=args.seed,
    )
    result = pixelify_frames(project.load_asset(args.asset), spec)
    if args.dry_run:
        out.envelope(
            "pixelify",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
        )
        return ExitCode.OK
    report = project.commit(
        "pixelify",
        params={
            "asset": args.asset,
            "width": spec.target_width,
            "palette": spec.palette,
            "colors": spec.colors,
            "dither": spec.dither,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=(args.asset,),
        changed_frames=tuple(frame.id for frame in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.report("pixelify", project, report)
    return ExitCode.OK


def _parse_tag_pairs(values: Sequence[str] | None) -> dict[str, str]:
    tags: dict[str, str] = {}
    for text in values or ():
        key, sep, value = text.partition("=")
        if not sep:
            raise UsageError("tag must be key=value", value=text)
        tags[key.strip()] = value.strip()
    return tags


def _parse_axis_tags(values: Sequence[str] | None) -> dict[int, dict[str, str]]:
    """``--tag-row 0:direction=south`` -> ``{0: {'direction': 'south'}}``."""

    out: dict[int, dict[str, str]] = {}
    for text in values or ():
        index_text, sep, rest = text.partition(":")
        if not sep:
            raise UsageError("axis tag must be INDEX:key=value", value=text)
        try:
            index = int(index_text)
        except ValueError as exc:
            raise UsageError("axis tag index must be an integer", value=text) from exc
        out.setdefault(index, {}).update(_parse_tag_pairs([rest]))
    return out


def cmd_split(args: argparse.Namespace, out: Output) -> int:
    from .slicing import (  # noqa: PLC0415
        ComponentsSpec,
        GridSpec,
        ManualSpec,
        NamedRect,
        SliceSpec,
        slice_frames,
    )

    project = _require_project(args)
    frames = project.load_asset(args.asset)
    if len(frames) != 1:
        raise UsageError(
            "split takes a single-frame asset", asset=args.asset, frames=len(frames)
        )

    grid = components = manual = None
    if args.mode == "grid":
        grid = GridSpec(
            columns=args.columns,
            rows=args.rows,
            cell_width=args.cell_width,
            cell_height=args.cell_height,
            margin=tuple(args.margin),
            gap=tuple(args.gap),
            order=args.order,
            keep_empty=args.keep_empty,
            tail=args.tail,
        )
    elif args.mode == "components":
        components = ComponentsSpec(
            min_area=args.min_area,
            merge_gap=args.merge_gap,
            padding=args.padding,
            connectivity=args.connectivity,
            order=args.order,
        )
    else:
        if not args.rects:
            raise UsageError("manual mode needs --rects FILE")
        payload = json.loads(Path(args.rects).read_text(encoding="utf-8"))
        manual = ManualSpec(
            rects=tuple(
                NamedRect(entry["name"], Rect(*entry["rect"]))
                for entry in payload["rects"]
            )
        )

    spec = SliceSpec(
        mode=args.mode,
        grid=grid,
        components=components,
        manual=manual,
        name_template=args.name_template,
        tags=_parse_tag_pairs(args.tag),
        tag_rows=_parse_axis_tags(args.tag_row),
        tag_cols=_parse_axis_tags(args.tag_col),
    )

    result = slice_frames(frames.frames[0].image, spec, set_id=args.as_name)

    for warning in result.warnings:
        out.warn(f"warning[{warning.code}]: {warning.message}")

    if args.dry_run:
        for entry in result.to_dict()["frames"]:
            out.note(
                f"  {entry['index']:>3} {entry['id']:<20} rect={entry['rect']} tags={entry['tags']}"
            )
        out.envelope(
            "split",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
            result=result.to_dict(),
        )
        return ExitCode.OK

    report = project.commit(
        "split",
        params={
            "asset": args.asset,
            "mode": args.mode,
            "name_template": args.name_template,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=(args.asset,),
        changed_frames=tuple(f.id for f in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.note(
        f"  {len(result.frames)} frames: {', '.join(f.id for f in result.frames.frames)}"
    )
    out.report("split", project, report)
    return ExitCode.OK


def cmd_align(args: argparse.Namespace, out: Output) -> int:
    from .alignment import AlignmentSpec, align_frames  # noqa: PLC0415
    from .model import Point, Size  # noqa: PLC0415

    project = _require_project(args)
    frames = project.load_asset(args.asset)

    canvas = None
    if args.canvas != "auto":
        try:
            width, height = (int(part) for part in args.canvas.split("x"))
        except ValueError as exc:
            raise UsageError("canvas must be auto or WxH", value=args.canvas) from exc
        canvas = Size(width, height)

    offsets: dict[str, Point] = {}
    for text in args.offset or ():
        frame_id, sep, coords = text.partition("=")
        if not sep:
            raise UsageError("offset must be FRAME=X,Y", value=text)
        try:
            x, y = (int(part) for part in coords.split(","))
        except ValueError as exc:
            raise UsageError("offset must be FRAME=X,Y", value=text) from exc
        offsets[frame_id.strip()] = Point(x, y)

    fallback = None
    if args.fallback_anchor:
        try:
            fx, fy = (int(part) for part in args.fallback_anchor.split(","))
        except ValueError as exc:
            raise UsageError(
                "fallback anchor must be X,Y", value=args.fallback_anchor
            ) from exc
        fallback = Point(fx, fy)

    spec = AlignmentSpec(
        mode=args.mode,
        canvas=canvas,
        padding=args.padding,
        offsets=offsets,
        empty=args.empty,
        fallback_anchor=fallback,
        overflow=args.overflow,
    )
    result = align_frames(frames, spec)

    for warning in result.warnings:
        out.warn(f"warning[{warning.code}]: {warning.message}")

    if args.dry_run:
        out.note(
            f"canvas {result.canvas.width}x{result.canvas.height}, anchor {result.anchor.as_tuple()}"
        )
        for placement in result.placements:
            out.note(f"  {placement.id:<20} offset={placement.offset.as_tuple()}")
        out.envelope(
            "align",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
            result=result.to_dict(),
        )
        return ExitCode.OK

    report = project.commit(
        "align",
        params={
            "asset": args.asset,
            "mode": args.mode,
            "canvas": args.canvas,
            "padding": args.padding,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=(args.asset,),
        changed_frames=tuple(f.id for f in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.note(
        f"canvas {result.canvas.width}x{result.canvas.height}, anchor {result.anchor.as_tuple()}"
    )
    out.report("align", project, report)
    return ExitCode.OK


def cmd_compose(args: argparse.Namespace, out: Output) -> int:
    from .composition import (  # noqa: PLC0415
        CompositionSpec,
        LayerInput,
        compose_layers,
    )
    from .model import Size  # noqa: PLC0415

    project = _require_project(args)

    layers: list[LayerInput] = []
    for text in args.layer:
        name, sep, asset = text.partition("=")
        if not sep:
            raise UsageError("layer must be NAME=ASSET", value=text)
        layers.append(
            LayerInput(name=name.strip(), frames=project.load_asset(asset.strip()))
        )

    canvas_size = None
    canvas_rule = args.canvas
    if args.canvas not in ("union", "from-layer"):
        try:
            width, height = (int(part) for part in args.canvas.split("x"))
        except ValueError as exc:
            raise UsageError(
                "canvas must be union, from-layer or WxH", value=args.canvas
            ) from exc
        canvas_size = Size(width, height)
        canvas_rule = "fixed"

    spec = CompositionSpec(
        match=args.match.replace("-", "_"),
        match_keys=tuple(args.match_key or ()),
        broadcast_single=not args.no_broadcast_single,
        missing=args.missing.replace("-", "_"),
        canvas="from_layer" if canvas_rule == "from-layer" else canvas_rule,
        canvas_size=canvas_size,
        canvas_layer=args.canvas_layer,
        overflow=args.overflow,
        padding=args.padding,
    )

    result = compose_layers(layers, spec, set_id=args.as_name)

    for warning in result.warnings:
        out.warn(f"warning[{warning.code}]: {warning.message}")

    if args.dry_run:
        out.note(
            f"canvas {result.canvas.width}x{result.canvas.height}, anchor {result.anchor.as_tuple()}"
        )
        for frame, matches in zip(result.frames.frames, result.matches):
            joined = ", ".join(f"{m.layer}={m.frame_id or '-'}" for m in matches)
            out.note(f"  {frame.id:<20} {joined}")
        out.envelope(
            "compose",
            project=str(project.root),
            revision=project.head_revision,
            warnings=result.warnings,
            metrics=result.metrics,
            result=result.to_dict(),
        )
        return ExitCode.OK

    report = project.commit(
        "compose",
        params={
            "layers": [text for text in args.layer],
            "match": args.match,
            "missing": args.missing,
            "canvas": args.canvas,
            "as": args.as_name,
        },
        assets={args.as_name: result.frames},
        inputs=tuple(text.partition("=")[2] for text in args.layer),
        changed_frames=tuple(f.id for f in result.frames.frames),
        warnings=result.warnings,
        metrics=result.metrics,
    )
    out.note(
        f"canvas {result.canvas.width}x{result.canvas.height}, {len(result.frames)} frames"
    )
    out.report("compose", project, report)
    return ExitCode.OK


def cmd_pack(args: argparse.Namespace, out: Output) -> int:
    from .model import Size  # noqa: PLC0415
    from .packing import PackSpec, pack_frames  # noqa: PLC0415

    project = _require_project(args)
    frames = project.load_asset(args.asset)

    try:
        max_w, max_h = (int(part) for part in args.max_size.split("x"))
    except ValueError as exc:
        raise UsageError("max-size must be WxH", value=args.max_size) from exc

    spec = PackSpec(
        layout=args.layout,
        columns=args.columns,
        rows=args.rows,
        padding=args.padding,
        margin=args.margin,
        extrude=args.extrude,
        trim=args.trim,
        max_size=Size(max_w, max_h),
        multi_page=args.multi_page,
        dedupe=args.dedupe,
    )
    bundle = pack_frames(frames, spec)

    for warning in bundle.warnings:
        out.warn(f"warning[{warning.code}]: {warning.message}")
    out.note(
        f"{bundle.metrics['pages']} page(s) {bundle.metrics['page_sizes']}, "
        f"coverage {bundle.metrics['coverage']:.0%}"
    )

    if args.dry_run:
        out.envelope(
            "pack",
            project=str(project.root),
            revision=project.head_revision,
            warnings=bundle.warnings,
            metrics=bundle.metrics,
            result=bundle.to_dict(),
        )
        return ExitCode.OK

    # Pages are stored as an ordinary asset so they are versioned and undoable
    # like everything else; the atlas description rides in the revision metrics.
    from .model import Frame, FrameSet, Point, Rect  # noqa: PLC0415

    page_frames = tuple(
        Frame(
            id=f"page_{page.index}",
            image=page.image,
            source_size=page.size,
            trim_rect=Rect(0, 0, page.size.width, page.size.height),
            trim_offset=Point(0, 0),
            anchor=Point(0, 0),
        )
        for page in bundle.pages
    )
    report = project.commit(
        "pack",
        params={"asset": args.asset, "layout": args.layout, "as": args.as_name},
        assets={args.as_name: FrameSet(id=args.as_name, frames=page_frames)},
        inputs=(args.asset,),
        warnings=bundle.warnings,
        metrics={**bundle.metrics, "atlas": bundle.to_dict()},
    )
    out.report("pack", project, report)
    return ExitCode.OK


def cmd_export(args: argparse.Namespace, out: Output) -> int:
    from .export import ExportSpec, export_atlas, export_frames  # noqa: PLC0415
    from .model import Size  # noqa: PLC0415
    from .packing import PackSpec, pack_frames  # noqa: PLC0415

    project = _require_project(args)
    frames = project.load_asset(args.asset)
    spec = ExportSpec(format=args.format, name=args.name, overwrite=args.overwrite)

    if args.dry_run:
        out.note(f"would write {args.format} to {args.output}")
        out.envelope(
            "export", project=str(project.root), revision=project.head_revision
        )
        return ExitCode.OK

    if args.format == "frames":
        bundle = export_frames(frames, args.output, spec)
    else:
        try:
            max_w, max_h = (int(part) for part in args.max_size.split("x"))
        except ValueError as exc:
            raise UsageError("max-size must be WxH", value=args.max_size) from exc
        atlas = pack_frames(
            frames,
            PackSpec(
                layout=args.layout,
                columns=args.columns,
                padding=args.padding,
                extrude=args.extrude,
                trim=args.trim,
                max_size=Size(max_w, max_h),
                multi_page=args.multi_page,
            ),
        )
        bundle = export_atlas(atlas, args.output, spec)

    for path in bundle.files:
        out.note(f"  {path.name}")
    out.envelope(
        "export",
        project=str(project.root),
        revision=project.head_revision,
        outputs=tuple(p.name for p in bundle.files),
        metrics=bundle.metrics,
        result=bundle.to_dict(),
    )
    return ExitCode.OK


def cmd_history(args: argparse.Namespace, out: Output) -> int:
    project = _require_project(args)

    if args.history_action == "list":
        records = project.history(limit=args.limit)
        rows = [
            {
                "revision": r.revision,
                "parent": r.parent_revision,
                "operation": r.operation,
                "outputs": list(r.outputs),
                "warnings": len(r.warnings),
                "created_at": r.created_at,
            }
            for r in records
        ]
        for row in rows:
            out.note(
                f"  r{row['revision']:<4} {row['operation']:<18} {row['created_at']}"
            )
        if not rows:
            out.note("  (no revisions yet)")
        out.envelope(
            "history.list",
            project=str(project.root),
            revision=project.head_revision,
            result={"entries": rows, "redo_stack": project.redo_stack},
        )
        return ExitCode.OK

    if args.history_action == "show":
        record = project.read_revision(args.revision)
        out.note(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        out.envelope(
            "history.show",
            project=str(project.root),
            revision=project.head_revision,
            result=record.to_dict(),
        )
        return ExitCode.OK

    command = f"history.{args.history_action}"
    if args.dry_run:
        target, moved = (
            project.preview_undo(args.steps)
            if args.history_action == "undo"
            else project.preview_redo(args.steps)
        )
        out.note(
            f"would {args.history_action} {moved} step(s): "
            f"revision {project.head_revision} -> {target}"
        )
        if moved < args.steps:
            out.warn(
                f"warning[history.at_{'start' if args.history_action == 'undo' else 'end'}]: "
                f"only {moved} step(s) available"
            )
        out.envelope(
            command,
            project=str(project.root),
            revision=project.head_revision,
            metrics={"steps": moved, "target_revision": target},
        )
        return ExitCode.OK

    report = (
        project.undo(args.steps)
        if args.history_action == "undo"
        else project.redo(args.steps)
    )
    out.report(command, project, report)
    return ExitCode.OK


def cmd_doctor(args: argparse.Namespace, out: Output) -> int:
    from .image_io import pillow_version  # noqa: PLC0415

    checks: list[dict[str, Any]] = [
        {"name": "python", "status": "ok", "detail": sys.version.split()[0]},
        {"name": "schema", "status": "ok", "detail": f"v{SCHEMA_VERSION}"},
    ]

    pillow = pillow_version()
    checks.append(
        {
            "name": "pillow",
            "status": "ok" if pillow else "error",
            "detail": pillow or "missing; pip install -e .[workshop]",
        }
    )

    try:
        import numpy  # noqa: PLC0415

        checks.append({"name": "numpy", "status": "ok", "detail": numpy.__version__})
    except ImportError:
        checks.append({"name": "numpy", "status": "error", "detail": "missing"})

    try:
        import torch  # noqa: PLC0415

        checks.append({"name": "torch", "status": "ok", "detail": torch.__version__})
        from pixel_snapper_core import runtime_description  # noqa: PLC0415

        checks.append(
            {"name": "device", "status": "ok", "detail": runtime_description()}
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        checks.append({"name": "torch", "status": "error", "detail": str(exc)})

    for optional in ("rectpack", "rembg"):
        try:
            __import__(optional)
            checks.append({"name": optional, "status": "ok", "detail": "available"})
        except ImportError:
            checks.append(
                {
                    "name": optional,
                    "status": "skip",
                    "detail": "optional, not installed",
                }
            )

    for check in checks:
        out.note(f"  {check['status']:<5} {check['name']:<10} {check['detail']}")

    failed = any(c["status"] == "error" for c in checks)
    out.envelope("doctor", ok=not failed, result={"checks": checks})
    return ExitCode.BACKEND_UNAVAILABLE if failed else ExitCode.OK


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description="Sprite Workshop pixel asset pipeline"
    )
    parser.add_argument("--project", metavar="PATH", help="project directory")
    parser.add_argument(
        "--json", action="store_true", help="emit one machine-readable object"
    )
    parser.add_argument("--quiet", action="store_true", help="hide normal progress")
    parser.add_argument("--verbose", action="store_true", help="add diagnostic detail")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate without committing"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a project")
    p_init.add_argument("path")
    p_init.add_argument("--name", help="display name, may contain any language")
    p_init.add_argument(
        "--id", help="lowercase ascii project id; defaults to the directory name"
    )
    p_init.set_defaults(func=cmd_init)

    p_import = sub.add_parser("import", help="copy a file into sources/")
    p_import.add_argument("path")
    p_import.add_argument("--as", dest="as_name", required=True)
    p_import.add_argument(
        "--adopt",
        action="store_true",
        help="also take the image as a 1x asset, without running recovery",
    )
    p_import.add_argument(
        "--anchor", type=int, nargs=2, metavar=("X", "Y"), help="anchor for --adopt"
    )
    p_import.set_defaults(func=cmd_import)

    p_inspect = sub.add_parser("inspect", help="list sources, assets and clips")
    p_inspect.set_defaults(func=cmd_inspect)

    p_recover = sub.add_parser("recover", help="recover a source to its true 1x grid")
    p_recover.add_argument("source")
    p_recover.add_argument(
        "--algorithm", choices=("optimized", "legacy_exact"), default="optimized"
    )
    p_recover.add_argument("--device", default="auto")
    p_recover.add_argument("--ignore-alpha", action="store_true")
    p_recover.add_argument("--as", dest="as_name", required=True)
    p_recover.set_defaults(func=cmd_recover)

    p_background = sub.add_parser("background", help="make the background transparent")
    b_sub = p_background.add_subparsers(dest="background_action", required=True)

    def add_background_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("asset")
        parser.add_argument(
            "--mode", choices=("exact", "rgb", "lab", "rembg"), default="lab"
        )
        parser.add_argument(
            "--samples", choices=("corners", "border", "colors"), default="corners"
        )
        parser.add_argument("--color", action="append", metavar="#RRGGBB")
        parser.add_argument("--at", action="append", metavar="X,Y")
        parser.add_argument("--tolerance", type=float, default=10.0)
        parser.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
        parser.add_argument(
            "--no-border-only",
            action="store_true",
            help="also erase background-coloured areas inside the character",
        )
        parser.add_argument("--min-island-area", type=int, default=0)
        parser.add_argument("--max-hole-area", type=int, default=0)
        parser.add_argument("--alpha", choices=("hard", "soft"), default="hard")
        parser.add_argument("--soft-range", type=float, default=4.0)
        parser.add_argument("--despill", choices=("none", "nearest"), default="none")
        parser.add_argument("--per-frame-samples", action="store_true")

    b_analyze = b_sub.add_parser("analyze", help="report what removal would do")
    add_background_options(b_analyze)

    b_remove = b_sub.add_parser("remove", help="erase the background")
    add_background_options(b_remove)
    b_remove.add_argument("--as", dest="as_name", required=True)
    b_remove.add_argument("--mask-as", help="name for the mask asset")
    b_remove.add_argument("--mask-only", action="store_true")

    b_apply = b_sub.add_parser("apply-mask", help="apply a mask asset to a frame set")
    b_apply.add_argument("asset")
    b_apply.add_argument("--mask", required=True)
    b_apply.add_argument("--invert", action="store_true")
    b_apply.add_argument("--as", dest="as_name", required=True)
    p_background.set_defaults(func=cmd_background)

    p_outline = sub.add_parser("outline", help="add a grid-aligned sprite outline")
    p_outline.add_argument("asset")
    p_outline.add_argument(
        "--position", choices=("outer", "inner", "center"), default="outer"
    )
    p_outline.add_argument("--thickness", type=int, default=1)
    p_outline.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
    p_outline.add_argument(
        "--keep-diagonal",
        action="store_true",
        help="include purely diagonal neighbours",
    )
    p_outline.add_argument(
        "--color-mode",
        choices=("fixed", "darken-neighbor", "hue-shift"),
        default="fixed",
    )
    p_outline.add_argument("--color", default="#000000")
    p_outline.add_argument("--darken", type=int, default=40)
    p_outline.add_argument("--inner-shadow", action="store_true")
    p_outline.add_argument("--as", dest="as_name", required=True)
    p_outline.set_defaults(func=cmd_outline)

    p_pixelify = sub.add_parser(
        "pixelify", help="downsample and quantize an illustration"
    )
    p_pixelify.add_argument("asset")
    p_pixelify.add_argument("--width", type=int, default=64)
    p_pixelify.add_argument(
        "--palette", choices=("auto", "gameboy", "pico8", "nes"), default="auto"
    )
    p_pixelify.add_argument("--colors", type=int, default=16)
    p_pixelify.add_argument(
        "--dither", choices=("none", "bayer4", "floyd-steinberg"), default="none"
    )
    p_pixelify.add_argument("--sharpen", type=int, default=0)
    p_pixelify.add_argument("--seed", type=int, default=42)
    p_pixelify.add_argument("--as", dest="as_name", required=True)
    p_pixelify.set_defaults(func=cmd_pixelify)

    p_split = sub.add_parser("split", help="cut a sheet into frames")
    p_split.add_argument("asset")
    p_split.add_argument(
        "--mode", choices=("grid", "components", "manual"), default="grid"
    )
    p_split.add_argument("--columns", type=int)
    p_split.add_argument("--rows", type=int)
    p_split.add_argument("--cell-width", type=int)
    p_split.add_argument("--cell-height", type=int)
    p_split.add_argument(
        "--margin",
        type=int,
        nargs=4,
        default=(0, 0, 0, 0),
        metavar=("L", "T", "R", "B"),
    )
    p_split.add_argument("--gap", type=int, nargs=2, default=(0, 0), metavar=("X", "Y"))
    p_split.add_argument("--order", choices=("row", "column"), default="row")
    p_split.add_argument("--keep-empty", action="store_true")
    p_split.add_argument("--tail", choices=("error", "crop", "pad"), default="error")
    p_split.add_argument("--min-area", type=int, default=1)
    p_split.add_argument("--merge-gap", type=int, default=0)
    p_split.add_argument("--padding", type=int, default=0)
    p_split.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
    p_split.add_argument(
        "--rects", help="JSON file of named rectangles for manual mode"
    )
    p_split.add_argument("--name-template", default="{set}_{index:02d}")
    p_split.add_argument("--tag", action="append", metavar="KEY=VALUE")
    p_split.add_argument("--tag-row", action="append", metavar="ROW:KEY=VALUE")
    p_split.add_argument("--tag-col", action="append", metavar="COL:KEY=VALUE")
    p_split.add_argument("--as", dest="as_name", required=True)
    p_split.set_defaults(func=cmd_split)

    p_align = sub.add_parser("align", help="put frames on a common canvas")
    p_align.add_argument("asset")
    p_align.add_argument(
        "--mode",
        choices=("center", "canvas_center", "feet", "anchor", "custom"),
        default="feet",
    )
    p_align.add_argument("--canvas", default="auto", help="auto or WxH")
    p_align.add_argument("--padding", type=int, default=0)
    p_align.add_argument("--offset", action="append", metavar="FRAME=X,Y")
    p_align.add_argument(
        "--empty", choices=("error", "canvas_center", "fallback"), default="error"
    )
    p_align.add_argument("--fallback-anchor", metavar="X,Y")
    p_align.add_argument("--overflow", choices=("error", "clip"), default="error")
    p_align.add_argument("--as", dest="as_name", required=True)
    p_align.set_defaults(func=cmd_align)

    p_compose = sub.add_parser("compose", help="stack frame sets into one")
    p_compose.add_argument(
        "--layer",
        action="append",
        required=True,
        metavar="NAME=ASSET",
        help="repeat in paint order; the first layer is the base",
    )
    p_compose.add_argument(
        "--match",
        choices=("by-index", "by-id", "by-tag", "broadcast"),
        default="by-index",
    )
    p_compose.add_argument("--match-key", action="append", metavar="KEY")
    p_compose.add_argument("--no-broadcast-single", action="store_true")
    p_compose.add_argument(
        "--missing", choices=("error", "skip-layer", "hold-last"), default="error"
    )
    p_compose.add_argument("--canvas", default="union", help="union, from-layer or WxH")
    p_compose.add_argument("--canvas-layer")
    p_compose.add_argument("--padding", type=int, default=0)
    p_compose.add_argument("--overflow", choices=("error", "clip"), default="error")
    p_compose.add_argument("--as", dest="as_name", required=True)
    p_compose.set_defaults(func=cmd_compose)

    def add_pack_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--layout",
            choices=("horizontal", "vertical", "grid", "compact"),
            default="compact",
        )
        parser.add_argument("--columns", type=int)
        parser.add_argument("--padding", type=int, default=0)
        parser.add_argument("--extrude", type=int, default=0)
        parser.add_argument("--trim", action="store_true")
        parser.add_argument("--max-size", default="2048x2048")
        parser.add_argument("--multi-page", action="store_true")

    p_pack = sub.add_parser("pack", help="arrange frames into atlas pages")
    p_pack.add_argument("asset")
    add_pack_options(p_pack)
    p_pack.add_argument("--rows", type=int)
    p_pack.add_argument("--margin", type=int, default=0)
    p_pack.add_argument("--dedupe", action="store_true")
    p_pack.add_argument("--as", dest="as_name", required=True)
    p_pack.set_defaults(func=cmd_pack)

    p_export = sub.add_parser("export", help="write assets outside the project")
    p_export.add_argument("asset")
    p_export.add_argument(
        "--format", choices=("generic-json", "frames"), default="generic-json"
    )
    p_export.add_argument("--output", required=True)
    p_export.add_argument("--name", default="atlas")
    p_export.add_argument("--overwrite", action="store_true")
    add_pack_options(p_export)
    p_export.set_defaults(func=cmd_export)

    p_history = sub.add_parser("history", help="inspect and move the revision head")
    h_sub = p_history.add_subparsers(dest="history_action", required=True)
    h_list = h_sub.add_parser("list")
    h_list.add_argument("--limit", type=int, default=20)
    h_show = h_sub.add_parser("show")
    h_show.add_argument("revision", type=int)
    h_undo = h_sub.add_parser("undo")
    h_undo.add_argument("--steps", type=int, default=1)
    h_redo = h_sub.add_parser("redo")
    h_redo.add_argument("--steps", type=int, default=1)
    p_history.set_defaults(func=cmd_history)

    p_doctor = sub.add_parser("doctor", help="check the environment")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Output(as_json=args.json, quiet=args.quiet)

    try:
        return int(args.func(args, out))
    except WorkshopError as error:
        out.warn(f"error[{error.code}]: {error.message}")
        if args.verbose and error.details:
            out.warn(
                f"  details: {json.dumps(dict(error.details), ensure_ascii=False)}"
            )
        out.envelope(args.command, ok=False, error=error.to_dict())
        return error.code
    except KeyboardInterrupt:  # pragma: no cover
        out.warn("interrupted")
        return ExitCode.FAILED
    except (
        Exception
    ) as error:  # unknown failures map to 4, never leak a traceback by default
        out.warn(f"error[{ExitCode.FAILED}]: {error}")
        if args.verbose:
            import traceback  # noqa: PLC0415

            traceback.print_exc()
        out.envelope(
            args.command,
            ok=False,
            error={"code": ExitCode.FAILED, "message": str(error), "details": None},
        )
        return ExitCode.FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
