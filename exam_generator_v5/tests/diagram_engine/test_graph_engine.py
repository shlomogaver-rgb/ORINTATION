import numpy as np
import pytest
from helpers import run

from diagram_engine import safe_math as sm
from diagram_engine.graph import feature_detector as fd
from diagram_engine.graph import qualitative_parser as qp
from diagram_engine.schemas import DiagramSpec


@pytest.mark.parametrize("expr,x,y", [("x^(1/3)", -8, -2), ("x^(2/3)", -8, 4), ("x^(4/3)", -8, 16), ("x^(-1/3)", -8, -0.5), ("x^(-2/3)", -8, 0.25)])
def test_real_rational_powers(expr, x, y):
    assert sm.safe_function(expr)(np.array([float(x)]))[0] == pytest.approx(y)


def test_real_rational_power_helper():
    assert sm.real_rational_power(-8, 1, 3) == pytest.approx(-2) and sm.real_rational_power(-8, 2, 3) == pytest.approx(4)
    assert sm.real_rational_power(-8, 4, 6) == pytest.approx(4)            # fraction reduced first
    assert np.isnan(sm.real_rational_power(-8, 1, 2)) and np.isnan(sm.real_rational_power(0, -1, 3))


@pytest.mark.parametrize("bad", ["Integral(x)", "x.subs(1)", "Symbol(1)", "__import__('os')", "y", "lambda: 1"])
def test_ast_whitelist(bad):
    with pytest.raises(Exception):
        sm.parse_expression(bad)


def test_prompt_example_domain_sqrt_sum():
    f = fd.features(sm.parse_expression("sqrt(x^2-1)+2sqrt(16-x^2)"), -5, 5)
    assert [[round(a, 2), round(b, 2)] for a, b in f["domain_intervals"]] == [[-4.0, -1.0], [1.0, 4.0]]
    assert f["branches"] == 2 and f["symmetry"] == "even"


@pytest.mark.parametrize("expr,lo,hi,key,val", [
    ("ln(x-1)", -2, 6, "vertical_asymptotes", [1.0]),
    ("(x^2+1)/x", -5, 5, "oblique_asymptotes", [[1.0, 0.0]]),
    ("(x^2-4)/(x-2)", -4, 6, "oblique_asymptotes", []),
    ("x^3", -3, 3, "symmetry", "odd"),
    ("1/(x-2)", -4, 6, "branches", 2),
    ("(x^2-4)/(x-2)", -4, 6, "holes", [[2.0, 4.0]]),
])
def test_graph_features(expr, lo, hi, key, val):
    f = fd.features(sm.parse_expression(expr), lo, hi)
    got = f[key]
    flat = lambda v: [float(x) for x in np.ravel(np.array(v, dtype=float))] if not isinstance(v, (str, int)) else v  # noqa: E731
    assert (flat(got) == pytest.approx(flat(val)) if not isinstance(val, (str, int)) else got == val), (key, got)


def test_monotonicity_intervals():
    f = fd.features(sm.parse_expression("(x-2)^2"), -2, 6)
    assert f["decreasing"][0][1] == pytest.approx(2, abs=0.01) and f["increasing"][0][0] == pytest.approx(2, abs=0.01)


def topo(lms, branches, asy=()):
    return DiagramSpec.model_validate({"diagram_type": "graph", "subtype": "qualitative_graph", "confidence": 0.9,
                                       "graph_topology": {"axes": {"x_min": -5, "x_max": 10, "y_min": -5, "y_max": 5},
                                                          "landmarks": lms, "branches": branches, "asymptotes": list(asy)}})


def test_qualitative_no_equation_and_no_invented_extrema():
    s = topo([{"x": -1, "y": 0, "label": "", "kind": "x_intercept", "style": "none"}, {"x": 0, "y": 1, "label": "(0,1)", "kind": "marked"},
              {"x": 3, "y": 4, "label": "(3,4)", "kind": "max"}, {"x": 6, "y": 0, "label": "", "kind": "x_intercept", "style": "none"}],
             [{"landmarks": [0, 1, 2, 3], "left": {"toward": "minus_inf"}, "right": {"toward": "minus_inf"}}])
    assert qp.validate(s.graph_topology) == []
    xs, ys = qp.curve_points(s.graph_topology, s.graph_topology.branches[0])
    d = np.sign(np.diff(ys))
    assert np.count_nonzero(np.diff(d[d != 0])) == 1                          # exactly one turn: the marked maximum
    assert ys[np.argmax(ys)] == pytest.approx(4, abs=1e-3)
    spec = s.model_dump()
    spec["observed"] = {"num_branches": 1, "num_maxima": 1, "num_minima": 0}
    spec["labels"] = [{"text": "(0,1)", "confidence": 0.99}, {"text": "(3,4)", "confidence": 0.99}]
    r = run(spec)
    assert r.spec.graph is None and r.decision.action != "original"


def test_qualitative_inconsistent_topology_rejected():
    s = topo([{"x": 0, "y": 1, "kind": "marked"}, {"x": 2, "y": 3, "kind": "marked"}, {"x": 4, "y": 0, "kind": "marked"}],
             [{"landmarks": [0, 1, 2]}])
    assert any("אסור להמציא קיצון" in e for e in qp.validate(s.graph_topology))
    s2 = topo([{"x": 0, "y": 1, "kind": "marked"}, {"x": 1, "y": 3, "kind": "min"}, {"x": 2, "y": 0, "kind": "marked"}], [{"landmarks": [0, 1, 2]}])
    assert any("מינימום" in e for e in qp.validate(s2.graph_topology))


def test_qualitative_formula_in_text_warns():
    s = topo([{"x": 0, "y": 1, "kind": "max"}], [{"landmarks": [0], "left": {"toward": "minus_inf"}, "right": {"toward": "minus_inf"}}])
    r = run(s.model_dump(), "נתונה $f(x)=-x^2+1$")
    assert any("נוסחה מפורשת" in w for w in r.validation.warnings)


def test_multiple_choice_options_rendered_separately():
    o = {"axes": {"x_min": -3, "x_max": 3, "y_min": -3, "y_max": 3}, "curves": [{"id": "g", "expression": "x^2"}]}
    r = run({"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": [],
             "multi_graph": {"options": [{"label": l, "formula": o} for l in ("I", "II", "III", "IV")]},
             "observed": {"num_options": 4, "option_labels": ["I", "II", "III", "IV"]}})
    assert r.manifest["options"] == ["I", "II", "III", "IV"] and set(r.manifest["option_manifests"]) == {"I", "II", "III", "IV"}
    bad = run({"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9,
               "multi_graph": {"options": [{"label": "I", "formula": o}, {"label": "I", "formula": o}]}})
    assert not bad.validation.ok
