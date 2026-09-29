"""Conics (circle / ellipse / hyperbola / parabola): canonical parameters, foci, vertices, eccentricity, rendering as the
two exact function branches of the existing graph renderer, and loci by eliminating a parameter."""
from __future__ import annotations

import sympy

x, y, t = sympy.symbols("x y t", real=True)


def ellipse(a, b, h=0, k=0) -> dict:
    a, b = sympy.nsimplify(a), sympy.nsimplify(b)
    c = sympy.sqrt(abs(a ** 2 - b ** 2))
    try:
        major_x = bool(a >= b)
    except TypeError:                     # symbolic a, b with unknown order: the major axis is NOT decided (never guessed)
        return {"kind": "ellipse", "a": a, "b": b, "h": h, "k": k, "foci": [], "major_axis": "undetermined",
                "focal_distance": c, "e": None, "equation": sympy.Eq((x - h) ** 2 / a ** 2 + (y - k) ** 2 / b ** 2, 1),
                "vertices": [(h + a, k), (h - a, k), (h, k + b), (h, k - b)]}
    foci = [(h + c, k), (h - c, k)] if major_x else [(h, k + c), (h, k - c)]
    return {"kind": "ellipse", "a": a, "b": b, "h": h, "k": k, "foci": foci, "e": c / max(a, b), "major_axis": "x" if major_x else "y",
            "equation": sympy.Eq((x - h) ** 2 / a ** 2 + (y - k) ** 2 / b ** 2, 1),
            "vertices": [(h + a, k), (h - a, k), (h, k + b), (h, k - b)]}


def hyperbola(a, b, h=0, k=0) -> dict:
    a, b = sympy.nsimplify(a), sympy.nsimplify(b)
    c = sympy.sqrt(a ** 2 + b ** 2)
    return {"kind": "hyperbola", "a": a, "b": b, "h": h, "k": k, "foci": [(h + c, k), (h - c, k)], "e": c / a,
            "equation": sympy.Eq((x - h) ** 2 / a ** 2 - (y - k) ** 2 / b ** 2, 1), "vertices": [(h + a, k), (h - a, k)],
            "asymptotes": [k + b / a * (x - h), k - b / a * (x - h)]}


def parabola(p, h=0, k=0) -> dict:
    """y^2 = 2p(x-h) shifted by k (Israeli convention y^2 = 2px, focus (p/2, 0), directrix x = -p/2)."""
    p = sympy.nsimplify(p)
    return {"kind": "parabola", "p": p, "h": h, "k": k, "foci": [(h + p / 2, k)], "directrix": h - p / 2,
            "equation": sympy.Eq((y - k) ** 2, 2 * p * (x - h)), "vertices": [(h, k)]}


def from_equation(eq: sympy.Eq) -> dict:
    """Identify a canonical conic from its equation (ellipse / circle / hyperbola / parabola)."""
    e = sympy.expand(eq.lhs - eq.rhs)
    P = sympy.Poly(e, x, y)
    A, C = P.coeff_monomial(x ** 2), P.coeff_monomial(y ** 2)
    D, E, F = P.coeff_monomial(x), P.coeff_monomial(y), P.coeff_monomial(1)
    if A != 0 and C != 0:
        h, k = -D / (2 * A), -E / (2 * C)
        rhs = -(F - A * h ** 2 - C * k ** 2)
        if A * C > 0:
            a, b = sympy.sqrt(rhs / A), sympy.sqrt(rhs / C)
            return ellipse(a, b, h, k) | ({"kind": "circle"} if sympy.simplify(a - b) == 0 else {})
        if rhs / A > 0:
            return hyperbola(sympy.sqrt(rhs / A), sympy.sqrt(-rhs / C), h, k)
    if A == 0 and C != 0 and D != 0:
        k = -E / (2 * C)
        h = (C * k ** 2 - F) / D                                  # C(y-k)^2 = -D(x - h)
        return parabola(-D / (2 * C), h, k)
    if C == 0 and A != 0 and E != 0:                              # vertical parabola: A(x-h)^2 = -E(y - k)
        h = -D / (2 * A)
        k = (A * h ** 2 - F) / E
        p = -E / (2 * A)
        return {"kind": "parabola", "p": p, "h": h, "k": k, "axis": "vertical", "foci": [(h, k + p / 2)], "directrix": k - p / 2,
                "equation": sympy.Eq((x - h) ** 2, 2 * p * (y - k)), "vertices": [(h, k)]}
    raise ValueError("not a canonical conic")


def graph_spec(conic: dict, window: float | None = None) -> dict:
    """Exact drawing through the existing formula-graph renderer: the conic as its two function branches."""
    h, k = float(conic["h"]), float(conic["k"])
    if conic["kind"] in ("ellipse", "circle"):
        a, b = float(conic["a"]), float(conic["b"])
        up, lo = f"{k}+{b}*sqrt(1-(x-{h})^2/{a ** 2})", f"{k}-{b}*sqrt(1-(x-{h})^2/{a ** 2})"
        R = window or 1.3 * max(a, b) + max(abs(h), abs(k))
    elif conic["kind"] == "hyperbola":
        a, b = float(conic["a"]), float(conic["b"])
        up, lo = f"{k}+{b}*sqrt((x-{h})^2/{a ** 2}-1)", f"{k}-{b}*sqrt((x-{h})^2/{a ** 2}-1)"
        R = window or 3 * max(a, b) + max(abs(h), abs(k))
    else:
        p = float(conic["p"])
        up, lo = f"{k}+sqrt({2 * p}*(x-{h}))", f"{k}-sqrt({2 * p}*(x-{h}))"
        R = window or 4 * abs(p) + max(abs(h), abs(k)) + 2
    pts = [{"name": f"F{j + 1}", "x": float(fx), "y": float(fy), "kind": "marked"} for j, (fx, fy) in enumerate(conic["foci"])]
    return {"diagram_type": "graph", "subtype": "formula_graph", "confidence": 1.0, "labels": [],
            "graph": {"axes": {"x_min": -R, "x_max": R, "y_min": -R, "y_max": R, "show_grid": False},
                      "curves": [{"id": "c1", "expression": up, "source": "computed"}, {"id": "c2", "expression": lo, "source": "computed"}],
                      "points": pts}}


def locus(px, py, params, constraints=()) -> sympy.Expr:
    """Implicit equation of the locus of (px(t), py(t)) by eliminating the parameter(s)."""
    X, Y = sympy.symbols("X Y", real=True)
    G = sympy.groebner([X - px, Y - py, *constraints], *params, X, Y, order="lex")
    free = [g for g in G.exprs if not (g.free_symbols & set(params))]
    return sympy.factor(free[0].subs({X: x, Y: y})) if free else None
