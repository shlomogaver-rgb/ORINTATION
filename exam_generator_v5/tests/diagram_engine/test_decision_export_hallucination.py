import pytest
from helpers import de, geo, run

from diagram_engine import comparison
from diagram_engine.decision import decide
from diagram_engine.schemas import ComparisonResult, DiagramSpec, ValidationResult

TRI = {"A": (0, 0), "B": (4, 0), "C": (2, 3)}


def _cmp(v=1.0, critical=()):
    return ComparisonResult(structure_match_score=v, topology_score=v, constraint_score=v, label_match_score=v, math_score=v,
                            layout_score=v, overall_score=v, critical=list(critical))


@pytest.mark.parametrize("conf,action", [(0.99, "high_confidence_preview"), (0.94, "high_confidence_preview"), (0.9, "review"),
                                         (0.85, "review"), (0.8, "draft"), (0.7, "draft"), (0.69, "original")])
def test_policy_thresholds(conf, action):
    assert decide(conf, 1.0, ValidationResult(ok=True), _cmp()).action == action


def test_critical_blocks_even_at_099():
    d = decide(0.99, 0.99, ValidationResult(ok=True), _cmp(0.99, ["missing point"]))
    assert d.action == "original"
    assert decide(0.99, 0.99, ValidationResult(ok=False, errors=["x"]), _cmp()).action == "original"


def test_export_gate_requires_teacher_valid_and_no_critical():
    r = run(geo(TRI))
    # v5.6: nothing about this triangle is independently verified (no text) -> teacher review, never high confidence
    assert r.decision.action == "review" and r.coverage["verification_coverage"] == 0 and not de.usable_in_document(r)
    assert de.approve(r) and de.usable_in_document(r)
    r.review.approved_by = ""                                   # approval not by a teacher
    assert not de.usable_in_document(r)
    r.review.approved_by = "teacher"
    r.comparison.critical.append("x")
    assert not de.usable_in_document(r)


def test_teacher_can_not_approve_blocked_reconstruction():
    r = run(geo(TRI, observed={"num_points": 4}))
    assert r.decision.action == "original" and not de.approve(r)


HALLUCINATIONS = {
    "extra point": {"points": ["A", "B", "C", "D"]}, "missing point": {"points": ["A", "B"]},
    "extra segment": {"segments": ["AB", "AC", "BC", "BD"]}, "missing segment": {"segments": ["AB", "AC"]},
    "extra circle": {"circles": 1}, "wrong label": {"labels": ["A", "B", "X"]}, "invented angle": {"angle_values": ["30"]},
    "invented parallel mark": {"parallel_mark_groups": 1}, "invented equal mark": {"equal_mark_groups": 1},
    "invented right angle": {"right_angle_marks": 1},
}


@pytest.mark.parametrize("name", list(HALLUCINATIONS))
def test_geometry_candidate_with_hallucination_blocked(name):
    spec = DiagramSpec.model_validate(geo(TRI))
    _, png, man = de.render_spec(spec)
    res = comparison.compare(spec, {**man, **HALLUCINATIONS[name]}, None, png)
    assert res.critical, name
    assert decide(0.99, 0.99, ValidationResult(ok=True), res).action == "original"


def _graph(**kw):
    g = {"axes": {"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5}, "curves": [{"id": "f", "expression": "1/(x-1)"}]}
    g.update(kw)
    return {"diagram_type": "graph", "confidence": 0.95, "graph": g, "labels": []}


@pytest.mark.parametrize("name,observed", [
    ("wrong asymptote", {"num_curves": 1, "vertical_asymptotes": [2.0]}),
    ("wrong branch count", {"num_curves": 1, "num_branches": 1}),
    ("different intercept", {"num_curves": 1, "y_intercept": 3}),
    ("wrong endpoint type", {"num_curves": 1, "open_endpoints": [[2, 1]]}),
])
def test_graph_hallucinations_blocked(name, observed):
    r = run({**_graph(), "observed": observed})
    assert r.comparison.critical and r.decision.action == "original", name


def test_invented_equation_label_blocked():
    spec = _graph()
    spec["graph"]["curves"][0]["label"] = "g(x)"
    spec["labels"] = [{"text": "f(x)", "confidence": 0.99}]
    assert any("אינן במקור" in c for c in run(spec).comparison.critical)


def test_render_lock_parallel_renders_identical():
    """Regression: parallel question workers rendered with shared matplotlib rcParams (race)."""
    from concurrent.futures import ThreadPoolExecutor

    from diagram_engine import cache
    specs = [DiagramSpec.model_validate(_graph(curves=[{"id": "f", "expression": f"x^2-{i}"}])) for i in range(6)]
    cache.RENDER.clear()
    with ThreadPoolExecutor(3) as ex:
        first = list(ex.map(lambda s: de.render_spec(s)[0], specs))
    cache.RENDER.clear()
    second = [de.render_spec(s)[0] for s in specs]
    assert first == second


def test_bidi_brackets_mirrored_regression():
    from diagram_engine.text_utils import visual
    assert visual("המחיר (בשקלים)") == "(םילקשב) ריחמה"
    assert "f(x)" in visual("גרף f(x) של")


def test_process_diagram_api_uses_edited_bytes_and_bbox():
    import io

    from PIL import Image, ImageDraw
    im = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(im).line((110, 20, 190, 80), fill="black", width=3)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    import json
    res = de.process_diagram(buf.getvalue(), "", bbox=[0, 500, 1000, 1000], question_id=3, raw_spec_json=json.dumps(geo(TRI)))
    with Image.open(io.BytesIO(res.source_image)) as s:
        assert s.size == (100, 100)
    assert res.preview_svg and res.preview_png and res.cleaned_image and res.record.figure_id == "q3f1"
    assert res.decision.action in ("high_confidence_preview", "review", "draft")
