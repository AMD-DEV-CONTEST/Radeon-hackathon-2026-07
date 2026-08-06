"""Dependency-light surface meshes from reconstructed point clouds.

Builds a binary occupancy grid at `voxel_fraction` of the cloud diagonal,
optionally dilates it to close small holes, and emits a quad (two
triangles) for every occupied-voxel face adjacent to empty space. Triangle
winding is oriented so normals point away from the voxel centre, giving a
valid (if coarse) closed surface for downstream measurement / viewing.

This is deliberately simple: plants are thin and irregular, so a smooth
Poisson-style surface is out of scope for the cost-controlled pipeline;
the voxel surface is a robust, dependency-free topology deliverable.

``implicit_voxel_mesh`` is the presentation-oriented alternative. It cleans a
binary occupancy grid with 6-connectivity, turns it into a smooth scalar field,
and extracts an isosurface with marching tetrahedra. Unlike the legacy exposed
voxel-face mesh, disconnected shells never share corner vertices and the output
does not contain axis-aligned staircase faces.
"""

from __future__ import annotations

import numpy as np

_CUBE_CORNERS = np.asarray(
    [
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    ],
    dtype=np.int64,
)

# Six tetrahedra sharing the 0--6 body diagonal. Applying the same split to
# every grid cell gives matching diagonals on shared cube faces.
_CUBE_TETRAHEDRA = (
    (0, 1, 2, 6),
    (0, 2, 3, 6),
    (0, 3, 7, 6),
    (0, 7, 4, 6),
    (0, 4, 5, 6),
    (0, 5, 1, 6),
)

# Face tables for a unit voxel at grid offset (0,0,0): each entry is the
# quad's 4 corner offsets (x, y, z) in counter-clockwise order as seen from
# outside, plus the outward normal offset used to find the neighbouring cell.
_FACES = [
    ([(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)], (1, 0, 0)),  # +x
    ([(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)], (-1, 0, 0)),  # -x
    ([(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)], (0, 1, 0)),  # +y
    ([(0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)], (0, -1, 0)),  # -y
    ([(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)], (0, 0, 1)),  # +z
    ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], (0, 0, -1)),  # -z
]


def voxel_surface_mesh(
    points: np.ndarray,
    *,
    voxel_fraction: float = 0.01,
    dilate: int = 1,
    maximum: int = 400_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, faces) of a voxel-surface mesh in the input frame.

    `vertices` is (V, 3) float64; `faces` is (F, 3) int64 triangle indices.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 4:
        raise ValueError(f"points must have shape (M, 3) with M >= 4, got {pts.shape}")
    finite = pts[np.isfinite(pts).all(axis=1)]
    if len(finite) < 4:
        raise ValueError("fewer than 4 finite points")
    diagonal = float(np.linalg.norm(finite.max(axis=0) - finite.min(axis=0)))
    if diagonal <= 0.0:
        raise ValueError("point cloud has zero diagonal")
    if len(finite) > maximum:
        indices = np.sort(
            np.random.default_rng(0).choice(len(finite), maximum, replace=False)
        )
        finite = finite[indices]
    voxel_size = float(diagonal * voxel_fraction)
    origin = finite.min(axis=0)
    indices = np.floor((finite - origin) / voxel_size).astype(np.int64)
    shape = tuple(int(indices[:, axis].max()) + 1 for axis in range(3))
    grid = np.zeros(shape, dtype=np.uint8)
    grid[tuple(indices[:, 0]), tuple(indices[:, 1]), tuple(indices[:, 2])] = 1
    if dilate > 0:
        grid = _dilate(grid, iterations=dilate)

    pad = np.pad(grid, 1, constant_values=0)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    vertex_index: dict[tuple[int, int, int], int] = {}
    occupied = np.argwhere(pad > 0)  # padded coordinates, 1-based

    def _add_vertex(corner: np.ndarray) -> int:
        # `corner` is a padded coordinate; map back to the grid frame by -1.
        key = (int(corner[0]) - 1, int(corner[1]) - 1, int(corner[2]) - 1)
        if key not in vertex_index:
            vertex_index[key] = len(vertices)
            vertices.append(
                (
                    float(origin[0] + (corner[0] - 1.0) * voxel_size),
                    float(origin[1] + (corner[1] - 1.0) * voxel_size),
                    float(origin[2] + (corner[2] - 1.0) * voxel_size),
                )
            )
        return vertex_index[key]

    for cell in occupied:
        i, j, k = (int(c) for c in cell)  # padded coordinates (1-based)
        for corners, outward in _FACES:
            neighbour = np.asarray(outward) + (i, j, k)
            if pad[tuple(neighbour)]:
                continue  # face is interior
            quad = [np.asarray(corner) + (i, j, k) for corner in corners]
            a, b, c, d = (_add_vertex(corner) for corner in quad)
            # Orient the triangle normal outward as a safety net.
            tri = (a, b, c)
            normal = np.cross(
                np.asarray(vertices[b]) - np.asarray(vertices[a]),
                np.asarray(vertices[c]) - np.asarray(vertices[a]),
            )
            if np.dot(normal, outward) < 0.0:
                tri = (a, c, b)
            faces.append(tri)
            faces.append((a, c, d) if tri == (a, b, c) else (a, d, c))

    if not faces:
        raise ValueError("empty mesh: no boundary faces (dilate too large?)")
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def implicit_voxel_mesh(
    points: np.ndarray,
    *,
    voxel_fraction: float = 0.005,
    closing: int = 1,
    minimum_component_voxels: int = 8,
    smooth_sigma: float = 0.65,
    level: float = 0.2,
    maximum: int = 400_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract a smooth isosurface from a topology-cleaned occupancy field.

    This is intended for thin, densely sampled plant surfaces. Morphology uses
    face connectivity rather than a 26-neighbour dilation, avoiding accidental
    bridges between nearby leaves. Components smaller than
    ``minimum_component_voxels`` are treated as reconstruction floaters.

    The implementation uses SciPy's prebuilt ndimage operations and a local
    marching-tetrahedra extractor; no compiled meshing extension is required.
    """
    from scipy import ndimage

    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 4:
        raise ValueError(f"points must have shape (M, 3) with M >= 4, got {pts.shape}")
    finite = pts[np.isfinite(pts).all(axis=1)]
    if len(finite) < 4:
        raise ValueError("fewer than 4 finite points")
    diagonal = float(np.linalg.norm(finite.max(axis=0) - finite.min(axis=0)))
    if diagonal <= 0.0:
        raise ValueError("point cloud has zero diagonal")
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be between 0 and 1, got {level}")
    if smooth_sigma < 0.0:
        raise ValueError(f"smooth_sigma must be non-negative, got {smooth_sigma}")
    if len(finite) > maximum:
        keep = np.sort(np.random.default_rng(0).choice(len(finite), maximum, False))
        finite = finite[keep]

    voxel_size = float(diagonal * voxel_fraction)
    origin = finite.min(axis=0) - 2.0 * voxel_size
    indices = np.floor((finite - origin) / voxel_size).astype(np.int64)
    shape = tuple(int(indices[:, axis].max()) + 3 for axis in range(3))
    occupied = np.zeros(shape, dtype=bool)
    occupied[tuple(indices.T)] = True

    face_structure = ndimage.generate_binary_structure(3, 1)
    if closing > 0:
        occupied = ndimage.binary_closing(
            occupied, structure=face_structure, iterations=closing
        )
    labels, component_count = ndimage.label(occupied, structure=face_structure)
    if component_count and minimum_component_voxels > 1:
        counts = np.bincount(labels.ravel())
        keep_labels = counts >= minimum_component_voxels
        keep_labels[0] = False
        occupied = keep_labels[labels]
    if not occupied.any():
        raise ValueError("occupancy cleanup removed every voxel")

    field = occupied.astype(np.float32)
    if smooth_sigma > 0.0:
        field = ndimage.gaussian_filter(field, sigma=smooth_sigma, mode="constant")
    vertices, faces = _marching_tetrahedra(field, level=level)
    if not len(faces):
        raise ValueError("implicit field has no isosurface")
    vertices = origin + vertices * voxel_size
    return vertices.astype(np.float64), faces


def _marching_tetrahedra(
    field: np.ndarray, *, level: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return an oriented triangle isosurface for a dense scalar grid."""
    if field.ndim != 3 or min(field.shape) < 2:
        raise ValueError(
            f"field must be a 3D grid of at least 2 cells, got {field.shape}"
        )
    low = field[:-1, :-1, :-1]
    minimum = low.copy()
    maximum = low.copy()
    for corner in _CUBE_CORNERS[1:]:
        view = field[
            corner[0] : corner[0] + field.shape[0] - 1,
            corner[1] : corner[1] + field.shape[1] - 1,
            corner[2] : corner[2] + field.shape[2] - 1,
        ]
        minimum = np.minimum(minimum, view)
        maximum = np.maximum(maximum, view)
    candidate = (minimum < level) & (maximum >= level)
    cells = np.argwhere(candidate)

    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    edge_vertices: dict[tuple[int, int], int] = {}
    stride_yz = field.shape[1] * field.shape[2]
    stride_z = field.shape[2]

    def grid_id(point: np.ndarray) -> int:
        return int(point[0] * stride_yz + point[1] * stride_z + point[2])

    def edge_vertex(
        a_point: np.ndarray, b_point: np.ndarray, a_value: float, b_value: float
    ) -> int:
        a_id, b_id = grid_id(a_point), grid_id(b_point)
        key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        index = edge_vertices.get(key)
        if index is not None:
            return index
        fraction = (level - a_value) / (b_value - a_value)
        index = len(vertices)
        vertices.append(a_point + fraction * (b_point - a_point))
        edge_vertices[key] = index
        return index

    for cell in cells:
        cube_points = cell + _CUBE_CORNERS
        cube_values = field[tuple(cube_points.T)]
        for tetrahedron in _CUBE_TETRAHEDRA:
            local = np.asarray(tetrahedron, dtype=np.int64)
            values = cube_values[local]
            inside = np.flatnonzero(values >= level)
            outside = np.flatnonzero(values < level)
            if len(inside) in (0, 4):
                continue
            tetra_points = cube_points[local]
            crossing: list[int] = []
            for a in inside:
                for b in outside:
                    crossing.append(
                        edge_vertex(
                            tetra_points[a], tetra_points[b], values[a], values[b]
                        )
                    )
            triangles = (
                [(crossing[0], crossing[1], crossing[2])]
                if len(crossing) == 3
                else [
                    (crossing[0], crossing[1], crossing[2]),
                    (crossing[1], crossing[3], crossing[2]),
                ]
            )
            inward = tetra_points[inside].mean(axis=0)
            outward = tetra_points[outside].mean(axis=0)
            direction = outward - inward
            for triangle in triangles:
                a, b, c = (vertices[index] for index in triangle)
                if np.dot(np.cross(b - a, c - a), direction) < 0.0:
                    triangle = (triangle[0], triangle[2], triangle[1])
                faces.append(triangle)
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def _dilate(grid: np.ndarray, *, iterations: int) -> np.ndarray:
    """Binary dilation with a 26-neighbourhood ball (fill small holes)."""
    result = grid.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1, constant_values=0)
        grown = result.copy()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    if di == dj == dk == 0:
                        continue
                    grown |= padded[
                        1 + di : 1 + di + result.shape[0],
                        1 + dj : 1 + dj + result.shape[1],
                        1 + dk : 1 + dk + result.shape[2],
                    ]
        result = grown
    return result
