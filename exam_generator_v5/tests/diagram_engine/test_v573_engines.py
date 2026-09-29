"""Semantic engines (V5.7.3): complex numbers, conics + loci, vectors, analytic 3D, ExpressionAST, function dependency
graph, piecewise processes, multi-series and hybrid diagrams. Generic cases - different numbers/letters/orientations."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest
import sympy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import diagram_engine as de  # noqa: E402
from diagram_engine.semantic import complex_numbers as cx, conics, expression_ast as ea, functions as fn, space3d, vectors  # noqa: E402


# ---------------------------------------------------------------- complex numbers -> points -> polygon
@pytest.mark.parametrize("n,w,sides", [(4, "16", 4), (3, "8*I", 3), (6, "-1", 6), (5, "1+I", 5)])
def test_de_moivre_roots_form_a_regular_polygon_drawn_from_scratch(n, w, sides):
    zs = cx.roots(n, sympy.sympify(w))
    for z in zs:
        assert sympy.simplify(sympy.expand_complex(z ** n) - sympy.sympify(w)) == 0 or abs(complex(sympy.N(z ** n)) - complex(sympy.N(sympy.sympify(w)))) < 1e-9
    spec = cx.polygon_spec(zs)
    r = de.process("cx", json.dumps(spec), "", None)
    assert r.validation.ok, r.validation.errors
    P = [(p.x, p.y) for p in r.spec.geometry.points]
    d = [math.dist(P[k], P[(k + 1) % n]) for k in range(n)]
    assert max(d) - min(d) < 1e-9 and len(r.spec.geometry.segments) == sides      # straight equal edges
    assert "<text" not in de.render_spec(r.spec)[0]


def test_complex_point_mapping_and_polar():
    z = cx.parse("3+4i")
    assert cx.to_point(z) == (3.0, 4.0)
    r, t = cx.polar(z)
    assert r == 5 and abs(float(t) - math.atan2(4, 3)) < 1e-12


# ---------------------------------------------------------------- conics and loci
x, y = conics.x, conics.y


@pytest.mark.parametrize("eq,kind,focus", [
    (sympy.Eq(x ** 2 / 25 + y ** 2 / 9, 1), "ellipse", (4, 0)),
    (sympy.Eq(x ** 2 / 9 + y ** 2 / 25, 1), "ellipse", (0, 4)),
    (sympy.Eq(x ** 2 / 16 - y ** 2 / 9, 1), "hyperbola", (5, 0)),
    (sympy.Eq(y ** 2, 8 * x), "parabola", (2, 0)),
    (sympy.Eq((x - 1) ** 2 + (y + 2) ** 2, 4), "circle", (1, -2)),
])
def test_conic_identified_and_drawn_exactly(eq, kind, focus):
    c = conics.from_equation(eq)
    assert c["kind"] == kind
    assert any(abs(float(fx) - focus[0]) < 1e-9 and abs(float(fy) - focus[1]) < 1e-9 for fx, fy in c["foci"])
    spec = conics.graph_spec(c)
    r = de.process("cn", json.dumps(spec), "", None)
    assert r.validation.ok, r.validation.errors
    import numpy as np
    from diagram_engine import safe_math as sm
    for cur in r.spec.graph.curves:                                  # every drawn sample satisfies the conic equation
        f = sm.safe_function(cur.expression)
        xs = np.linspace(-6, 6, 400)
        ys = f(xs)
        ok = np.isfinite(ys)
        resid = [float((eq.lhs - eq.rhs).subs({x: a, y: b})) for a, b in zip(xs[ok][::40], ys[ok][::40])]
        assert all(abs(v) < 1e-6 for v in resid)


def test_locus_by_parameter_elimination():
    t = sympy.Symbol("t", real=True)
    # B = (4, 0); C = (3t, t) moves on the line through O and A(3,1); P = midpoint of BC -> a straight line
    L = conics.locus((4 + 3 * t) / 2, t / 2, [t])
    assert sympy.simplify(L.subs({x: 2, y: 0})) == 0 and sympy.simplify(L.subs({x: 3.5, y: 0.5})) == 0


# ---------------------------------------------------------------- vectors: symbol <-> edge <-> coordinates
def test_vector_semantics_pyramid():
    M = sympy.Matrix
    V = vectors.VectorSpace(points={"A": M([0, 0, 0]), "B": M([4, 0, 0]), "C": M([1, 3, 0]), "S": M([1, 1, 5])})
    for s_, (a, b) in {"u": ("A", "B"), "v": ("A", "C"), "w": ("A", "S")}.items():
        V.define(s_, a, b)
    V.points["E"] = V.points["S"] + sympy.Rational(3, 4) * (V.points["B"] - V.points["S"])
    V.points["F"] = V.points["S"] + sympy.Rational(3, 4) * (V.points["C"] - V.points["S"])
    assert V.express("B", "C", ["u", "v", "w"]) == {"u": -1, "v": 1, "w": 0}
    assert vectors.parallel(V.edge("E", "F"), V.edge("B", "C"))
    assert V.express("E", "F", ["u", "v"]) == {"u": sympy.Rational(-3, 4), "v": sympy.Rational(3, 4)}


# ---------------------------------------------------------------- analytic 3D
def test_space3d_relations():
    P = space3d.plane([0, 0, 1], 0)
    L = space3d.line([0, 0, 3], [1, 0, -1])
    assert list(space3d.line_plane_intersection(L, P)) == [3, 0, 0]
    assert sympy.simplify(space3d.angle_line_plane(L, P) - sympy.pi / 4) == 0
    assert space3d.distance_point_plane([2, 3, 7], P) == 7
    assert space3d.box_volume([2, 0, 0], [0, 5, 0], [0, 0, 8]) == 80
    Q = space3d.plane_from_points([0, 0, 0], [1, 0, 0], [0, 1, 1])
    assert sympy.simplify(space3d.angle_planes(P, Q) - sympy.pi / 4) == 0


# ---------------------------------------------------------------- ExpressionAST
@pytest.mark.parametrize("expr,root_kind", [("2*a*x/(a**2-9*x**2)", "Fraction"), ("exp(2*x)-4", "Sum"), ("log(x-2)", "Log"),
                                            ("sqrt(x**2-1)", "Root"), ("(1+I)**3", "Unknown_or_Power")])
def test_expression_ast(expr, root_kind):
    e = sympy.sympify(expr, locals={"I": sympy.I})
    ast = ea.from_sympy(e)
    assert ast.kind == root_kind or root_kind.startswith("Unknown_or") and ast.kind in ("Power", "Sum", "Product")
    assert ea.validate(ast) == []
    assert ea.to_sympy_latex(e)


# ---------------------------------------------------------------- function dependency graph / processes
def test_function_dependency_graph_verifies_and_flags():
    G = fn.FunctionDependencyGraph()
    X = fn.x
    G.add("f", sympy.exp(2 * X) - 4 * X)
    G.add("fp", 2 * sympy.exp(2 * X) - 4)
    G.relate("fp", "DERIVATIVE_OF", "f")
    G.add("g", None)
    G.relate("g", "NEGATIVE_OF", "fp")
    assert G.check() == [] and sympy.simplify(G.derive("g") + G.funcs["fp"]) == 0
    G.add("h", 3 * sympy.exp(2 * X))
    G.relate("h", "DERIVATIVE_OF", "f")
    assert any("FUNCTION_RELATION_CONFLICT" in m for m in G.check())


def test_piecewise_process_growth_then_decay_is_continuous():
    ph = fn.process([{"rule": "2000*1.1**t", "until": "2000*1.1**t - 5000"}, {"rule": "y0*0.9**t", "until": 30}])
    assert len(ph) == 2 and abs(ph[0]["t1"] - math.log(2.5) / math.log(1.1)) < 1e-9
    t = fn.t
    assert abs(float(ph[0]["expr"].subs(t, ph[0]["t1"])) - float(ph[1]["expr"].subs(t, ph[1]["t0"]))) < 1e-6


def test_multi_series_graph_keeps_labelled_series_and_hybrid_layer_does_not_change_math():
    spec = {"diagram_type": "graph", "subtype": "formula_graph", "confidence": 0.95, "labels": [],
            "graph": {"axes": {"x_min": 0, "x_max": 10, "y_min": 0, "y_max": 12},
                      "curves": [{"id": "I", "label": "I", "expression": "3*1.1^x"}, {"id": "II", "label": "II", "expression": "3*1.2^x"}]},
            "observed": {"num_curves": 2}}
    r = de.process("ms", json.dumps(spec), "", None)
    assert r.validation.ok and len(r.spec.graph.curves) == 2
    base = de.render_spec(r.spec)[2]
    hyb = json.loads(json.dumps(spec))
    hyb["graph"]["illustrations"] = [{"kind": "person", "x": 0.5, "y": 1, "size": 1.5}, {"kind": "basket", "x": 8, "y": 9}]
    r2 = de.process("hy", json.dumps(hyb), "", None)
    man2 = de.render_spec(r2.spec)[2]
    assert {k: v for k, v in man2.items() if k != "illustrations"} == base and len(man2["illustrations"]) == 2
