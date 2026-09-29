"""Deterministic incidence / order checks on a solved layout (used by validation and comparison)."""
from __future__ import annotations

import numpy as np

from ..schemas import GeometrySpec


def point_order_holds(geo: GeometrySpec, order: list[str], tol: float = 1e-6) -> bool:
    P = {p.id: np.array([p.x, p.y]) for p in geo.points}
    if not all(k in P for k in order):
        return False
    a, b = P[order[0]], P[order[-1]]
    ab = b - a
    n2 = float(ab @ ab)
    if n2 < 1e-18:
        return False
    ts = [float((P[k] - a) @ ab) / n2 for k in order]
    cross_ok = all(abs(float(ab[0] * (P[k] - a)[1] - ab[1] * (P[k] - a)[0])) / n2 < 1e-5 for k in order)
    return cross_ok and all(t2 > t1 + tol for t1, t2 in zip(ts, ts[1:]))


def orders_in_spec(geo: GeometrySpec) -> list[list[str]]:
    return [list(c.points) for c in geo.constraints if c.type == "point_order"]


def tangent_points(geo: GeometrySpec) -> list[str]:
    return sorted(c.points[0] for c in geo.constraints if c.type == "tangent")
