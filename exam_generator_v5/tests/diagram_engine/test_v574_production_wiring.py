"""V5.7.4: semantic engines wired through the REAL pipeline (schema -> de.process -> validation -> render), formula pipeline,
k-of-n subparts and figure-to-subpart placement. Each engine: schema + pipeline + unseen variants."""
from __future__ import annotations

import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import diagram_engine as de  # noqa: E402
import exam_core as c  # noqa: E402
from diagram_engine.ai_schema import AIDiagramSpec, schema_is_gemini_safe, to_spec  # noqa: E402


def _proc(spec, text=""):
    return de.process("s", json.dumps(spec, ensure_ascii=False), text, None)


def test_ai_schema_exposes_typed_semantics_and_stays_gemini_safe():
    js = AIDiagramSpec.model_json_schema()
    assert "semantics" in AIDiagramSpec.model_fields and schema_is_gemini_safe(js) == []
    blob = json.dumps(js)
    for k in ("complex_plane", "conics", "vectors", "space3d", "function_relations", "formulas"):
        assert k in blob


# ---------------------------------------------------------------- complex numbers
@pytest.mark.parametrize("n,w", [(4, "16"), (3, "8i"), (6, "-64"), (5, "32")])
def test_complex_roots_build_the_drawing_in_production(n, w):
    r = _proc({"diagram_type": "geometry", "confidence": 0.9, "labels": [],
               "semantics": {"complex_plane": {"roots_of": {"n": n, "w": w}, "polygon": True}}})
    assert r.audit["semantics"]["built"] == ["complex_plane"] and r.validation.ok, r.validation.errors
    P = [(p.x, p.y) for p in r.spec.geometry.points]
    sides = [math.dist(P[k], P[(k + 1) % n]) for k in range(n)]
    assert len(P) == n and max(sides) - min(sides) < 1e-9 and "<svg" in de.render_spec(r.spec)[0]


def test_complex_semantics_verify_a_wrong_proposal():
    prop = {"diagram_type": "geometry", "confidence": 0.9, "labels": [{"text": "A", "confidence": 1}],
            "geometry": {"points": [{"id": "A", "x": 4, "y": 3}]},
            "semantics": {"complex_plane": {"numbers": [{"label": "A", "value": "3+4i"}], "polygon": False}}}
    r = _proc(prop)
    assert any("COMPLEX_POINT_CONFLICT" in m for m in r.comparison.critical) and r.decision.action == "original"
    prop["geometry"]["points"][0].update(x=3, y=4)
    assert not any("COMPLEX" in m for m in _proc(prop).comparison.critical)


def test_polar_complex_input():
    r = _proc({"diagram_type": "geometry", "confidence": 0.9, "labels": [],
               "semantics": {"complex_plane": {"numbers": [{"label": "w", "r": 2, "theta_deg": 60}], "polygon": False}}})
    p = r.spec.geometry.points[0]
    assert abs(p.x - 1) < 1e-9 and abs(p.y - math.sqrt(3)) < 1e-9


# ---------------------------------------------------------------- conics
@pytest.mark.parametrize("eq,kind", [("x^2/25+y^2/9=1", "ellipse"), ("x^2/16-y^2/9=1", "hyperbola"), ("y^2=8x", "parabola"),
                                     ("(x-1)^2+(y+2)^2=4", "circle"), ("x^2/12+y^2/4=1", "ellipse")])
def test_conic_builds_graph_in_production(eq, kind):
    r = _proc({"diagram_type": "graph", "confidence": 0.9, "labels": [], "semantics": {"conics": [{"equation": eq}]}})
    assert r.audit["semantics"]["built"] == [f"conic:{kind}"] and r.validation.ok and len(r.spec.graph.curves) == 2


def test_conic_kind_and_focus_conflicts():
    r = _proc({"diagram_type": "graph", "confidence": 0.9, "labels": [],
               "semantics": {"conics": [{"equation": "x^2/25+y^2/9=1", "claimed_kind": "hyperbola"}]}})
    assert any("CONIC_KIND_CONFLICT" in m for m in r.comparison.critical)
    prop = {"diagram_type": "graph", "confidence": 0.9, "labels": [],
            "graph": {"axes": {"x_min": -6, "x_max": 6, "y_min": -6, "y_max": 6},
                      "curves": [{"id": "u", "expression": "3*sqrt(1-x^2/25)"}], "points": [{"name": "F", "x": 5, "y": 0}]},
            "semantics": {"conics": [{"equation": "x^2/25+y^2/9=1"}]}}
    assert any("CONIC_FOCUS_CONFLICT" in m for m in _proc(prop).comparison.critical)       # true focus is (4, 0)


def test_unsupported_conic_goes_to_teacher():
    r = _proc({"diagram_type": "graph", "confidence": 0.9, "labels": [], "semantics": {"conics": [{"equation": "import os"}]}})
    assert any("SEMANTIC_UNSUPPORTED" in m for m in r.contradictions) and r.decision.action != "high_confidence_preview"


# ---------------------------------------------------------------- vectors
PYR = [{"id": "A", "x": 0, "y": 0, "z": 0}, {"id": "B", "x": 4, "y": 0, "z": 0}, {"id": "C", "x": 1, "y": 3, "z": 0},
       {"id": "S", "x": 1, "y": 1, "z": 5}, {"id": "E", "x": 3.25, "y": 0.25, "z": 1.25}, {"id": "F", "x": 1, "y": 2.5, "z": 1.25}]


@pytest.mark.parametrize("claim,ok", [({"kind": "parallel", "refs": ["EF", "BC"]}, True), ({"kind": "ratio", "refs": ["EF", "BC"], "value": 0.75}, True),
                                      ({"kind": "ratio", "refs": ["EF", "BC"], "value": 0.5}, False),
                                      ({"kind": "combination", "refs": ["BC", "u", "v"], "coeffs": [-1, 1]}, True),
                                      ({"kind": "perpendicular", "refs": ["u", "w"]}, False)])
def test_vector_claims_checked_in_production(claim, ok):
    vecs = [{"name": "u", "from_point": "A", "to_point": "B"}, {"name": "v", "from_point": "A", "to_point": "C"},
            {"name": "w", "from_point": "A", "to_point": "S"}, {"name": "EF", "from_point": "E", "to_point": "F"},
            {"name": "BC", "from_point": "B", "to_point": "C"}]
    r = _proc({"diagram_type": "spatial", "confidence": 0.9, "labels": [], "spatial": {"solids": []},
               "semantics": {"vectors": {"points": PYR, "vectors": vecs, "claims": [claim]}}})
    assert (not any("SEMANTIC_CLAIM_CONFLICT" in m for m in r.comparison.critical)) == ok


# ---------------------------------------------------------------- analytic 3D
@pytest.mark.parametrize("claim,ok", [({"kind": "on_plane", "refs": ["P", "pl"]}, True), ({"kind": "on_plane", "refs": ["Q", "pl"]}, False),
                                      ({"kind": "angle_line_plane", "refs": ["L", "pl"], "value": 45}, True),
                                      ({"kind": "distance_point_plane", "refs": ["Q", "pl"], "value": 7}, True)])
def test_space3d_claims_in_production(claim, ok):
    pts = [{"id": "P", "x": 3, "y": 5, "z": 0}, {"id": "Q", "x": 2, "y": 3, "z": 7}, {"id": "L0", "x": 0, "y": 0, "z": 3},
           {"id": "L1", "x": 1, "y": 0, "z": 2}]
    r = _proc({"diagram_type": "spatial", "confidence": 0.9, "labels": [], "spatial": {"solids": []},
               "semantics": {"space3d": {"points": pts, "lines": [{"id": "L", "through": ["L0", "L1"]}],
                                         "planes": [{"id": "pl", "equation": "z=0"}], "claims": [claim]}}})
    assert (not any("SEMANTIC_CLAIM_CONFLICT" in m for m in r.comparison.critical)) == ok


# ---------------------------------------------------------------- function dependencies on real curves
@pytest.mark.parametrize("rel,child_expr,ok", [("DERIVATIVE_OF", "2*x-4", True), ("DERIVATIVE_OF", "2*x", False),
                                               ("NEGATIVE_OF", "-(x^2-4*x)", True), ("VERTICAL_SCALE_OF", "3*(x^2-4*x)", True)])
def test_function_relations_checked_on_the_drawn_curves(rel, child_expr, ok):
    spec = {"diagram_type": "graph", "confidence": 0.9, "labels": [],
            "graph": {"axes": {"x_min": -2, "x_max": 6, "y_min": -10, "y_max": 10},
                      "curves": [{"id": "f", "expression": "x^2-4*x"}, {"id": "g", "expression": child_expr}]},
            "observed": {"num_curves": 2},
            "semantics": {"function_relations": [{"child": "g", "relation": rel, "parent": "f", **({"k": 3} if rel == "VERTICAL_SCALE_OF" else {})}]}}
    r = _proc(spec)
    assert (not any("FUNCTION_RELATION_CONFLICT" in m for m in r.comparison.critical)) == ok, r.comparison.critical


# ---------------------------------------------------------------- formula pipeline
@pytest.mark.parametrize("latex,root", [("\\frac{2x}{x^2-9}", "Fraction"), ("e^{2x}-4x", "Sum"), ("\\sqrt{x^2-1}", "Root"),
                                        ("\\ln(x-2)", "Log"), ("f(x)=2x+\\frac{2}{x}", "Equation"), ("4^{n+1}+p", "Sum"),
                                        ("\\left(2-\\frac{1}{x}\\right)^{3}", "Power"), ("0\\le x\\le 7", "Inequality")])
def test_formula_ast_round_trip(latex, root):
    from diagram_engine import formula_pipeline as fp
    r = fp.analyse(latex)
    assert r["status"] == "OK" and r["ast_root"] == root, r


def test_formula_cross_check_flags_disagreement_and_blocks_until_teacher_confirms():
    from diagram_engine import formula_pipeline as fp
    fs = fp.question_formulas(["נתונה הפונקצייה $f(x)=x^{3}-12x$."])
    assert fp.cross_check(fs, "f(x) = x3 − 12x") == []                          # same numbers in the text layer
    bad = fp.question_formulas(["נתונה הפונקצייה $f(x)=x^{5}-12x$."])            # exponent misread 3 -> 5
    assert fp.cross_check(bad, "f(x) = x3 − 12x") and fp.cross_check(bad, None) == []
    q = c.empty_question(1, 10, "")
    q.analysis_error = ""
    q.text = "נתונה הפונקצייה $f(x)=x^{5}-12x$."
    q.solution_steps = [c.SolutionStep(section_id="", step_title="t", content="c", final_answer="a")]
    c.check_formulas(q, "f(x) = x3 − 12x")
    errs, _ = c.validate_exam(c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="",
                                             translated_instructions="", labels=c.HEBREW_LABELS, questions=[q]),
                              {"choice_groups": [], "num_questions": 1}, [{"question_number": 1, "images": []}])
    assert any("FORMULA_UNCERTAIN" in e for e in errs)
    q.teacher_verified = True
    errs2, _ = c.validate_exam(c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="",
                                              translated_instructions="", labels=c.HEBREW_LABELS, questions=[q]),
                               {"choice_groups": [], "num_questions": 1}, [{"question_number": 1, "images": []}])
    assert not any("FORMULA_UNCERTAIN" in e for e in errs2)


# ---------------------------------------------------------------- k-of-n subparts, figures per subpart, RTL options
def _q_k_of_n(points, sec_points, k, rubric):
    q = c.empty_question(1, points, "")
    q.analysis_error = ""
    q.text = "ענו על שלושה מארבעת הסעיפים."
    q.required_sections = k
    q.sections = [c.QuestionSection(section_id=s, text="t", points=p) for s, p in zip("אבגד", sec_points)]
    q.solution_steps = [c.SolutionStep(section_id=s, step_title="t", content="c", final_answer="a") for s in "אבגד"]
    q.rubric_steps = [c.RubricStep(section_id=s, stage_desc="d", percentage=r_, full_credit="f", partial_credit="p", zero_credit="z")
                      for s, r_ in zip("אבגד", rubric)]
    q.teacher_verified = True
    return q


def _errs(q):
    ex = c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="", translated_instructions="",
                        labels=c.HEBREW_LABELS, questions=[q])
    return c.validate_exam(ex, {"choice_groups": [], "num_questions": 1}, [{"question_number": 1, "images": []}])[0]


def test_answer_k_of_n_subparts_scoring():
    ok = _q_k_of_n(20, [20 / 3] * 4, 3, [100 / 3] * 4)
    assert not [e for e in _errs(ok) if "סעיף" in e or "מחוון" in e]
    bad = _q_k_of_n(20, [5] * 4, 3, [25] * 4)
    assert any("מתוך 4" in e for e in _errs(bad))


def test_rtl_option_order():
    s = {"diagram_type": "graph", "subtype": "multi_choice_graphs", "confidence": 0.9, "labels": [],
         "multi_graph": {"columns": 2, "options": [{"label": l, "formula": {"axes": {"x_min": -3, "x_max": 3, "y_min": -3, "y_max": 3},
                                                                              "curves": [{"id": l, "expression": "x"}]}} for l in ("I", "II", "III", "IV")]},
         "observed": {"num_options": 4}}
    slots = dict(de.render_spec(_proc(s).spec)[2]["option_slots"])
    assert slots == {"I": 1, "II": 0, "III": 3, "IV": 2}          # right-to-left, top-to-bottom


def test_raw_model_evidence_is_kept_per_question():
    import mock_gemini
    from test_app import page_image
    from test_core import meta
    mock_gemini.install()
    svc = c.GeminiService("k")
    exam, _ = c.run_full_analysis(svc, meta(), [{"question_number": i, "points": 50.0, "images": [page_image()]} for i in (1, 2)],
                                  verify=False)
    for q in exam.questions:
        kinds = [e["schema"] for e in q.model_evidence]
        assert kinds[0] == "QuestionAI" and "AIDiagramSpec" in kinds               # raw PASS 1 and PASS 2
        assert all(e["raw_text"] and e["prompt_version"] == c.PROMPT_VERSION and e["source_hashes"] for e in q.model_evidence)
    assert exam.questions[0].model_evidence != exam.questions[1].model_evidence



@pytest.mark.parametrize("latex", ["\\frac{AB}{AC", "\\left(", "}{", "\\sqrt{", "x^{", "\\binom53"])
def test_formula_pipeline_never_crashes(latex):
    from diagram_engine import formula_pipeline as fp
    assert fp.analyse(latex)["status"] in ("UNPARSED", "INVALID", "OK")



# ---------------------------------------------------------------- structural LaTeX AST on notation NOT used to build it
@pytest.mark.parametrize("latex,root", [
    ("\\frac{x^{2}}{a^{2}}+\\frac{y^{2}}{b^{2}}=1", "Equation"),                   # conics (other exams)
    ("z=r(\\cos\\theta+i\\sin\\theta)", "Equation"),                              # complex polar form
    ("\\overrightarrow{AB}\\cdot\\overrightarrow{AC}=0", "Equation"),               # vectors
    ("\\lim_{x\\to\\infty}\\frac{2x+1}{x-3}=2", "Equation"),                      # limits
    ("\\sum_{k=1}^{n}k^{2}", "Sum_"),                                                  # sums
    ("\\log_{2}(x-1)>3", "Inequality"),                                                # log base + inequality
    ("\\int_{1}^{e}\\frac{\\ln x}{x}dx", "Integral"),
    ("\\triangle PQR\\sim\\triangle KLM", "Relation"),                              # geometry relations, other letters
    ("\\angle KLM=35^{\\circ}", "Equation"),
    ("P(A\\cap B)=0.3", "Equation"), ("P(A\\mid B)", "FunctionApplication"),          # probability
    ("\\max_{x}f(x)", "Operator"), ("3:5", "Relation"), ("x_{1,2}=\\frac{-b\\pm\\sqrt{b^{2}-4ac}}{2a}", "Equation"),
    ("\\sqrt[3]{x+1}", "Root"), ("\\left|x-2\\right|<5", "Inequality"), ("\\binom{8}{3}p^{3}(1-p)^{5}", "Product"),
    ("f''(x)", "FunctionApplication"), ("\\text{שטח}=\\frac{1}{2}ah", "Equation"),
])
def test_structural_latex_ast_on_unseen_notation(latex, root):
    from diagram_engine import latex_ast
    assert latex_ast.parse(latex).kind == root


@pytest.mark.parametrize("latex", ["\\frac{1}{", "x^", "\\unknowncmd{x}", "(a+b", "\\sqrt[3{x}"])
def test_broken_latex_is_reported_never_guessed(latex):
    from diagram_engine import formula_pipeline as fp
    assert fp.analyse(latex)["status"] == "UNPARSED"
