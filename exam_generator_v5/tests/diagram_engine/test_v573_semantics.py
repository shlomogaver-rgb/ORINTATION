"""V5.7.3 generalisation tests: clause-level semantics, plural dimensions. Each rule is tested with paraphrases,
alternative letters and orders - never only the original failure sentence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import diagram_engine as de  # noqa: E402
from diagram_engine import text_facts as tf  # noqa: E402


@pytest.mark.parametrize("text,given,goal", [
    ("הנקודה E נמצאת על הקטע BO, ומצאו את BE.", "point_on_segment(E,B,O)", "BE"),
    ("הנקודה K נמצאת על הקטע PQ, וחשבו את PK.", "point_on_segment(K,P,Q)", "PK"),
    ("נתון כי הנקודה M נמצאת על הקטע AD; מצאו את AM.", "point_on_segment(M,A,D)", "AM"),
    ("F היא אמצע הקטע BC, וקבעו את סוג המרובע.", "midpoint(F,B,C)", "סוג"),
])
def test_given_and_goal_in_one_sentence(text, given, goal):
    kinds = tf.clauses(text)
    assert [k for k, _ in kinds] == ["GIVEN", "GOAL"], kinds
    assert given in {f.key for f in tf.extract(tf.given_text(text))}
    assert goal in kinds[1][1]


@pytest.mark.parametrize("text,claimed_key", [
    ("והוכיחו כי AB = CD.", "equal_length(A,B,C,D)"),
    ("הוכח ש-PQ = RS.", "equal_length(P,Q,R,S)"),
    ("הראו כי AB ∥ CD.", "parallel(A,B,C,D)"),
    ("הסבירו מדוע EF מקביל ל-BC.", "parallel(B,C,E,F)"),
    ("נמקו מדוע KL מאונך ל-MN.", "perpendicular(K,L,M,N)"),
    ("הוכיחו: AB = CD.", "equal_length(A,B,C,D)"),
    ("(1) הוכיחו: $\\triangle ADG\\sim\\triangle BDC$.", "segment(B,C)"),
    ("הראו: PQ ∥ RS.", "parallel(P,Q,R,S)"),
])
def test_claim_to_prove_is_never_a_given(text, claimed_key):
    assert tf.clauses(text)[0][0] == "CLAIM"
    assert claimed_key not in {f.key for f in tf.extract(tf.given_text(text))}


QUAD = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABCD"],
        "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 4, "y": 0}, {"id": "C", "x": 5, "y": 3}, {"id": "D", "x": 0.5, "y": 2.5}],
                     "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "D"}, {"a": "D", "b": "A"}]},
        "observed": {"num_points": 4, "point_labels": list("ABCD")}}


@pytest.mark.parametrize("claim", ["א. הוכיחו כי AB = CD.", "ב. הראו כי AB ∥ CD.", "ג. והסבירו מדוע AD מאונך ל-AB."])
def test_claims_do_not_distort_the_drawing(claim):
    r = de.process("c", json.dumps(QUAD), "במרובע ABCD.\n" + claim, None)
    assert r.spec.geometry.constraints == [], [c.type for c in r.spec.geometry.constraints]
    assert not r.missing_required


def test_given_in_subpart_still_enforced():
    r = de.process("c", json.dumps(QUAD), "במרובע ABCD.\nנתון כי AB = CD, והוכיחו כי AD ∥ BC.", None)
    types = [c.type for c in r.spec.geometry.constraints]
    assert types == ["equal_length"]                                 # the given only - not the claim


@pytest.mark.parametrize("text,expected", [
    ('אורכי מקצועות הבסיס של התיבה הם 60 ס"מ ו-30 ס"מ.', {"dimension(length,60)", "dimension(length,30)"}),
    ('אורכי צלעות המלבן הם 8 ס״מ ו-5 ס״מ.', {"dimension(length,8)", "dimension(length,5)"}),
    ('מידות האקווריום הן 50 ס"מ, 40 ס"מ ו-30 ס"מ.', {"dimension(length,50)", "dimension(width,40)", "dimension(height,30)"}),
    ('רדיוסי הגלילים הם 3 ס"מ ו-7 ס"מ.', {"dimension(radius,3)", "dimension(radius,7)"}),
    ('מידות התיבה: 12 ו-9 ו-4 ס"מ.', {"dimension(length,12)", "dimension(width,9)", "dimension(height,4)"}),
])
def test_plural_dimensions_lose_no_value(text, expected):
    got = {f.key for f in tf.extract(text) if f.fact_type == "dimension"}
    assert expected <= got, got


# ---------------------------------------------------------------- graph-CV: no false blocks on simple correct graphs
def _gspec(e):
    return {"diagram_type": "graph", "confidence": 0.95, "labels": [],
            "graph": {"axes": {"x_min": -5, "x_max": 5, "y_min": -6, "y_max": 6, "show_grid": False, "show_numbers": False},
                      "curves": [{"id": "f", "expression": e}]}, "observed": {"num_curves": 1}}


@pytest.mark.parametrize("expr", ["x", "x+1", "x^3", "exp(x)", "-x+2", "x^2-4", "ln(x)", "sin(x)", "1/(x-1)+1", "2^x", "x^3-3x", "-exp(-x)"])
def test_graph_cv_never_blocks_a_correct_simple_graph(expr):
    src = de.render_spec(de.process("s", json.dumps(_gspec(expr)), "", None).spec)[1]
    r = de.process("g", json.dumps(_gspec(expr)), "", src)
    assert not any("VISUAL_GRAPH_CONFLICT" in c for c in r.contradictions), (expr, r.audit.get("graph_cv"))


def test_exp_horizontal_asymptote_from_symbolic_limit():
    from diagram_engine.graph.graph_cv import symbolic_horizontal_asymptotes
    from diagram_engine.schemas import DiagramSpec
    s = DiagramSpec.model_validate(_gspec("exp(x)"))
    assert symbolic_horizontal_asymptotes(s) == [0.0]


# ---------------------------------------------------------------- bar charts: any style, negative values
def _bars(values, face, cats=("A", "B", "C", "D")):
    from matplotlib.ticker import MultipleLocator

    from diagram_engine.render_base import export, new_figure
    fig, ax = new_figure(5, 4)
    ax.bar(list(cats[:len(values)]), values, color=face, edgecolor="#000000", linewidth=1.5)
    ax.yaxis.set_major_locator(MultipleLocator(10))
    ax.spines[["top", "right"]].set_visible(False)
    if min(values) < 0:
        ax.axhline(0, color="#000", lw=1.2)
    return export(fig)[1]


needs_ocr = pytest.mark.skipif(not __import__("diagram_engine.ocr", fromlist=["available"]).available(), reason="no Tesseract")


@needs_ocr
@pytest.mark.parametrize("face", ["#000000", "#333333", "#dddddd", "#ffffff", "#3a7bd5", "#999999"])
@pytest.mark.parametrize("values", [[30, 50, 20, 40], [12, 37, 25], [45, 5]])
def test_bar_cv_any_bar_style(face, values):
    from diagram_engine.charts import bar_cv
    d = bar_cv.detect(_bars(values, face))
    assert d["stable"], d["reason"]
    assert bar_cv.compare(values, d, 10) == []


@needs_ocr
@pytest.mark.parametrize("values", [[30, -20, 10], [-15, 25, -5, 10]])
def test_bar_cv_negative_values(values):
    from diagram_engine.charts import bar_cv
    d = bar_cv.detect(_bars(values, "#999999"))
    assert d["stable"], d["reason"]
    assert bar_cv.compare(values, d, 10) == []


def test_negative_values_policy_per_chart_kind():
    base = {"diagram_type": "chart", "confidence": 0.95, "labels": [], "observed": {}}
    ok = de.process("b", json.dumps({**base, "chart": {"kind": "bar", "categories": ["a", "b"], "values": [3, -2]}}), "", None)
    assert ok.validation.ok
    pie = de.process("b", json.dumps({**base, "chart": {"kind": "pie", "categories": ["a", "b"], "values": [3, -2]}}), "", None)
    assert not pie.validation.ok


# ---------------------------------------------------------------- OCR numbers bound to the exact entity (by location)
def _tri(ab, bc, pts=None, names="ABC"):
    a, b, c = names
    P = pts or {a: (0, 0), b: (8, 0), c: (8, 5)}
    return {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in names],
            "geometry": {"points": [{"id": k, "x": v[0], "y": v[1]} for k, v in P.items()],
                         "segments": [{"a": a, "b": b}, {"a": b, "b": c}, {"a": c, "b": a}],
                         "length_labels": [{"a": a, "b": b, "text": ab}, {"a": b, "b": c, "text": bc}]},
            "observed": {"num_points": 3, "point_labels": sorted(names), "num_segments": 3}}


@needs_ocr
@pytest.mark.parametrize("names,pts", [("ABC", None), ("PQR", {"P": (0, 0), "Q": (8, 0), "R": (8, 5)}),
                                       ("KLM", {"K": (0, 6), "L": (7, 0), "M": (0, 0)})])
def test_swapped_lengths_are_caught_by_location(names, pts):
    src = de.render_spec(de.process("s", json.dumps(_tri("5", "7", pts, names)), "", None).spec)[1]
    ok = de.process("g", json.dumps(_tri("5", "7", pts, names)), "", src)
    g = ok.audit["ocr_geometry_numbers"]
    assert not g["conflicts"], g
    bad = de.process("g", json.dumps(_tri("7", "5", pts, names)), "", src)
    gb = bad.audit["ocr_geometry_numbers"]
    if gb["binding"] == "affine":                    # labels readable -> the swap is detected by location
        assert any("LENGTH_VALUE_CONFLICT" in c for c in bad.contradictions), gb
    else:                                            # labels unreadable -> values are NOT bound, so never "confirmed"
        assert gb["binding"].startswith("unverified") and not gb["confirmed"], gb
    assert bad.decision.action != "high_confidence_preview" and not de.usable_in_document(bad)



@pytest.mark.parametrize("text", ["נסמן ב־S את שטח המשולש BDC.", "ונסמן ב-h את הגובה שיורד מקודקוד O במשולש BOD.",
                                  "נסמן: PQR הוא המשולש שקודקודיו אמצעי הצלעות."])
def test_definition_clause_is_not_a_drawn_given(text):
    assert tf.clauses(text)[0][0] == "DEFINITION"
    assert not [f for f in tf.extract(tf.given_text(text)) if f.fact_type == "segment"]


def test_line_wording_vs_drawn_segment_is_review_not_block():
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABC"],
            "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 4, "y": 1}, {"id": "C", "x": 2, "y": 3}],
                         "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}]},
            "observed": {"num_points": 3, "point_labels": list("ABC"), "num_segments": 3}}
    r = de.process("x", json.dumps(spec), "הישר AB עובר דרך C.", None)
    assert not any("extent" in c for c in r.comparison.critical)
    assert any("LINEAR_EXTENT_REVIEW" in c for c in r.contradictions) and r.decision.action != "high_confidence_preview"
