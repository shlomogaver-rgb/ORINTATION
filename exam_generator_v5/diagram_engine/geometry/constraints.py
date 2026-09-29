"""Residual functions of geometric constraints (0 = satisfied). Lengths are normalised by the diagram size S."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from ..schemas import GConstraint, GeometrySpec

METRIC = {"equal_length", "parallel", "perpendicular", "right_angle", "angle_value", "equal_angle", "equilateral",
          "isosceles", "rectangle", "square", "midpoint", "ratio_on_segment", "diameter"}
MARGIN = 0.02


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(*v))
    return v / n if n > 1e-12 else v * 0.0


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _angle(P: dict, a: str, b: str, c: str) -> float:
    u, v = P[a] - P[b], P[c] - P[b]
    return math.atan2(abs(_cross(u, v)), float(np.dot(u, v)))


def size_of(geo: GeometrySpec) -> float:
    pts = [p for p in geo.points if not p.hidden]
    if not pts:
        return 1.0
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    return max(1e-6, max(xs) - min(xs), max(ys) - min(ys))


def circle_of(geo: GeometrySpec, c: GConstraint, P: dict):
    """(centre_point, radius) of the circle referred to by a constraint (by id, or by centre point for v1 forms)."""
    circ = None
    if c.circle:
        circ = next((ci for ci in geo.circles if (ci.id or ci.center) == c.circle), None)
    if circ is None and c.type == "on_circle" and len(c.points) > 1:
        circ = next((ci for ci in geo.circles if ci.center == c.points[1]), None)
    if circ is None and len(geo.circles) == 1 and c.type in ("diameter", "chord", "secant", "radius", "inside_circle",
                                                            "outside_circle", "tangent", "on_circle"):
        circ = geo.circles[0]
    if circ is None:
        return None, None
    center = circ.center or f"__c_{circ.id or 0}"
    if center not in P:
        return None, None
    ref = circ.through or (circ.through_points[0] if circ.through_points else None)
    r = float(np.hypot(*(P[ref] - P[center]))) if ref and ref in P else float(circ.radius or 0.0)
    return center, r


def residuals(c: GConstraint, P: dict[str, np.ndarray], geo: GeometrySpec, S: float,
              curves: dict[str, Callable] | None = None) -> list[float]:
    p, t = c.points, c.type
    L = lambda a, b: float(np.hypot(*(P[b] - P[a])))  # noqa: E731
    if t == "equal_length":
        return [(L(p[0], p[1]) - L(p[2], p[3])) / S]
    if t == "parallel":
        return [_cross(_unit(P[p[1]] - P[p[0]]), _unit(P[p[3]] - P[p[2]]))]
    if t == "perpendicular":
        return [float(np.dot(_unit(P[p[1]] - P[p[0]]), _unit(P[p[3]] - P[p[2]])))]
    if t == "right_angle":
        return [float(np.dot(_unit(P[p[0]] - P[p[1]]), _unit(P[p[2]] - P[p[1]])))]
    if t == "angle_value":
        return [_angle(P, p[0], p[1], p[2]) - math.radians(float(c.value or 0))]
    if t == "equal_angle":
        return [_angle(P, p[0], p[1], p[2]) - _angle(P, p[3], p[4], p[5])]
    if t == "midpoint":
        d = (P[p[0]] - (P[p[1]] + P[p[2]]) / 2) / S
        return [float(d[0]), float(d[1])]
    if t == "ratio_on_segment":
        r = float(c.value if c.value is not None else 0.5)
        d = (P[p[0]] - (P[p[1]] + r * (P[p[2]] - P[p[1]]))) / S
        return [float(d[0]), float(d[1])]
    if t in ("collinear", "point_on_line"):
        base = (p[1], p[2]) if t == "point_on_line" else (p[0], p[1])
        others = [p[0]] if t == "point_on_line" else p[2:]
        return [_cross(P[base[1]] - P[base[0]], P[k] - P[base[0]]) / S ** 2 for k in others]
    if t in ("on_segment", "point_on_ray"):
        a, b = P[p[1]], P[p[2]]
        ab = b - a
        tt = float(np.dot(P[p[0]] - a, ab) / max(1e-12, float(np.dot(ab, ab))))
        hinge = max(0.0, MARGIN - tt) + (max(0.0, tt - 1.0 + MARGIN) if t == "on_segment" else 0.0)
        return [_cross(ab, P[p[0]] - a) / S ** 2, hinge]
    if t == "point_order":   # p[0]-p[1]-...-p[n]: collinear and strictly in this order
        a, b = P[p[0]], P[p[-1]]
        ab = b - a
        n2 = max(1e-12, float(np.dot(ab, ab)))
        ts = [float(np.dot(P[k] - a, ab) / n2) for k in p]
        out = [_cross(ab, P[k] - a) / S ** 2 for k in p[1:-1]]
        out += [max(0.0, ts[i] - ts[i + 1] + MARGIN) for i in range(len(ts) - 1)]
        return out
    if t == "intersection":  # P = AB ∩ CD
        return [_cross(P[p[2]] - P[p[1]], P[p[0]] - P[p[1]]) / S ** 2, _cross(P[p[4]] - P[p[3]], P[p[0]] - P[p[3]]) / S ** 2]
    if t in ("on_circle", "radius", "chord", "secant", "diameter", "concyclic", "inside_circle", "outside_circle", "tangent"):
        if t == "concyclic":
            return _concyclic(p, P, S)
        center, r = circle_of(geo, c, P)
        if center is None:
            return [0.0]
        on = lambda k: (float(np.hypot(*(P[k] - P[center]))) - r) / S  # noqa: E731
        if t in ("on_circle", "radius"):
            return [on(p[0])]
        if t in ("chord", "secant"):
            return [on(p[0]), on(p[1])]
        if t == "diameter":
            d = (P[center] - (P[p[0]] + P[p[1]]) / 2) / S
            return [on(p[0]), on(p[1]), float(d[0]), float(d[1])]
        if t == "inside_circle":
            return [max(0.0, float(np.hypot(*(P[p[0]] - P[center]))) / S - r / S + MARGIN)]
        if t == "outside_circle":
            return [max(0.0, r / S - float(np.hypot(*(P[p[0]] - P[center]))) / S + MARGIN)]
        # tangent: line through T=p[0] and A=p[1] touches the circle at T
        return [on(p[0]), float(np.dot(_unit(P[p[0]] - P[center]), _unit(P[p[1]] - P[p[0]])))]
    if t == "equilateral":
        return [(L(p[0], p[1]) - L(p[1], p[2])) / S, (L(p[1], p[2]) - L(p[2], p[0])) / S]
    if t == "isosceles":     # apex p[0]
        return [(L(p[0], p[1]) - L(p[0], p[2])) / S]
    if t in ("rectangle", "square"):
        ra = lambda a, b, cc: float(np.dot(_unit(P[a] - P[b]), _unit(P[cc] - P[b])))  # noqa: E731
        out = [ra(p[0], p[1], p[2]), ra(p[1], p[2], p[3]), ra(p[2], p[3], p[0])]
        if t == "square":
            out.append((L(p[0], p[1]) - L(p[1], p[2])) / S)
        return out
    if t in ("parallel_to_x_axis", "perpendicular_to_y_axis"):
        return [(P[p[0]][1] - P[p[1]][1]) / S]
    if t in ("parallel_to_y_axis", "perpendicular_to_x_axis"):
        return [(P[p[0]][0] - P[p[1]][0]) / S]
    if t == "on_x_axis":
        return [P[p[0]][1] / S]
    if t == "on_y_axis":
        return [P[p[0]][0] / S]
    if t in ("inside_polygon", "outside_polygon"):
        poly = [P[v] for v in (c.polygon or p[1:])]
        area2 = sum(_cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))
        sgn = 1.0 if area2 > 0 else -1.0
        vals = [sgn * _cross(poly[(i + 1) % len(poly)] - poly[i], P[p[0]] - poly[i]) / S ** 2 for i in range(len(poly))]
        if t == "inside_polygon":
            return [max(0.0, MARGIN * 0.1 - v) for v in vals]
        return [max(0.0, min(vals) + MARGIN * 0.1)]
    if t in ("perpendicular_foot", "centroid", "circumcenter", "incenter"):
        target = construct(t, [P[k] for k in p[1:]])
        if target is None:
            return [1.0]
        d = (P[p[0]] - target) / S
        return [float(d[0]), float(d[1])]
    if t == "on_curve":
        f = (curves or {}).get(c.curve)
        if f is None:
            return [0.0]
        y = float(f(np.array([float(P[p[0]][0])]))[0])
        return [(P[p[0]][1] - y) / S if math.isfinite(y) else 1.0]
    return [0.0]


def _concyclic(p: list[str], P: dict, S: float) -> list[float]:
    """All points on one circle: circumcentre of the first three, equal distance for the rest."""
    a, b, c = P[p[0]], P[p[1]], P[p[2]]
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return [1.0]
    ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
    uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
    o = np.array([ux, uy])
    r = float(np.hypot(*(a - o)))
    return [(float(np.hypot(*(P[k] - o))) - r) / S for k in p[3:]]


def construct(kind: str, pts: list) -> "np.ndarray | None":
    """Exact constructions used both as residuals and by the symbolic pre-resolution of the solver."""
    if kind == "intersection":                       # line AB ∩ line CD
        a, b, c, d = pts
        r, s_ = b - a, d - c
        den = _cross(r, s_)
        if abs(den) < 1e-12:
            return None
        t = _cross(c - a, s_) / den
        return a + t * r
    if kind == "perpendicular_foot":                 # foot from A to line BC
        a, b, c = pts
        bc = c - b
        n2 = float(bc @ bc)
        return None if n2 < 1e-18 else b + (float((a - b) @ bc) / n2) * bc
    if kind == "centroid":
        return (pts[0] + pts[1] + pts[2]) / 3
    if kind == "circumcenter":
        a, b, c = pts
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-12:
            return None
        ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
        uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
        return np.array([ux, uy])
    if kind == "incenter":
        a, b, c = pts
        la, lb, lc = np.hypot(*(b - c)), np.hypot(*(a - c)), np.hypot(*(a - b))
        s_ = la + lb + lc
        return None if s_ < 1e-12 else (la * a + lb * b + lc * c) / s_
    return None
