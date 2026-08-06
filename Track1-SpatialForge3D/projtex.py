"""
Front-projection texturing for SpatialForge 3D.

TripoSR's vertex colors are soft. The input photo is not. This module finds the
camera orientation whose mesh silhouette best matches the input image, then
samples the actual photo pixels onto the visible surface. Hidden vertices are
filled by nearest neighbor from the visible set, so the back stays plausible
instead of blank.

Pure numpy + PIL. No GPU, no OpenGL, no new model weights.
"""
import itertools

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree


def _axis_aligned_rotations():
    Rs = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, p in enumerate(perm):
                M[i, p] = signs[i]
            if abs(np.linalg.det(M) - 1) < 1e-6:
                Rs.append(M)
    return Rs


_ROTATIONS = _axis_aligned_rotations()


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _normalize(v):
    v = v - (v.min(axis=0) + v.max(axis=0)) / 2.0
    scale = np.abs(v).max()
    return v / (scale if scale > 0 else 1.0)


def _silhouette(pts_xy, res):
    """Rasterize projected points into a filled occupancy mask."""
    ij = np.clip(((pts_xy + 1.0) * 0.5 * (res - 1)).astype(np.int32), 0, res - 1)
    m = np.zeros((res, res), dtype=bool)
    m[ij[:, 1], ij[:, 0]] = True
    m = ndimage.binary_dilation(m, iterations=2)
    return ndimage.binary_fill_holes(m)


def _image_mask(img, res):
    """Binary mask of the subject from an RGBA or near-white-background image."""
    im = img.convert("RGBA").resize((res, res), Image.BILINEAR)
    a = np.asarray(im)
    alpha = a[:, :, 3]
    if alpha.min() < 250:
        return alpha > 127
    rgb = a[:, :, :3].astype(np.int32)
    return rgb.sum(axis=2) < (250 * 3)


def find_front_view(mesh, image, res=72, refine=True):
    """Return the rotation whose silhouette best matches the image."""
    v = _normalize(np.asarray(mesh.vertices, dtype=np.float64))
    target = _image_mask(image, res)
    target_flip = target[::-1, :]

    def iou(mask):
        inter = np.logical_and(mask, target).sum()
        union = np.logical_or(mask, target).sum()
        a = inter / union if union else 0.0
        inter2 = np.logical_and(mask, target_flip).sum()
        union2 = np.logical_or(mask, target_flip).sum()
        b = inter2 / union2 if union2 else 0.0
        return max(a, b)

    best_score, best_R = -1.0, np.eye(3)
    for R in _ROTATIONS:
        s = iou(_silhouette((v @ R.T)[:, :2], res))
        if s > best_score:
            best_score, best_R = s, R

    if refine:
        for ay in np.deg2rad(np.arange(-20, 21, 5)):
            for ax in np.deg2rad(np.arange(-12, 13, 6)):
                R = _rot_x(ax) @ _rot_y(ay) @ best_R
                s = iou(_silhouette((v @ R.T)[:, :2], res))
                if s > best_score:
                    best_score, best_R = s, R

    return best_R, best_score


def project_texture(mesh, image, zbuf_res=512, fallback=(200, 198, 195), base_colors=None):
    """Sample the input photo onto the mesh from its best-matching front view.

    Returns (mesh, info). The mesh gains per-vertex colors: real photo pixels on
    the visible surface, nearest-neighbor fill elsewhere.
    """
    R, fit = find_front_view(mesh, image)

    v_raw = np.asarray(mesh.vertices, dtype=np.float64)
    v = _normalize(v_raw) @ R.T
    n = np.asarray(mesh.vertex_normals, dtype=np.float64) @ R.T

    img = image.convert("RGB")
    W, H = img.size
    pix = np.asarray(img)

    # Fit the projection to the subject's bounding box in image space so the
    # mesh silhouette and the photo subject line up rather than the full frame.
    mask = _image_mask(image, max(W, H) // 4)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        x0, x1, y0, y1 = 0, mask.shape[1] - 1, 0, mask.shape[0] - 1
    else:
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    sx = (x0 + (x1 - x0) * ((v[:, 0] + 1) / 2)) / (mask.shape[1] - 1)
    sy = (y0 + (y1 - y0) * ((1 - v[:, 1]) / 2)) / (mask.shape[0] - 1)

    px = np.clip((sx * (W - 1)).astype(np.int32), 0, W - 1)
    py = np.clip((sy * (H - 1)).astype(np.int32), 0, H - 1)
    sampled = pix[py, px].astype(np.float64)

    # Visibility: front-facing plus nearest along the view axis in a z-buffer.
    facing = n[:, 2] > 0.02
    gi = np.clip(((v[:, 0] + 1) * 0.5 * (zbuf_res - 1)).astype(np.int32), 0, zbuf_res - 1)
    gj = np.clip(((v[:, 1] + 1) * 0.5 * (zbuf_res - 1)).astype(np.int32), 0, zbuf_res - 1)
    key = gj.astype(np.int64) * zbuf_res + gi

    # Depth-tolerant occlusion: a vertex counts as visible if it sits within
    # `tol` of the frontmost surface in its cell, not only if it is the single
    # nearest. Strict winner-takes-all discards most of a dense mesh.
    tol = 0.03 * (v[:, 2].max() - v[:, 2].min())
    front_z = {}
    for k, z in zip(key, v[:, 2]):
        if k not in front_z or z > front_z[k]:
            front_z[k] = z
    fz = np.array([front_z[k] for k in key])
    unoccluded = v[:, 2] >= (fz - tol)

    visible = facing & unoccluded
    if visible.sum() < 32:
        visible = facing
    if visible.sum() < 32:
        cols = np.tile(np.array(fallback, dtype=np.float64), (len(v), 1))
    else:
        cols = np.empty((len(v), 3), dtype=np.float64)
        cols[visible] = sampled[visible]
        hidden = ~visible
        if hidden.any():
            if base_colors is not None and len(base_colors) == len(v):
                # Model-predicted colors are a better guess for unseen surface
                # than smearing copies of front-facing photo pixels.
                cols[hidden] = np.asarray(base_colors, dtype=np.float64)[hidden]
            else:
                tree = cKDTree(v[visible])
                _, nn = tree.query(v[hidden], workers=-1)
                cols[hidden] = sampled[visible][nn] * 0.82

    # Blend photo and fill at grazing angles so the seam is gradual, then
    # smooth speckle where visible and filled vertices interleave.
    if visible.sum() >= 32:
        w = np.clip(n[:, 2] / 0.30, 0.0, 1.0)[:, None]
        if base_colors is not None and len(base_colors) == len(v):
            fill_ref = np.asarray(base_colors, dtype=np.float64)
        else:
            fill_ref = cols.copy()
        cols = np.where(visible[:, None], cols * w + fill_ref * (1 - w), cols)

        tree_all = cKDTree(v)
        _, knn = tree_all.query(v, k=9, workers=-1)
        cols = cols[knn].mean(axis=1)

    rgba = np.concatenate(
        [np.clip(cols, 0, 255).astype(np.uint8),
         np.full((len(v), 1), 255, dtype=np.uint8)], axis=1
    )
    mesh.visual.vertex_colors = rgba

    return mesh, {
        "silhouette_fit": float(fit),
        "visible_frac": float(visible.mean()),
        "n_vertices": int(len(v)),
    }