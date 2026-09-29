"""Deterministic facts of a formula graph on a window: domain, roots, intercept, extrema, monotonicity, asymptotes
(vertical / horizontal / oblique), removable holes, symmetry and branch count."""
from __future__ import annotations

from typing import Any

import numpy as np
import sympy

from .. import safe_math as sm
from ..schemas import GraphCurve, GraphPoint, GraphSpec
from .evaluator import sample, split_branches


def _bisect(f, a: float, b: float, fa: float) -> float:
    for _ in range(80):
        m = (a + b) / 2
        fm = float(f(np.array([m]))[0])
        if not np.isfinite(fm):
            return m
        if (fm < 0) == (fa < 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2


def _poly_real_roots(expr: sympy.Expr) -> list[float] | None:
    try:
        poly = sympy.Poly(sympy.expand(expr), sm.X)
        if poly.degree() > 8:
            return None
        return sorted({float(r) for r in sympy.real_roots(poly)})
    except Exception:
        return None


def _intervals(mask: np.ndarray, xs: np.ndarray) -> list[list[float]]:
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = xs[i]
        if (not m or i == len(mask) - 1) and start is not None:
            end = xs[i] if m else xs[i - 1]
            out.append([round(float(start), 6), round(float(end), 6)])
            start = None
    return out


def features(expr: sympy.Expr, lo: float, hi: float, y_span: float | None = None) -> dict[str, Any]:
    f = sm.to_numpy(expr)
    xs, ys = sample(expr, lo, hi, 4001)
    finite = np.isfinite(ys)
    span = max(1e-9, float(np.nanmax(np.abs(ys[finite]))) if finite.any() else 1.0)
    out: dict[str, Any] = {"finite_fraction": float(finite.mean()), "roots": [], "extrema": [], "vertical_asymptotes": [],
                           "holes": [], "horizontal_asymptotes": [], "oblique_asymptotes": [], "y_intercept": None,
                           "domain_intervals": _intervals(finite, xs), "increasing": [], "decreasing": [],
                           "symmetry": "none", "branches": 0}
    try:
        num, den = sympy.fraction(sympy.together(expr))
        if den.free_symbols:
            den_roots = _poly_real_roots(den) or []
            reduced = sympy.cancel(expr)
            _, den2 = sympy.fraction(sympy.together(reduced))
            poles = (_poly_real_roots(den2) or []) if den2.free_symbols else []
            for r in den_roots:
                if lo <= r <= hi:
                    if any(abs(r - p) < 1e-9 for p in poles):
                        out["vertical_asymptotes"].append(r)
                    else:
                        out["holes"].append([r, float(sympy.N(reduced.subs(sm.X, r)))])
            rnum, rden = sympy.fraction(sympy.together(reduced))
            if not rden.free_symbols:
                rnum, rden = None, None          # after cancelling it is a polynomial: no asymptote at all
            if rnum is not None and not rnum.has(sympy.Abs) and _poly_real_roots(rnum) is not None and _poly_real_roots(rden) is not None:
                num, den = rnum, rden
                dn, dd = sympy.degree(num, sm.X), sympy.degree(den, sm.X)
                if dn < dd:
                    out["horizontal_asymptotes"].append(0.0)
                elif dn == dd:
                    out["horizontal_asymptotes"].append(float(sympy.LC(num, sm.X) / sympy.LC(den, sm.X)))
                elif dn == dd + 1:
                    q, _ = sympy.div(sympy.Poly(num, sm.X), sympy.Poly(den, sm.X))
                    c = q.all_coeffs()
                    out["oblique_asymptotes"].append([float(c[0]), float(c[1]) if len(c) > 1 else 0.0])
        if expr.has(sympy.log):   # log(g(x)): vertical asymptote where g(x) = 0 (exact roots of the argument)
            for node in expr.atoms(sympy.log):
                for r0 in _poly_real_roots(node.args[0]) or []:
                    if lo <= r0 <= hi and not any(abs(r0 - v) < 1e-9 for v in out["vertical_asymptotes"]):
                        out["vertical_asymptotes"].append(r0)
    except Exception:
        pass
    poles = out["vertical_asymptotes"]
    exact = _poly_real_roots(expr)
    roots: list[float] = []
    if exact is not None:
        roots = [r for r in exact if lo <= r <= hi]
    else:
        for i in range(len(xs) - 1):
            a, b = ys[i], ys[i + 1]
            if not (np.isfinite(a) and np.isfinite(b)):
                continue
            if a == 0:
                roots.append(float(xs[i]))
            elif (a < 0) != (b < 0) and not any(xs[i] <= p <= xs[i + 1] for p in poles):
                r = _bisect(f, float(xs[i]), float(xs[i + 1]), float(a))
                if abs(float(f(np.array([r]))[0])) < 1e-6 * max(1.0, span):
                    roots.append(r)
        absy = np.abs(ys)
        for i in range(1, len(xs) - 1):
            if np.isfinite(absy[i]) and absy[i] < 1e-10 and not any(abs(xs[i] - r) < 1e-6 for r in roots):
                roots.append(float(xs[i]))
        for a, b in out["domain_intervals"]:   # roots at a domain endpoint (e.g. sqrt(x-2))
            for edge in (a, b):
                v = f(np.array([edge]))[0]
                if np.isfinite(v) and abs(v) < 1e-7 and not any(abs(edge - r) < 1e-6 for r in roots):
                    roots.append(edge)
    out["roots"] = sorted({round(r, 10) for r in roots})
    if lo <= 0 <= hi:
        y0 = f(np.array([0.0]))[0]
        out["y_intercept"] = float(y0) if np.isfinite(y0) else None
    try:
        d = sm.to_numpy(sympy.diff(expr, sm.X))
        dys = d(xs)
        for i in range(len(xs) - 1):
            a, b = dys[i], dys[i + 1]
            if np.isfinite(a) and np.isfinite(b) and (a < 0) != (b < 0) and a != 0:
                r = _bisect(d, float(xs[i]), float(xs[i + 1]), float(a))
                yr = float(f(np.array([r]))[0])
                if np.isfinite(yr) and not any(abs(r - p) < 1e-6 for p in poles):
                    out["extrema"].append({"x": round(r, 9), "y": round(yr, 9), "kind": "min" if a < 0 else "max"})
        fin = np.isfinite(dys) & finite
        out["increasing"] = _intervals(fin & (dys > 1e-12), xs)
        out["decreasing"] = _intervals(fin & (dys < -1e-12), xs)
    except Exception:
        pass
    w = min(abs(lo), abs(hi))
    if w > 0:
        t = np.linspace(-w, w, 801)
        a, b = sm.to_numpy(expr)(t), sm.to_numpy(expr)(-t)
        both = np.isfinite(a) & np.isfinite(b)
        if both.sum() > 20 and (np.isfinite(a) == np.isfinite(b)).all():
            if np.allclose(a[both], b[both], atol=1e-9, rtol=1e-9):
                out["symmetry"] = "even"
            elif np.allclose(a[both], -b[both], atol=1e-9, rtol=1e-9):
                out["symmetry"] = "odd"
    jump = 0.75 * (y_span if y_span else 2 * span)
    out["branches"] = len(split_branches(xs, ys, poles, jump))
    return out


def add_computed_holes(graph: GraphSpec, curve: GraphCurve, feats: dict[str, Any]) -> None:
    """A removable discontinuity is part of the function's graph - add it explicitly (source=computed)."""
    for hx, hy in feats.get("holes", []):
        if not any(abs(p.x - hx) < 1e-9 and abs(p.y - hy) < 1e-9 for p in graph.points):
            graph.points.append(GraphPoint(name="", x=hx, y=hy, style="open", on_curve="", source="computed"))
