"""Diagram engine: unit, regression, anti-hallucination and acceptance tests.  Run: python -m pytest -q tests"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import diagram_engine as de  # noqa: E402
from diagram_engine import comparison, constraints, graph_parser, geometry_parser, safe_math as sm  # noqa: E402
from diagram_engine.schemas import DiagramSpec  # noqa: E402
from diagram_engine.validator import validate  # noqa: E402


def graph(expr=None, axes=None, observed=None, pieces=None, points=None, asymptotes=None, conf=0.95, labels=None):
    curve = {"id": "f", "label": "f(x)", "expression": expr or ""}
    if pieces:
        curve["pieces"] = pieces
    return {"diagram_type": "graph", "confidence": conf,
            "graph": {"axes": axes or {"x_min": -10, "x_max": 10, "y_min": -10, "y_max": 10},
                      "curves": [curve] if (expr or pieces) else [], "points": points or [], "asymptotes": asymptotes or []},
            "labels": labels if labels is not None else [{"text": "f(x)", "confidence": 0.99}],
            "observed": observed or {"num_curves": 1}}


def run(spec: dict, text: str = "", allow_auto=False):
    return de.process("fig", json.dumps(spec), text, None, allow_auto=allow_auto)


def tri(points, segs=("AB", "BC", "CA"), extra=None, conf=0.95, observed=None, labels=None):
    g = {"points": [{"id": k, "x": v[0], "y": v[1]} for k, v in points.items()],
         "segments": [{"a": s[0], "b": s[1]} for s in segs]}
    g.update(extra or {})
    return {"diagram_type": "geometry", "confidence": conf, "geometry": g,
            "labels": labels if labels is not None else [{"text": k, "confidence": 0.99} for k in points],
            "observed": observed or {"num_points": len(points), "point_labels": sorted(points), "num_segments": len(segs)}}


# ================================================================ safe math / real roots (req. 8, 38, 39)
@pytest.mark.parametrize("expr,x,y", [("x^(1/3)", -8, -2), ("cbrt(x)", -8, -2), ("cuberoot(x)", -27, -3), (r"\sqrt[3]{x}", -8, -2),
                                      ("x^(2/3)", -8, 4), ("(x-2)^(1/3)", -6, -2), ("x^(1/5)", -32, -2)])
def test_real_odd_roots(expr, x, y):
    assert sm.safe_function(expr)(np.array([float(x)]))[0] == pytest.approx(y)


def test_even_root_of_negative_is_undefined():
    assert np.isnan(sm.safe_function("sqrt(x)")(np.array([-4.0]))[0])
    assert np.isnan(sm.real_power(-8, 1, 2))
    assert sm.real_power(-8, 2, 3) == pytest.approx(4)


@pytest.mark.parametrize("bad", ["__import__('os')", "x.__class__", "open(1)", "lambda: 1", "y+x", "9^9^9^9", "9^(9^9)", "exec(1)"])
def test_parser_rejects_code(bad):
    with pytest.raises(Exception):
        sm.parse_expression(bad)


# ================================================================ graphs (req. 7, 16, 33)
GRAPH_CASES = {
    "linear": ("2x+1", {"roots": [-0.5], "y0": 1}),
    "quadratic": ("(x-2)^2-1", {"roots": [1, 3], "y0": 3}),
    "cubic": ("x^3-4x", {"roots": [-2, 0, 2], "y0": 0}),
    "sqrt": ("sqrt(x-2)+1", {"roots": [], "y0": None}),
    "cbrt": ("cbrt(x)", {"roots": [0], "y0": 0}),
    "abs": ("abs(x-1)-2", {"roots": [-1, 3], "y0": -1}),
    "negative_domain": ("sqrt(-x)", {"roots": [0], "y0": 0}),
}


@pytest.mark.parametrize("name", list(GRAPH_CASES))
def test_graph_regressions(name):
    expr, exp = GRAPH_CASES[name]
    r = run(graph(expr), f"נתונה הפונקציה $f(x)={expr}$")
    assert r.validation.ok, r.validation.errors
    f = r.validation.info["graph_features"]["f"]
    assert f["roots"] == pytest.approx(exp["roots"], abs=1e-6)
    assert (f["y_intercept"] is None) == (exp["y0"] is None)
    if exp["y0"] is not None:
        assert f["y_intercept"] == pytest.approx(exp["y0"])
    assert r.manifest["curves"] == ["f"] and not r.comparison.critical


def test_rational_asymptote_and_hole():
    r = run(graph("(x^2-1)/((x-1)(x-3))", observed={"num_curves": 1}), "")
    f = r.validation.info["graph_features"]["f"]
    assert f["vertical_asymptotes"] == pytest.approx([3.0])
    assert f["holes"] == [[1.0, pytest.approx(-1.0)]]
    assert f["horizontal_asymptotes"] == [1.0]
    open_pts = [p for p in r.spec.graph.points if p.style == "open" and p.source == "computed"]
    assert len(open_pts) == 1 and open_pts[0].x == pytest.approx(1.0)


def test_explicit_asymptote_drawn():
    r = run(graph("1/x", asymptotes=[{"kind": "vertical", "value": 0}, {"kind": "horizontal", "value": 0}]))
    assert r.validation.ok and r.manifest["asymptotes"] == [["vertical", 0.0], ["horizontal", 0.0]]


def test_piecewise_open_closed_endpoints():
    pieces = [{"expression": "x+1", "x_from": -4, "x_to": 1, "left_closed": True, "right_closed": False},
              {"expression": "3-x", "x_from": 1, "x_to": 4, "left_closed": True, "right_closed": True}]
    obs = {"num_curves": 1, "open_endpoints": [[1, 2]], "closed_endpoints": [[-4, -3], [1, 2], [4, -1]]}
    r = run(graph(pieces=pieces, observed=obs))
    assert r.validation.ok, r.validation.errors
    kinds = sorted((e[1], e[2], e[3]) for e in r.manifest["endpoints"])
    assert kinds == [(-4, -3, "closed"), (1, 2, "closed"), (1, 2, "open"), (4, -1, "closed")]
    assert not r.comparison.critical
    # an open endpoint that became closed is a critical mismatch
    pieces[0]["right_closed"] = True
    r2 = run(graph(pieces=pieces, observed=obs))
    assert any("פתוחה" in c for c in r2.comparison.critical) and r2.decision.action == "original"


def test_point_on_curve_is_checked_by_substitution():
    ok = run(graph("x^2", points=[{"name": "A", "x": 2, "y": 4, "on_curve": "f"}],
                   labels=[{"text": "A", "confidence": 0.99}, {"text": "f(x)", "confidence": 0.99}]))
    assert ok.validation.ok
    bad = run(graph("x^2", points=[{"name": "A", "x": 2, "y": 5, "on_curve": "f"}]))
    assert not bad.validation.ok and any("אינה על העקומה" in e for e in bad.validation.errors)


def test_no_real_values_in_domain_is_error():
    r = run(graph("sqrt(x-20)", axes={"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5}))
    assert not r.validation.ok and r.decision.action == "original"


def test_malformed_equation_is_error():
    r = run(graph("x^^2+"))
    assert not r.validation.ok and r.decision.action == "original"


def test_intercept_change_is_critical():
    r = run(graph("x^2-4", observed={"num_curves": 1, "x_intercepts": [-3, 3]}))
    assert any("ציר x" in c for c in r.comparison.critical) and r.decision.action == "original"


def test_image_only_curve_never_reaches_high_confidence():
    r = run(graph("x^2", conf=0.99, observed={"num_curves": 1}), "", allow_auto=True)
    assert r.parser_confidence <= 0.90 and r.decision.action != "high_confidence_preview" and r.review.status == "pending"


def test_functions_from_text_variants():
    names = {n: t for n, t, _ in graph_parser.functions_from_text("נתונה $y=\\sqrt{x-2}+1$ וגם g(x) = 2x-3, ו-$h(x)=\\frac{1}{x}$.")}
    assert set(names) == {"y", "g", "h"}


# ================================================================ acceptance tests (req. 45)
def test_acceptance_1_parabola():
    r = run(graph("x^2", axes={"x_min": -2, "x_max": 6, "y_min": -2, "y_max": 8},
                  observed={"num_curves": 1, "x_intercepts": [1, 3], "y_intercept": 3}), "נתונה הפונקציה $f(x)=(x-2)^2-1$")
    f = r.validation.info["graph_features"]["f"]
    assert f["roots"] == pytest.approx([1, 3]) and f["y_intercept"] == pytest.approx(3)
    assert f["extrema"] == [{"x": pytest.approx(2), "y": pytest.approx(-1), "kind": "min"}]
    assert r.spec.graph.curves[0].source == "text" and r.decision.action in ("review", "high_confidence_preview")


def test_acceptance_2_cuberoot():
    pts = [{"name": "", "x": x, "y": y, "on_curve": "f"} for x, y in ((-8, -2), (0, 0), (8, 2))]
    r = run(graph("cuberoot(x)", points=pts, axes={"x_min": -10, "x_max": 10, "y_min": -3, "y_max": 3}), "y=cuberoot(x)")
    assert r.validation.ok, r.validation.errors
    ys = sm.safe_function("cuberoot(x)")(np.array([-8.0, 0.0, 8.0]))
    assert ys == pytest.approx([-2, 0, 2])


def test_acceptance_3_isosceles_marks():
    spec = tri({"A": (0, 0), "B": (6, 0), "C": (2.6, 4.2)},
               extra={"equal_marks": [{"segments": [["A", "C"], ["B", "C"]], "ticks": 1}]},
               observed={"num_points": 3, "point_labels": ["A", "B", "C"], "num_segments": 3, "equal_mark_groups": 1})
    r = run(spec, "במשולש שווה שוקיים ABC נתון AC=BC.")
    assert r.validation.ok, r.validation.errors
    P = {p.id: np.array([p.x, p.y]) for p in r.spec.geometry.points}
    assert math.dist(P["A"], P["C"]) == pytest.approx(math.dist(P["B"], P["C"]), rel=1e-7)
    assert r.manifest["equal_mark_groups"] == 1 and not r.comparison.critical


def test_acceptance_4_right_angle_mark_kept():
    spec = tri({"A": (0, 3.1), "B": (0, 0), "C": (4.2, 0.2)},
               extra={"angle_marks": [{"vertex": "B", "a": "A", "b": "C", "kind": "right"}]},
               observed={"num_points": 3, "point_labels": ["A", "B", "C"], "num_segments": 3, "right_angle_marks": 1})
    r = run(spec, "במשולש ישר זווית ABC ($\\angle B=90^\\circ$)")
    assert r.validation.ok and r.manifest["right_angle_marks"] == 1
    P = {p.id: np.array([p.x, p.y]) for p in r.spec.geometry.points}
    assert float(np.dot(P["A"] - P["B"], P["C"] - P["B"])) == pytest.approx(0, abs=1e-6)


def test_acceptance_5_parallel_marks_kept():
    spec = tri({"A": (0, 0), "B": (5, 0.3), "C": (1, 2), "D": (6, 2.1)}, segs=("AB", "CD"),
               extra={"parallel_marks": [{"segments": [["A", "B"], ["C", "D"]], "arrows": 1}]},
               observed={"num_points": 4, "point_labels": ["A", "B", "C", "D"], "num_segments": 2, "parallel_mark_groups": 1})
    r = run(spec, "נתון $AB \\parallel CD$.")
    assert r.validation.ok and r.manifest["parallel_mark_groups"] == 1
    P = {p.id: np.array([p.x, p.y]) for p in r.spec.geometry.points}
    u, v = P["B"] - P["A"], P["D"] - P["C"]
    assert u[0] * v[1] - u[1] * v[0] == pytest.approx(0, abs=1e-6)


def test_acceptance_6_blurry_label_not_invented():
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)},
               labels=[{"text": "A", "confidence": 0.99}, {"text": "B", "confidence": 0.45, "alternatives": ["8", "R"]},
                       {"text": "C", "confidence": 0.99}])
    r = run(spec)
    assert not r.validation.ok and any("'B'" in e for e in r.validation.errors)
    assert r.decision.action == "original" and not de.usable_in_document(r)
    assert not de.approve(r)


def test_acceptance_7_low_confidence_uses_original():
    r = run(tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)}, conf=0.5), allow_auto=True)
    assert r.decision.action == "original" and not de.usable_in_document(r)


# ================================================================ geometry (req. 9-12, 33, 47, 54)
def test_midpoint_and_collinear_from_text():
    spec = tri({"A": (0, 0), "B": (6, 0), "C": (2, 4), "D": (3.3, 0.1)}, segs=("AB", "BC", "CA", "CD"))
    r = run(spec, "D היא אמצע הצלע AB.")
    P = {p.id: np.array([p.x, p.y]) for p in r.spec.geometry.points}
    assert P["D"] == pytest.approx((P["A"] + P["B"]) / 2)


def test_circle_chord_tangent():
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "OABTP"],
            "geometry": {"points": [{"id": "O", "x": 0, "y": 0}, {"id": "A", "x": -3, "y": 0.1}, {"id": "B", "x": 2.1, "y": 2.2},
                                    {"id": "T", "x": 0.1, "y": -3}, {"id": "P", "x": 4, "y": -3.2}],
                         "circles": [{"center": "O", "through": "A"}],
                         "segments": [{"a": "A", "b": "B"}, {"a": "T", "b": "P"}, {"a": "O", "b": "T"}],
                         "constraints": [{"type": "on_circle", "points": ["B", "O"], "source": "mark"},
                                         {"type": "on_circle", "points": ["T", "O"], "source": "mark"}]},
            "observed": {"num_points": 5, "num_circles": 1, "num_segments": 3}}
    r = run(spec, "PT משיק למעגל בנקודה T.")
    assert r.validation.ok, r.validation.errors
    P = {p.id: np.array([p.x, p.y]) for p in r.spec.geometry.points}
    R = math.dist(P["O"], P["A"])
    assert math.dist(P["O"], P["B"]) == pytest.approx(R) and math.dist(P["O"], P["T"]) == pytest.approx(R)
    assert float(np.dot(P["T"] - P["O"], P["P"] - P["T"])) == pytest.approx(0, abs=1e-6)
    assert r.manifest["circles"] == 1


def test_angle_value_mark_and_label():
    spec = tri({"A": (0, 0), "B": (5, 0), "C": (1.5, 3)},
               extra={"angle_marks": [{"vertex": "C", "a": "A", "b": "B", "kind": "arc", "value": "40"}]},
               labels=[{"text": t, "confidence": 0.99} for t in ("A", "B", "C", "40")])
    r = run(spec)
    assert r.validation.ok and r.manifest["angle_values"] == ["40"] and r.manifest["angle_marks"] == 1


def test_impossible_constraints_rejected():
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)},
               extra={"constraints": [{"type": "right_angle", "points": ["A", "B", "C"], "source": "text"},
                                      {"type": "right_angle", "points": ["B", "A", "C"], "source": "text"}]})
    r = run(spec)
    assert not r.validation.ok and r.decision.action == "original"


def test_side_of_line_flip_is_critical():
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3), "D": (2, -1.5)}, segs=("AB", "BC", "CA", "AD"),
               extra={"constraints": [{"type": "midpoint", "points": ["D", "A", "C"], "source": "text"}]})
    r = run(spec)
    assert any("צד" in c for c in r.comparison.critical) and r.decision.action == "original"


def test_not_to_scale_no_inferred_relations():
    """Two sides that merely LOOK equal must not become an equality constraint."""
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3.4641)})
    r = run(spec, "נתון משולש ABC.")
    assert r.spec.geometry.constraints == []


def test_text_relation_with_unknown_point_does_not_add_point():
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)})
    r = run(spec, "E היא אמצע הצלע AB.")
    assert sorted(p.id for p in r.spec.geometry.points) == ["A", "B", "C"]
    assert any("E" in w for w in r.validation.warnings)


def test_relations_from_text_patterns():
    rels, _ = geometry_parser.relations_from_text(
        "במשולש ABC נתון $AB=AC$, $DE \\parallel BC$, $AD \\perp BC$, $\\angle ABC = 70^\\circ$, M היא אמצע הצלע BC.")
    kinds = sorted(c.type for c in rels)
    assert kinds == ["angle_value", "equal_length", "midpoint", "parallel", "perpendicular"]


# ================================================================ validator holes (req. 15)
@pytest.mark.parametrize("mutate,msg", [
    (lambda g: g["segments"].append({"a": "A", "b": "Z"}), "לא קיימת"),
    (lambda g: g["points"].append({"id": "A", "x": 9, "y": 9}), "כפולים"),
    (lambda g: g["angle_marks"].append({"vertex": "Q", "a": "A", "b": "B"}), "לא קיימת"),
    (lambda g: g["equal_marks"].append({"segments": [["A", "B"], ["X", "Y"]]}), "לא קיימת"),
    (lambda g: g["equal_marks"].append({"segments": [["A", "B"]]}), "לפחות שני"),
])
def test_geometry_validator_rejects(mutate, msg):
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)}, extra={"angle_marks": [], "equal_marks": []})
    mutate(spec["geometry"])
    r = run(spec)
    assert not r.validation.ok and any(msg in e for e in r.validation.errors), r.validation.errors


def test_chart_validation_and_text_priority():
    bad = {"diagram_type": "chart", "confidence": 0.9, "chart": {"kind": "bar", "categories": ["a", "b"], "values": [1]}}
    assert not run(bad).validation.ok
    spec = {"diagram_type": "chart", "confidence": 0.9, "chart": {"kind": "bar", "categories": ["ראשון", "שני"], "values": [3, 4]},
            "observed": {"num_bars": 2}}
    r = run(spec, "ראשון: 5\nשני: 7")
    assert r.spec.chart.values == [5, 7] and r.spec.chart.values_source == "text" and r.validation.ok


@pytest.mark.parametrize("chart", [
    {"kind": "histogram", "bins": [0, 10, 20, 30], "values": [4, 7, 2]},
    {"kind": "pie", "categories": ["א", "ב"], "values": [1, 3]},
    {"kind": "frequency_table", "col_labels": ["ציון", "שכיחות"], "table": [["60", "3"], ["70", "5"]]},
    {"kind": "two_way_table", "row_labels": ["בנים", "בנות"], "col_labels": ["כן", "לא"], "table": [["3", "4"], ["5", "6"]]},
])
def test_chart_kinds_render(chart):
    r = run({"diagram_type": "chart", "confidence": 0.9, "chart": chart})
    assert r.validation.ok, r.validation.errors
    assert r.manifest["kind"] == chart["kind"]


def test_pie_has_no_invented_percentages():
    r = run({"diagram_type": "chart", "confidence": 0.9, "chart": {"kind": "pie", "categories": ["a", "b"], "values": [1, 3]}})
    svg, _, _ = de.render_spec(r.spec)
    assert "%" not in svg


# ================================================================ anti-hallucination (req. 34)
def test_renderer_draws_exactly_the_spec():
    spec = DiagramSpec.model_validate(tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)}))
    _, _, man = de.render_spec(spec)
    assert man == {**comparison.expected_manifest(spec), "points": ["A", "B", "C"]} | {k: man[k] for k in man if k not in comparison.expected_manifest(spec)}
    assert man["circles"] == 0 and man["right_angle_marks"] == 0 and man["equal_mark_groups"] == 0 and man["parallel_mark_groups"] == 0
    assert man["angle_values"] == [] and man["length_labels"] == [] and man["labels"] == ["A", "B", "C"]


@pytest.mark.parametrize("extra", [{"points": ["A", "B", "C", "D"]}, {"segments": ["AB", "AC", "BC", "BD"]}, {"circles": 1},
                                   {"labels": ["A", "B", "C", "X"]}, {"angle_values": ["30"]}, {"parallel_mark_groups": 1},
                                   {"equal_mark_groups": 1}])
def test_hallucinated_object_is_critical(extra):
    spec = DiagramSpec.model_validate(tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)}))
    _, png, man = de.render_spec(spec)
    tampered = {**man, **extra}
    res = comparison.compare(spec, tampered, None, png)
    assert res.critical


def test_hallucinated_equation_and_label_blocked():
    spec = graph("x^2", labels=[{"text": "f(x)", "confidence": 0.99}])
    spec["graph"]["curves"][0]["label"] = "g(x)"
    r = run(spec)
    assert any("אינן במקור" in c for c in r.comparison.critical)


def test_rendering_is_deterministic():
    spec = DiagramSpec.model_validate(graph("x^3-4x"))
    from diagram_engine.graph_renderer import render
    s1, p1, _ = render(spec)
    s2, p2, _ = render(spec)
    assert s1 == s2 and p1 == p2


# ================================================================ review / decision / fail-safe (req. 20, 26, 30, 31)
def test_approval_bound_to_spec_and_edit_voids_it():
    spec = tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)})
    r = run(spec)
    assert r.decision.action in ("review", "draft", "high_confidence_preview") and not de.usable_in_document(r)
    assert de.approve(r) and de.usable_in_document(r)
    edited = r.spec.model_copy(deep=True)
    edited.geometry.points[2].y = 2.5
    r2 = de.apply_teacher_edit(r, edited, "הזזת C", "", None)
    assert r2.review.status == "pending" and not de.usable_in_document(r2) and len(r2.review.teacher_edits) == 1


def test_nothing_is_ever_approved_without_teacher():
    spec = graph("(x-2)^2-1", observed={"num_curves": 1, "x_intercepts": [1, 3], "y_intercept": 3}, conf=0.99)
    r = run(spec, "f(x)=(x-2)^2-1", allow_auto=True)     # allow_auto is ignored in v5.5
    assert r.decision.action == "high_confidence_preview"
    assert r.review.status == "pending" and not de.usable_in_document(r)
    assert de.approve(r) and de.usable_in_document(r)


@pytest.mark.parametrize("raw", ["", "not json", "[1,2]", '{"diagram_type": "geometry"}', '{"diagram_type":"graph","graph":{"curves":[{"expression":"x**"}]}}'])
def test_pipeline_never_raises(raw):
    r = de.process("f", raw, "", b"")
    assert r.decision.action == "original" and r.teacher_message and not de.usable_in_document(r)


def test_legacy_5x_spec_is_converted():
    legacy = json.dumps({"x_range": [-4, 4], "y_range": [-5, 8], "objects": [{"type": "function", "expression": "x^2-4", "label": "f(x)"}]})
    r = de.process("f", legacy, "", None, figure_type_hint="function_graph", fallback_confidence=0.9)
    assert r.spec.diagram_type == "graph" and r.validation.ok


def test_export_bundle_contents():
    r = run(tri({"A": (0, 0), "B": (4, 0), "C": (2, 3)}))
    import io, zipfile
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, format="PNG")
    z = zipfile.ZipFile(io.BytesIO(de.export_bundle({"q1f1": r}, {"q1f1": buf.getvalue()})))
    names = set(z.namelist())
    for n in ("source.png", "cleaned.png", "spec.json", "render.svg", "render.png", "validation.json", "comparison.json", "review.json", "audit.json"):
        assert f"q1f1/{n}" in names
