"""Cuboids, cylinders and labelled polyhedra (box ABCDA'B'C'D', pyramid SABC) in 3D."""
from __future__ import annotations

from ..schemas import Solid

BOX_NAMES = ["A", "B", "C", "D", "A'", "B'", "C'", "D'"]


def box_vertices(s: Solid) -> dict[str, list[float]]:
    """Explicit vertices win; otherwise a cuboid from width/depth/height with the standard ABCDA'B'C'D' naming
    (bottom A back-left, B back-right, C front-right, D front-left; primes on top)."""
    if s.vertices:
        return s.vertices
    w, dp, h = s.dims.get("width", 1.0), s.dims.get("depth", 1.0), s.dims.get("height", 1.0)
    ox, oy, oz = s.origin
    base = {"A": [0, dp, 0], "B": [w, dp, 0], "C": [w, 0, 0], "D": [0, 0, 0]}
    out = {k: [ox + v[0], oy + v[1], oz + v[2]] for k, v in base.items()}
    out.update({k + "'": [ox + v[0], oy + v[1], oz + h] for k, v in base.items()})
    return out


def box_edges() -> list[list[str]]:
    return [["A", "B"], ["B", "C"], ["C", "D"], ["D", "A"], ["A'", "B'"], ["B'", "C'"], ["C'", "D'"], ["D'", "A'"],
            ["A", "A'"], ["B", "B'"], ["C", "C'"], ["D", "D'"]]


def hidden_vertex_oblique(verts: dict[str, list[float]]) -> str | None:
    """For a cuboid in the oblique view the hidden vertex is the bottom-back-left one (min x, max y, min z)."""
    if not verts:
        return None
    return min(verts, key=lambda k: (verts[k][2], verts[k][0], -verts[k][1]))
