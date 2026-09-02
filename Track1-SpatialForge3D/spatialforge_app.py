"""
SpatialForge 3D - unified app
Text or image in, interactive 3D asset out. Fully local on AMD Radeon + ROCm.

Fast mode:    TripoSR   ~3s   textured (vertex colors)
Quality mode: TripoSG   ~75s  superior geometry + CPU smooth/decimate

All telemetry measured at runtime. Nothing estimated.
"""
import os
import sys
import time
import tempfile

import numpy as np
import torch
import itertools

import trimesh
import gradio as gr
from scipy.spatial import cKDTree
from PIL import Image

TRIPOSR_DIR = "/persistent/TripoSR"
TRIPOSG_DIR = "/persistent/TripoSG"
sys.path.insert(0, TRIPOSR_DIR)
sys.path.insert(0, TRIPOSG_DIR)
sys.path.insert(0, os.path.join(TRIPOSG_DIR, "scripts"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GPU_NAME = torch.cuda.get_device_name(0) if DEVICE == "cuda" else "CPU"
TOTAL_VRAM = (
    torch.cuda.get_device_properties(0).total_memory / 1024**3 if DEVICE == "cuda" else 0
)
print(f"[SpatialForge] {GPU_NAME} | {TOTAL_VRAM:.0f} GB VRAM | torch {torch.__version__}")

# ---------------------------------------------------------------- Fast: TripoSR
from turntable import render_turntable
from projtex import project_texture

from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground, to_gradio_3d_orientation
import rembg

t = time.time()
sr_model = TSR.from_pretrained(
    "stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt"
)
sr_model.renderer.set_chunk_size(8192)
sr_model.to(DEVICE)
SR_LOAD_MS = (time.time() - t) * 1000
rembg_session = rembg.new_session()
print(f"[SpatialForge] TripoSR resident in {SR_LOAD_MS:.0f} ms")

# ------------------------------------------------------------- Quality: TripoSG
from triposg.pipelines.pipeline_triposg import TripoSGPipeline
from image_process import prepare_image
from briarmbg import BriaRMBG
import pymeshlab

t = time.time()
_sg_weights = os.path.join(TRIPOSG_DIR, "pretrained_weights/TripoSG")
_rmbg_weights = os.path.join(TRIPOSG_DIR, "pretrained_weights/RMBG-1.4")
rmbg_net = BriaRMBG.from_pretrained(_rmbg_weights).to(DEVICE)
rmbg_net.eval()
sg_pipe = TripoSGPipeline.from_pretrained(_sg_weights).to(DEVICE, torch.float16)
SG_LOAD_MS = (time.time() - t) * 1000
print(f"[SpatialForge] TripoSG resident in {SG_LOAD_MS:.0f} ms")

# ------------------------------------------------------- Text: SDXL-Turbo (lazy)
_txt_pipe = None
TXT_LOAD_MS = 0.0


def get_text_pipe():
    global _txt_pipe, TXT_LOAD_MS
    if _txt_pipe is None:
        from diffusers import AutoPipelineForText2Image

        t = time.time()
        _txt_pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo", torch_dtype=torch.float16, variant="fp16"
        ).to(DEVICE)
        TXT_LOAD_MS = (time.time() - t) * 1000
        print(f"[SpatialForge] SDXL-Turbo resident in {TXT_LOAD_MS:.0f} ms")
    return _txt_pipe


# ------------------------------------------------------------------- helpers
def sync():
    if DEVICE == "cuda":
        torch.cuda.synchronize()


def _axis_aligned_rotations():
    Rs = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, pp in enumerate(perm):
                M[i, pp] = signs[i]
            if abs(np.linalg.det(M) - 1) < 1e-6:
                Rs.append(M)
    return Rs


_ROTATIONS = _axis_aligned_rotations()


def _unit(v):
    v = v - v.mean(axis=0)
    return v / np.abs(v).max()


def transfer_colors(src_mesh, dst_mesh):
    """Map vertex colors from a colored mesh onto an uncolored one.

    Both meshes describe the same object but come from different models, so
    scale and axis convention differ. Normalize both to a unit cube, search the
    24 axis-aligned rotations for the alignment with lowest mean nearest-neighbor
    distance, then copy colors by nearest neighbor.
    """
    src_cols = np.asarray(src_mesh.visual.vertex_colors)
    if src_cols.ndim != 2 or len(src_cols) != len(src_mesh.vertices):
        return dst_mesh, None

    sv = _unit(np.asarray(src_mesh.vertices, dtype=np.float64))
    dv = _unit(np.asarray(dst_mesh.vertices, dtype=np.float64))
    tree = cKDTree(sv)

    best_score, best_R = None, None
    for R in _ROTATIONS:
        score = tree.query(dv @ R.T, workers=-1)[0].mean()
        if best_score is None or score < best_score:
            best_score, best_R = score, R

    idx = tree.query(dv @ best_R.T, workers=-1)[1]
    dst_mesh.visual.vertex_colors = src_cols[idx]
    return dst_mesh, best_score


def decimate(mesh, n_faces):
    """pymeshlab quadric edge collapse. Same approach TripoSG ships."""
    if mesh.faces.shape[0] <= n_faces:
        return mesh
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
    ms.meshing_merge_close_vertices()
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=n_faces)
    m = ms.current_mesh()
    return trimesh.Trimesh(vertices=m.vertex_matrix(), faces=m.face_matrix())


def run_fast(image, fg_ratio, resolution):
    stages = {}

    t = time.time()
    img = remove_background(image, rembg_session)
    img = resize_foreground(img, fg_ratio)
    a = np.array(img).astype(np.float32) / 255.0
    a = a[:, :, :3] * a[:, :, 3:4] + (1 - a[:, :, 3:4]) * 0.5
    img = Image.fromarray((a * 255.0).astype(np.uint8))
    sync()
    stages["Background removal (u2net, CPU)"] = (time.time() - t) * 1000

    t = time.time()
    with torch.no_grad():
        codes = sr_model([img], device=DEVICE)
    sync()
    stages["TripoSR inference (GPU, AOTriton)"] = (time.time() - t) * 1000

    t = time.time()
    try:
        meshes = sr_model.extract_mesh(codes, has_vertex_color=True, resolution=resolution)
    except TypeError:
        meshes = sr_model.extract_mesh(codes, resolution=resolution)
    mesh = to_gradio_3d_orientation(meshes[0])
    stages["Marching cubes (CPU fallback)"] = (time.time() - t) * 1000

    return mesh, stages, img


def run_quality(image, steps, guidance, target_faces, smooth_iters, color_mode, fg_ratio, resolution):
    stages = {}

    t = time.time()
    _tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    image.convert("RGBA").save(_tmp.name)
    img = prepare_image(_tmp.name, bg_color=np.array([1.0, 1.0, 1.0]), rmbg_net=rmbg_net)
    sync()
    stages["Background removal (BriaRMBG, GPU)"] = (time.time() - t) * 1000

    t = time.time()
    with torch.no_grad():
        out = sg_pipe(
            image=img,
            generator=torch.Generator(device=sg_pipe.device).manual_seed(42),
            num_inference_steps=steps,
            guidance_scale=guidance,
        ).samples[0]
    sync()
    stages[f"TripoSG rectified flow, {steps} steps (GPU)"] = (time.time() - t) * 1000

    t = time.time()
    mesh = trimesh.Trimesh(out[0].astype(np.float32), np.ascontiguousarray(out[1]))
    raw_faces = len(mesh.faces)
    stages["Marching cubes, ROCm CPU patch"] = (time.time() - t) * 1000

    if smooth_iters > 0:
        t = time.time()
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=int(smooth_iters))
        stages[f"Taubin smoothing, {int(smooth_iters)} iters (CPU)"] = (time.time() - t) * 1000

    t = time.time()
    mesh = decimate(mesh, int(target_faces))
    stages[f"Quadric decimation, {raw_faces:,} to {len(mesh.faces):,} faces (CPU)"] = (
        time.time() - t
    ) * 1000

    if color_mode in ("Photo + model fill", "Photo projection"):
        t = time.time()
        base = None
        if color_mode == "Photo + model fill":
            sr_mesh, sr_stages, _ = run_fast(image, fg_ratio, resolution)
            for k, vv in sr_stages.items():
                stages["Base color pass: " + k] = vv
            tmp, _fit = transfer_colors(sr_mesh, mesh.copy())
            try:
                base = np.asarray(tmp.visual.vertex_colors)[:, :3].astype(np.float64)
            except Exception:
                base = None
            t = time.time()
        try:
            mesh, pinfo = project_texture(mesh, img, base_colors=base)
            stages[
                f"Photo projection [silhouette fit {pinfo['silhouette_fit']:.2f}, "
                f"{pinfo['visible_frac']*100:.0f}% direct] (CPU)"
            ] = (time.time() - t) * 1000
        except Exception as e:
            stages[f"Photo projection FAILED: {str(e)[:50]}"] = (time.time() - t) * 1000
    elif color_mode == "TripoSR colors":
        t = time.time()
        sr_mesh, sr_stages, _ = run_fast(image, fg_ratio, resolution)
        for k, v in sr_stages.items():
            stages["Color pass: " + k] = v
        mesh, fit = transfer_colors(sr_mesh, mesh)
        label = "Color transfer, TripoSR to TripoSG (CPU)"
        if fit is not None:
            label += f" [fit {fit:.4f}]"
        stages[label] = (time.time() - t) * 1000 - sum(sr_stages.values())

    return mesh, stages, img


def generate(mode, image, prompt, fg_ratio, resolution, steps, guidance, target_faces, smooth_iters, color_mode, do_video):
    if image is None and not (prompt or "").strip():
        return None, "", None, None, "Upload an image or enter a text prompt."

    if DEVICE == "cuda":
        torch.cuda.reset_peak_memory_stats()

    stages = {}
    source = "uploaded image"

    if image is None:
        pipe = get_text_pipe()
        t = time.time()
        with torch.no_grad():
            image = pipe(
                prompt=f"{prompt.strip()}, single object, centered, plain background, product photo",
                num_inference_steps=4,
                guidance_scale=0.0,
            ).images[0]
        sync()
        stages["SDXL-Turbo text to image (GPU)"] = (time.time() - t) * 1000
        source = "text prompt"

    if image.mode != "RGBA":
        image = image.convert("RGBA")

    if mode == "Fast (TripoSR)":
        mesh, s, proc = run_fast(image, fg_ratio, int(resolution))
    else:
        mesh, s, proc = run_quality(image, int(steps), guidance, target_faces, smooth_iters, color_mode, fg_ratio, int(resolution))
    stages.update(s)

    t = time.time()
    out = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
    mesh.export(out.name)
    stages["GLB export (CPU)"] = (time.time() - t) * 1000

    video_path = None
    if do_video:
        t = time.time()
        vf = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        try:
            render_turntable(mesh, vf.name, n_frames=90, size=640, fps=30)
            video_path = vf.name
            stages["Turntable render, 90 frames 640p (CPU)"] = (time.time() - t) * 1000
        except Exception as e:
            stages[f"Turntable render FAILED: {str(e)[:60]}"] = (time.time() - t) * 1000

    peak = torch.cuda.max_memory_allocated() / 1024**3 if DEVICE == "cuda" else 0
    total = sum(stages.values())
    size_mb = os.path.getsize(out.name) / 1024**2

    viewer = f"""
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.4.0/model-viewer.min.js"></script>
<model-viewer
  src="/file={out.name}"
  alt="Generated 3D asset"
  camera-controls
  auto-rotate
  auto-rotate-delay="0"
  rotation-per-second="24deg"
  environment-image="neutral"
  shadow-intensity="1.4"
  shadow-softness="0.9"
  exposure="1.15"
  tone-mapping="aces"
  camera-orbit="35deg 72deg 105%"
  style="width:100%;height:560px;background:linear-gradient(180deg,#1a1a1f 0%,#0d0d10 100%);border-radius:8px;">
</model-viewer>
"""

    rows = "\n".join(f"| {k} | {v:.0f} ms |" for k, v in stages.items())
    tele = f"""### ROCm Hardware Telemetry

| Stage | Time |
|---|---|
{rows}
| **End-to-end** | **{total:.0f} ms** |

**Mode:** {mode} | **Input:** {source}
**Hardware:** {GPU_NAME} (gfx1100) | ROCm 7.2.1 | PyTorch {torch.__version__}
**Peak VRAM:** {peak:.2f} GB of {TOTAL_VRAM:.0f} GB ({peak/TOTAL_VRAM*100:.1f}%)
**Mesh:** {len(mesh.vertices):,} vertices | {len(mesh.faces):,} faces | {size_mb:.1f} MB
**Model load excluded:** TripoSR {SR_LOAD_MS:.0f} ms, TripoSG {SG_LOAD_MS:.0f} ms
"""
    return proc, viewer, out.name, video_path, tele


EXAMPLES = [
    os.path.join(TRIPOSR_DIR, "examples", f)
    for f in ["chair.png", "teapot.png", "robot.png", "hamburger.png", "poly_fox.png"]
    if os.path.exists(os.path.join(TRIPOSR_DIR, "examples", f))
]

with gr.Blocks(title="SpatialForge 3D") as demo:
    gr.Markdown(
        "# SpatialForge 3D\n"
        "Text or image to interactive 3D asset. Fully local inference on AMD Radeon + ROCm.\n\n"
        "**Fast** runs TripoSR in about 3 seconds with vertex colors. "
        "**Quality** runs TripoSG for far better geometry, then smooths and decimates on CPU."
    )
    with gr.Row():
        with gr.Column(scale=1):
            mode = gr.Radio(
                ["Fast (TripoSR)", "Quality (TripoSG)"],
                value="Fast (TripoSR)",
                label="Mode",
            )
            in_img = gr.Image(label="Upload an image", type="pil", image_mode="RGBA")
            prompt = gr.Textbox(
                label="...or describe it (leave image empty)",
                placeholder="a weathered brass diving helmet",
            )
            with gr.Accordion("Fast mode settings", open=False):
                fg_ratio = gr.Slider(0.5, 1.0, value=0.85, step=0.05, label="Foreground ratio")
                resolution = gr.Slider(128, 320, value=256, step=32, label="Mesh grid")
            with gr.Accordion("Quality mode settings", open=False):
                steps = gr.Slider(20, 50, value=50, step=5, label="Flow steps")
                guidance = gr.Slider(3.0, 10.0, value=7.0, step=0.5, label="Guidance scale")
                target_faces = gr.Slider(
                    20000, 400000, value=120000, step=10000, label="Target faces"
                )
                smooth_iters = gr.Slider(0, 24, value=4, step=1, label="Taubin iterations")
                color_mode = gr.Radio(
                    ["None (clay)", "Photo + model fill", "Photo projection", "TripoSR colors"],
                    value="Photo + model fill",
                    label="Surface color",
                    info="Photo projection samples your actual input image onto the mesh",
                )
            do_video = gr.Checkbox(
                label="Render turntable MP4 (adds ~20s, CPU)", value=True
            )
            btn = gr.Button("Generate 3D Asset", variant="primary")
            proc_img = gr.Image(label="Preprocessed input", interactive=False)
        with gr.Column(scale=1):
            viewer_html = gr.HTML(
                '<div style="height:560px;display:flex;align-items:center;'
                'justify-content:center;background:linear-gradient(180deg,#1a1a1f,#0d0d10);'
                'border-radius:8px;color:#555;font-family:system-ui">'
                'Studio viewer loads after generation</div>'
            )
            out_3d = gr.Model3D(label="Download .glb", clear_color=[0.09, 0.09, 0.11, 1.0])
            out_vid = gr.Video(label="Turntable MP4", autoplay=True)
            tele = gr.Markdown("Telemetry appears after generation.")

    if EXAMPLES:
        gr.Examples(examples=EXAMPLES, inputs=[in_img], label="Examples")

    btn.click(
        generate,
        inputs=[mode, in_img, prompt, fg_ratio, resolution, steps, guidance, target_faces, smooth_iters, color_mode, do_video],
        outputs=[proc_img, viewer_html, out_3d, out_vid, tele],
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)