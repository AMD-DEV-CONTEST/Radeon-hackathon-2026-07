"""
Turntable MP4 renderer for SpatialForge 3D.

Pure CPU software rasterizer. No OpenGL, no display, no CUDA. Uses a
painter's algorithm with backface culling and Lambert + rim shading, then
supersamples down for antialiasing. Encodes with imageio-ffmpeg.
"""
import numpy as np
from PIL import Image, ImageDraw
import imageio.v2 as imageio


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def _rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def _prepare(mesh, max_faces):
    """Decimate if needed, center, and scale to fit a unit sphere."""
    m = mesh
    if len(m.faces) > max_faces:
        try:
            m = m.simplify_quadric_decimation(face_count=max_faces)
        except Exception:
            pass

    v = np.asarray(m.vertices, dtype=np.float64)
    f = np.asarray(m.faces, dtype=np.int64)

    v = v - (v.min(axis=0) + v.max(axis=0)) / 2.0
    radius = np.linalg.norm(v, axis=1).max()
    if radius > 0:
        v = v / radius

    cols = None
    try:
        vc = np.asarray(m.visual.vertex_colors)
        if vc.ndim == 2 and len(vc) == len(v):
            cols = vc[:, :3].astype(np.float64) / 255.0
    except Exception:
        cols = None

    return v, f, cols


def render_turntable(
    mesh,
    out_path,
    n_frames=90,
    size=640,
    fps=30,
    supersample=2,
    elevation_deg=18.0,
    max_faces=30000,
    base_color=(0.78, 0.78, 0.80),
    bg_top=(26, 26, 31),
    bg_bottom=(13, 13, 16),
):
    v, f, vcols = _prepare(mesh, max_faces)
    S = size * supersample

    # Backdrop gradient, drawn once and reused.
    grad = np.zeros((S, S, 3), dtype=np.uint8)
    for i in range(S):
        t = i / max(S - 1, 1)
        grad[i, :, :] = [
            int(bg_top[c] * (1 - t) + bg_bottom[c] * t) for c in range(3)
        ]
    backdrop = Image.fromarray(grad)

    Rx = _rot_x(np.deg2rad(elevation_deg))
    key = np.array([-0.35, 0.55, 0.75])
    key /= np.linalg.norm(key)
    fill = np.array([0.6, 0.1, 0.35])
    fill /= np.linalg.norm(fill)

    scale = S * 0.40
    cx = cy = S / 2.0

    writer = imageio.get_writer(
        out_path, fps=fps, codec="libx264", quality=8, macro_block_size=1
    )

    try:
        for i in range(n_frames):
            ang = 2.0 * np.pi * i / n_frames
            M = Rx @ _rot_y(ang)
            vr = v @ M.T

            tri = vr[f]                                  # (F,3,3)
            e1 = tri[:, 1] - tri[:, 0]
            e2 = tri[:, 2] - tri[:, 0]
            n = np.cross(e1, e2)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            ln[ln == 0] = 1.0
            n = n / ln

            front = n[:, 2] > 0.0                        # backface cull
            if not front.any():
                front = np.ones(len(f), dtype=bool)

            idx = np.nonzero(front)[0]
            depth = tri[idx, :, 2].mean(axis=1)
            order = idx[np.argsort(depth)]               # far to near

            nn = n[order]
            lam = np.clip(nn @ key, 0, 1)
            lam2 = np.clip(nn @ fill, 0, 1)
            rim = np.power(np.clip(1.0 - nn[:, 2], 0, 1), 2.5)
            shade = 0.18 + 0.72 * lam + 0.22 * lam2 + 0.30 * rim

            if vcols is not None:
                base = vcols[f[order]].mean(axis=1)
            else:
                base = np.tile(np.array(base_color), (len(order), 1))

            rgb = np.clip(base * shade[:, None], 0, 1)
            rgb = np.power(rgb, 1 / 2.2)                 # gamma
            rgb8 = (rgb * 255).astype(np.uint8)

            xs = tri[order, :, 0] * scale + cx
            ys = -tri[order, :, 1] * scale + cy
            pts = np.stack([xs, ys], axis=2).astype(np.int32)

            img = backdrop.copy()
            draw = ImageDraw.Draw(img)
            for p, c in zip(pts, rgb8):
                draw.polygon(
                    [(p[0, 0], p[0, 1]), (p[1, 0], p[1, 1]), (p[2, 0], p[2, 1])],
                    fill=(int(c[0]), int(c[1]), int(c[2])),
                )

            frame = img.resize((size, size), Image.LANCZOS)
            writer.append_data(np.asarray(frame))
    finally:
        writer.close()

    return out_path