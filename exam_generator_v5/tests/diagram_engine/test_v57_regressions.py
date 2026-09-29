"""V5.7 regression tests for every known bug in the spec (section 69) + security + OCR + solver."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from helpers import de, geo, pts, run
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "diagram_engine" / "acceptance" / "fixtures"

from diagram_engine import ocr, safe_math as sm, symbols, text_facts  # noqa: E402


# ---------------------------------------------------------------- math parsing
@pytest.mark.parametrize("expr,declared,expected", [
    ("2ax", {"a": {}}, "2*a*x"), ("3xy", {"y": {}}, "3*x*y"), ("ab", {"a": {}, "b": {}}, "a*b"),
    ("2abx", {"a": {}, "b": {}}, "2*a*b*x"), ("ax²", {"a": {}}, "a*x**2"), ("3R", {"R": {}}, "3*R"), ("2πr", {"r": {}}, "2*pi*r")])
def test_implicit_multiplication(expr, declared, expected):
    with sm.symbol_context(declared, {k: 2 for k in declared}):
        assert str(sm.parse_expression(expr)) == expected


def test_implicit_multiplication_never_guesses_undeclared():
    with pytest.raises(sm.ExpressionError):
        sm.parse_expression("2ax")


def test_symbol_table_categories():
    t = symbols.classify("נתונה הפונקצייה f(x)=ax²+2ax+3. a הוא פרמטר.", "ax^2+2ax+3")
    assert t["functions"] == ["f"] and t["independent_variables"] == ["x"] and t["parameters"] == ["a"] and t["units"] == []


def test_cuberoot_real():
    assert sm.safe_function("cuberoot(x)")(np.array([-8.0]))[0] == pytest.approx(-2)


# ---------------------------------------------------------------- Hebrew morphology, units, binding
def _dims(text):
    return {f.key: f.value for f in text_facts.extract(text) if f.fact_type == "dimension"}


@pytest.mark.parametrize("text,key", [
    ('אקווריום שאורכו 60 ס"מ', "dimension(length,60)"), ("אקווריום שאורכו 60 ס״מ", "dimension(length,60)"),
    ('רוחבו 30 ס"מ', "dimension(width,30)"), ('וגובהו 40 ס"מ', "dimension(height,40)"), ('הגליל שרדיוסו 6 ס״מ', "dimension(radius,6)"),
    ("קוטרו 12 מ״מ", "dimension(diameter,12)"), ('שטחו 20 סמ"ר', None), ("אורכו 8 מטרים", "dimension(length,8)")])
def test_hebrew_morphology_and_units(text, key):
    d = _dims(text)
    assert (key in d) if key else True, d


def test_dimension_binding_to_object():
    d = _dims('הגליל שרדיוסו 6 ס״מ')["dimension(radius,6)"]
    assert d["entity_kind"] == "cylinder" and d["unit"] == 'ס"מ'
    s = _dims("הקטע AB שאורכו 8 ס״מ")["dimension(length,8)"]
    assert s["entity"] == "AB" and s["entity_kind"] == "segment"


def test_dimension_bound_to_nearest_object_in_same_sentence():
    d = {f.key: f.value for f in text_facts.extract('גובה הקרטון הוא 24 ס"מ. רדיוס הבסיס של כל כוס הוא 3 ס"מ.') if f.fact_type == "dimension"}
    assert d["dimension(height,24)"]["entity_kind"] == "cuboid" and d["dimension(radius,3)"]["entity_kind"] == "cylinder"


def test_dimension_on_wrong_object_is_not_satisfied():
    spec = {"diagram_type": "spatial", "subtype": "cylinder_in_box", "confidence": 0.95, "labels": [],
            "spatial": {"solids": [{"id": "box", "kind": "cuboid", "dims": {"width": 6, "depth": 3, "height": 4}},
                                   {"id": "cyl", "kind": "cylinder", "dims": {"radius": 1, "height": 2}, "origin": [9, 0, 0]}],
                        "dimensions": [{"object": "box", "dimension_type": "width", "value": 6, "unit": "cm"}]}}
    r = run(spec, "הגליל שרדיוסו 6 ס״מ")          # the 6 is bound to the BOX in the proposal
    assert r.decision.action == "original"


def test_generic_dimension_without_target_is_invalid():
    g = {"diagram_type": "generic", "confidence": 0.9, "generic": {"width": 100, "height": 50,
         "shapes": [{"kind": "rect", "x": 5, "y": 5, "w": 20, "h": 20, "text": "a"}],
         "dimensions": [{"x1": 5, "y1": 30, "x2": 25, "y2": 30, "text": "8 מטרים"}]}}
    assert not run(g).validation.ok


# ---------------------------------------------------------------- semantic geometry
def _quad():
    return geo({"A": (0, 0), "B": (4.2, 0.3), "C": (4.0, 2.7), "D": (0.2, 3.1)}, segs=("AB", "BC", "CD", "DA"))


@pytest.mark.parametrize("text,check", [
    ("ABCD הוא מלבן", "rect"), ("הריבוע ABCD", "square"), ("ABCD מקבילית", "par"), ("המעוין ABCD", "rhombus")])
def test_semantic_quadrilaterals(text, check):
    r = run(_quad(), text)
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    P = pts(r)
    A, B, C, D = P["A"], P["B"], P["C"], P["D"]
    cross = lambda u, v: u[0] * v[1] - u[1] * v[0]  # noqa: E731
    assert abs(cross(B - A, C - D)) < 1e-6 and abs(cross(C - B, D - A)) < 1e-6
    if check in ("rect", "square"):
        assert abs(float((B - A) @ (C - B))) < 1e-6
    if check in ("square", "rhombus"):
        assert np.hypot(*(B - A)) == pytest.approx(np.hypot(*(C - B)))


def test_isosceles_without_legs_requires_review_not_guess():
    r = run(geo({"A": (0, 0), "B": (4, 0), "C": (2, 3)}), "ABC משולש שווה שוקיים")
    assert r.spec.geometry.constraints == [] or all(c.type != "equal_length" for c in r.spec.geometry.constraints)
    assert r.decision.action != "high_confidence_preview" and r.coverage["ambiguous_fact_count"] >= 1


def test_inscribed_triangle():
    s = geo({"A": (0, 2.1), "B": (-1.8, -1), "C": (1.9, -1.1)}, extra={"circles": [{"id": "c1", "through_points": ["A", "B", "C"]}]})
    r = run(s, "המשולש ABC חסום במעגל")
    assert r.validation.ok and not r.comparison.critical


def test_tangent_meets_x_axis_at_F():
    s = geo({"O": (0, 2), "C": (1.5, 3.3), "F": (4.5, 0.2)}, segs=("OC", "CF"),
            extra={"circles": [{"id": "c1", "center": "O", "through": "C"}], "coordinate_axes": True})
    r = run(s, "דרך C העבירו משיק החותך את ציר x בנקודה F")
    assert r.validation.ok and not r.comparison.critical, (r.validation.errors, r.comparison.critical)
    P = pts(r)
    assert abs(P["F"][1]) < 1e-6 and abs(float((P["C"] - P["O"]) @ (P["F"] - P["C"]))) < 1e-6


def test_section_only_FE_is_required():
    """V5.7.2 semantics: FE given DECLARATIVELY in a subpart is reconstruction-critical (blocks when missing);
    FE mentioned only in a REQUEST ('הבע ... את FE') is for the solution and does not block."""
    sys.path.insert(0, str(Path(__file__).parent))
    from test_v56_regressions import box_spec
    from diagram_engine.text_facts import split_by_role
    stem = "בתיבה ABCDA'B'C'D' הנקודה F היא אמצע הקטע BC. הנקודה E נמצאת על האלכסון A'C' כך ש-A'E = 3/4 A'C'."
    declarative = ["מעבירים את הקטע FE.", "הבע באמצעות u,v,w את A'E."]
    recon, _ = split_by_role(declarative)
    full = stem + "\n" + " ".join(declarative)
    rec = de.process("f", json.dumps(box_spec(((("A'", "C'"),)))), full, None, required_text=stem + " " + recon)
    assert rec.decision.action == "original" and any("segment(E,F)" in c for c in rec.comparison.critical)
    request_only = ["הבע באמצעות u,v,w את A'E ואת FE."]
    recon2, _ = split_by_role(request_only)
    rec2 = de.process("f", json.dumps(box_spec(((("A'", "C'"),)))), stem + "\n" + request_only[0], None,
                      required_text=stem + " " + recon2)
    assert not any("segment(E,F)" in c for c in rec2.comparison.critical)


# ---------------------------------------------------------------- solver
def test_solver_timeout_requires_review():
    from diagram_engine.geometry.solver import solve
    from diagram_engine.schemas import GeometrySpec
    g = GeometrySpec.model_validate(geo({"A": (0, 0), "B": (4, 0.3), "C": (2, 3)},
                                        extra={"constraints": [{"type": "right_angle", "points": ["A", "C", "B"], "source": "text"}]})["geometry"])
    r = solve(g, timeout_s=0.0)
    assert not r["ok"] and r["code"] == "SOLVER_TIMEOUT"


def test_solver_residual_failure_code():
    from diagram_engine.geometry.solver import solve
    from diagram_engine.schemas import GeometrySpec
    g = GeometrySpec.model_validate(geo({"A": (0, 0), "B": (4, 0), "C": (2, 3)},
                                        extra={"constraints": [{"type": "angle_value", "points": ["A", "C", "B"], "value": 60, "source": "text"},
                                                               {"type": "angle_value", "points": ["A", "C", "B"], "value": 80, "source": "text"}]})["geometry"])
    r = solve(g)
    assert not r["ok"] and r["code"] == "SOLVER_CONVERGENCE_ERROR"


def test_hybrid_solver_computes_constructions_directly():
    from diagram_engine.geometry.solver import solve
    from diagram_engine.schemas import GeometrySpec
    g = GeometrySpec.model_validate(geo({"A": (0, 0), "B": (4, 0.3), "C": (2, 3), "M": (2.4, 0.4)}, segs=("AB", "CM"),
                                        extra={"constraints": [{"type": "midpoint", "points": ["M", "A", "B"], "source": "text"}]})["geometry"])
    r = solve(g)
    assert r["ok"] and r["derived"] == ["M"] and r["variables"] == 3


# ---------------------------------------------------------------- scatter: the real scan, degraded like a phone photo
@pytest.mark.parametrize("degrade", ["blur", "jpeg", "noise", "rotate1"])
def test_real_scatter_scan_degraded_is_exact_or_safely_unstable(degrade):
    from diagram_engine.charts import scatter
    from diagram_engine.schemas import GraphAxes
    im = Image.open(FIX / "q16_p3_2.png").convert("RGB")
    if degrade == "blur":
        im = im.filter(ImageFilter.GaussianBlur(1.2))
    elif degrade == "noise":
        a = np.asarray(im).astype(int) + np.random.default_rng(0).integers(-25, 25, np.asarray(im).shape)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    elif degrade == "rotate1":
        im = im.rotate(1.0, fillcolor="white", resample=Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, format="JPEG" if degrade == "jpeg" else "PNG", quality=45)
    A = GraphAxes(x_min=0, x_max=30, y_min=0, y_max=60, x_step=5, y_step=10)
    r = scatter.detect(buf.getvalue(), A)
    truth = [[5, 50], [10, 40], [15, 30], [15, 20], [20, 30], [25, 10]]
    if r["stable"]:
        assert scatter.match(truth, r["points"], A) == [], (degrade, r["points"])       # never a WRONG point set
    # unstable -> the engine blocks (teacher decides); both are safe outcomes


# ---------------------------------------------------------------- independent OCR on the real images
needs_ocr = pytest.mark.skipif(not ocr.available(), reason="Tesseract not installed")


@needs_ocr
def test_ocr_reads_real_table_numbers():
    r = ocr.table_cells((FIX / "q18_p12_4.png").read_bytes())
    nums = [[c["numeric"] or c["text"] for c in row[1:]] for row in r["rows"][1:]]
    assert r["ok"] and nums == [["60", "150", "180", "210"], ["5", "21", "9", "10"]]


@needs_ocr
def test_ocr_conflict_message_is_explicit_hebrew():
    from test_v56_regressions import HEB  # noqa: F401  (import check only)
    sys.path.insert(0, str(ROOT / "tests" / "diagram_engine" / "acceptance"))
    from cases import CASES
    s = json.loads(json.dumps(CASES["A07_table_haircuts"]["spec"]))
    s["table"]["rows"][2][2]["text"] = "12"
    s["observed"]["table_cells"][2][2] = "12"
    r = de.process("t", json.dumps(s, ensure_ascii=False), "", (FIX / "q18_p12_4.png").read_bytes())
    assert r.decision.action == "original"
    assert any("OCR זיהה 21 וניתוח התמונה זיהה 12" in c for c in r.contradictions)


def test_ocr_unavailable_fails_closed(monkeypatch):
    from diagram_engine.ocr import engine
    monkeypatch.setattr(engine, "available", lambda: False)
    from diagram_engine.ocr import verify
    res = verify.run(de.DiagramSpec(diagram_type="table"), b"x", "")
    assert res["facts"] == [] and not res["available"]


# ---------------------------------------------------------------- schema / structured output failure
def test_schema_validation_failed_code():
    r = de.process("f", '{"diagram_type": "geometry", "geometry": {"points": [{"id": "A"}]}}', "", None)
    assert r.decision.action == "original" and r.audit.get("error_code") == "SCHEMA_VALIDATION_FAILED"


# ---------------------------------------------------------------- RTL in SVG: labels are baked as vector paths
def test_svg_labels_are_vector_paths_not_text():
    s = {"diagram_type": "chart", "confidence": 0.9, "chart": {"kind": "bar", "title": "מספר תלמידים (בשקלים)",
                                                               "categories": ["ראשון", "שני"], "values": [3, 4]}}
    r = run(s)
    svg, _, _ = de.render_spec(r.spec)
    assert "<text" not in svg and "<script" not in svg.lower() and "<foreignObject" not in svg


# ---------------------------------------------------------------- security of uploads
def test_upload_rejects_malformed_and_oversized():
    import exam_core as core
    with pytest.raises(core.ImageInputError):
        core.image_to_png_bytes(b"not an image")
    with pytest.raises(core.ImageInputError):
        core.image_to_png_bytes(b"0" * (core.MAX_UPLOAD_BYTES + 1))
    big = Image.new("1", (9000, 9000))
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    with pytest.raises(core.ImageInputError):
        core.image_to_png_bytes(buf.getvalue())


def test_retry_has_total_time_limit():
    import exam_core as core
    svc = core.GeminiService("k", client=object(), max_total_time=0.0, sleep=lambda s: None)
    with pytest.raises(core.GeminiError):
        svc.generate([], core.QuestionAI, "sys")


# ---------------------------------------------------------------- session workspace
def test_workspace_store_get_invalidate_cleanup_and_traversal(tmp_path):
    sys.path.insert(0, str(ROOT))
    from workspace import SessionWorkspaceManager, cleanup_stale
    a, b = SessionWorkspaceManager("s1", root=tmp_path), SessionWorkspaceManager("s2", root=tmp_path)
    pa = a.store("exam.docx", b"A")
    b.store("exam.docx", b"B")
    assert a.get("exam.docx") == b"A" and b.get("exam.docx") == b"B"          # no collision between sessions
    a.store("../../etc/passwd", b"x")                                           # flattened, stays inside the workspace
    assert all(Path(p).parent == a.root for p in [pa]) and not (tmp_path.parent / "etc").exists()
    a.store("pdf_1", b"1")
    a.invalidate("pdf_")
    assert not a.has("pdf_1") and a.has("exam.docx")
    a.cleanup()
    assert not a.root.exists() and b.get("exam.docx") == b"B"
    import os
    import time
    os.utime(b.root, (time.time() - 10 ** 6, time.time() - 10 ** 6))
    assert cleanup_stale(1, root=tmp_path) == 0                                 # active sessions are never removed
    b.cleanup()
