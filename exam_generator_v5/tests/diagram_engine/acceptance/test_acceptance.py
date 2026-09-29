"""Acceptance suite on the supplied Bagrut questionnaires. Pass = schema+deterministic validation pass, 0 critical,
required facts/labels/topology 100% - or a SAFE fallback to the original where that is the designed behaviour."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import diagram_engine as de  # noqa: E402
from cases import CASES, SCATTER, variant  # noqa: E402
from diagram_engine.generic.comparator import adjacency  # noqa: E402
from diagram_engine.graph import feature_detector  # noqa: E402
from diagram_engine import safe_math as sm  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def run(case: dict):
    src = (FIX / case["fixture"]).read_bytes()
    return de.process(case["fixture"], json.dumps(case["spec"], ensure_ascii=False), case["text"], src)


@pytest.mark.parametrize("name", list(CASES))
def test_case_decision_is_safe(name):
    case = CASES[name]
    r = run(case)
    if case["expect"] == "original":
        assert r.decision.action == "original" and not de.usable_in_document(r)
        return
    assert r.validation.ok, r.validation.errors
    assert r.comparison.critical == [], r.comparison.critical
    assert r.decision.action in ("review", "high_confidence_preview", "draft"), r.decision
    assert r.review.status == "pending" and not de.usable_in_document(r)       # never exported before the teacher
    assert de.approve(r) and de.usable_in_document(r)


def P(r, pid):
    g = r.spec.geometry or r.spec.mixed.geometry
    p = next(p for p in g.points if p.id == pid)
    return np.array([p.x, p.y])


def test_A01_required_facts():
    r = run(CASES["A01_qualitative"])
    assert r.spec.graph is None                                # no equation invented
    kinds = [l[0] for l in r.manifest["landmarks"]]
    assert kinds == ["max", "x_intercept", "min"] and r.manifest["branches"] == 1
    assert sorted(r.manifest["labels"]) == sorted(["(6 , a)", "(12 , 0)", "(18, −2a)", "f(x)"])


def test_A02_formula_domain_and_option_match():
    expr = sm.parse_expression(CASES["A02_formula_options"]["formula"])
    f = feature_detector.features(expr, 0, 20)
    assert f["domain_intervals"][0][0] == pytest.approx(3.2, abs=0.01)
    d = feature_detector.features(sm.parse_expression("2-10/sqrt(5x-16)"), 3.2001, 20)
    assert d["roots"] == pytest.approx([8.2], abs=1e-6)                   # f'(8.2)=0
    r = run(CASES["A02_formula_options"])
    assert r.manifest["options"] == ["I", "II", "III", "IV"]              # four separate options, order kept
    from diagram_engine.graph.qualitative_parser import topology_summary
    target = {"vertical_asymptotes": [3.2], "horizontal_asymptotes": [2.0], "x_intercepts": [8.2]}
    opts = {o.label: topology_summary(o.topology) for o in r.spec.multi_graph.options}
    from diagram_engine.graph.comparator import match_options
    assert match_options(target, opts) == ["II"]                          # deterministic answer, separate from rendering


def test_A03_A10_options_topology_preserved():
    for name in ("A03_rational_options", "A10_log_options"):
        r = run(CASES[name])
        assert r.manifest["options"] == ["I", "II", "III", "IV"]
        for o in r.spec.multi_graph.options:
            assert r.manifest["option_manifests"][o.label]["branches"] == len(o.topology.branches)
            assert len(r.manifest["option_manifests"][o.label]["asymptotes"]) == len(o.topology.asymptotes)


def test_A04_text_construction_not_drawn_into_figure():
    r = run(CASES["A04_formula_no_construction"])
    f = r.validation.info["graph_features"]["f"]
    assert f["roots"] == pytest.approx([-1, 1]) and f["branches"] == 2 and f["symmetry"] == "even"
    assert r.manifest["points"] == []                                     # A, B from the text are NOT in the figure


def test_A05_scatter_detected_deterministically():
    r = run(CASES["A05_scatter"])
    det = r.validation.info["scatter_detection"]
    assert det["stable"] and len(det["points"]) == 6
    assert r.parser_confidence >= 0.96


def test_A06_adjacency_dimension():
    r = run(CASES["A06_generic_plan"])
    assert adjacency(r.spec) == CASES["A06_generic_plan"]["adjacency"]
    assert r.manifest["dimensions"] == [["8 מטרים", ["A", "G"]]]


def test_A08_exact_coordinates_tangent_diameter_order():
    r = run(CASES["A08_coordinate_circle"])
    for k, v in CASES["A08_coordinate_circle"]["exact"].items():
        assert P(r, k) == pytest.approx(v, abs=1e-6), k
    M, A, D, C = P(r, "M"), P(r, "A"), P(r, "D"), P(r, "C")
    assert float((A - M) @ (D - A)) == pytest.approx(0, abs=1e-6)        # tangent at A
    assert np.allclose((A + C) / 2, M)                                    # AC diameter


def test_A09_box_and_pyramid_topology():
    r = run(CASES["A09_box"])
    assert r.manifest["edges"] == 12 and r.manifest["hidden_edges"] == 3 and len(r.manifest["vertices"]) == 8
    r2 = run(CASES["A09b_pyramid_vectors"])
    assert sorted(v[2] for v in r2.manifest["vectors"]) == ["u", "v", "w"]
    assert ["F", "B", "C", pytest.approx(2 / 3)] in r2.manifest["points_on_edges"]


def test_A11_normal_regions_labels_boxes():
    r = run(CASES["A11_normal"])
    assert r.manifest["regions"] == 12 and r.manifest["lines"] == 11 and r.manifest["boxes"] == 11
    assert r.manifest["labels"] == CASES["A11_normal"]["spec"]["normal"]["percentages"] and r.manifest["symmetric_labels"]


def test_A12_voxel_never_invents_hidden_cubes():
    r = run(CASES["A12_voxel"])
    assert r.decision.action == "original" and any("נסתרות" in e for e in r.validation.errors)


def test_A13_dimensions_and_radius_semantics():
    r = run(CASES["A13_carton_cup"])
    dims = {(d[0], d[1]): d[2] for d in r.manifest["dimensions"]}
    assert dims[("carton", "height")] == '24 ס"מ' and dims[("cup", "radius")] == '3 ס"מ'
    assert ("cup", "diameter") not in dims


def test_A14_circle_kite_relations():
    r = run(CASES["A14_circle_kite"])
    O, A, B, C, E, K, M = (P(r, k) for k in "OABCEKM")
    R = math.dist(O, A)
    assert math.dist(O, B) == pytest.approx(R) and math.dist(O, C) == pytest.approx(R) and np.allclose((A + B) / 2, O)
    assert math.dist(M, K) == pytest.approx(math.dist(M, E)) and math.dist(O, K) == pytest.approx(math.dist(O, E))
    assert math.dist(O, M) > R


# ---------------------------------------------------------------- deliberately wrong candidates must be blocked
BAD = {
    "A01_extra_max": ("A01_qualitative", lambda s: s["graph_topology"]["landmarks"].insert(2, {"x": 14, "y": -0.5, "kind": "max", "label": "(14 , b)"})),
    "A05_extra_point": ("A05_scatter", lambda s: s["scatter"]["points"].append([30, 60])),
    "A05_missing_point": ("A05_scatter", lambda s: s["scatter"]["points"].pop()),
    "A05_moved_point": ("A05_scatter", lambda s: s["scatter"]["points"].__setitem__(0, [5, 40])),
    "A06_missing_region": ("A06_generic_plan", lambda s: s["generic"]["shapes"].pop()),
    "A07_wrong_number": ("A07_table_haircuts", lambda s: s["table"]["rows"][1][2].__setitem__("text", "15")),
    "A08_lost_tangent": ("A08_coordinate_circle", lambda s: s["geometry"]["segments"].pop(1)),
    "A09_missing_hidden_edge": ("A09_box", lambda s: s["spatial"]["solids"][0]["edges"].pop()),
    "A11_changed_percent": ("A11_normal", lambda s: s["normal"]["percentages"].__setitem__(5, "18%")),
    "A11_missing_region": ("A11_normal", lambda s: s["normal"]["percentages"].pop()),
    "A13_wrong_dimension": ("A13_carton_cup", lambda s: s["spatial"]["dimensions"][0].__setitem__("text", "42 ס\"מ")),
    "A14_extra_point": ("A14_circle_kite", lambda s: s["geometry"]["points"].append({"id": "F", "x": 3, "y": 3})),
    "A14_wrong_order": ("A14_circle_kite", lambda s: s["geometry"]["points"].__setitem__(6, {"id": "E", "x": -1.1, "y": -0.95})),
    "A02_merged_options": ("A02_formula_options", lambda s: s["multi_graph"]["options"].pop()),
}


@pytest.mark.parametrize("name", list(BAD))
def test_wrong_candidate_is_blocked(name):
    base, mutate = BAD[name]
    r = run(variant(CASES[base], mutate))
    assert r.decision.action == "original", (name, r.decision, r.validation.errors, r.comparison.critical)
    assert not de.usable_in_document(r) and not de.approve(r)
