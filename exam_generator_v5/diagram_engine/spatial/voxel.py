"""Cube structures: columns (x, y, height). Counts, top view and occlusion analysis are deterministic."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from ..schemas import VoxelSpec
from .projection import iso


def cubes(v: VoxelSpec) -> list[tuple[int, int, int]]:
    return [(c.x, c.y, z) for c in v.columns for z in range(c.height)]


def total(v: VoxelSpec) -> int:
    return sum(max(0, c.height) for c in v.columns)


def top_view(v: VoxelSpec, nx: int, ny: int) -> list[list[bool]]:
    grid = [[False] * nx for _ in range(ny)]
    for c in v.columns:
        if c.height > 0 and 0 <= c.x < nx and 0 <= c.y < ny:
            grid[ny - 1 - c.y][c.x] = True
    return grid


def _faces(x: int, y: int, z: int) -> list[tuple[str, list[tuple[float, float]]]]:
    P = lambda a, b, c: iso(a, b, c)  # noqa: E731
    return [
        ("top", [P(x, y, z + 1), P(x + 1, y, z + 1), P(x + 1, y + 1, z + 1), P(x, y + 1, z + 1)]),
        ("left", [P(x, y, z), P(x, y + 1, z), P(x, y + 1, z + 1), P(x, y, z + 1)]),
        ("front", [P(x, y, z), P(x + 1, y, z), P(x + 1, y, z + 1), P(x, y, z + 1)]),
    ]


def draw_order(cs: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    return sorted(cs, key=lambda c: (-(c[0] + c[1]), c[2]))   # far first, bottom first


def visibility(v: VoxelSpec, scale: int = 40) -> dict:
    """Painter's algorithm into an id buffer: which cubes / column tops are actually visible."""
    cs = cubes(v)
    if not cs:
        return {"visible": set(), "hidden": set(), "hidden_tops": []}
    pts = [iso(*p) for c in cs for p in ((c[0], c[1], c[2]), (c[0] + 1, c[1] + 1, c[2] + 1), (c[0] + 1, c[1], c[2]), (c[0], c[1] + 1, c[2] + 1))]
    minx, miny = min(p[0] for p in pts), min(p[1] for p in pts)
    maxx, maxy = max(p[0] for p in pts), max(p[1] for p in pts)
    W, H = int((maxx - minx) * scale) + 4, int((maxy - miny) * scale) + 4
    buf = Image.new("I", (W, H), 0)
    d = ImageDraw.Draw(buf)
    order = draw_order(cs)
    for i, c in enumerate(order, 1):
        for _, poly in _faces(*c):
            d.polygon([((px - minx) * scale + 2, H - ((py - miny) * scale + 2)) for px, py in poly], fill=i)
    seen = set(np.unique(np.asarray(buf)).tolist()) - {0}
    vis = {order[i - 1] for i in seen}
    tops = {(c.x, c.y): (c.x, c.y, c.height - 1) for c in v.columns if c.height > 0}
    hidden_tops = sorted(k for k, t in tops.items() if t not in vis)
    return {"visible": vis, "hidden": set(cs) - vis, "hidden_tops": hidden_tops}
