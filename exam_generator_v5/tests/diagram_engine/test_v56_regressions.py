"""V5.6 regression tests A–J + Hebrew parser + schema/prompt consistency."""
from __future__ import annotations

import copy
import typing

import numpy as np
import pytest
from helpers import de, geo, pts, run

from diagram_engine import constants, safe_math as sm, symbols, text_facts
from diagram_engine.decision import decide_v3
from diagram_engine.schemas import ComparisonResult, DiagramSpec, ValidationResult
from diagram_engine.verification import confidence

# ---------------------------------------------------------------- Hebrew parser V2 (real formulations)
HEB = [
    ("ABC הוא משולש שווה צלעות", ["equilateral(A,B,C)"]),
    ("ABC הוא משולש שווה-צלעות", ["equilateral(A,B,C)"]),
    ("המשולש ABC שווה צלעות", ["equilateral(A,B,C)"]),
    ("AC = BC", ["equal_length(A,C,B,C)"]),
    ("הנקודה D נמצאת על המשך BC", ["point_order(B,C,D)", "collinear(B,C,D)"]),
    ("המשך BC חותך את ציר x בנקודה D", ["point_order(B,C,D)", "on_x_axis(D)"]),
    ("AD חותך את המעגל בנקודה E", ["point_on_line(E,A,D)", "on_circle(E)"]),
    ("AB מקבילה לציר y", ["parallel_to_y_axis(A,B)"]),
    ("AB מקבילה לציר x", ["parallel_to_x_axis(A,B)"]),
    ("AB מאונכת לציר x", ["parallel_to_y_axis(A,B)"]),
    ("AB מאונכת לציר y", ["parallel_to_x_axis(A,B)"]),
    ("נתון כי AD מאונך ל-BC", ["perpendicular(A,D,B,C)"]),
    ("AB מקביל ל-CD", ["parallel(A,B,C,D)"]),
    ("CB הוא קוטר במעגל", ["diameter(B,C)"]),
    ("דרך C העבירו משיק למעגל", ["tangent(C)"]),
    ("CF משיק למעגל בנקודה C", ["tangent(C,F)"]),
    ("F היא אמצע הקטע BC", ["midpoint(F,B,C)"]),
    ("הנקודה E נמצאת על האלכסון A'C'", ["point_on_segment(E,A',C')"]),
    ("A'E = 3/4 A'C'", ["ratio_on_segment(E,A',C')"]),
    ("A,B,C,E נמצאות על אותו מעגל", ["concyclic(A,B,C,E)", "on_circle(E)"]),
    ("הנקודות A,E,D נמצאות על ישר אחד", ["collinear(A,D,E)"]),
    ("הנקודות B,C,D נמצאות על ישר אחד", ["collinear(B,C,D)"]),
    ("$AB \\parallel CD$ ו-$AD \\perp BC$", ["parallel(A,B,C,D)", "perpendicular(A,D,B,C)"]),
    ("המשך הקטע MA חותך את ציר ה-y בנקודה B", ["point_order(B,A,M)", "on_y_axis(B)"]),   # canonical form of M-A-B
]


@pytest.mark.parametrize("text,expected", HEB)
def test_hebrew_parser_v2(text, expected):
    keys = {f.key for f in text_facts.extract(text)}
    for e in expected:
        assert e in keys, (text, e, keys)


def test_hebrew_ratio_value_and_dimension_semantics():
    r = next(f for f in text_facts.extract("A'E = 3/4 A'C'") if f.fact_type == "ratio_on_segment")
    assert r.value == pytest.approx(0.75)
    d = next(f for f in text_facts.extract('רדיוס הבסיס של הגליל הוא 6 ס"מ') if f.fact_type == "dimension")
    assert {k: d.value[k] for k in ("dimension_type", "value", "unit")} == {"dimension_type": "radius", "value": 6.0, "unit": 'ס"מ'}
    assert d.value["entity_kind"] == "cylinder"
    d2 = next(f for f in text_facts.extract('קוטר הבסיס 12 ס"מ') if f.fact_type == "dimension")
    assert d2.value["dimension_type"] == "diameter"


def test_points_mentioned_are_required():
    keys = {f.key for f in text_facts.extract("הנקודה E נמצאת על הקטע BO") if f.required}
    assert {"point(E)", "point(B)", "point(O)"} <= keys


# ---------------------------------------------------------------- TEST A: correlated omission (prompt scenario A,B,C,D,E)
CIRCLE_TEXT = ("ABC הוא משולש שווה צלעות. הנקודה D נמצאת על המשך BC. AD חותך את המעגל בנקודה E. "
               "הנקודות A,B,C,E נמצאות על אותו מעגל.")


def circle_spec(with_e=True):
    pts_ = {"A": (0, 3.3), "B": (-1.9, 0), "C": (1.9, 0), "D": (5, 0)}
    segs = ["AB", "AC", "BD", "AD"]
    through = ["A", "B", "C"]
    if with_e:
        pts_["E"] = (2.0, 1.4)
        through.append("E")
    s = geo(pts_, segs=segs, extra={"circles": [{"id": "c1", "through_points": through}]})
    s["observed"] = {"num_points": len(pts_), "point_labels": sorted(pts_)}      # the AI's own (possibly wrong) observation
    return s


def test_A_circle_with_E_all_required_facts_hold():
    r = run(circle_spec(True), CIRCLE_TEXT)
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    P = pts(r)
    O = P["__c_c1"]
    assert all(abs(np.hypot(*(P[k] - O)) - np.hypot(*(P["A"] - O))) < 1e-6 for k in "BCE")
    assert r.decision.action in ("review", "high_confidence_preview")


def test_A_E_missing_in_spec_and_observed_is_blocked():
    r = run(circle_spec(False), CIRCLE_TEXT)
    assert "missing_required_point_E" in r.missing_required
    assert r.decision.action == "original" and not de.usable_in_document(r) and not de.approve(r)


# ---------------------------------------------------------------- TEST B
def test_B_parallel_y_axis_extracted_enforced_and_contradiction_logged():
    s = geo({"A": (0, 0), "B": (4, 0.3), "C": (2, 3)})                       # the AI drew AB horizontal
    r = run(s, "הקטע AB מקביל לציר y")
    P = pts(r)
    assert abs(P["A"][0] - P["B"][0]) < 1e-6                                 # the text wins
    assert r.contradictions and r.confidence["semantic_confidence"] < 1.0
    assert r.decision.action != "high_confidence_preview"


# ---------------------------------------------------------------- TEST C / D
def test_C_R_positive_parameter_semicircle():
    with sm.symbol_context(symbols.extract("R הוא פרמטר חיובי"), {"R": 2}):
        e = sm.parse_expression("sqrt(R^2-x^2)")
        sc = sm.semicircle(e)
        assert sc["shape"] == "upper_semicircle" and str(sc["radius"]) == "R"
        assert str(sm.domain(e)) == "Interval(-R, R)"
    r = run({"diagram_type": "graph", "confidence": 0.95, "labels": [],
             "graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -1, "y_max": 3, "show_numbers": False},
                       "curves": [{"id": "f", "expression": "sqrt(R^2-x^2)"}]}, "observed": {"num_curves": 1}},
            "נתונה הפונקצייה $f(x)=\\sqrt{R^2-x^2}$, R הוא פרמטר חיובי.")
    assert r.validation.ok and r.spec.symbols["R"]["positive"] and r.spec.graph.curves[0].source == "text"


def test_C_undeclared_parameter_is_not_guessed():
    r = run({"diagram_type": "graph", "confidence": 0.95,
             "graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -1, "y_max": 3}, "curves": [{"id": "f", "expression": "sqrt(R^2-x^2)"}]}}, "")
    assert not r.validation.ok and r.decision.action == "original"


def test_D_a_positive_parameter():
    with sm.symbol_context(symbols.extract("a הוא פרמטר חיובי"), {"a": 2}):
        e = sm.parse_expression("a*x^2-4")
        assert sm.to_numpy(e)(np.array([1.0]))[0] == pytest.approx(-2)


# ---------------------------------------------------------------- TEST E: faint grid scatter
def test_E_faint_grid_scatter_ticks_fallback_or_safe():
    import io

    from PIL import Image, ImageDraw

    from diagram_engine.charts import scatter
    from diagram_engine.schemas import GraphAxes
    A = GraphAxes(x_min=0, x_max=30, y_min=0, y_max=60, x_step=5, y_step=10)

    def synth(grid, ticks):
        im = Image.new("RGB", (700, 460), "white")
        d = ImageDraw.Draw(im)
        if grid:
            for i in range(1, 7):
                d.line((60 + i * 100, 40, 60 + i * 100, 400), fill=(240,) * 3)
                d.line((60, 400 - i * 60, 660, 400 - i * 60), fill=(240,) * 3)
        d.line((60, 400, 680, 400), fill="black", width=2)
        d.line((60, 400, 60, 20), fill="black", width=2)
        if ticks:
            for i in range(1, 7):
                d.line((60 + i * 100, 401, 60 + i * 100, 407), fill="black", width=2)
                d.line((53, 400 - i * 60, 59, 400 - i * 60), fill="black", width=2)
        for x, y in [[5, 50], [15, 20], [25, 10]]:
            cx, cy = 60 + x * 20, 400 - y * 6
            d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill="black")
        b = io.BytesIO()
        im.save(b, format="PNG")
        return b.getvalue()

    r = scatter.detect(synth(True, True), A)
    assert r["stable"] and r["method"] == "ticks" and scatter.match([[5, 50], [15, 20], [25, 10]], r["points"], A) == []
    assert not scatter.detect(synth(False, False), A)["stable"]            # -> original


# ---------------------------------------------------------------- TEST F: vector box with A'C' and FE
BOX_TEXT = "בתיבה ABCDA'B'C'D' הנקודה F היא אמצע הקטע BC. הנקודה E נמצאת על האלכסון A'C' כך ש-A'E = 3/4 A'C'. הקטע FE."


def box_spec(construction=(("A'", "C'"), ("F", "E"))):
    from diagram_engine.schemas import Solid
    from diagram_engine.spatial.solids import box_vertices
    v = box_vertices(Solid(id="b", kind="cuboid", dims={"width": 4, "depth": 3, "height": 3}))
    return {"diagram_type": "spatial", "subtype": "vector_box", "confidence": 0.95, "labels": [],
            "spatial": {"solids": [{"id": "b", "kind": "cuboid", "vertices": v, "hidden_edges": [["A", "B"], ["A", "D"], ["A", "A'"]]}],
                        "points_on_edges": [{"id": "F", "a": "B", "b": "C", "ratio": 0.5}],
                        "points_on_diagonals": [{"id": "E", "a": "A'", "b": "C'", "ratio": 0.75}],
                        "construction_segments": [{"from": a, "to": b} for a, b in construction],
                        "vectors": [{"from": "A", "to": "B", "label": "u"}, {"from": "B", "to": "C", "label": "v"}, {"from": "A", "to": "A'", "label": "w"}]}}


def test_F_vector_box_draws_AC_diagonal_and_FE():
    r = run(box_spec(), BOX_TEXT)
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    assert ["segment", "A'", "C'"] in r.manifest["construction"] and ["segment", "F", "E"] in r.manifest["construction"]
    assert ["E", "A'", "C'", 0.75] in r.manifest["points_on_edges"]


@pytest.mark.parametrize("keep", [(("A'", "C'"),), (("F", "E"),)])
def test_F_missing_construction_segment_blocked(keep):
    r = run(box_spec(keep), BOX_TEXT)
    assert r.decision.action == "original" and r.comparison.critical


# ---------------------------------------------------------------- TEST G: radius never becomes diameter
AQ_TEXT = 'אקווריום בצורת תיבה שמידותיו 60 ס"מ, 30 ס"מ ו-40 ס"מ. בתוכו גליל. רדיוס הבסיס של הגליל הוא 6 ס"מ וגובהו 18 ס"מ.'


def aq_spec(measure="radius"):
    return {"diagram_type": "spatial", "subtype": "cylinder_in_box", "confidence": 0.95, "labels": [],
            "spatial": {"solids": [{"id": "box", "kind": "cuboid", "dims": {"width": 60, "depth": 30, "height": 40}},
                                   {"id": "cylinder_1", "kind": "cylinder", "dims": {"radius": 6, "height": 18}, "origin": [20, 10, 0]}],
                        "dimensions": [{"object": "cylinder_1", "dimension_type": measure, "value": 6, "unit": "cm", "text": '6 ס"מ'},
                                       {"object": "cylinder_1", "dimension_type": "height", "value": 18, "unit": "cm", "text": '18 ס"מ'}],
                        "relations": [{"type": "inside", "a": "cylinder_1", "b": "box"}]}}


def test_G_radius_stays_radius():
    r = run(aq_spec("radius"), AQ_TEXT)
    assert r.validation.ok and not r.comparison.critical
    d = r.spec.spatial.dimensions[0]
    assert (d.solid, d.measure, d.value, d.unit) == ("cylinder_1", "radius", 6, "cm")


def test_G_radius_as_diameter_is_critical():
    r = run(aq_spec("diameter"), AQ_TEXT)
    assert r.decision.action == "original" and any("רדיוס/קוטר" in c for c in r.comparison.critical)


# ---------------------------------------------------------------- TEST H: one diagram_type list everywhere
def test_H_diagram_type_consistency():
    import exam_core as core

    from diagram_engine import classifier, pipeline
    from diagram_engine.schemas import SUBTYPES, DiagramType
    schema_types = tuple(typing.get_args(DiagramType))
    assert schema_types == constants.DIAGRAM_TYPES
    enum = '"diagram_type": "' + "|".join(constants.DIAGRAM_TYPES) + '"'
    assert enum in core.DIAGRAM_SYSTEM_PROMPT                       # PASS-2 prompt
    assert '"diagram_type": "graph|geometry|chart|generic|unknown"' not in core.QUESTION_SYSTEM_PROMPT + core.DIAGRAM_SYSTEM_PROMPT
    from diagram_engine.ai_schema import AIDiagramSpec
    assert tuple(typing.get_args(AIDiagramSpec.model_fields["diagram_type"].annotation)) == constants.DIAGRAM_TYPES
    assert set(SUBTYPES) == set(constants.DIAGRAM_TYPES) - {"unknown"}
    for t in constants.DIAGRAM_TYPES:
        s = DiagramSpec(diagram_type=t)
        s.subtype = classifier.default_subtype(s) if t != "chart" else "bar_chart"
        if t == "unknown":
            with pytest.raises(ValueError):
                pipeline._renderer(s)
        else:
            assert callable(pipeline._renderer(s)), t
            assert s.subtype in SUBTYPES[t], t


# ---------------------------------------------------------------- TEST I: confidence bounded by coverage
def test_I_confidence_bounded_by_verification():
    c = confidence(0.99, 1.0, 1.0, 0.60)
    assert c["final_confidence"] == pytest.approx(0.60) and c["model_confidence"] == 0.99
    cmp = ComparisonResult(structure_match_score=1, topology_score=1, constraint_score=1, label_match_score=1, math_score=1,
                           layout_score=1, overall_score=1)
    d = decide_v3(ValidationResult(ok=True), cmp, c, {"verification_coverage": 0.6, "ai_only_fact_count": 3}, [])
    assert d.action == "review" and d.confidence == pytest.approx(0.60)
    hi = decide_v3(ValidationResult(ok=True), cmp, confidence(0.99, 1, 1, 1.0), {"verification_coverage": 1.0, "ai_only_fact_count": 0}, [])
    assert hi.action == "high_confidence_preview"


# ---------------------------------------------------------------- TEST J: unsupported critical feature -> original, never dropped
def test_J_unknown_feature_in_ai_json_is_not_silently_dropped():
    s = box_spec()
    s["spatial"]["construction_arcs"] = [{"center": "A", "from": "B", "to": "D"}]    # not representable
    r = run(s, BOX_TEXT)
    assert "spatial.construction_arcs" in r.spec.unsupported_features and r.decision.action == "original"


def test_J_ai_declared_unsupported_feature():
    s = geo({"A": (0, 0), "B": (4, 0), "C": (2, 3)})
    s["unsupported_features"] = ["shaded sector between arcs"]
    assert run(s).decision.action == "original"


def test_parser_version_changes_cache_key():
    from diagram_engine import cache
    assert constants.PARSER_VERSION.startswith("diagram-engine/3.") and cache.key("x") != __import__("hashlib").sha256(b"x").hexdigest()
