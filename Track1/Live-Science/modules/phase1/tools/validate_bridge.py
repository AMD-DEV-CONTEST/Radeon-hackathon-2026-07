#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
ROUTES = {"programmatic", "realizable", "hybrid"}
MOMENT_KINDS = {"stable_state", "pre_event", "post_event"}
EVENT_TYPES = {
    "object_appearance",
    "object_disappearance",
    "split",
    "merge",
    "connection",
    "collapse",
    "topology_change",
    "camera_change",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def safe_child(root: Path, relative: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(relative, str) or not relative:
        errors.append(f"{label} must be a non-empty relative path")
        return None
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"{label} is not a safe relative path: {relative!r}")
        return None
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label} escapes the bridge directory: {relative!r}")
        return None
    return candidate


def inspect_png(path: Path) -> tuple[int, int, bool, bool]:
    data = path.read_bytes()
    if len(data) < 33 or data[:8] != PNG_SIGNATURE:
        raise ValueError("invalid PNG signature or truncated file")
    offset = 8
    width = height = color_type = None
    has_transparency_chunk = False
    saw_iend = False
    compressed_image = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("truncated PNG chunk")
        chunk_data = data[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise ValueError(f"invalid CRC in {chunk_type.decode('ascii', errors='replace')} chunk")
        if chunk_type == b"IHDR":
            if length != 13:
                raise ValueError("invalid IHDR length")
            width, height, _, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"tRNS":
            has_transparency_chunk = True
        elif chunk_type == b"IDAT":
            compressed_image.extend(chunk_data)
        elif chunk_type == b"IEND":
            saw_iend = True
            break
        offset = chunk_end
    if width is None or height is None or width < 1 or height < 1 or not saw_iend:
        raise ValueError("missing or invalid IHDR/IEND")
    if not compressed_image:
        raise ValueError("missing IDAT image data")
    try:
        zlib.decompress(compressed_image)
    except zlib.error as exc:
        raise ValueError(f"invalid compressed image data: {exc}") from exc
    alpha_capable = color_type in {4, 6} or has_transparency_chunk
    return width, height, alpha_capable, has_transparency_chunk


def validate_png(
    path: Path,
    label: str,
    errors: list[str],
) -> tuple[int, int, bool] | None:
    if not path.exists() or not path.is_file():
        errors.append(f"{label} does not exist: {path}")
        return None
    if path.stat().st_size == 0:
        errors.append(f"{label} is empty: {path}")
        return None
    try:
        width, height, alpha_capable, _ = inspect_png(path)
    except Exception as exc:
        errors.append(f"{label} is not a valid PNG: {exc}")
        return None
    return width, height, alpha_capable


def string_array(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    if any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must contain only strings")
    return [item for item in value if isinstance(item, str)]


def main() -> int:
    run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    bridge_dir = run_dir / "bridge"
    manifest_path = bridge_dir / "manifest.json"
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest_path.exists() or not manifest_path.is_file():
        fail(f"missing bridge manifest: {manifest_path}")
        return 1
    if manifest_path.stat().st_size == 0:
        fail(f"empty bridge manifest: {manifest_path}")
        return 1
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid bridge/manifest.json: {exc}")
        return 1
    if not isinstance(manifest, dict):
        fail("bridge/manifest.json root must be an object")
        return 1

    if manifest.get("version") != 1:
        errors.append("manifest version must equal 1")
    route = manifest.get("route")
    if route not in ROUTES:
        errors.append(f"invalid route: {route!r}")

    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")
        meta = {}
    duration = meta.get("duration")
    fps = meta.get("fps")
    width = meta.get("width")
    height = meta.get("height")
    if not is_number(duration) or duration <= 0:
        errors.append("meta.duration must be a positive number")
        duration = 0
    if not is_number(fps) or fps <= 0 or fps > 60:
        errors.append("meta.fps must be in (0, 60]")
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        errors.append("meta.width must be a positive integer")
        width = 0
    if not isinstance(height, int) or isinstance(height, bool) or height < 1:
        errors.append("meta.height must be a positive integer")
        height = 0

    if manifest.get("targetStyle") is not None and not isinstance(
        manifest.get("targetStyle"), str
    ):
        errors.append("targetStyle must be a string or null")
    if not isinstance(manifest.get("reason"), str):
        errors.append("reason must be a string")
    string_array(manifest.get("worldContinuity"), "worldContinuity", errors)

    raw_moments = manifest.get("keyMoments")
    if not isinstance(raw_moments, list):
        errors.append("keyMoments must be an array")
        raw_moments = []
    moments: dict[str, dict[str, Any]] = {}
    ordered_moments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_moments):
        if not isinstance(raw, dict):
            errors.append(f"keyMoments[{index}] must be an object")
            continue
        moment_id = raw.get("id")
        label = f"key moment {moment_id if isinstance(moment_id, str) else index}"
        if not isinstance(moment_id, str) or not SAFE_ID.fullmatch(moment_id):
            errors.append(f"{label} has unsafe ID; expected {SAFE_ID.pattern}")
            continue
        if moment_id in moments:
            errors.append(f"duplicate key moment ID: {moment_id}")
            continue
        moments[moment_id] = raw
        ordered_moments.append(raw)
        time = raw.get("time")
        if not is_number(time) or time < 0 or time > duration:
            errors.append(f"{label} time must be within [0, {duration}]")
        if raw.get("kind") not in MOMENT_KINDS:
            errors.append(f"{label} has invalid kind: {raw.get('kind')!r}")
        if not isinstance(raw.get("description"), str):
            errors.append(f"{label}.description must be a string")
        event_id = raw.get("eventId")
        if event_id is not None and not isinstance(event_id, str):
            errors.append(f"{label}.eventId must be a string or null")
        string_array(raw.get("visibleObjects"), f"{label}.visibleObjects", errors)
        string_array(raw.get("preserve"), f"{label}.preserve", errors)
        if not isinstance(raw.get("realizable"), bool):
            errors.append(f"{label}.realizable must be a boolean")

    poster_id = manifest.get("posterMomentId")
    if poster_id is not None:
        if not isinstance(poster_id, str) or not SAFE_ID.fullmatch(poster_id):
            errors.append("posterMomentId must be null or a path-safe key moment ID")
        elif poster_id not in moments:
            errors.append(f"posterMomentId references missing key moment: {poster_id}")

    raw_events = manifest.get("events")
    if not isinstance(raw_events, list):
        errors.append("events must be an array")
        raw_events = []
    events: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            errors.append(f"events[{index}] must be an object")
            continue
        event_id = raw.get("id")
        label = f"event {event_id if isinstance(event_id, str) else index}"
        if not isinstance(event_id, str) or not event_id:
            errors.append(f"{label}.id must be a non-empty string")
            continue
        if event_id in events:
            errors.append(f"duplicate event ID: {event_id}")
            continue
        events[event_id] = raw
        if raw.get("type") not in EVENT_TYPES:
            errors.append(f"{label} has invalid type: {raw.get('type')!r}")
        string_array(raw.get("objects"), f"{label}.objects", errors)
        pre_id = raw.get("preMomentId")
        post_id = raw.get("postMomentId")
        pre = moments.get(pre_id) if isinstance(pre_id, str) else None
        post = moments.get(post_id) if isinstance(post_id, str) else None
        if pre is None:
            errors.append(f"{label} references missing preMomentId: {pre_id!r}")
        if post is None:
            errors.append(f"{label} references missing postMomentId: {post_id!r}")
        if pre is not None:
            if pre.get("kind") != "pre_event":
                errors.append(f"{label} pre moment {pre_id} must have kind pre_event")
            if pre.get("eventId") != event_id:
                errors.append(f"{label} pre moment {pre_id} must reference eventId {event_id}")
        if post is not None:
            if post.get("kind") != "post_event":
                errors.append(f"{label} post moment {post_id} must have kind post_event")
            if post.get("eventId") != event_id:
                errors.append(f"{label} post moment {post_id} must reference eventId {event_id}")
        if pre is not None and post is not None:
            pre_time, post_time = pre.get("time"), post.get("time")
            if is_number(pre_time) and is_number(post_time) and post_time <= pre_time:
                errors.append(f"{label} post time must be strictly later than pre time")

    for moment_id, moment in moments.items():
        event_id = moment.get("eventId")
        if isinstance(event_id, str) and event_id not in events:
            errors.append(f"key moment {moment_id} references missing eventId: {event_id}")

    if route == "realizable" and not ordered_moments:
        errors.append("realizable route must contain at least one key moment")
    if route == "hybrid" and not any(
        moment.get("realizable") is True for moment in ordered_moments
    ):
        errors.append(
            "hybrid route must have at least one realizable key moment; use programmatic otherwise"
        )

    exported_count = 0
    pillow_available = False
    try:
        from PIL import Image

        pillow_available = True
    except ImportError:
        Image = None  # type: ignore[assignment,misc]

    for moment in ordered_moments:
        moment_id = moment["id"]
        must_have_assets = route == "realizable" or (
            route == "hybrid" and moment.get("realizable") is True
        )
        assets = moment.get("assets")
        if assets is None:
            if must_have_assets:
                errors.append(f"key moment {moment_id} must have presentation/clean/overlay assets")
            continue
        if not isinstance(assets, dict):
            errors.append(f"key moment {moment_id}.assets must be an object or null")
            continue
        exported_count += 1
        inspected: dict[str, tuple[int, int, bool]] = {}
        for mode in ("presentation", "clean", "overlay"):
            expected = f"{mode}/{moment_id}.png"
            relative = assets.get(mode)
            if relative != expected:
                errors.append(
                    f"key moment {moment_id} {mode} asset must be {expected!r}, got {relative!r}"
                )
                continue
            path = safe_child(
                bridge_dir,
                relative,
                f"key moment {moment_id} {mode} asset",
                errors,
            )
            if path is None:
                continue
            result = validate_png(path, f"key moment {moment_id} {mode} asset", errors)
            if result is not None:
                inspected[mode] = result
                asset_width, asset_height, alpha_capable = result
                if (asset_width, asset_height) != (width, height):
                    errors.append(
                        f"key moment {moment_id} {mode} is {asset_width}x{asset_height}, "
                        f"expected {width}x{height}"
                    )
                if mode == "overlay" and not alpha_capable:
                    errors.append(f"key moment {moment_id} overlay PNG has no alpha support")
                if mode == "overlay" and alpha_capable and pillow_available and Image is not None:
                    try:
                        with Image.open(path) as image:
                            alpha_min, _ = image.convert("RGBA").getchannel("A").getextrema()
                            if alpha_min == 255:
                                errors.append(
                                    f"key moment {moment_id} overlay is fully opaque; "
                                    "its background must be transparent"
                                )
                    except Exception as exc:
                        errors.append(f"could not inspect key moment {moment_id} overlay alpha: {exc}")
        dimensions = {(value[0], value[1]) for value in inspected.values()}
        if len(dimensions) > 1:
            errors.append(f"key moment {moment_id} asset dimensions do not match across modes")

    if exported_count and not pillow_available:
        warnings.append(
            "Pillow is unavailable; overlay alpha capability was checked from PNG headers, "
            "but actual transparent pixels were not inspected"
        )

    contact_sheet = manifest.get("contactSheet")
    contact_required = route in {"realizable", "hybrid"}
    if contact_required and contact_sheet is None:
        errors.append(f"{route} route requires contactSheet")
    if contact_sheet is not None:
        if contact_sheet != "contact_sheet.png":
            errors.append(
                f"contactSheet must be 'contact_sheet.png' when present, got {contact_sheet!r}"
            )
        else:
            contact_path = safe_child(bridge_dir, contact_sheet, "contactSheet", errors)
            if contact_path is not None:
                validate_png(contact_path, "contactSheet", errors)

    if errors:
        for error in errors:
            fail(error)
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print("PASS: Bridge outputs are structurally valid.")
    print(f"  route: {route}")
    print(f"  key moments: {len(ordered_moments)}")
    print(f"  exported moments: {exported_count}")
    print(f"  events: {len(events)}")
    print(f"  output directory: {bridge_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
