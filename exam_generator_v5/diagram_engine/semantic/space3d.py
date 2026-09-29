"""Analytic 3D geometry: points, lines (point + direction), planes (n . X = d), intersections, angles, distances, volumes."""
from __future__ import annotations

import sympy

M = sympy.Matrix


def line(p, d):
    return {"p": M(p), "d": M(d)}


def plane_from_points(a, b, c):
    n = (M(b) - M(a)).cross(M(c) - M(a))
    return {"n": n, "d": n.dot(M(a))}


def plane(n, d):
    return {"n": M(n), "d": sympy.nsimplify(d)}


def line_plane_intersection(L, P):
    t = sympy.Symbol("t")
    s = sympy.solve(P["n"].dot(L["p"] + t * L["d"]) - P["d"], t)
    return None if not s else L["p"] + s[0] * L["d"]


def angle_lines(L1, L2):
    return sympy.acos(abs(L1["d"].dot(L2["d"])) / (L1["d"].norm() * L2["d"].norm()))


def angle_line_plane(L, P):
    return sympy.asin(abs(L["d"].dot(P["n"])) / (L["d"].norm() * P["n"].norm()))


def angle_planes(P1, P2):
    return sympy.acos(abs(P1["n"].dot(P2["n"])) / (P1["n"].norm() * P2["n"].norm()))


def distance_point_plane(q, P):
    return abs(P["n"].dot(M(q)) - P["d"]) / P["n"].norm()


def box_volume(a, b, c) -> sympy.Expr:
    return abs(M(a).dot(M(b).cross(M(c))))                # parallelepiped / box spanned by three edges


def pyramid_volume(base_area, h):
    return sympy.Rational(1, 3) * base_area * h
