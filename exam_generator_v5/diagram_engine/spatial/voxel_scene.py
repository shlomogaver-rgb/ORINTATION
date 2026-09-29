"""Generic voxel scene built ON TOP of the existing VoxelSpec (columns / total / top_view / visibility are kept):
occupancy, height map, dense matrix, bounding box, orthographic views (height profiles + silhouettes), delta
classification, view impact, and camera-depth painter ordering for any camera."""
from __future__ import annotations

import numpy as np

from ..schemas import VoxelSpec

VIEWS = ("TOP_FROM_POS_Z", "FRONT_FROM_NEG_Y", "FRONT_FROM_POS_Y", "SIDE_FROM_NEG_X", "SIDE_FROM_POS_X")


class VoxelGrid:
    def __init__(self, cells: set[tuple[int, int, int]] | None = None) -> None:
        self.cells = set(cells or ())

    @classmethod
    def from_spec(cls, v: VoxelSpec) -> "VoxelGrid":
        return cls({(c.x, c.y, z) for c in v.columns for z in range(max(0, c.height))})

    @classmethod
    def from_height_matrix(cls, H) -> "VoxelGrid":
        H = np.asarray(H)
        if H.ndim != 2 or not np.all(np.isfinite(H)) or np.any(H < 0) or np.any(H != np.round(H)):
            raise ValueError("height matrix must be rectangular, finite, integer and >= 0")
        return cls({(i, j, z) for i in range(H.shape[0]) for j in range(H.shape[1]) for z in range(int(H[i, j]))})

    def occupied(self, x: int, y: int, z: int) -> bool:
        return (x, y, z) in self.cells

    def occupied_cells(self) -> list[tuple[int, int, int]]:
        return sorted(self.cells)

    def bounding_box(self) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
        if not self.cells:
            return None
        a = np.array(sorted(self.cells))
        return tuple(int(v) for v in a.min(axis=0)), tuple(int(v) for v in a.max(axis=0))

    def height_map(self) -> np.ndarray:
        bb = self.bounding_box()
        if bb is None:
            return np.zeros((0, 0), int)
        (x0, y0, _), (x1, y1, _) = bb
        H = np.zeros((x1 - x0 + 1, y1 - y0 + 1), int)
        for x, y, z in self.cells:
            H[x - x0, y - y0] = max(H[x - x0, y - y0], z + 1)
        return H

    def dense_matrix(self) -> np.ndarray:
        bb = self.bounding_box()
        if bb is None:
            return np.zeros((0, 0, 0), bool)
        (x0, y0, z0), (x1, y1, z1) = bb
        D = np.zeros((x1 - x0 + 1, y1 - y0 + 1, z1 - z0 + 1), bool)
        for x, y, z in self.cells:
            D[x - x0, y - y0, z - z0] = True
        return D

    def view(self, name: str) -> np.ndarray:
        """Binary silhouette of an orthographic view (rows = up/depth axis as seen, cols = left->right as seen)."""
        D = self.dense_matrix()
        if D.size == 0:
            return np.zeros((0, 0), bool)
        if name == "TOP_FROM_POS_Z":
            return D.any(axis=2).T[::-1]                # rows: y (far at top), cols: x
        if name == "FRONT_FROM_NEG_Y":
            return D.any(axis=1).T[::-1]                # rows: z (top first), cols: x
        if name == "FRONT_FROM_POS_Y":
            return D.any(axis=1).T[::-1, ::-1]
        if name == "SIDE_FROM_NEG_X":
            return D.any(axis=0).T[::-1, ::-1]          # looking along +x: y runs right-to-left
        if name == "SIDE_FROM_POS_X":
            return D.any(axis=0).T[::-1]
        raise ValueError(name)

    def height_profile(self, name: str) -> list[int]:
        return [int(c.sum()) for c in self.view(name).T]

    def depth_order(self, camera) -> list[tuple[int, int, int]]:
        """Back-to-front painter order for ANY camera (by the camera depth of each voxel centre)."""
        return sorted(self.cells, key=lambda c: -camera.project((c[0] + 0.5, c[1] + 0.5, c[2] + 0.5))[2])


def delta(before: VoxelGrid, after: VoxelGrid) -> dict:
    added, removed = after.cells - before.cells, before.cells - after.cells
    kind = "UNCHANGED" if not added and not removed else ("ADDED" if added and not removed else ("REMOVED" if removed and not added else "MIXED_DELTA"))
    return {"kind": kind, "added": sorted(added), "removed": sorted(removed)}


def view_impact(before: VoxelGrid, after: VoxelGrid) -> list[str]:
    out = []
    for name, tag in (("TOP_FROM_POS_Z", "TOP_CHANGED"), ("FRONT_FROM_NEG_Y", "FRONT_CHANGED"), ("SIDE_FROM_POS_X", "SIDE_CHANGED")):
        a, b = before.view(name), after.view(name)
        if a.shape != b.shape or not np.array_equal(a, b):
            out.append(tag)
    return out
