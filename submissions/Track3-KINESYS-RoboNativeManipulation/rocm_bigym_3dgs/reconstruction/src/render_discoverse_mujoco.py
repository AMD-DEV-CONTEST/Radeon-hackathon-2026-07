#!/usr/bin/env python3
"""Render a native 3DGS background from MuJoCo camera state."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import av
import mujoco
import numpy as np
import torch
from gaussian_renderer.gs_renderer_mujoco import GSRendererMuJoCo
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scipy.spatial.transform import Rotation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seconds", type=int, default=18)
    parser.add_argument("--scene-slug", default="mipnerf360_kitchen")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_mjcf(
    output: Path,
    fovy: float,
    width: int,
    height: int,
    scene_slug: str,
) -> Path:
    if not scene_slug.replace("_", "").replace("-", "").isalnum():
        raise RuntimeError(f"unsafe scene slug: {scene_slug!r}")
    xml = f"""<mujoco model="{scene_slug}_native_gaussian_background">
  <compiler angle="degree" autolimits="true"/>
  <option timestep="0.002" gravity="0 0 -9.81" integrator="RK4"/>
  <visual>
    <global offwidth="{width}" offheight="{height}" fovy="{fovy:.9g}"/>
    <map znear="0.01"/>
  </visual>
  <worldbody>
    <body name="gaussian_camera_rig" mocap="true">
      <camera name="gaussian_camera" mode="fixed" fovy="{fovy:.9g}"/>
    </body>
  </worldbody>
</mujoco>
"""
    path = output / f"{scene_slug}_gaussian.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def set_mujoco_camera(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    c2w_opencv: np.ndarray,
    fovy: float,
    camera_id: int,
) -> None:
    if c2w_opencv.shape != (4, 4) or not np.isfinite(c2w_opencv).all():
        raise RuntimeError("invalid camera-to-world matrix")
    conversion = np.diag([1.0, -1.0, -1.0])
    rotation_mujoco = c2w_opencv[:3, :3] @ conversion
    quaternion_xyzw = Rotation.from_matrix(rotation_mujoco).as_quat()
    data.mocap_pos[0] = c2w_opencv[:3, 3]
    data.mocap_quat[0] = quaternion_xyzw[[3, 0, 1, 2]]
    model.cam_fovy[camera_id] = fovy
    mujoco.mj_forward(model, data)


def tensor_to_rgb(tensor: torch.Tensor) -> np.ndarray:
    return (
        tensor.clamp(0.0, 1.0)
        .mul(255.0)
        .byte()
        .detach()
        .cpu()
        .numpy()
    )


def panel(image: Image.Image, title: str, size: tuple[int, int]) -> Image.Image:
    fitted = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size[0], size[1] + 54), (15, 18, 24))
    canvas.paste(fitted, (0, 54))
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 18), title, font=ImageFont.load_default(), fill=(242, 244, 248))
    return canvas


def make_comparison(
    assets: Path,
    mujoco_heldout: Path,
    destination: Path,
) -> None:
    panels = [
        panel(Image.open(assets / "reference_source.png"), "Original held-out RGB", (640, 480)),
        panel(Image.open(assets / "reference_gsplat.png"), "3DGS exact-K held-out", (640, 480)),
        panel(Image.open(mujoco_heldout), "MuJoCo-driven native 3DGS", (640, 480)),
    ]
    comparison = Image.new("RGB", (1920, 534))
    for index, item in enumerate(panels):
        comparison.paste(item, (index * 640, 0))
    comparison.save(destination)


def make_contact_sheet(frames: list[np.ndarray], destination: Path) -> None:
    if len(frames) != 9:
        raise RuntimeError(f"expected 9 contact-sheet frames, found {len(frames)}")
    sheet = Image.new("RGB", (1920, 1080), (0, 0, 0))
    for index, frame in enumerate(frames):
        thumbnail = ImageOps.fit(
            Image.fromarray(frame),
            (640, 360),
            method=Image.Resampling.LANCZOS,
        )
        sheet.paste(thumbnail, ((index % 3) * 640, (index // 3) * 360))
    sheet.save(destination)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    camera_path = json.loads(
        (args.assets / "camera-path.json").read_text(encoding="utf-8")
    )
    trajectory = np.asarray(camera_path["camtoworlds"], dtype=np.float64)
    expected_frames = args.seconds * args.fps
    if trajectory.shape != (expected_frames, 4, 4):
        raise RuntimeError(
            f"camera path shape {trajectory.shape} != {(expected_frames, 4, 4)}"
        )
    coverage = camera_path["coverage"]
    coverage_passed = (
        float(coverage["max_nearest_training_translation"]) <= 0.25
        and float(coverage["max_nearest_training_rotation_degrees"]) <= 20.0
    )
    if not coverage_passed:
        raise RuntimeError(f"camera trajectory leaves capture envelope: {coverage}")

    ply_path = args.assets / "gaussians.ply"
    if not ply_path.is_file():
        raise RuntimeError(f"missing Gaussian PLY: {ply_path}")
    fovy = float(camera_path["fovy_degrees"])
    xml_path = write_mjcf(
        args.output,
        fovy,
        args.width,
        args.height,
        args.scene_slug,
    )
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    camera_id = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_CAMERA,
        "gaussian_camera",
    )
    if camera_id < 0 or model.ngeom != 0 or model.nmocap != 1:
        raise RuntimeError(
            f"unexpected MJCF structure: camera={camera_id} ngeom={model.ngeom} "
            f"nmocap={model.nmocap}"
        )

    config = {
        "schema_version": 1,
        "use_gaussian_renderer": True,
        "gs_model_dict": {"background": "gaussians.ply"},
        "mujoco_scene": xml_path.name,
        "background_mujoco_body": None,
        "background_mesh": None,
        "background_collision": False,
    }
    config_path = args.output / "discoverse-config.json"
    config_path.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    renderer = GSRendererMuJoCo({"background": str(ply_path)}, model)
    if len(renderer.gs_body_ids) != 0 or bool(renderer.dynamic_mask.any()):
        raise RuntimeError("background Gaussian was unexpectedly mapped to a MuJoCo body")

    comparison = camera_path["comparison"]
    comparison_c2w = np.asarray(comparison["camtoworld"], dtype=np.float64)
    set_mujoco_camera(
        model,
        data,
        comparison_c2w,
        float(comparison["fovy_degrees"]),
        camera_id,
    )
    comparison_render = renderer.render(
        model,
        data,
        [camera_id],
        args.width,
        args.height,
    )[camera_id][0]
    heldout_path = args.output / f"{args.scene_slug}_mujoco_heldout.png"
    Image.fromarray(tensor_to_rgb(comparison_render)).save(heldout_path)

    video_path = args.output / f"{args.scene_slug}_mujoco_3dgs.mp4"
    container = av.open(str(video_path), mode="w")
    stream = container.add_stream("libx264", rate=args.fps)
    stream.width = args.width
    stream.height = args.height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "17", "preset": "medium"}

    preview_index = expected_frames // 2
    preview_rgb: np.ndarray | None = None
    sample_indices = set(np.linspace(0, expected_frames - 1, 9).round().astype(int))
    sampled_frames: list[np.ndarray] = []
    black_fractions: list[float] = []
    finite_depth_fractions: list[float] = []
    luminance_means: list[float] = []
    finite_state = True
    started = time.perf_counter()
    for frame_index, c2w in enumerate(trajectory):
        target_time = (frame_index + 1) / args.fps
        while data.time + 1e-10 < target_time:
            mujoco.mj_step(model, data)
            finite_state = finite_state and bool(
                np.isfinite(data.qpos).all()
                and np.isfinite(data.qvel).all()
                and np.isfinite(data.qacc).all()
            )
        set_mujoco_camera(model, data, c2w, fovy, camera_id)
        renderer.update_gaussians(data)
        rgb_tensor, depth_tensor = renderer.render(
            model,
            data,
            [camera_id],
            args.width,
            args.height,
        )[camera_id]
        rgb = tensor_to_rgb(rgb_tensor)
        depth = depth_tensor.detach().cpu().numpy()
        black_fractions.append(float(np.mean(np.max(rgb, axis=2) < 5)))
        finite_depth_fractions.append(
            float(np.mean(np.isfinite(depth) & (depth > 0.0)))
        )
        luminance_means.append(
            float(
                np.mean(
                    0.2126 * rgb[..., 0]
                    + 0.7152 * rgb[..., 1]
                    + 0.0722 * rgb[..., 2]
                )
            )
        )
        if frame_index == preview_index:
            preview_rgb = rgb.copy()
        if frame_index in sample_indices:
            sampled_frames.append(rgb.copy())
        frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    render_seconds = time.perf_counter() - started

    if preview_rgb is None:
        raise RuntimeError("preview frame was not produced")
    preview_path = args.output / f"{args.scene_slug}_mujoco_preview.png"
    Image.fromarray(preview_rgb).save(preview_path)
    comparison_path = args.output / f"{args.scene_slug}_three_way.png"
    make_comparison(args.assets, heldout_path, comparison_path)
    contact_sheet_path = args.output / f"{args.scene_slug}_contact_sheet.png"
    make_contact_sheet(sampled_frames, contact_sheet_path)

    decoded_frames = 0
    with av.open(str(video_path)) as decoded:
        video_stream = decoded.streams.video[0]
        codec_name = video_stream.codec_context.name
        pixel_format = video_stream.codec_context.format.name
        decoded_width = int(video_stream.width)
        decoded_height = int(video_stream.height)
        decoded_fps = float(video_stream.average_rate)
        for _ in decoded.decode(video=0):
            decoded_frames += 1

    visual_coverage_passed = (
        float(np.median(black_fractions)) <= 0.05
        and float(max(black_fractions)) <= 0.20
        and float(np.median(finite_depth_fractions)) >= 0.80
        and float(np.mean(luminance_means)) >= 20.0
    )
    video_passed = (
        decoded_frames == expected_frames
        and codec_name == "h264"
        and pixel_format == "yuv420p"
        and decoded_width == args.width
        and decoded_height == args.height
        and abs(decoded_fps - args.fps) < 1e-6
    )
    passed = finite_state and coverage_passed and visual_coverage_passed and video_passed
    report = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "integration": {
            "renderer": "gaussian_renderer.GSRendererMuJoCo",
            "configuration": config,
            "ply_loaded_directly": True,
            "mesh_or_obj_loaded": False,
            "static_background": True,
        },
        "mujoco": {
            "version": mujoco.__version__,
            "xml_compiled": True,
            "simulation_seconds": args.seconds,
            "finite_state": finite_state,
            "model_bodies": int(model.nbody),
            "model_geoms": int(model.ngeom),
            "model_contacts_final": int(data.ncon),
            "background_body_count": 0,
            "background_geom_count": 0,
            "background_collision_count": 0,
        },
        "camera_coverage": {
            "passed": coverage_passed,
            **coverage,
        },
        "visual_coverage": {
            "passed": visual_coverage_passed,
            "black_fraction_median": float(np.median(black_fractions)),
            "black_fraction_max": float(max(black_fractions)),
            "finite_depth_fraction_median": float(
                np.median(finite_depth_fractions)
            ),
            "luminance_mean": float(np.mean(luminance_means)),
        },
        "video": {
            "passed": video_passed,
            "path": video_path.name,
            "codec": codec_name,
            "pixel_format": pixel_format,
            "width": decoded_width,
            "height": decoded_height,
            "fps": decoded_fps,
            "frames": decoded_frames,
            "duration_seconds": decoded_frames / args.fps,
            "render_wall_seconds": render_seconds,
            "render_fps": decoded_frames / render_seconds,
            "bytes": video_path.stat().st_size,
            "sha256": sha256(video_path),
        },
        "artifacts": {
            "preview": preview_path.name,
            "heldout": heldout_path.name,
            "comparison": comparison_path.name,
            "contact_sheet": contact_sheet_path.name,
            "mjcf": xml_path.name,
            "config": config_path.name,
        },
    }
    report_path = args.output / "mujoco-discoverse-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    renderer = None
    torch.cuda.empty_cache()
    if not passed:
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
