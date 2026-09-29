"""V5.7.5 integration closure - one regression group per task (written FIRST, against the 5.7.4 code)."""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import exam_core as c  # noqa: E402


def _exam(qs):
    return c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="", translated_instructions="",
                          labels=c.HEBREW_LABELS, questions=qs)


def _meta(n=1):
    return {"school_name": "", "exam_name": "t", "grade": "", "level": "", "teacher_name": "", "duration": 90, "num_questions": n,
            "language": "עברית", "date": "", "instructions": "", "choice_groups": [], "logo_bytes": None}


def _q(total, secs, groups=(), rubric=None, text="שאלה"):
    """secs: [(id, points, group_id)]"""
    q = c.empty_question(1, total, "")
    q.analysis_error = ""
    q.text = text
    q.sections = [c.QuestionSection(section_id=s, text="t", points=p, selection_group=g) for s, p, g in secs]
    q.selection_groups = [c.SelectionGroup(group_id=g, choose_k=k) for g, k in groups]
    q.solution_steps = [c.SolutionStep(section_id=s, step_title="t", content="c", final_answer="a") for s, _, _ in secs]
    rub = rubric if rubric is not None else [100 * c.scoring.points_if_answered(q, s) / total for s, _, _ in secs]
    q.rubric_steps = [c.RubricStep(section_id=s, stage_desc="d", percentage=r, full_credit="f", partial_credit="p", zero_credit="z")
                      for (s, _, _), r in zip(secs, rub)]
    q.teacher_verified = True
    return q


def _errors(q):
    return [e for e in c.validate_exam(_exam([q]), _meta(), [{"question_number": 1, "images": []}])[0] if any(w in e for w in ("סעיף", "סעיפ", "מחוון", "ניקוד"))]


# ================================================================ TASK 1: k-of-n scoring
@pytest.mark.parametrize("total,n,k", [(20, 4, 3), (30, 3, 2), (12, 5, 4)])
def test_k_of_n_rebalance_validate_rubric(total, n, k):
    secs = [(sid, 1.0, "g") for sid in "אבגדה"[:n]]
    q = _q(total, secs, [("g", k)], rubric=[10] * n)
    c.rebalance_question(q)                                               # the UI auto-balance action
    per = total / k
    assert all(abs(s.points - per) < 0.011 for s in q.sections), [s.points for s in q.sections]   # NOT total/n
    assert _errors(q) == []
    assert abs(sum(r.percentage for r in q.rubric_steps) - 100 * n / k) < 0.5


def test_mandatory_plus_choose_one_of_two():
    q = _q(20, [("א", 1, ""), ("ב", 1, "g"), ("ג", 1, "g")], [("g", 1)], rubric=[10, 10, 10])
    c.rebalance_question(q)
    pts = {s.section_id: s.points for s in q.sections}
    assert pts == {"א": 10.0, "ב": 10.0, "ג": 10.0}                       # answered paths: א + (ב or ג) = 20
    assert _errors(q) == [] and c.scoring.answered_total(q) == 20


def test_ordinary_question_unchanged():
    q = _q(20, [("א", 3, ""), ("ב", 5, "")], rubric=[30, 30])
    c.rebalance_question(q)
    assert [s.points for s in q.sections] == [7.5, 12.5] and sum(r.percentage for r in q.rubric_steps) == 100
    assert _errors(q) == []


def test_k_of_n_bad_config_is_an_error_and_prompt_is_qualified():
    q = _q(20, [(s, 5.0, "g") for s in "אבגד"], [("g", 3)], rubric=[25] * 4)
    assert _errors(q)                                                     # 4 x 5 is WRONG for choose 3 of 4
    assert "The sum of section points must equal the question's authoritative total points given to you." not in c.QUESTION_SYSTEM_PROMPT


def test_k_of_n_student_docx_shows_the_rule_but_no_points():
    """V5.7.6: the STUDENT exam states the rule without internal point values; the rubric keeps them."""
    q = _q(20, [(s, 1.0, "g") for s in "אבגד"], [("g", 3)], rubric=[10] * 4)
    c.rebalance_question(q)
    qd = [{"question_number": 1, "points": 20, "images": []}]
    data, _ = c.create_word_document(_exam([q]), _meta(), qd, "exam")
    txt = "".join(re.findall(r"<w:t[^>]*>([^<]+)</w:t>", zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()))
    assert "ענו על שלושה מארבעת הסעיפים א–ד." in txt and "6.67" not in txt and "נקודות" not in txt
    rub, _ = c.create_word_document(_exam([q]), _meta(), qd, "rubric")
    rtxt = "".join(re.findall(r"<w:t[^>]*>([^<]+)</w:t>", zipfile.ZipFile(io.BytesIO(rub)).read("word/document.xml").decode()))
    assert "6.67" in rtxt


# ================================================================ TASK 2: structural formula cross-check
@pytest.mark.parametrize("a,b,kind", [("x+3", "x-3", "sign"), ("\\frac{2}{x}", "\\frac{x}{2}", "fraction"), ("x^{3}", "3x", "structure"),
                                      ("\\sqrt{x+3}", "\\sqrt{x}+3", "structure"), ("\\int_{1}^{5}f(x)dx", "\\int_{5}^{1}f(x)dx", "bounds"),
                                      ("a+2", "b+2", "symbol"), ("x^{3}-12x", "x^{5}-12x", "number")])
def test_structural_formula_differences_detected(a, b, kind):
    from diagram_engine import formula_pipeline as fp
    diffs = fp.compare_structure(a, b)
    assert diffs, (a, b)
    assert fp.compare_structure(a, a) == []


def test_unrelated_number_elsewhere_does_not_validate_a_wrong_exponent():
    from diagram_engine import formula_pipeline as fp
    text_layer = "נתונה הפונקציה f(x) = x3 − 12x .\nלאחר 5 ימים נמדד ..."
    fs = fp.question_formulas(["$f(x)=x^{5}-12x$"])
    assert fp.cross_check(fs, text_layer)                                  # 5 exists elsewhere - still a conflict
    ok = fp.question_formulas(["$f(x)=x^{3}-12x$"])
    assert fp.cross_check(ok, text_layer) == []


# ================================================================ TASK 3: comma / coordinates
@pytest.mark.parametrize("text,expected", [("(3,4)", ["3", "4"]), ("(-2,5)", ["-2", "5"]), ("(3,-4)", ["3", "-4"]), ("(1.5,2.75)", ["1.5", "2.75"]),
                                           ("1,000", ["1000"]), ("1,000,000", ["1000000"]), ("הנקודה A(3,4) נמצאת", ["3", "4"]),
                                           ("y=2x+1 עובר ב-(0,1)", ["2", "1", "0", "1"])])
def test_context_aware_numeric_tokens(text, expected):
    from diagram_engine import formula_pipeline as fp
    assert fp.numeric_tokens(text) == expected


def test_correct_coordinate_is_never_uncertain_because_of_commas():
    from diagram_engine import formula_pipeline as fp
    fs = fp.question_formulas(["הנקודה $A(3,4)$ נמצאת על הישר."])
    assert fp.cross_check(fs, "A(3,4) נמצאת על הישר") == []


# ================================================================ TASK 4: formula validation fingerprint
def _fq(text):
    q = c.empty_question(1, 10, "")
    q.analysis_error = ""
    q.text = text
    q.solution_steps = [c.SolutionStep(section_id="", step_title="t", content="c", final_answer="a")]
    return q


def _formula_errors(q, layer):
    qd = [{"question_number": 1, "images": [], "document": {"text_layer": layer}}]
    return [e for e in c.validate_exam(_exam([q]), _meta(), qd)[0] if "FORMULA" in e]


LAYER = "f(x) = x3 − 12x"


def test_wrong_then_corrected_formula_revalidates():
    q = _fq("נתונה $f(x)=x^{5}-12x$.")
    c.check_formulas(q, LAYER)
    assert q.formula_uncertain and _formula_errors(q, LAYER)
    q.text = "נתונה $f(x)=x^{3}-12x$."                                   # teacher fixes the exponent
    assert _formula_errors(q, LAYER) == []                                # stale 'uncertain' is not reused


def test_correct_then_broken_by_teacher_is_caught_even_if_verified():
    q = _fq("נתונה $f(x)=x^{3}-12x$.")
    c.check_formulas(q, LAYER)
    q.teacher_verified = True
    c.mark_teacher_verified(q)
    for bad in ("נתונה $f(x)=x^{3}+12x$.", "נתונה $f(x)=x^{4}-12x$.", "נתונה $g(x)=x^{3}-12x$.", "נתונה $f(x)=x^{3}-13x$."):
        q.text = bad
        assert any("FORMULA" in e for e in _formula_errors(q, LAYER)), bad


def test_hebrew_only_edit_keeps_the_validation():
    q = _fq("נתונה $f(x)=x^{3}-12x$.")
    c.check_formulas(q, LAYER)
    fp0 = q.formula_fingerprint
    q.text = "נתונה הפונקציה $f(x)=x^{3}-12x$ בתחום הגדרתה."
    assert c.formula_fingerprint(q) == fp0 and _formula_errors(q, LAYER) == []


# ================================================================ TASK 5: PASS 2 reconstruction context
def test_pass2_receives_subpart_givens_but_not_goals_or_claims(monkeypatch):
    import mock_gemini
    mock_gemini.install()
    sent = []
    orig = c.GeminiService.generate

    def spy(self, parts, schema, *a, **k):
        if schema.__name__ == "AIDiagramSpec":
            sent.append(" ".join(getattr(p, "text", "") or "" for p in parts))
        return orig(self, parts, schema, *a, **k)
    monkeypatch.setattr(c.GeminiService, "generate", spy)
    ai = c.QuestionAI(topic="t", text="במשולש ABC הנקודה D על BC.",
                      sections=[c.QuestionSection(section_id="א", text="חשבו את AD.", points=10),
                                c.QuestionSection(section_id="ב", text="E היא אמצע AB, והוכיחו כי AB=CD.", points=10)],
                      figures=[c.FigureRef(description="f", section_id="סעיף ב", bbox=[])])
    q = c.postprocess_question(ai, 1, 20, 1)
    from test_app import page_image
    img = page_image()
    c.extract_diagrams_pass2(c.GeminiService("k"), q, {"images": [img], "masters": [img]})
    ctx = sent[0]
    assert "E היא אמצע AB" in ctx and "D על BC" in ctx                   # stem + subpart givens reach PASS 2
    assert "AB=CD" not in ctx.split("GIVENS")[1].split("QUESTION TEXT")[0]  # the claim is NOT a given
    assert "חשבו את AD" not in ctx.split("GIVENS")[1].split("QUESTION TEXT")[0]


# ================================================================ TASK 6: FigureRef.section_id
@pytest.mark.parametrize("raw", ["ב", "סעיף ב", "ב.", "(ב)", "ב)", "סעיף ב.", " ב "])
def test_section_id_forms_are_canonical(raw):
    assert c.clean_section_id(raw) == "ב"


def test_figure_with_section_label_binds_to_its_subpart_in_docx():
    ai = c.QuestionAI(topic="t", text="גזע",
                      sections=[c.QuestionSection(section_id="(א)", text="SECTION_A", points=10),
                                c.QuestionSection(section_id="ב.", text="SECTION_B", points=10)],
                      figures=[c.FigureRef(description="f", section_id="סעיף ב", bbox=[])])
    q = c.postprocess_question(ai, 1, 20, 1)
    assert [s_.section_id for s_ in q.sections] == ["א", "ב"] and q.figures[0].section_id == "ב"
    # actual DOCX placement: the figure comes AFTER section ב's text and not before section א
    import diagram_engine as de
    from diagram_engine.schemas import DiagramSpec
    from test_app import page_image
    spec = {"diagram_type": "graph", "confidence": 0.95, "labels": [{"text": "x", "confidence": 0.99}, {"text": "y", "confidence": 0.99}],
            "graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -3, "y_max": 3, "x_label": "x", "y_label": "y"},
                      "curves": [{"id": "f", "expression": "x"}]},
            "observed": {"num_curves": 1}}
    q.diagram_specs[q.figures[0].figure_id] = DiagramSpec.model_validate(spec)
    img = de.render_spec(de.process("s", json.dumps(spec), "", None).spec)[1]      # a source that really shows the graph
    c.attach_diagrams(q, [img], masters=[img])
    assert de.approve(q.diagrams[q.figures[0].figure_id])
    q.solution_steps = [c.SolutionStep(section_id=s_, step_title="t", content="c", final_answer="a") for s_ in "אב"]
    data, _ = c.create_word_document(_exam([q]), _meta(), [{"question_number": 1, "points": 20, "images": [img]}], "exam")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert xml.index("SECTION_A") < xml.index("SECTION_B") < xml.index("svgBlip")


# ================================================================ TASK 7: evidence bound to source identity
def _item(b):
    import image_store as ims
    return ims.ImageItem.from_bytes(b) if hasattr(ims.ImageItem, "from_bytes") else None


def test_pdf_evidence_follows_source_not_number():
    from document.state import build_questions_data
    from test_app import page_image
    from PIL import Image
    a = page_image()
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, format="PNG")
    other = buf.getvalue()
    ev = {c.image_digest(a): {"source_question": 7, "text_layer": "PDF TEXT", "response_templates": []}}
    mk = lambda b: {"current": b, "master": b}  # noqa: E731
    pts = {1: 10, 2: 10}
    # PDF Q2 replaced by an unrelated image -> no evidence
    qd = build_questions_data({1: [mk(other)], 2: [mk(other)]}, pts, 2, source_evidence=ev)
    assert all("document" not in d for d in qd)
    # renumbered: the PDF source moved from Q2 to Q1 -> evidence follows the source
    qd = build_questions_data({1: [mk(a)], 2: [mk(other)]}, pts, 2, source_evidence=ev)
    assert qd[0]["document"]["text_layer"] == "PDF TEXT" and "document" not in qd[1]


# ================================================================ TASK 8: symbolic conics
@pytest.mark.parametrize("eq,kind", [("x^2/a^2+y^2/b^2=1", "ellipse"), ("x^2/R^2+y^2/R^2=1", "circle"), ("y^2=2px", "parabola"),
                                     ("x^2=2py", "parabola"), ("x^2/a^2-y^2/b^2=1", "hyperbola")])
def test_symbolic_conics_are_represented_without_numbers(eq, kind):
    import diagram_engine as de
    from diagram_engine.semantic import bridge
    con = bridge.conic_from_text(eq)
    assert con["kind"] == kind and con["symbolic"] and con["parameters"]
    r = de.process("s", json.dumps({"diagram_type": "graph", "confidence": 0.9, "labels": [], "semantics": {"conics": [{"equation": eq}]}}), "", None)
    assert r.audit["semantics"]["symbolic"] and r.decision.action != "high_confidence_preview"   # never a guessed numeric drawing


# ================================================================ TASK 9: symbolic complex polar form
@pytest.mark.parametrize("text", ["r(\\cos\\theta+i\\sin\\theta)", "r(cos(theta)+i sin(theta))", "2(\\cos\\alpha+i\\sin\\alpha)"])
def test_symbolic_polar_complex_is_preserved(text):
    from diagram_engine.semantic import complex_numbers as cx
    r, t = cx.parse_polar(text)
    assert not r.is_Float and not t.is_number


def test_ui_auto_balance_uses_the_canonical_scoring_model():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "core.rebalance_question(q)" in src
    import inspect
    assert "scoring.rebalance(q)" in inspect.getsource(c.rebalance_question)
    q = _q(20, [(s, 1.0, "g") for s in "אבגד"], [("g", 3)], rubric=[10] * 4)
    c.rebalance_question(q)                           # exactly what the UI button runs
    assert {round(s.points, 2) for s in q.sections} == {6.67}
