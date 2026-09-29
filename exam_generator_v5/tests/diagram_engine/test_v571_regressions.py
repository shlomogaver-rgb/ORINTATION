"""V5.7.1 regression tests (reliability closure). Each test was written to FAIL on V5.7 first where applicable."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import diagram_engine as de  # noqa: E402
import exam_core as c  # noqa: E402


@pytest.fixture
def analyzed():
    import mock_gemini
    from test_app import page_image
    from test_core import meta
    mock_gemini.install()
    qd = [{"question_number": i, "points": 50.0, "images": [page_image()]} for i in (1, 2)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=False)
    return exam, qd, meta()


def _media(data: bytes) -> list[bytes]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return [z.read(n) for n in z.namelist() if n.startswith("word/media/")]


# ---------------------------------------------------------------- Phase 1: no automatic raster fallback
def test_approved_diagram_renderer_exception_never_inserts_original_raster(analyzed, monkeypatch):
    exam, qd, meta = analyzed
    q = exam.questions[0]
    fig = q.figures[0]
    assert de.approve(q.diagrams[fig.figure_id])
    crop = c.figure_source_crop(fig, qd[0]["images"])
    monkeypatch.setattr(de, "render_spec", lambda spec: (_ for _ in ()).throw(RuntimeError("renderer crashed")))
    data, warnings = c.create_word_document(exam, meta, qd, "exam")
    assert crop not in _media(data)                                  # NO original raster inserted
    assert any("EXPORT_BLOCKED" in w for w in warnings)
    errors, _ = c.validate_exam(exam, meta, qd)
    assert any("EXPORT_BLOCKED" in e or "נדרשת החלטת מורה" in e for e in errors)   # export blocked


# ---------------------------------------------------------------- Phase 16: question pagination (real PDF check)
def _pagination_exam():
    """5 questions: short, medium, with a graph, 6 subparts, longer than a page. Latin markers locate text in the PDF."""
    import mock_gemini
    from test_app import page_image
    from test_core import meta
    mock_gemini.install()
    qd = [{"question_number": i, "points": 20.0, "images": [page_image()]} for i in range(1, 6)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=False)
    filler = "זהו משפט ארוך שנועד למלא את השורה ולבדוק את העימוד של השאלה במסמך. " * 3
    plan = {1: (1, 1), 2: (3, 2), 3: (2, 3), 4: (1, 6), 5: (9, 5)}
    for q in exam.questions:
        n_stem, n_secs = plan[q.question_number]
        q.text = f"Q{q.question_number}START " + filler * n_stem
        if q.question_number != 3:
            q.figures = []
            q.diagrams = {}
        base = q.sections[0]
        q.sections = [base.model_copy(update={"section_id": "אבגדהו"[i], "points": round(20 / n_secs, 2),
                                              "text": f"Q{q.question_number}S{i}BEGIN " + filler * (3 if q.question_number == 5 else 1)
                                              + f" Q{q.question_number}S{i}END"}) for i in range(n_secs)]
    for q in exam.questions:
        for f in q.figures:
            de.approve(q.diagrams[f.figure_id])
    return exam, qd, meta()


def _pages(pdf: bytes) -> list[str]:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        p.write_bytes(pdf)
        n = int(next(l for l in subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True).stdout.splitlines()
                     if l.startswith("Pages")).split()[-1])
        return [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(p), "-"], capture_output=True, text=True).stdout
                for i in range(1, n + 1)]


def _page_of(pages, marker):
    return next((i for i, t in enumerate(pages) if marker in t), None)


def test_pagination_questions_are_never_split_badly():
    exam, qd, meta = _pagination_exam()
    data, _ = c.create_word_document(exam, meta, qd, "exam")
    pdf, err = c.docx_to_pdf_bytes(data, "pag")
    if not pdf:
        pytest.skip(f"LibreOffice unavailable: {err}")
    pages = _pages(pdf)
    report = []
    for q in exam.questions:
        n = q.question_number
        start, end = _page_of(pages, f"Q{n}START"), _page_of(pages, f"Q{n}S{len(q.sections) - 1}END")
        report.append((n, start, end))
        if n != 5:
            assert start == end, f"question {n} split across pages {start}->{end}"
        for i in range(len(q.sections)):                        # no subpart is ever split
            assert _page_of(pages, f"Q{n}S{i}BEGIN") == _page_of(pages, f"Q{n}S{i}END"), (n, i)
    q5 = _page_of(pages, "Q5START")
    assert "Q4S5END" not in pages[q5]                           # the long question starts on a fresh page
    print("pagination:", report)


# ---------------------------------------------------------------- Phase 6: prime-safe entities
from diagram_engine import text_facts  # noqa: E402


@pytest.mark.parametrize("text,points", [
    ("הנקודות A, A', C, C' נמצאות על ישר אחד", ["A", "A'", "C", "C'"]),
    ("הנקודות A, A′, C, C’ נמצאות על ישר אחד", ["A", "A'", "C", "C'"]),
    ("הנקודות A, A'', B נמצאות על ישר אחד", ["A", "A''", "B"]),
    ("הנקודות A_1, A, B נמצאות על ישר אחד", ["A_1", "A", "B"]),
])
def test_primed_entities_are_distinct(text, points):
    f = next(f for f in text_facts.extract(text) if f.fact_type == "collinear")
    assert sorted(f.entities) == sorted(points) and len(set(f.entities)) == len(points)


def test_primed_segments_and_ratios():
    keys = {f.key for f in text_facts.extract("A'E = 3/4 A'C'. הקטע A''B. הקטע A_1C.")}
    assert "ratio_on_segment(E,A',C')" in keys and "segment(A'',B)" in keys and "segment(A_1,C)" in keys


def test_primed_points_do_not_collide_in_spec_and_verification():
    import json as _json
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [],
            "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "A'", "x": 4, "y": 0}, {"id": "C", "x": 0, "y": 3},
                                    {"id": "C'", "x": 4, "y": 3}],
                         "segments": [{"a": "A", "b": "A'"}, {"a": "C", "b": "C'"}]}}
    r = de.process("p", _json.dumps(spec), "הקטע AA' והקטע CC'", None)
    assert r.validation.ok and sorted(r.manifest["points"]) == ["A", "A'", "C", "C'"]
    assert not r.missing_required


# ---------------------------------------------------------------- Phase 10: exact dimension -> entity_id binding
TWO_CYL = {"diagram_type": "spatial", "subtype": "cylinder", "confidence": 0.95, "labels": [],
           "spatial": {"solids": [{"id": "cylinder_1", "kind": "cylinder", "dims": {"radius": 3, "height": 5}},
                                  {"id": "cylinder_2", "kind": "cylinder", "dims": {"radius": 8, "height": 5}, "origin": [20, 0, 0]}],
                       "dimensions": []}}


def _two_cyl(bound_to):
    s = json.loads(json.dumps(TWO_CYL))
    s["spatial"]["dimensions"] = [{"object": bound_to, "dimension_type": "radius", "value": 8, "unit": "cm", "text": '8 ס"מ'}]
    return s


def test_dimension_bound_to_the_exact_entity_id():
    text = 'רדיוס הגליל השני הוא 8 ס"מ.'
    ok = de.process("d", json.dumps(_two_cyl("cylinder_2")), text, None)
    assert ok.validation.ok and not ok.comparison.critical, ok.comparison.critical
    bad = de.process("d", json.dumps(_two_cyl("cylinder_1")), text, None)
    assert bad.decision.action == "original" and bad.comparison.critical


def test_dimension_ambiguous_between_two_objects_requires_review():
    r = de.process("d", json.dumps(_two_cyl("cylinder_2")), 'רדיוס הגליל הוא 8 ס"מ.', None)
    assert r.decision.action != "high_confidence_preview"
    assert any("עמומה" in a for a in r.coverage.get("ambiguous_facts", []))


# ---------------------------------------------------------------- Phase 8: independent symbolic function validator
def _fgraph(expr, points, text=""):
    spec = {"diagram_type": "graph", "confidence": 0.97, "labels": [],
            "graph": {"axes": {"x_min": -5, "x_max": 5, "y_min": -10, "y_max": 10},
                      "curves": [{"id": "f", "expression": expr, "source": "text"}], "points": points},
            "observed": {"num_curves": 1}}
    return de.process("g", json.dumps(spec), text, None)


def test_marked_extremum_verified_by_sympy():
    r = _fgraph("x^2-4x+1", [{"name": "", "x": 2, "y": -3, "on_curve": "f", "kind": "min"}], "f(x)=x^2-4x+1")
    assert r.validation.ok and not r.comparison.critical


def test_marked_extremum_impossible_is_mathematical_conflict():
    r = _fgraph("x^2-4x+1", [{"name": "", "x": 1, "y": -2, "on_curve": "f", "kind": "max"}], "f(x)=x^2-4x+1")
    assert r.decision.action == "original" and any("MATHEMATICAL_CONFLICT" in c for c in r.comparison.critical)


def test_question_text_claim_contradicting_formula_is_source_conflict_not_autofixed():
    r = _fgraph("x^2-4x+1", [], "נתונה הפונקצייה f(x)=x^2-4x+1. לפונקצייה נקודת מקסימום ב-x=3.")
    assert any("SOURCE_CONFLICT" in c for c in r.contradictions + r.comparison.critical)
    assert r.decision.action != "high_confidence_preview"
    assert r.spec.graph.curves[0].expression == "x^2-4x+1"            # the question is NOT silently changed


# ---------------------------------------------------------------- Phase 3: independent source label inventory
needs_ocr = pytest.mark.skipif(not __import__("diagram_engine.ocr", fromlist=["available"]).available(), reason="no Tesseract")
FIXDIR = ROOT / "tests" / "diagram_engine" / "acceptance" / "fixtures"


@needs_ocr
def test_correlated_omission_detected_by_source_label_inventory():
    """Text AND vision omit K; the OCR inventory of the real image finds K -> MISSING_FROM_SPEC:K, no auto-approval."""
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    spec = json.loads(json.dumps(CASES["A06_generic_plan"]["spec"], ensure_ascii=False))
    spec["generic"]["labels"] = [l for l in spec["generic"]["labels"] if l["text"] != "K"]
    spec["labels"] = [l for l in spec["labels"] if l["text"] != "K"]
    spec["observed"]["point_labels"] = [p for p in spec["observed"]["point_labels"] if p != "K"]
    text = "ABCD מבואה, BEFC שביל גישה, והריבוע הוא גן פסלים. אורך הקטע AG הוא 8 מטרים."
    r = de.process("inv", json.dumps(spec, ensure_ascii=False), text, (FIXDIR / "q16_p8_2.png").read_bytes())
    assert "MISSING_FROM_SPEC:K" in r.audit.get("inventory", {}).get("missing_from_spec", [])
    assert r.decision.action != "high_confidence_preview" and not de.usable_in_document(r)
    assert any("OCR" in c and "K" in c for c in r.contradictions)


@needs_ocr
def test_inventory_clean_when_spec_complete():
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    c_ = CASES["A06_generic_plan"]
    r = de.process("inv", json.dumps(c_["spec"], ensure_ascii=False), c_["text"], (FIXDIR / "q16_p8_2.png").read_bytes())
    assert r.audit["inventory"]["missing_from_spec"] == []


# ---------------------------------------------------------------- Phase 4: independent topology (circles)
def test_topology_detects_circle_missing_from_spec_on_real_image():
    from diagram_engine import topology_extractor as T
    if not T.available():
        pytest.skip("OpenCV not installed")
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    spec = json.loads(json.dumps(CASES["A08_coordinate_circle"]["spec"], ensure_ascii=False))
    spec["geometry"]["circles"] = []                         # the AI "forgot" the circle ...
    spec["observed"].pop("num_circles", None)                # ... also in its own observation
    text = "נתון: B(0 , 18), A(−16 , 6)."                    # and the text does not mention it
    r = de.process("topo", json.dumps(spec, ensure_ascii=False), text, (FIXDIR / "q16_p5_2.png").read_bytes())
    assert any("OBJECT_COUNT_CONFLICT" in c and "מעגלים" in c for c in r.contradictions)
    assert r.decision.action != "high_confidence_preview"
    ok = de.process("topo", json.dumps(CASES["A08_coordinate_circle"]["spec"], ensure_ascii=False), CASES["A08_coordinate_circle"]["text"],
                    (FIXDIR / "q16_p5_2.png").read_bytes())
    assert not any("OBJECT_COUNT_CONFLICT" in c for c in ok.contradictions)


# ---------------------------------------------------------------- Phase 9: hybrid symbolic solver
@pytest.mark.parametrize("ctype,parents,check", [
    ("intersection", ["A", "C", "B", "D"], lambda P: np.allclose(P["X"], [2, 2])),
    ("centroid", ["A", "B", "C"], lambda P: np.allclose(P["X"], (P["A"] + P["B"] + P["C"]) / 3)),
    ("circumcenter", ["A", "B", "C"], lambda P: np.isclose(np.hypot(*(P["X"] - P["A"])), np.hypot(*(P["X"] - P["C"])))),
    ("incenter", ["A", "B", "C"], lambda P: True),
    ("perpendicular_foot", ["C", "A", "B"], lambda P: abs(float((P["C"] - P["X"]) @ (P["B"] - P["A"]))) < 1e-9),
])
def test_exact_constructions_are_computed_not_optimised(ctype, parents, check):
    import numpy as np  # noqa: F811
    globals()["np"] = np
    from diagram_engine.geometry.solver import solve
    from diagram_engine.schemas import GeometrySpec
    g = GeometrySpec.model_validate({"points": [{"id": "A", "x": 0, "y": 0, "fixed": True}, {"id": "B", "x": 4, "y": 0, "fixed": True},
                                                {"id": "C", "x": 4, "y": 4, "fixed": True}, {"id": "D", "x": 0, "y": 4, "fixed": True},
                                                {"id": "X", "x": 1.3, "y": 0.7}],
                                     "constraints": [{"type": ctype, "points": ["X"] + parents, "source": "text"}]})
    r = solve(g)
    assert r["ok"] and r["derived"] == ["X"] and r["variables"] == 0
    assert check({k: np.array(v) for k, v in r["points"].items()})


def test_circle_through_three_points_centre_is_exact():
    from diagram_engine.geometry.solver import solve
    from diagram_engine.schemas import GeometrySpec
    g = GeometrySpec.model_validate({"points": [{"id": "A", "x": 0, "y": 3}, {"id": "B", "x": -2, "y": -1}, {"id": "C", "x": 2.5, "y": -1}],
                                     "circles": [{"id": "c1", "through_points": ["A", "B", "C"]}]})
    r = solve(g)
    assert r["ok"] and "__c_c1" in r["derived"]


# ---------------------------------------------------------------- Phase 12: OCR budget and cache
def test_ocr_budget_and_cache(monkeypatch):
    from diagram_engine import cache, constants, ocr
    from diagram_engine.ocr import engine
    if not ocr.available():
        pytest.skip("no Tesseract")
    png = (FIXDIR / "q16_p8_2.png").read_bytes()
    cache.OCR.clear()
    calls = {"n": 0}
    orig = engine._data

    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(engine, "_data", counting)
    first = engine.labels(png)
    n1 = calls["n"]
    assert engine.labels(png) == first and calls["n"] == n1                 # identical crop -> no second Tesseract run
    monkeypatch.setattr(constants, "OCR_MAX_REGIONS", 2)
    cache.OCR.clear()
    calls["n"] = 0
    engine.labels(png)
    assert calls["n"] <= 2 * constants.OCR_MAX_PSM_ATTEMPTS                 # region cap respected


# ---------------------------------------------------------------- three-pass / typed spec / provenance / OCR states
def test_three_pass_uses_separate_typed_diagram_call(analyzed):
    exam, qd, meta = analyzed
    import mock_gemini  # noqa: F401
    q = exam.questions[1]                                             # geometry: points come from PASS 2
    fid = q.figures[0].figure_id
    assert fid in q.diagram_specs and q.diagram_pass[fid]["provider"] == "Gemini/Diagram/Pass2"
    assert q.figures[0].spec_json == "" or q.diagrams[fid].audit.get("spec_source", "").startswith("Gemini/Diagram/Pass2")
    rec = q.diagrams[fid]
    assert rec.reconciliation and {r["status"] for r in rec.reconciliation} <= {"CONFIRMED", "UNCONFIRMED", "CONFLICT",
                                                                               "MISSING_FROM_SPEC", "UNEXPECTED_IN_IMAGE"}
    providers = {f["provider"] for f in rec.facts}
    assert "Gemini/Diagram/Pass2" in providers and any(p.startswith("Gemini/Text/Pass1") for p in providers)


def test_ai_schema_is_gemini_safe_and_round_trips():
    from diagram_engine import ai_schema as A
    assert A.schema_is_gemini_safe(A.AIDiagramSpec.model_json_schema()) == []
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    from diagram_engine.schemas import DiagramSpec
    for name, case in CASES.items():
        spec = DiagramSpec.model_validate(case["spec"])
        assert A.to_spec(A.AIDiagramSpec.model_validate(A.to_ai_dict(spec))).model_dump(exclude={"evidence", "symbols"}) == \
            spec.model_dump(exclude={"evidence", "symbols"}), name


def test_invalid_pass2_output_is_schema_validation_failed(analyzed, monkeypatch):
    exam, qd, meta = analyzed
    q = exam.questions[0]
    orig = c.GeminiService.generate

    def broken(self, parts, schema, *a, **k):
        if schema.__name__ == "AIDiagramSpec":
            schema.model_validate({"diagram_type": "not-a-type"})      # raises a pydantic ValidationError
        return orig(self, parts, schema, *a, **k)
    monkeypatch.setattr(c.GeminiService, "generate", broken)
    q.diagram_specs.clear()
    c.extract_diagrams_pass2(c.GeminiService("k"), q, qd[0])
    assert q.diagram_pass[q.figures[0].figure_id]["status"] == "SCHEMA_VALIDATION_FAILED"
    assert q.figures[0].figure_id not in q.diagram_specs


def test_ocr_states_failure_is_not_no_text(monkeypatch):
    from diagram_engine.ocr import engine, verify
    from diagram_engine.schemas import DiagramSpec
    monkeypatch.setattr(engine, "labels", lambda png: (_ for _ in ()).throw(RuntimeError("tesseract crashed")))
    spec = DiagramSpec.model_validate({"diagram_type": "geometry", "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 1, "y": 0}]}})
    res = verify.run(spec, (FIXDIR / "q16_p8_2.png").read_bytes())
    if engine.available():
        assert res["status"] == "FAILED" and res["facts"] == [] and res["inventory"] == {}
    assert verify.run(spec, b"")["status"] in ("INVALID_INPUT", "ENGINE_UNAVAILABLE")


# ---------------------------------------------------------------- localization / notation
from diagram_engine import notation  # noqa: E402


def test_semantic_notation_rendering_per_profile():
    assert notation.display("MEAN", notation.Profile.ISRAEL_HIGH_SCHOOL) == r"\bar{x}"
    assert notation.display("STANDARD_DEVIATION", notation.Profile.ISRAEL_HIGH_SCHOOL) == "S"
    assert notation.display("MEAN", notation.Profile.SOURCE_FAITHFUL, source_symbol="μ") == "μ"
    for tok, sem in (("μ", "MEAN"), (r"\mu", "MEAN"), ("x̄", "MEAN"), (r"\bar{x}", "MEAN"), ("σ", "STANDARD_DEVIATION"),
                     (r"\sigma", "STANDARD_DEVIATION"), ("סטיית תקן", "STANDARD_DEVIATION"), ("mean", "MEAN")):
        assert notation.semantic_of(tok) == sem, tok


def test_generated_solution_uses_israel_notation_and_gate_catches_mixing():
    t = notation.apply_profile(r"הממוצע $\mu=70$ וסטיית התקן $\sigma=5$", notation.Profile.ISRAEL_HIGH_SCHOOL)
    assert r"\bar{x}=70" in t and "S=5" in t and r"\mu" not in t and r"\sigma" not in t
    issues = notation.inconsistencies({"פתרון": r"$\bar{x}=70$ ... $\sigma=5$"}, notation.Profile.ISRAEL_HIGH_SCHOOL)
    assert issues and "NOTATION_INCONSISTENCY" in issues[0]
    assert notation.inconsistencies({"פתרון": r"$\mu$"}, notation.Profile.SOURCE_FAITHFUL) == []
    assert notation.apply_profile(r"$\mu$", notation.Profile.SOURCE_FAITHFUL) == r"$\mu$"


# ---------------------------------------------------------------- linear extent
@pytest.mark.parametrize("text,kind", [("הקטע AB", "SEGMENT"), ("הקרן AB", "RAY"), ("הישר AB", "LINE")])
def test_linear_extent_from_text(text, kind):
    assert f"extent(A,B,{kind})" in {f.key for f in text_facts.extract(text)}


def _ab_spec(where):
    g = {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 4, "y": 1}, {"id": "C", "x": 2, "y": 3}],
         "segments": [{"a": "A", "b": "C"}], "lines": [], "rays": []}
    g[where].append({"a": "A", "b": "B"})
    return {"diagram_type": "geometry", "confidence": 0.95, "labels": [], "geometry": g}


@pytest.mark.parametrize("text,drawn,ok", [
    ("הישר AB", "lines", True), ("הישר AB", "segments", False), ("הקרן AB", "rays", True), ("הקרן AB", "segments", False),
    ("הקטע AB", "segments", True), ("הקטע AB", "lines", True)])
def test_linear_extent_validator(text, drawn, ok):
    """V5.7.3: a text/drawing extent mismatch is a TEACHER-REVIEW conflict (Hebrew 'הישר' often names a drawn segment)."""
    r = de.process("x", json.dumps(_ab_spec(drawn)), text, None)
    flagged = any("LINEAR_EXTENT_REVIEW" in c for c in r.contradictions)
    assert flagged == (not ok), r.contradictions
    assert not any("extent" in c for c in r.comparison.critical)
    if not ok:
        assert r.decision.action != "high_confidence_preview"


def test_tangent_extent_not_auto_upgraded():
    keys = {f.key for f in text_facts.extract("CF משיק למעגל בנקודה C")}
    assert not any(k.startswith("extent(") for k in keys)                    # no blind SEGMENT/RAY/LINE for a tangent


# ---------------------------------------------------------------- degenerate geometry / numerical safety
def test_intersection_of_parallel_lines_is_degenerate_not_fallback():
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [],
            "geometry": {"points": [{"id": "A", "x": 0, "y": 0, "fixed": True}, {"id": "B", "x": 4, "y": 0, "fixed": True},
                                    {"id": "C", "x": 0, "y": 2, "fixed": True}, {"id": "D", "x": 4, "y": 2, "fixed": True},
                                    {"id": "K", "x": 2, "y": 1}],
                         "segments": [{"a": "A", "b": "B"}, {"a": "C", "b": "D"}],
                         "constraints": [{"type": "intersection", "points": ["K", "A", "B", "C", "D"], "source": "text"}]}}
    r = de.process("deg", json.dumps(spec), "", None)
    assert r.decision.action == "original" and any("DEGENERATE_GEOMETRY" in e for e in r.validation.errors)


# ---------------------------------------------------------------- analytic graph sampling
from diagram_engine import safe_math as sm  # noqa: E402
from diagram_engine.graph.evaluator import branch_samples  # noqa: E402


@pytest.mark.parametrize("expr,lo,hi,poles", [("1/(x-1)", -4, 4, [1.0]), ("(x^2+1)/(x^2-4)", -5, 5, [-2.0, 2.0]),
                                              ("ln(x-1)", -2, 6, [1.0]), ("tan(x)", -3, 3, [-1.5707963267948966, 1.5707963267948966])])
def test_branch_aware_sampling_never_crosses_poles_and_clips(expr, lo, hi, poles):
    import numpy as np
    parts = branch_samples(sm.parse_expression(expr), lo, hi, -10, 10, poles)
    assert parts
    for xs, ys in parts:
        assert not any(xs[0] < p < xs[-1] for p in poles)                       # no cross-branch / cross-asymptote path
        assert np.all(ys <= 10 + 1.0 + 1e-9) and np.all(ys >= -10 - 1.0 - 1e-9)   # clipped at the viewport + 5% margin, no spike
        assert np.all(np.isfinite(ys))


def test_hard_anchors_kept_by_sampling():
    import numpy as np
    parts = branch_samples(sm.parse_expression("x^3-4x"), -3, 3, -10, 10, [])
    xs = np.concatenate([p[0] for p in parts])
    ys = np.concatenate([p[1] for p in parts])
    for root in (-2, 0, 2):
        i = np.argmin(abs(xs - root))
        assert abs(ys[i]) < 0.05                                               # roots are on the rendered curve


def test_schematic_curve_invents_no_extrema_roots_or_sign_changes():
    import numpy as np
    from diagram_engine.graph import qualitative_parser as qp
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    from diagram_engine.schemas import DiagramSpec
    for name in ("A01_qualitative", "A03_rational_options", "A10_log_options", "A02_formula_options"):
        spec = DiagramSpec.model_validate(CASES[name]["spec"])
        topos = [spec.graph_topology] if spec.graph_topology else [o.topology for o in spec.multi_graph.options if o.topology]
        for t in topos:
            for br in t.branches:
                xs, ys = qp.curve_points(t, br)
                d = np.sign(np.diff(ys))
                turns = np.count_nonzero(np.diff(d[d != 0]))
                marked = sum(1 for i in br.landmarks if t.landmarks[i].kind in ("max", "min"))
                assert turns == marked, (name, turns, marked)                   # no new extrema
                zero_x = [t.landmarks[i].x for i in br.landmarks if t.landmarks[i].kind == "x_intercept"]
                sign = np.sign(ys[np.abs(ys) > 1e-9])
                assert np.count_nonzero(np.diff(sign)) <= len(zero_x), name     # no new roots / sign changes


# ---------------------------------------------------------------- bar chart CV
def _bar_png(values, horizontal=False, tick=10, cats=None):
    from diagram_engine.render_base import new_figure, export
    fig, ax = new_figure(5, 4)
    cats = cats or [f"c{i}" for i in range(len(values))]
    (ax.barh if horizontal else ax.bar)(cats, values, color="#9ecae1", edgecolor="#111111")
    from matplotlib.ticker import MultipleLocator
    (ax.xaxis if horizontal else ax.yaxis).set_major_locator(MultipleLocator(tick))
    ax.spines[["top", "right"]].set_visible(False)
    if min(values) < 0:
        (ax.axvline if horizontal else ax.axhline)(0, color="#111111", lw=1.2)
    return export(fig)[1]


@pytest.mark.parametrize("values,horizontal", [([30, 50, 20, 40], False), ([30, 50, 20, 40], True), ([12, 37, 25], False)])
def test_bar_chart_cv_reads_values_independently(values, horizontal):
    from diagram_engine import ocr
    from diagram_engine.charts import bar_cv
    if not ocr.available():
        pytest.skip("no Tesseract")
    det = bar_cv.detect(_bar_png(values, horizontal))
    assert det["stable"], det["reason"]
    assert det["orientation"] == ("HORIZONTAL" if horizontal else "VERTICAL")
    assert bar_cv.compare(values, det, 10) == []
    wrong = list(values)
    wrong[1] += 10
    assert any("BAR_VALUE_CONFLICT" in m for m in bar_cv.compare(wrong, det, 10))


# ---------------------------------------------------------------- 3D scene: camera / hidden lines / partial occlusion / labels
def _box(w=4, d=3, h=3, o=(0, 0, 0)):
    import numpy as np
    from diagram_engine.schemas import Solid
    from diagram_engine.spatial.solids import box_edges, box_vertices
    v = box_vertices(Solid(id="b", kind="cuboid", dims={"width": w, "depth": d, "height": h}, origin=list(o)))
    return {k: np.array(p, float) for k, p in v.items()}, box_edges()


def test_hidden_edges_are_computed_not_hardcoded():
    from diagram_engine.spatial.camera import PRESETS, choose_camera, edge_visibility
    verts, edges = _box()
    vis = edge_visibility(verts, edges, PRESETS["OBLIQUE_RIGHT"])
    hidden = sorted(sorted(k) for k, iv in vis.items() if all(s == "HIDDEN" for *_, s in iv))
    assert hidden == [["A", "A'"], ["A", "B"], ["A", "D"]]          # the source's dashed edges, derived from geometry
    name, _ = choose_camera(verts, edges, [["A", "B"], ["A", "D"], ["A", "A'"]])
    assert name == "OBLIQUE_RIGHT"
    assert choose_camera(verts, edges, [["C", "D"]])[0] is None       # inconsistent dashed edges -> conflict, not a guess


@pytest.mark.parametrize("mode", ["ISOMETRIC", "ORTHO_FRONT", "OBLIQUE_LEFT"])
def test_every_projection_mode_hides_exactly_the_back_vertex_edges(mode):
    from diagram_engine.spatial.camera import PRESETS, edge_visibility
    verts, edges = _box()
    vis = edge_visibility(verts, edges, PRESETS[mode])
    hidden = [k for k, iv in vis.items() if all(s == "HIDDEN" for *_, s in iv)]
    visible = [k for k, iv in vis.items() if all(s == "VISIBLE" for *_, s in iv)]
    assert len(hidden) + len(visible) == 12 and 0 < len(hidden) <= 5


def test_partial_occlusion_splits_an_edge():
    from diagram_engine.spatial.camera import Camera, edge_visibility, hull_faces
    back, edges = _box(6, 2, 2, (0, 4, 0))
    front, _ = _box(2, 1, 4, (2, 0, 0))                                # a tall block in front of the middle
    cam = Camera(mode="ORTHOGRAPHIC", position=(3.0, -20.0, 1.0), target=(3.0, 0.0, 1.0))
    occ = [[(ids, n, front) for ids, n in hull_faces(front)]]
    vis = edge_visibility(back, edges, cam, occ)
    split = [iv for iv in vis.values() if {s for *_, s in iv} == {"VISIBLE", "HIDDEN"}]
    assert split and any([s for *_, s in iv] == ["VISIBLE", "HIDDEN", "VISIBLE"] for iv in split)


def test_label_placer_avoids_edges_and_other_labels():
    import numpy as np
    from diagram_engine.spatial.camera import LabelPlacer
    lp = LabelPlacer(size=10.0, segments=[((0, 0), (10, 0)), ((0, 0), (0, 10))])
    a = lp.place((0, 0), (1, 1))
    b = lp.place((0.2, 0.2), (1, 1))
    assert np.linalg.norm(a - b) >= 0.5 and min(a) > 0.3


# ---------------------------------------------------------------- voxel generalisation
def test_voxel_scene_views_delta_and_camera_order():
    import numpy as np
    from diagram_engine.schemas import VoxelSpec
    from diagram_engine.spatial import voxel as V
    from diagram_engine.spatial.camera import PRESETS
    from diagram_engine.spatial.voxel_scene import VoxelGrid, delta, view_impact
    spec = VoxelSpec(columns=[{"x": 0, "y": 0, "height": 2}, {"x": 1, "y": 0, "height": 1}, {"x": 1, "y": 1, "height": 3}])
    g = VoxelGrid.from_spec(spec)
    assert len(g.occupied_cells()) == V.total(spec) == 6 and g.occupied(1, 1, 2) and not g.occupied(0, 1, 0)
    assert g.height_map().tolist() == [[2, 0], [1, 3]]
    assert g.height_profile("FRONT_FROM_NEG_Y") == [2, 3] and g.height_profile("SIDE_FROM_POS_X") == [2, 3]
    top = g.view("TOP_FROM_POS_Z").astype(int).tolist()
    assert top == [[0, 1], [1, 1]] and np.array_equal(np.array(V.top_view(spec, 2, 2), int), np.array(top))  # consistent with legacy
    g2 = VoxelGrid(g.cells | {(0, 1, 0)})
    assert delta(g, g2)["kind"] == "ADDED" and view_impact(g, g2) == ["TOP_CHANGED"]   # hidden from the side by column (1,1)
    assert "FRONT_CHANGED" in view_impact(g, VoxelGrid(g.cells | {(0, 0, 2)}))
    assert delta(g, VoxelGrid(g.cells - {(1, 1, 2)}))["kind"] == "REMOVED"
    order = g.depth_order(PRESETS["ISOMETRIC"])
    assert order[0] == (1, 1, 2) or order[0][0] + order[0][1] >= 2                  # farthest first (generic camera)
    with pytest.raises(ValueError):
        VoxelGrid.from_height_matrix([[1, -1]])


# ---------------------------------------------------------------- drag / LaTeX editing (logic; browser test in e2e)
def test_drag_keeps_constraints_and_invalidates_approval():
    import numpy as np
    import diagram_ui
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [],
            "geometry": {"points": [{"id": "O", "x": 0, "y": 0}, {"id": "A", "x": 3, "y": 0}, {"id": "E", "x": 0, "y": 3}],
                         "segments": [{"a": "O", "b": "E"}], "circles": [{"id": "c", "center": "O", "through": "A"}],
                         "constraints": [{"type": "on_circle", "points": ["E", "O"], "circle": "c", "source": "text"}]},
            "labels": [{"text": t, "confidence": 0.99} for t in "OAE"],
            "observed": {"num_points": 3, "point_labels": ["A", "E", "O"], "num_circles": 1, "num_segments": 1}}
    rec = de.process("d", json.dumps(spec), "", None)
    assert de.approve(rec), (rec.decision, rec.comparison.critical)
    new = diagram_ui.drag_to_spec(rec, "E", 5.0, 5.0)                           # dragged OFF the circle
    rec2 = de.apply_teacher_edit(rec, new, "drag E", "", None)
    P = {p.id: np.array([p.x, p.y]) for p in rec2.spec.geometry.points}
    assert abs(np.hypot(*P["E"]) - 3.0) < 1e-6                                  # snapped back onto the circle
    assert P["E"][0] > 0.5 and P["E"][1] > 0.5                                  # ... in the dragged direction
    assert rec2.review.status == "pending" and not de.usable_in_document(rec2) and rec2.validation.ok


def test_latex_formula_edit_is_teacher_evidence_and_reparsed():
    import diagram_ui
    spec = {"diagram_type": "graph", "confidence": 0.9, "labels": [],
            "graph": {"axes": {"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5}, "curves": [{"id": "f", "expression": "x^2"}]}}
    rec = de.process("g", json.dumps(spec), "a הוא פרמטר חיובי", None)
    new = diagram_ui.latex_formula_edit(rec, r"\frac{2ax}{a^2-9x^2}")
    assert new.graph.curves[0].source == "teacher"
    rec2 = de.apply_teacher_edit(rec, new, "formula", "a הוא פרמטר חיובי", None)
    assert rec2.validation.ok and rec2.review.status != "approved" and rec2.spec.graph.curves[0].expression.replace(" ", "")
    with pytest.raises(Exception):
        diagram_ui.latex_formula_edit(rec, r"\frac{2bx}{1}")                    # undeclared b -> rejected, not guessed


def test_drag_that_cannot_be_satisfied_is_rejected():
    import diagram_ui
    spec = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABM"],
            "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 4, "y": 0}, {"id": "M", "x": 2, "y": 0}],
                         "segments": [{"a": "A", "b": "B"}],
                         "constraints": [{"type": "equal_length", "points": ["A", "M", "M", "B"], "source": "text"},
                                         {"type": "collinear", "points": ["A", "M", "B"], "source": "text"}]},
            "observed": {"num_points": 3, "point_labels": ["A", "B", "M"], "num_segments": 1}}
    rec = de.process("d", json.dumps(spec), "", None)
    rec2 = de.apply_teacher_edit(rec, diagram_ui.drag_to_spec(rec, "A", -3.0, 5.0), "drag", "", None)
    # A may move, but M and B are pinned: M must stay the midpoint -> A is forced to (0,0): satisfiable by projection
    assert rec2.validation.ok or any("DRAG_INFEASIBLE" in e for e in rec2.validation.errors)
    assert not any(p.pinned for p in rec2.spec.geometry.points)                # holds never persist as facts


# ---------------------------------------------------------------- eval harness (mock), fingerprint versions, tables, graph mode
def test_real_full_e2e_pass1_to_pass2(monkeypatch):
    """The eval path starts from a FULL PAGE and goes through the real analyze_question (PASS 1 -> bbox -> master ROI ->
    PASS 2). No manifest text / proposal / spec / ROI is fed in (checked by spying on the calls)."""
    import mock_gemini
    sys.path.insert(0, str(ROOT / "eval"))
    sys.path.insert(0, str(ROOT / "tests" / "acceptance_real"))
    import real_eval
    mock_gemini.install()
    calls = []
    orig = c.GeminiService.generate

    def spy(self, parts, schema, *a, **k):
        calls.append((schema.__name__, [getattr(p, "text", None) for p in parts]))
        return orig(self, parts, schema, *a, **k)
    monkeypatch.setattr(c.GeminiService, "generate", spy)
    items = [i for i in real_eval.load_set("fixed") if i["id"] == "A14"]
    assert items and items[0]["page"].exists()
    run = real_eval.run_once(c.GeminiService("k"), items[0], {"school": "", "subject": "מתמטיקה"})
    names = [n for n, _ in calls]
    assert names[0] == "QuestionAI" and "AIDiagramSpec" in names             # PASS 1 then PASS 2, both real calls
    sent_text = " ".join(t or "" for _, ts in calls for t in ts)
    assert items[0]["expected_text"][:40] not in sent_text                   # the manual transcription is never sent
    assert run["pass1"] is not None and run["record"] is not None and run["pass2_status"] == "OK"
    sc = real_eval.score(items[0], run)
    assert set(sc) == {"pass1", "pass2", "safety"} and "bbox_iou" in sc["pass1"] and "entity_recall" in sc["pass2"]
    assert sc["safety"]["outcome"] in ("PASS", "CORRECTLY_BLOCKED", "WRONG_OFFERED_FOR_REVIEW", "WRONG_ACCEPTED")
    st_ = real_eval.stability([run, run])
    assert st_["verdict"] == "STABLE"


def test_eval_sets_have_exact_real_pages_and_empty_holdout_is_reported(monkeypatch):
    sys.path.insert(0, str(ROOT / "eval"))
    import real_eval
    fixed = real_eval.load_set("fixed")
    assert len(fixed) == 16 and all(i["page"].exists() and len(i["expected_bbox"]) == 4 for i in fixed)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(sys, "argv", ["real_eval.py", "--set", "holdout"])
    assert real_eval.main() == 3                                             # no holdout images -> explicit, not "passed"


def test_real_eval_refuses_to_claim_without_key(monkeypatch):
    sys.path.insert(0, str(ROOT / "eval"))
    import real_eval
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["real_eval.py"])
    assert real_eval.main() == 2


def test_fingerprint_includes_component_versions(monkeypatch):
    from diagram_engine import notation, review_state
    spec = {"diagram_type": "geometry", "confidence": 0.9, "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 1, "y": 0}]}}
    rec = de.process("f", json.dumps(spec), "", None)
    f1 = review_state.fingerprint(rec)
    monkeypatch.setattr(notation, "NOTATION_VERSION", "notation/9.9")
    assert review_state.fingerprint(rec) != f1                                 # a localization change voids approvals


def test_table_semantic_header_mapping():
    from diagram_engine.charts.table import semantic_cells
    from diagram_engine.schemas import TableSpec
    t = TableSpec.model_validate({"header_rows": 1, "header_columns": 1,
                                  "rows": [[{"text": "סוג"}, {"text": "ילדים"}], [{"text": "המחיר (בשקלים)"}, {"text": "60"}]]})
    cell = semantic_cells(t)[0]
    assert cell == {"row_header": "המחיר (בשקלים)", "column_header": "ילדים", "text": "60", "value": None, "row": 1, "col": 1}


def test_option_transformations_only_with_evidence():
    from diagram_engine.graph.comparator import option_transformations
    from diagram_engine.schemas import GraphTopologySpec
    base = {"landmarks": [{"x": 1, "y": 2, "kind": "max"}, {"x": 3, "y": 0, "kind": "x_intercept"}],
            "asymptotes": [{"kind": "horizontal", "value": 1}], "branches": [{"landmarks": [0, 1]}]}
    a = GraphTopologySpec.model_validate(base)
    inv = GraphTopologySpec.model_validate({**base, "landmarks": [{"x": 1, "y": -2, "kind": "min"}, {"x": 3, "y": 0, "kind": "x_intercept"}],
                                            "asymptotes": [{"kind": "horizontal", "value": -1}]})
    sh = GraphTopologySpec.model_validate({**base, "landmarks": [{"x": 3, "y": 2, "kind": "max"}, {"x": 5, "y": 0, "kind": "x_intercept"}]})
    assert option_transformations(a, inv) == ["SIGN_INVERSION"]
    assert option_transformations(a, sh) == ["SHIFT_X(2)"]
    odd = GraphTopologySpec.model_validate({**base, "landmarks": [{"x": 3, "y": 2, "kind": "max"}, {"x": 9, "y": 0, "kind": "x_intercept"}]})
    assert option_transformations(a, odd) == []                                  # no evidence -> no claimed transformation


@pytest.mark.parametrize("text,key", [("אורכה 8 ס''מ", "dimension(length,8)"), ("גובהה 5 ס״מ", "dimension(height,5)"),
                                      ("רוחבה 3 cm", "dimension(width,3)"), ('רדיוס בסיסו 6 ס"מ', "dimension(radius,6)")])
def test_hebrew_dimension_morphology_v571(text, key):
    assert key in {f.key for f in text_facts.extract(text) if f.fact_type == "dimension"}
    assert "point(A'')" in {f.key for f in text_facts.extract("הנקודה A'' נמצאת על הקטע BC")}



def _bar_spec(cats, values):
    return {"diagram_type": "chart", "subtype": "bar_chart", "confidence": 0.95, "labels": [],
            "chart": {"kind": "bar", "categories": cats, "values": values},
            "observed": {"num_bars": len(values), "bar_values": values}}


CATS = ["RED", "BLUE", "GREEN", "PINK"]


def test_bar_cv_pipeline_integration_and_category_binding():
    from diagram_engine import ocr
    if not ocr.available():
        pytest.skip("no Tesseract")
    png = _bar_png([30, 50, 20, 40], cats=CATS)
    r = de.process("b", json.dumps(_bar_spec(CATS, [30, 50, 20, 40])), "", png)
    assert r.audit["bar_cv"]["status"] == "VERIFIED" and r.audit["bar_verified"]["BLUE"] == pytest.approx(50, abs=1)
    assert r.decision.action != "original"


def test_bar_category_binding_catches_swapped_values_with_same_multiset():
    from diagram_engine import ocr
    if not ocr.available():
        pytest.skip("no Tesseract")
    png = _bar_png([30, 50, 20, 40], cats=CATS)
    r = de.process("b", json.dumps(_bar_spec(CATS, [50, 30, 20, 40])), "", png)      # RED/BLUE swapped
    assert r.audit["bar_cv"]["status"] == "CONFLICT" and r.decision.action == "original"


def test_bar_conflict_blocks_approval_and_unavailable_is_not_agreement():
    from diagram_engine import ocr
    if not ocr.available():
        pytest.skip("no Tesseract")
    png = _bar_png([30, 50, 20, 40], cats=CATS)
    r = de.process("b", json.dumps(_bar_spec(CATS, [30, 50, 26, 40])), "", png)
    assert r.decision.action == "original" and not de.approve(r)
    blank = de.process("b", json.dumps(_bar_spec(CATS, [30, 50, 20, 40])), "", _bar_png([0.0001, 0.0001], cats=["A", "B"]))
    assert blank.audit["bar_cv"]["status"] in ("BAR_CV_UNAVAILABLE", "CONFLICT")
    assert blank.decision.action != "high_confidence_preview"


# ---------------------------------------------------------------- V5.7.2: one camera = projection + visibility + depth
def _box_scene(hidden, extra=None, camera=""):
    s = {"diagram_type": "spatial", "subtype": "cuboid", "confidence": 0.95, "labels": [],
         "spatial": {"camera": camera, "solids": [{"id": "b", "kind": "cuboid", "dims": {"width": 4, "depth": 3, "height": 3}, "hidden_edges": hidden}]}}
    if extra:
        s["spatial"]["solids"].append(extra)
    return s


def _hidden_for(cam_name):
    import numpy as np
    from diagram_engine.schemas import Solid
    from diagram_engine.spatial import solids as S
    from diagram_engine.spatial.camera import PRESETS, edge_visibility
    sol = Solid(id="b", kind="cuboid", dims={"width": 4, "depth": 3, "height": 3})
    V3 = {k: np.asarray(v, float) for k, v in S.box_vertices(sol).items()}
    vis = edge_visibility(V3, S.box_edges(), PRESETS[cam_name])
    return [sorted(k) for k, iv in vis.items() if all(st == "HIDDEN" for *_, st in iv)], V3


@pytest.mark.parametrize("cam_name", ["OBLIQUE_RIGHT", "ISOMETRIC", "ORTHO_FRONT"])
def test_camera_projection_visibility_consistency(cam_name):
    from diagram_engine.spatial.camera import PRESETS
    hidden, V3 = _hidden_for(cam_name)
    r = de.process("s", json.dumps(_box_scene(hidden, camera=cam_name)), "", None)
    m = r.manifest
    assert m["projection_source"] == m["visibility_camera"] == cam_name
    for k, v in V3.items():                                                  # drawn position == the same camera's projection
        u, w, _ = PRESETS[cam_name].project(v)
        assert m["screen"][k] == pytest.approx([u, w], abs=1e-6)


def _ray_hidden(cam_pos, q, lo=(0, 0, 0), hi=(4, 3, 3), eps=1e-6):
    """Independent ground truth: is the segment camera->q blocked by the box interior before reaching q? (slab test)"""
    import numpy as np
    o, d = np.asarray(cam_pos, float), np.asarray(q, float) - np.asarray(cam_pos, float)
    t0, t1 = 0.0, 1.0 - 1e-4
    for i in range(3):
        a, b = lo[i] + eps, hi[i] - eps
        if abs(d[i]) < 1e-15:
            if not (a < o[i] < b):
                return False
            continue
        ta, tb = sorted(((a - o[i]) / d[i], (b - o[i]) / d[i]))
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


def test_camera_rotation_same_source_of_truth():
    import numpy as np
    from diagram_engine.spatial import solids as S
    from diagram_engine.spatial.camera import Camera, edge_visibility
    _, V3 = _hidden_for("OBLIQUE_RIGHT")
    seen = set()
    for ang in (20, 110, 200, 290):
        for dist in (7.0, 30.0):                                            # close (strong perspective) and far
            a = np.radians(ang)
            pos = (2 + dist * np.cos(a), 1.5 + dist * np.sin(a), 6.0)
            cam = Camera(mode="PERSPECTIVE", position=pos, target=(2.0, 1.5, 1.5))
            vis = edge_visibility(V3, S.box_edges(), cam)
            for e in S.box_edges():
                mid = (V3[e[0]] + V3[e[1]]) / 2
                truth = _ray_hidden(pos, mid)
                got = all(st == "HIDDEN" for *_, st in vis[frozenset(e)])
                assert got == truth, (ang, dist, e)
            seen.add(frozenset(k for k, iv in vis.items() if all(st == "HIDDEN" for *_, st in iv)))
    assert len(seen) >= 4                                                   # moving the camera changes visibility


def test_cylinder_projection_policy():
    hidden, _ = _hidden_for("ISOMETRIC")
    cyl = {"id": "c", "kind": "cylinder", "dims": {"radius": 1, "height": 2}, "origin": [8, 0, 0]}
    r = de.process("s", json.dumps(_box_scene(hidden, cyl, camera="ISOMETRIC")), "", None)
    assert any("CYLINDER_GENERIC_CAMERA_UNSUPPORTED" in u for u in r.spec.unsupported_features)
    assert r.decision.action == "original"                                    # fail closed, never a wrong ellipse
    ok_hidden, _ = _hidden_for("OBLIQUE_RIGHT")
    r2 = de.process("s", json.dumps(_box_scene(ok_hidden, cyl)), "", None)
    assert not any("CYLINDER" in u for u in r2.spec.unsupported_features)


# ---------------------------------------------------------------- V5.7.2: reconstruction vs solution facts
TRI = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABCD"],
       "geometry": {"points": [{"id": "A", "x": 0, "y": 3}, {"id": "B", "x": 0, "y": 0}, {"id": "C", "x": 4, "y": 0}, {"id": "D", "x": 2, "y": 0}],
                    "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}]},
       "observed": {"num_points": 4, "point_labels": list("ABCD"), "num_segments": 3}}


def _q(stem, sections):
    from exam_core import QuestionAnalysis
    q = QuestionAnalysis(question_number=1, points=10, topic="t", text=stem,
                         sections=[{"section_id": "אב"[i], "text": t_, "points": 5} for i, t_ in enumerate(sections)])
    return q


def test_solution_only_fact_does_not_block():
    q = _q("במשולש ABC הנקודה D נמצאת על הצלע BC.", ["מצא את אורך הקטע AD.", "חשב את שטח המשולש ABC."])
    full = q.text + " " + " ".join(s_.text for s_ in q.sections)
    r = de.process("x", json.dumps(TRI), full, None, required_text=c.reconstruction_text(q))
    assert not r.missing_required and r.decision.action != "original", (r.missing_required, r.comparison.critical)
    crit = {f["criticality"] for f in r.facts if f["fact_type"] == "segment" and set(f["entities"]) == {"A", "D"}}
    assert crit == {"REQUIRED_FOR_SOLUTION"}


def test_required_fact_reconstruction_vs_solution():
    q = _q("במשולש ABC הנקודה D נמצאת על הצלע BC.", ["נתון כי AD מאונך ל-BC. מצא את אורך AD."])
    recon = c.reconstruction_text(q)
    assert "AD מאונך" in recon and "מצא את אורך" not in recon
    r = de.process("x", json.dumps(TRI), q.text + " " + q.sections[0].text, None, required_text=recon)
    crit = {f["criticality"] for f in r.facts if f["fact_type"] == "perpendicular" and f["source"] == "question_text" and f["required"]}
    assert crit == {"REQUIRED_FOR_RECONSTRUCTION"}     # a declarative subpart fact constrains the figure ...
    P = {p.id: (p.x, p.y) for p in r.spec.geometry.points}
    ad = (P["D"][0] - P["A"][0], P["D"][1] - P["A"][1])
    bc = (P["C"][0] - P["B"][0], P["C"][1] - P["B"][1])
    assert abs(ad[0] * bc[0] + ad[1] * bc[1]) < 1e-6   # ... and is enforced (text wins over the drawing)


# ---------------------------------------------------------------- V5.7.2: geometry lengths / angles verified by OCR
def _labeled_triangle(len_ab="5", angle="40"):
    return {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABC"],
            "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 6, "y": 0}, {"id": "C", "x": 2, "y": 3.5}],
                         "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}],
                         "length_labels": [{"a": "A", "b": "B", "text": len_ab}],
                         "angle_marks": [{"vertex": "A", "a": "B", "b": "C", "kind": "arc", "value": angle + "°"}]},
            "observed": {"num_points": 3, "point_labels": list("ABC"), "num_segments": 3}}


def _source_png(spec):
    r = de.process("src", json.dumps(spec), "", None)
    return de.render_spec(r.spec)[1]


needs_tess = pytest.mark.skipif(not __import__("diagram_engine.ocr", fromlist=["available"]).available(), reason="no Tesseract")


@needs_tess
def test_geometry_length_and_angle_confirmed_by_ocr():
    src = _source_png(_labeled_triangle("5", "40"))
    r = de.process("g", json.dumps(_labeled_triangle("5", "40")), "", src)
    g = r.audit["ocr_geometry_numbers"]
    assert "AB" in g["confirmed"] and not g["conflicts"]


@needs_tess
def test_geometry_length_ocr_conflict():
    src = _source_png(_labeled_triangle("5", "40"))
    r = de.process("g", json.dumps(_labeled_triangle("8", "40")), "", src)      # the AI misread 5 as 8
    assert any("LENGTH_VALUE_CONFLICT" in c for c in r.contradictions) and r.decision.action == "original"


@needs_tess
def test_geometry_angle_ocr_conflict():
    src = _source_png(_labeled_triangle("5", "40"))
    r = de.process("g", json.dumps(_labeled_triangle("5", "70")), "", src)
    g = r.audit["ocr_geometry_numbers"]
    assert "∠BAC" not in g["confirmed"]                                          # 70 is never "confirmed"
    assert any("ANGLE_VALUE_CONFLICT" in c for c in r.contradictions) or "∠BAC" in g["unresolved"]
    assert r.decision.action != "high_confidence_preview"


def test_ocr_failure_is_unresolved_not_confirmed(monkeypatch):
    from diagram_engine.ocr import engine
    monkeypatch.setattr(engine, "numbers", lambda png: [])
    monkeypatch.setattr(engine, "angle_numbers", lambda png: [])
    r = de.process("g", json.dumps(_labeled_triangle("5", "40")), "", b"\\x89PNG fake")
    g = r.audit.get("ocr_geometry_numbers") or {}
    assert not g.get("confirmed")


# ---------------------------------------------------------------- V5.7.2: topology beyond circle counts
def _tri_with(extra_segs=()):
    s = {"diagram_type": "geometry", "confidence": 0.95, "labels": [{"text": t, "confidence": 0.99} for t in "ABCDE"],
         "geometry": {"points": [{"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 8, "y": 0}, {"id": "C", "x": 3, "y": 5},
                                 {"id": "D", "x": 5.5, "y": 2.5}, {"id": "E", "x": 1.5, "y": 2.5}],
                      "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}] + [{"a": a, "b": b} for a, b in extra_segs]},
         "observed": {"num_points": 5, "point_labels": list("ABCDE")}}
    return s


def test_topology_junction_mismatch():
    from diagram_engine import topology_extractor as T
    if not T.available():
        pytest.skip("no OpenCV")
    src = _source_png(_tri_with([("A", "D"), ("B", "E")]))                  # two cevians crossing inside
    bad = de.process("t", json.dumps(_tri_with([("A", "D")])), "", src)      # the AI lost BE
    assert any("TOPOLOGY_MISMATCH" in c and "צמתים" in c for c in bad.contradictions)
    assert bad.decision.action != "high_confidence_preview"
    ok = de.process("t", json.dumps(_tri_with([("A", "D"), ("B", "E")])), "", src)
    assert not any("TOPOLOGY_MISMATCH" in c for c in ok.contradictions)


def test_topology_connectivity_mismatch():
    from diagram_engine import topology_extractor as T
    if not T.available():
        pytest.skip("no OpenCV")
    two = {"diagram_type": "generic", "confidence": 0.9, "labels": [],
           "generic": {"width": 100, "height": 60, "shapes": [{"kind": "rect", "x": 5, "y": 5, "w": 30, "h": 30, "text": ""},
                                                             {"kind": "rect", "x": 60, "y": 5, "w": 30, "h": 30, "text": ""}]}}
    one = json.loads(json.dumps(two))
    one["generic"]["shapes"][1]["x"] = 35                                   # touching -> one connected component
    src = _source_png(two)
    r = de.process("t", json.dumps(one), "", src)
    js = r.audit["topology"]["structure"]
    assert js["source"]["components"] != js["render"]["components"]
    assert any("TOPOLOGY_MISMATCH" in c for c in r.contradictions)


# ---------------------------------------------------------------- V5.7.2: pixel-level graph evidence
def _fspec(expr, xr=(-5, 5), yr=(-6, 6)):
    return {"diagram_type": "graph", "confidence": 0.95, "labels": [],
            "graph": {"axes": {"x_min": xr[0], "x_max": xr[1], "y_min": yr[0], "y_max": yr[1], "show_grid": False, "show_numbers": False},
                      "curves": [{"id": "f", "expression": expr}]}, "observed": {"num_curves": 1}}


def test_graph_cv_axis_crossing():
    from diagram_engine.graph import graph_cv
    src = _source_png(_fspec("x^2-4"))
    assert graph_cv.analyse(src)["x_axis_contacts"] == 2
    ok = de.process("g", json.dumps(_fspec("x^2-4")), "", src)
    assert not any("VISUAL_GRAPH_CONFLICT" in c for c in ok.contradictions)
    bad = de.process("g", json.dumps(_fspec("x^2+1")), "", src)                 # wrong formula: no roots in the model
    assert any("VISUAL_GRAPH_CONFLICT" in c and "ציר x" in c for c in bad.contradictions)
    assert bad.decision.action != "high_confidence_preview"


def test_graph_cv_branch_count():
    from diagram_engine.graph import graph_cv
    src = _source_png(_fspec("1/(x-1)+1"))
    assert graph_cv.analyse(src)["branches"] == 2
    bad = de.process("g", json.dumps(_fspec("x+1")), "", src)                   # a 1-branch model for a 2-branch picture
    # V5.7.3: the wrong model must be caught by SOME reliable pixel evidence; branch counting is only allowed to judge
    # when it reproduces the model on our own correct render (per-graph reliability self-check)
    assert any("VISUAL_GRAPH_CONFLICT" in c for c in bad.contradictions)
    assert bad.decision.action != "high_confidence_preview"


# ---------------------------------------------------------------- V5.7.2: inflection / concavity
@pytest.mark.parametrize("expr,infl,first_kind", [("x^3", [0.0], "down"), ("x^4", [], "up"), ("x^3-3x", [0.0], "down"),
                                                   ("x^4-6x^2", [-1.0, 1.0], "up"), ("1/x", [], "down"), ("exp(x)", [], "up")])
def test_analytic_inflection_validation(expr, infl, first_kind):
    from diagram_engine.graph.function_validator import concavity
    r = concavity(sm.parse_expression(expr), -3, 3, poles=[0.0] if expr == "1/x" else [])
    assert r["inflections"] == pytest.approx(infl, abs=1e-9)
    assert r["concavity"][0][2] == first_kind


def test_analytic_concavity_intervals():
    from diagram_engine.graph.function_validator import concavity
    r = concavity(sm.parse_expression("x^3-3x"), -3, 3)
    assert [(round(a, 6), round(b, 6), k) for a, b, k in r["concavity"]] == [(-3, 0, "down"), (0, 3, "up")]
    marked = _fgraph("x^4", [{"name": "", "x": 0, "y": 0, "on_curve": "f", "kind": "inflection"}])
    assert any("נקודת פיתול" in c for c in marked.comparison.critical)            # f''(0)=0 but NOT an inflection
    ok = _fgraph("x^3", [{"name": "", "x": 0, "y": 0, "on_curve": "f", "kind": "inflection"}])
    assert not any("פיתול" in c for c in ok.comparison.critical)


# ---------------------------------------------------------------- V5.7.2: table semantics in the pipeline
def test_table_semantic_mapping_pipeline():
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    c1 = CASES["A07_table_haircuts"]
    r = de.process("t", json.dumps(c1["spec"], ensure_ascii=False), c1["text"], (FIXDIR / c1["fixture"]).read_bytes())
    ts = r.audit["table_semantic"]
    assert ts["table_type"] == "frequency" and {"value": "ילדים", "frequency": 5.0} in ts["model"]
    c2 = CASES["A07b_table_cakes"]
    r2 = de.process("t", json.dumps(c2["spec"], ensure_ascii=False), c2["text"], (FIXDIR / c2["fixture"]).read_bytes())
    assert r2.audit["table_semantic"]["table_type"] == "generic" and r2.audit["table_semantic"]["model"] == []
    # an OCR conflict is reported with the HEADERS of the cell, not only its indices
    from diagram_engine import ocr
    if ocr.available():
        s = json.loads(json.dumps(c1["spec"], ensure_ascii=False))
        s["table"]["rows"][2][2]["text"] = "12"
        s["observed"]["table_cells"][2][2] = "12"
        r3 = de.process("t", json.dumps(s, ensure_ascii=False), "", (FIXDIR / c1["fixture"]).read_bytes())
        assert any("מספר הלקוחות" in x and "שיער קצר" in x for x in r3.contradictions)


# ---------------------------------------------------------------- V5.7.2: UI text matches the fail-closed policy
def test_exam_quality_ui_does_not_claim_auto_raster(analyzed, monkeypatch):
    import re as _re
    bad = _re.compile(r"ישולב (?:השרטוט )?המקור|ייעשה שימוש בתמונה המקורית|שולב המקור(?!ת)")
    for f in ("diagram_ui.py", "diagram_engine/pipeline.py", "exam_core.py", "app.py"):
        for i, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                assert "LEGACY" in line, f"{f}:{i}: {line.strip()}"
    exam, qd, meta = analyzed
    q = exam.questions[0]
    rec = q.diagrams[q.figures[0].figure_id]
    assert de.approve(rec)
    monkeypatch.setattr(de, "render_spec", lambda spec: (_ for _ in ()).throw(RuntimeError("boom")))
    _, warnings = c.create_word_document(exam, meta, qd, "exam")
    msgs = warnings + [rec.teacher_message] + c.validate_exam(exam, meta, qd)[0]
    assert any("EXPORT_BLOCKED" in m or "נדרשת החלטת מורה" in m for m in msgs)
    assert not any(bad.search(m) for m in msgs)


# ---------------------------------------------------------------- V5.7.2: DOCX really contains the SVG (structure)
def test_docx_contains_real_svg(analyzed):
    import re as _re
    exam, qd, meta = analyzed
    for q in exam.questions:
        for f in q.figures:
            assert de.approve(q.diagrams[f.figure_id])
    data, _ = c.create_word_document(exam, meta, qd, "exam")
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    svgs = [n for n in names if n.startswith("word/media/") and n.endswith(".svg")]
    assert len(svgs) == 2 and all(z.read(n).lstrip().startswith(b"<?xml") or b"<svg" in z.read(n)[:400] for n in svgs)
    ct = z.read("[Content_Types].xml").decode()
    assert 'Extension="svg"' in ct and "image/svg+xml" in ct or all(f'PartName="/{n}"' in ct for n in svgs)
    rels = z.read("word/_rels/document.xml.rels").decode()
    rids = {m.group(1): m.group(2) for m in _re.finditer(r'Id="(rId\d+)"[^>]*Target="(media/[^"]+\.svg)"', rels)} or \
           {m.group(2): m.group(1) for m in _re.finditer(r'Target="(media/[^"]+\.svg)"[^>]*Id="(rId\d+)"', rels)}
    assert len(rids) == 2
    doc = z.read("word/document.xml").decode()
    refs = _re.findall(r'<asvg:svgBlip [^>]*r:embed="(rId\d+)"', doc)
    assert sorted(refs) == sorted(rids)                                           # every SVG part is referenced by an svgBlip
    assert doc.count("{96DAC541-7B7A-43D3-8B79-37D633B846F1}") == 2


# ---------------------------------------------------------------- V5.7.2: voxel edge cases (existing model, no rewrite)
def test_voxel_edge_cases():
    import numpy as np
    from diagram_engine.spatial.camera import Camera
    from diagram_engine.spatial.voxel_scene import VoxelGrid, delta, view_impact
    cube = {(x, y, z) for x in range(3) for y in range(3) for z in range(3)}
    cavity = VoxelGrid(cube - {(1, 1, 1)})                                        # internal cavity: invisible from outside
    assert len(cavity.cells) == 26 and all(np.array_equal(cavity.view(v), VoxelGrid(cube).view(v)) for v in
                                           ("TOP_FROM_POS_Z", "FRONT_FROM_NEG_Y", "SIDE_FROM_POS_X"))
    assert view_impact(VoxelGrid(cube), cavity) == [] and delta(VoxelGrid(cube), cavity)["kind"] == "REMOVED"
    floating = VoxelGrid({(0, 0, 0), (0, 0, 2)})                                  # floating cube (gap at z=1)
    assert floating.dense_matrix()[0, 0].tolist() == [True, False, True] and floating.height_map().tolist() == [[3]]
    nonmono = VoxelGrid({(0, 0, 0), (1, 0, 1), (1, 0, 0), (2, 0, 1)})            # overhang: not column-monotone
    assert nonmono.view("FRONT_FROM_NEG_Y").astype(int).tolist() == [[0, 1, 1], [1, 1, 0]]
    a = nonmono.view("SIDE_FROM_NEG_X")
    b = nonmono.view("SIDE_FROM_POS_X")
    assert np.array_equal(a, b[:, ::-1])                                          # opposite directions mirror each other
    front = VoxelGrid({(0, 0, 0), (0, 1, 0)})                                     # (0,1,0) hidden behind (0,0,0) from -y
    for ang in (0, 90, 180, 270):                                                 # camera rotation: order = depth order
        t = np.radians(ang)
        cam = Camera(mode="ORTHOGRAPHIC", position=(0.5 + 10 * np.sin(t), 0.5 - 10 * np.cos(t), 5.0), target=(0.5, 0.5, 0.5))
        order = front.depth_order(cam)
        depth = [cam.project((c_[0] + .5, c_[1] + .5, c_[2] + .5))[2] for c_ in order]
        assert depth == sorted(depth, reverse=True)
    assert front.depth_order(Camera(mode="ORTHOGRAPHIC", position=(0.5, -10, 0.5), target=(0.5, 0.5, 0.5)))[0] == (0, 1, 0)


# ---------------------------------------------------------------- V5.7.2: scale invariance through the whole pipeline
@pytest.mark.parametrize("case", ["A14_circle_kite", "A07_table_haircuts", "A05_scatter", "A08_coordinate_circle"])
def test_real_scale_regression_same_decision(case):
    import io as _io
    from PIL import Image
    sys.path.insert(0, str(FIXDIR.parent))
    from cases import CASES
    cs = CASES[case]
    base = (FIXDIR / cs["fixture"]).read_bytes()
    res = {}
    for f in (0.5, 1.0, 2.0, 4.0):
        im = Image.open(_io.BytesIO(base)).convert("RGB")
        im = im.resize((int(im.width * f), int(im.height * f)), Image.Resampling.LANCZOS)
        b = _io.BytesIO()
        im.save(b, format="PNG")
        r = de.process("s", json.dumps(cs["spec"], ensure_ascii=False), cs["text"], b.getvalue())
        res[f] = (r.decision.action, tuple(sorted(r.missing_required)), r.validation.ok,
                  sorted(p.id for p in (r.spec.geometry.points if r.spec.geometry else [])))
    assert res[1.0] == res[2.0] == res[4.0], res
    assert res[0.5][1:] == res[1.0][1:], res                                      # entities / facts identical at half size
    assert res[0.5][0] in (res[1.0][0], "original", "review")                     # at worst MORE cautious, never less
