import math

import numpy as np
import pytest
from helpers import geo, pts, run


def _ok(r):
    assert r.validation.ok, r.validation.errors
    assert not r.comparison.critical, r.comparison.critical


@pytest.mark.parametrize("ctype,points,check", [
    ("equilateral", ["A", "B", "C"], lambda P: math.dist(P["A"], P["B"]) == pytest.approx(math.dist(P["B"], P["C"])) and math.dist(P["C"], P["A"]) == pytest.approx(math.dist(P["A"], P["B"]))),
    ("isosceles", ["C", "A", "B"], lambda P: math.dist(P["C"], P["A"]) == pytest.approx(math.dist(P["C"], P["B"]))),
    ("equal_angle", ["C", "A", "B", "A", "B", "C"], lambda P: True),
    ("parallel_to_x_axis", ["A", "B"], lambda P: P["A"][1] == pytest.approx(P["B"][1])),
    ("perpendicular_to_x_axis", ["A", "C"], lambda P: P["A"][0] == pytest.approx(P["C"][0])),
])
def test_constraint_types(ctype, points, check):
    r = run(geo({"A": (0, 0.2), "B": (4, 0), "C": (1.8, 3.1)}, extra={"constraints": [{"type": ctype, "points": points, "source": "text"}]}))
    _ok(r)
    assert check(pts(r))


def test_rectangle_and_square():
    for kind in ("rectangle", "square"):
        r = run(geo({"A": (0, 0), "B": (4, 0.2), "C": (4.1, 2.9), "D": (0.1, 3)}, segs=("AB", "BC", "CD", "DA"),
                    extra={"constraints": [{"type": kind, "points": ["A", "B", "C", "D"], "source": "text"}]}))
        _ok(r)
        P = pts(r)
        assert float((P["B"] - P["A"]) @ (P["C"] - P["B"])) == pytest.approx(0, abs=1e-6)
        if kind == "square":
            assert math.dist(P["A"], P["B"]) == pytest.approx(math.dist(P["B"], P["C"]))


def test_point_order_B_C_D_and_A_E_D():
    spec = geo({"A": (0, 3), "B": (-1, 0), "C": (2, 0.3), "D": (5, -0.2), "E": (2.4, 1.6)}, segs=("AB", "BD", "AD", "AC"),
               extra={"constraints": [{"type": "point_order", "points": ["B", "C", "D"], "source": "text"},
                                      {"type": "point_order", "points": ["A", "E", "D"], "source": "text"}]},
               observed={"num_points": 5, "point_labels": list("ABCDE"), "point_orders": [["B", "C", "D"], ["A", "E", "D"]]})
    r = run(spec)
    _ok(r)
    from diagram_engine.geometry.incidence import point_order_holds
    assert point_order_holds(r.spec.geometry, ["B", "C", "D"]) and point_order_holds(r.spec.geometry, ["A", "E", "D"])
    assert not point_order_holds(r.spec.geometry, ["C", "B", "D"]) and not point_order_holds(r.spec.geometry, ["B", "D", "C"])


def test_wrong_point_order_is_critical():
    spec = geo({"A": (0, 3), "B": (-1, 0), "C": (2, 0), "D": (5, 0)}, segs=("AB", "BD"),
               observed={"num_points": 4, "point_labels": list("ABCD"), "point_orders": [["B", "D", "C"]]})
    assert run(spec).decision.action == "original"


def test_circle_through_points_hidden_centre_concyclic():
    """Prompt example A14-style: A,B,C,E on one circle; ABC equilateral; B-C-D; A-E-D; E = second intersection of AD."""
    spec = geo({"A": (0, 3.4), "B": (-2, 0), "C": (2, 0), "D": (5, 0), "E": (2.1, 1.5)}, segs=("AB", "AC", "BD", "AD", "CE"),
               extra={"circles": [{"id": "c1", "through_points": ["A", "B", "C", "E"]}],
                      "constraints": [{"type": "equilateral", "points": ["A", "B", "C"], "source": "text"},
                                      {"type": "point_order", "points": ["B", "C", "D"], "source": "text"},
                                      {"type": "point_order", "points": ["A", "E", "D"], "source": "text"}]},
               observed={"num_points": 5, "point_labels": list("ABCDE"), "num_circles": 1, "point_orders": [["B", "C", "D"], ["A", "E", "D"]]})
    r = run(spec)
    _ok(r)
    P = pts(r)
    O = P["__c_c1"]
    radii = [math.dist(O, P[k]) for k in "ABCE"]
    assert max(radii) - min(radii) < 1e-6
    assert "__c_c1" not in r.manifest["points"]                               # hidden centre is never drawn


def test_diameter_radius_chord_secant_tangent():
    spec = geo({"O": (0, 0), "A": (-3, 0.2), "B": (3.1, -0.1), "C": (1, 2.8), "T": (0.2, -3), "P": (4, -3.3)},
               segs=("AB", "OC", "TP", "OT"),
               extra={"circles": [{"id": "c", "center": "O", "through": "A"}],
                      "constraints": [{"type": "diameter", "points": ["A", "B"], "circle": "c", "source": "text"},
                                      {"type": "radius", "points": ["C"], "circle": "c", "source": "text"},
                                      {"type": "tangent", "points": ["T", "P"], "circle": "c", "source": "text"}]})
    r = run(spec)
    _ok(r)
    P = pts(r)
    R = math.dist(P["O"], P["A"])
    assert np.allclose((P["A"] + P["B"]) / 2, P["O"]) and math.dist(P["O"], P["C"]) == pytest.approx(R)
    assert math.dist(P["O"], P["T"]) == pytest.approx(R) and float((P["T"] - P["O"]) @ (P["P"] - P["T"])) == pytest.approx(0, abs=1e-6)


def test_lost_tangent_is_critical():
    spec = geo({"O": (0, 0), "A": (-3, 0), "T": (0, -3), "P": (4, -3)}, segs=("TP", "OT"),
               extra={"circles": [{"center": "O", "through": "A"}]},
               observed={"num_points": 4, "point_labels": ["A", "O", "P", "T"], "tangent_points": ["T"]})
    assert run(spec).decision.action == "original"


def test_inside_outside_circle_and_polygon():
    spec = geo({"O": (0, 0), "A": (2, 0), "M": (1.5, 0.5), "N": (1, 1)}, segs=("OA",),
               extra={"circles": [{"id": "c", "center": "O", "through": "A"}],
                      "constraints": [{"type": "outside_circle", "points": ["M"], "circle": "c", "source": "text"},
                                      {"type": "inside_circle", "points": ["N"], "circle": "c", "source": "text"}]})
    r = run(spec)
    _ok(r)
    P = pts(r)
    assert math.dist(P["O"], P["M"]) > math.dist(P["O"], P["A"]) > math.dist(P["O"], P["N"])


def test_fixed_coordinates_from_text_are_exact():
    r = run(geo({"A": (0.3, 3.8), "B": (-2.9, 0.1), "C": (4, 1)}), "נתון: A(0 , 4) ו-B(−3 , 0).")
    P = pts(r)
    assert P["A"] == pytest.approx((0, 4)) and P["B"] == pytest.approx((-3, 0)) and r.spec.geometry.coordinate_axes


def test_vision_only_metric_relation_not_enforced():
    spec = geo({"A": (0, 0), "B": (4, 0), "C": (2.3, 3)}, extra={"constraints": [{"type": "equal_length", "points": ["A", "C", "B", "C"]}]})
    r = run(spec)
    assert r.spec.geometry.constraints == [] and any("ממראה השרטוט" in w for w in r.validation.warnings)


def test_geometry_renderer_new_objects():
    spec = geo({"A": (0, 0), "B": (4, 0), "C": (0, 3)}, extra={
        "polygons": [{"vertices": ["A", "B", "C"], "fill": True}],
        "equal_angle_marks": [{"angles": [["B", "A", "C"], ["A", "C", "B"]], "arcs": 2}],
        "dimensions": [{"a": "A", "b": "B", "text": "8 מטרים"}]})
    r = run(spec)
    assert r.manifest["polygons"] == 1 and r.manifest["equal_angle_groups"] == 1 and r.manifest["dimensions"] == [["A", "B", "8 מטרים"]]
