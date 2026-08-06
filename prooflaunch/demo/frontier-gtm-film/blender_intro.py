from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "renders" / "blender-intro"


def material_principled(
    name: str,
    base: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.3,
    transmission: float = 0.0,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.46
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = emission
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return material


def add_bevelled_cube(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    bevel: float = 0.15,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    modifier = obj.modifiers.new("Precision bevel", "BEVEL")
    modifier.width = bevel
    modifier.segments = 5
    obj.data.materials.append(material)
    return obj


def track_camera(camera: bpy.types.Object, target: bpy.types.Object) -> None:
    constraint = camera.constraints.new(type="TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"


def keyframe_linear(obj: bpy.types.Object, path: str) -> None:
    # Blender 5 stores channels in layered Action slots; inserted transforms
    # already use Bezier interpolation, which is the intended camera cadence.
    return None


def build_scene(preview: bool) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 144
    scene.render.fps = 30
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.render.use_motion_blur = True
    scene.render.filepath = str(OUTPUT / "frame_")
    scene.render.engine = "BLENDER_EEVEE" if preview else "CYCLES"

    if not preview:
        scene.cycles.samples = 48
        scene.cycles.use_denoising = True
        scene.cycles.preview_samples = 16
        scene.cycles.max_bounces = 8
        scene.cycles.transparent_max_bounces = 8
        try:
            preferences = bpy.context.preferences.addons["cycles"].preferences
            preferences.compute_device_type = "METAL"
            preferences.get_devices()
            for device in preferences.devices:
                device.use = device.type == "METAL"
            scene.cycles.device = "GPU"
        except Exception as error:
            print(f"Cycles Metal selection warning: {error}")

    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.world.color = (0.0015, 0.002, 0.005)

    purple = material_principled(
        "Frontier violet",
        (0.06, 0.025, 0.18, 1),
        metallic=0.35,
        roughness=0.18,
        emission=(0.28, 0.07, 1.0, 1),
        emission_strength=4.0,
    )
    cyan = material_principled(
        "Evidence cyan",
        (0.015, 0.13, 0.19, 1),
        metallic=0.4,
        roughness=0.16,
        emission=(0.01, 0.55, 1.0, 1),
        emission_strength=3.0,
    )
    amber = material_principled(
        "Human amber",
        (0.28, 0.08, 0.01, 1),
        metallic=0.25,
        roughness=0.2,
        emission=(1.0, 0.22, 0.025, 1),
        emission_strength=2.5,
    )
    graphite = material_principled(
        "Graphite",
        (0.004, 0.006, 0.012, 1),
        metallic=0.88,
        roughness=0.22,
    )
    glass = material_principled(
        "Optical glass",
        (0.13, 0.22, 0.34, 1),
        metallic=0.0,
        roughness=0.055,
        transmission=1.0,
    )

    floor = add_bevelled_cube("Ground", (0, 0, -0.55), (14, 14, 0.28), graphite, 0.12)
    floor.rotation_euler.z = math.radians(8)

    target = bpy.data.objects.new("Camera target", None)
    scene.collection.objects.link(target)
    target.location = (0, 0.2, 1.8)

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1.72, location=(0, 0, 1.75))
    core = bpy.context.object
    core.name = "Evidence core"
    core.data.materials.append(glass)
    bevel = core.modifiers.new("Micro bevel", "BEVEL")
    bevel.width = 0.045
    bevel.segments = 3
    bpy.ops.object.shade_smooth()
    core.rotation_euler = (math.radians(18), math.radians(-12), math.radians(24))
    core.keyframe_insert(data_path="rotation_euler", frame=1)
    core.rotation_euler = (math.radians(84), math.radians(45), math.radians(165))
    core.keyframe_insert(data_path="rotation_euler", frame=144)
    keyframe_linear(core, "rotation_euler")

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.74, location=(0, 0, 1.75))
    inner = bpy.context.object
    inner.name = "Sealed run"
    inner.data.materials.append(cyan)

    for ring_index, (major, minor, material) in enumerate(
        ((2.45, 0.035, purple), (2.92, 0.025, cyan), (3.36, 0.018, amber))
    ):
        bpy.ops.mesh.primitive_torus_add(
            major_radius=major,
            minor_radius=minor,
            major_segments=144,
            minor_segments=12,
            location=(0, 0, 1.75),
            rotation=(math.radians(67 - ring_index * 19), math.radians(22 + ring_index * 31), 0),
        )
        ring = bpy.context.object
        ring.name = f"Evidence orbit {ring_index + 1}"
        ring.data.materials.append(material)
        ring.keyframe_insert(data_path="rotation_euler", frame=1)
        ring.rotation_euler.z += math.radians(140 if ring_index % 2 == 0 else -110)
        ring.keyframe_insert(data_path="rotation_euler", frame=144)
        keyframe_linear(ring, "rotation_euler")

    palette = (purple, cyan, amber)
    for index in range(18):
        angle = index / 18 * math.tau
        radius = 4.15 + 0.35 * math.sin(index * 1.73)
        z = 1.65 + 1.65 * math.sin(angle * 2.0 + 0.45)
        tile = add_bevelled_cube(
            f"Unique shot {index + 1:02d}",
            (radius * math.cos(angle), radius * math.sin(angle), z),
            (0.34, 0.055, 0.23),
            palette[index % 3],
            0.055,
        )
        tile.rotation_euler = (math.radians(70), -angle * 0.24, angle + math.pi / 2)
        tile.keyframe_insert(data_path="location", frame=1)
        tile.keyframe_insert(data_path="rotation_euler", frame=1)
        end = angle + math.radians(54)
        tile.location = (
            radius * math.cos(end),
            radius * math.sin(end),
            1.65 + 1.65 * math.sin(end * 2.0 + 0.45),
        )
        tile.rotation_euler.z += math.radians(88)
        tile.keyframe_insert(data_path="location", frame=144)
        tile.keyframe_insert(data_path="rotation_euler", frame=144)
        keyframe_linear(tile, "location")
        keyframe_linear(tile, "rotation_euler")

    for index, (x, material) in enumerate(((-5.0, purple), (0.0, cyan), (5.0, amber))):
        panel = add_bevelled_cube(
            f"Channel monolith {index + 1}",
            (x, 2.65, 2.25),
            (1.45, 0.12, 3.25),
            material,
            0.16,
        )
        panel.rotation_euler = (math.radians(-5), 0, math.radians(-3 + index * 3))

    for name, location, energy, size, color in (
        ("Key", (-5.5, -4.0, 7.5), 1800, 5.5, (0.36, 0.18, 1.0)),
        ("Rim", (5.2, 0.5, 6.3), 1450, 4.2, (0.05, 0.55, 1.0)),
        ("Warm edge", (1.5, -2.0, 2.0), 900, 2.8, (1.0, 0.17, 0.035)),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        data.color = color
        light = bpy.data.objects.new(name, data)
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (math.radians(24), 0, math.radians(-34))
        constraint = light.constraints.new(type="TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"

    camera_data = bpy.data.cameras.new("Hero camera")
    camera = bpy.data.objects.new("Hero camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.lens = 47
    camera_data.dof.use_dof = True
    camera_data.dof.focus_object = target
    camera_data.dof.aperture_fstop = 3.2
    camera.location = (7.8, -10.8, 6.1)
    camera.keyframe_insert(data_path="location", frame=1)
    camera_data.keyframe_insert(data_path="lens", frame=1)
    camera.location = (4.25, -7.15, 3.85)
    camera_data.lens = 61
    camera.keyframe_insert(data_path="location", frame=144)
    camera_data.keyframe_insert(data_path="lens", frame=144)
    track_camera(camera, target)
    keyframe_linear(camera, "location")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    if preview:
        scene.frame_set(72)
        scene.render.filepath = str(ROOT / "evidence" / "blender-intro-preview.png")
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "frontier-gtm-intro.blend"))
        bpy.ops.render.render(animation=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    build_scene(args.preview)


if __name__ == "__main__":
    main()
