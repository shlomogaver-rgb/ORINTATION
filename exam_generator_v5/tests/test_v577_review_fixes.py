"""V5.7.7: one regression per finding of the 5.7.6 deep review (written FIRST, against the 5.7.6 code)."""
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
import scoring  # noqa: E402
import text_structure as ts  # noqa: E402
from test_v575_closure import _exam, _meta  # noqa: E402


def _xml(data):
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


# ---- 1 (P0) absolute value -> native Word delimiter (not lone '|' runs)
@pytest.mark.parametrize("latex", ["|x|", "g(x)=|f(x)|", "|\\overrightarrow{AB}|=|\\overrightarrow{CD}|", "0<|q|<1", "\\left|x-2\\right|<5",
                                   "|\\overrightarrow{FE}|^{2}=2+h^{2}", "|z|^2=z\\bar{z}", "\\frac{|a|}{|b|}"])
def test_abs_value_is_a_native_delimiter(latex):
    from lxml import etree
    xml = etree.tostring(c.latex_to_omml(latex), encoding="unicode")
    assert "<m:d>" in xml and 'm:begChr m:val="|"' in xml
    assert not re.search(r"<m:t>\|</m:t>", xml)


def test_abs_value_survives_the_pdf_export():
    q = c.empty_question(1, 10, "")
    q.analysis_error, q.text, q.teacher_verified = "", ("נתון: $|x-2|=|y|$ וגם $g(x)=|f(x)|$ וגם $|FE|^{2}=2+h^{2}$, "
                                                      "כאשר $x\\to0^{+}$ וגם $f\\to0^{-}$ וגם $P(A\\mid B)+P(C\\mid D)$."), True
    q.solution_steps = [c.SolutionStep(section_id="", step_title="t", content="c", final_answer="a")]
    data, _ = c.create_word_document(_exam([q]), _meta(), [{"question_number": 1, "points": 10, "images": []}], "exam")
    pdf, _ = c.docx_to_pdf_bytes(data, "exam")
    if not pdf:
        pytest.skip("NOT RUN - LibreOffice unavailable")
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        txt = subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout
    assert "¿" not in txt and "∨" not in txt


# ---- 2 (P0) a line ending with a formula is not merged with the next sentence
@pytest.mark.parametrize("text", ["נתונה הפונקציה $f(x)=x^2-4$\nהנקודה A נמצאת על גרף הפונקציה.",
                                  "נתון $AB=5$\nהנקודה D נמצאת על BC."])
def test_formula_line_end_is_a_paragraph_boundary(text):
    assert len(ts.blocks(text)) == 2


def test_real_soft_wrap_still_joined():
    assert [b.text for b in ts.blocks("נתון כי הנקודה A נמצאת על גרף\nהפונקציה.")] == ["נתון כי הנקודה A נמצאת על גרף הפונקציה."]


# ---- 3 (P1) graph fidelity for axes at the edge / first quadrant, and it still catches a wrong trend
def _g(expr, x0, x1, y0, y1):
    return {"diagram_type": "graph", "confidence": 0.95, "labels": [{"text": "x", "confidence": 1}, {"text": "y", "confidence": 1}],
            "graph": {"axes": {"x_min": x0, "x_max": x1, "y_min": y0, "y_max": y1, "show_grid": False, "show_numbers": False},
                      "curves": [{"id": "f", "expression": expr}]}, "observed": {"num_curves": 1}}


@pytest.mark.parametrize("expr,w", [("10*1.2^x", (0, 10, 0, 70)), ("100*0.8^x", (0, 10, 0, 110)), ("x^2-1", (0, 5, -1, 10)),
                                    ("sqrt(x)", (0, 9, 0, 4)), ("5-x", (0, 5, 0, 6))])
def test_edge_axes_are_verifiable(expr, w):
    import diagram_engine as de
    from diagram_engine.graph import fidelity as F
    png = de.render_spec(de.process("s", json.dumps(_g(expr, *w)), "", None).spec)[1]
    assert F.check(png, png, 1)["decision"] == "PASS"


def test_first_quadrant_growth_vs_decay_is_a_mismatch():
    import diagram_engine as de
    src = de.render_spec(de.process("s", json.dumps(_g("10*1.2^x", 0, 10, 0, 70)), "", None).spec)[1]
    r = de.process("r", json.dumps(_g("60*0.8^x", 0, 10, 0, 70)), "", src)
    assert r.audit["graph_fidelity"]["decision"] == "MISMATCH" and not de.approve(r)


# ---- 4 (P1) thousands separators are not punctuation
def test_thousands_separators_do_not_trigger_structure_mismatch():
    q = c.postprocess_question(c.QuestionAI(topic="t", text="הסכום הוא 2100 שקלים, ולאחר מכן 22680 שקלים."), 1, 20, 1)
    assert ts.fidelity_issues(q, "הסכום הוא 2,100 שקלים, ולאחר מכן 22,680 שקלים.", True) == []
    q2 = c.postprocess_question(c.QuestionAI(topic="t", text="נתון כי $AB=AC$ D על BC E על AC."), 1, 20, 1)
    assert ts.fidelity_issues(q2, "נתון כי AB=AC, D על BC, E על AC. הנקודה (3,4).", True)       # real commas still counted


# ---- 5 (P1) OCR structure evidence for images detects the subpart markers
def test_image_ocr_finds_subpart_markers():
    from diagram_engine import ocr
    if not ocr.available():
        pytest.skip("NOT RUN - Tesseract unavailable")
    img = (ROOT / "tests/acceptance_real/teacher_holdout_1/h2_abs_options.png").read_bytes()
    q = c.empty_question(1, 20, "")
    c.check_text_structure(q, {"images": [img]})
    labels = ts.source_structure(q.text_structure_source.get("text", ""))["section_labels"]
    assert len(labels) >= 4, labels                                 # the image shows א–ה


# ---- 6 (P1) teacher verification is bound to the structure too
def test_structural_edit_after_verification_requires_reverification():
    ai = c.QuestionAI(topic="t", text="במשולש ABC.", sections=[c.QuestionSection(section_id=s, text="מצאו.", points=5) for s in "אבגד"])
    q = c.postprocess_question(ai, 1, 20, 1)
    q.solution_steps = [c.SolutionStep(section_id=s.section_id, step_title="t", content="c", final_answer="a") for s in q.sections]
    c.mark_teacher_verified(q)
    q.sections = q.sections[:3]
    q.sections[-1].points = 10
    errs = c.validate_exam(_exam([q]), _meta(), [{"question_number": 1, "images": []}])[0]
    assert any("REVALIDATION" in e for e in errs)


# ---- 7 (P1) k-of-n rebalance keeps general rubric stages
def test_rebalance_keeps_general_rubric_stages():
    q = c.empty_question(1, 20, "")
    q.sections = [c.QuestionSection(section_id=s, text="t", points=1, selection_group="g") for s in "אבגד"]
    q.selection_groups = [c.SelectionGroup(group_id="g", choose_k=3)]
    q.rubric_steps = [c.RubricStep(section_id="", stage_desc="כללי", percentage=10, full_credit="f", partial_credit="p", zero_credit="z")] + \
                     [c.RubricStep(section_id=s, stage_desc="d", percentage=20, full_credit="f", partial_credit="p", zero_credit="z") for s in "אבגד"]
    c.rebalance_question(q)
    assert q.rubric_steps[0].percentage == pytest.approx(10, abs=0.01)
    assert scoring.check(q) == []


# ---- 8 (P1) PDF evidence vs teacher edits of the source image
def test_teacher_crop_invalidates_response_templates_but_keeps_source_text():
    from document.state import build_questions_data
    from test_app import page_image
    a = page_image()
    ev = {c.image_digest(a): {"text_layer": "PDF", "response_templates": [{"role": "ANSWER_BOX"}], "import_ops_hash": ""}}
    qd = build_questions_data({1: [{"current": a, "master": a, "ops_hash": ""}]}, {1: 10}, 1, source_evidence=ev)
    assert qd[0]["document"]["response_templates"]
    qd = build_questions_data({1: [{"current": a, "master": a, "ops_hash": "cropped-123"}]}, {1: 10}, 1, source_evidence=ev)
    assert qd[0]["document"]["text_layer"] == "PDF" and qd[0]["document"]["response_templates"] == []
    assert qd[0]["document"]["edited_after_import"] is True


# ---- 9 (P2) subsection indentation on the START (right) side in RTL
def test_subsection_indent_uses_the_bidi_start_side():
    q = c.postprocess_question(c.QuestionAI(topic="t", text="t", sections=[c.QuestionSection(section_id="ב", text="(1) מצאו.\n(2) חשבו.", points=20)]), 1, 20, 1)
    q.solution_steps = [c.SolutionStep(section_id="ב", step_title="t", content="c", final_answer="a")]
    xml = _xml(c.create_word_document(_exam([q]), {**_meta(), "preserve_source_lines": False},
                                      [{"question_number": 1, "points": 20, "images": []}], "exam")[0])
    p2 = next(p for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S) if "(2) חשבו" in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))
    assert re.search(r'<w:ind [^>]*w:(?:start|left)="(?:4\d\d|8\d\d)"', p2), p2[:300]


# ---- 10 (P2) Hebrew-letter and numeric-dot subsections
@pytest.mark.parametrize("text", ["(א) מצאו את x.\n(ב) הוכיחו.", "1. מצאו את x.\n2. הוכיחו."])
def test_more_subsection_forms(text):
    assert [b.block_type for b in ts.blocks(text)] == ["SUBSECTION", "SUBSECTION"]


# ---- 11 (P2) non-contiguous choice group wording
def test_non_contiguous_choice_group_lists_members():
    q = c.empty_question(1, 20, "")
    q.sections = [c.QuestionSection(section_id="א", text="t", points=10), c.QuestionSection(section_id="ב", text="t", points=10, selection_group="g"),
                  c.QuestionSection(section_id="ג", text="t", points=0), c.QuestionSection(section_id="ד", text="t", points=10, selection_group="g")]
    q.selection_groups = [c.SelectionGroup(group_id="g", choose_k=1)]
    note = c.student_choice_note(q)
    assert "ב–ד" not in note and "ב" in note and "ד" in note


# ---- 12 (P2) UI control for question points
def test_ui_has_a_question_points_control():
    assert "show_question_points" in (ROOT / "app.py").read_text(encoding="utf-8")


# ---- 13 (P2) mixed graph+geometry goes through the fidelity gate
def test_mixed_graph_is_fidelity_checked():
    import diagram_engine as de

    def mixed(expr):
        return {"diagram_type": "mixed_graph_geometry", "confidence": 0.9, "labels": [{"text": "x", "confidence": 1}, {"text": "y", "confidence": 1}],
                "mixed": {"graph": {"axes": {"x_min": -3, "x_max": 3, "y_min": -6, "y_max": 6, "show_grid": False, "show_numbers": False},
                                    "curves": [{"id": "f", "expression": expr}]}, "geometry": {"points": []}}, "observed": {"num_curves": 1}}
    src = de.render_spec(de.process("s", json.dumps(mixed("x^2+1")), "", None).spec)[1]
    r = de.process("r", json.dumps(mixed("-x^2-1")), "", src)
    assert r.audit.get("graph_fidelity", {}).get("decision") == "MISMATCH"


# ---- 14 (P3) solutions document without w:br inside steps
def test_solution_steps_are_paragraphs_not_line_breaks():
    q = c.empty_question(1, 10, "")
    q.analysis_error, q.text = "", "שורת גזע ראשונה.\nשורת גזע שנייה."
    q.solution_steps = [c.SolutionStep(section_id="", step_title="t", content="שורה ראשונה.\nשורה שנייה.", final_answer="תשובה 1.\nתשובה 2.")]
    xml = _xml(c.create_word_document(_exam([q]), {**_meta(), "preserve_source_lines": False},
                                      [{"question_number": 1, "points": 10, "images": []}], "solution")[0])
    assert "<w:br/>" not in xml



def test_mid_is_a_relation_never_an_absolute_value():
    from lxml import etree
    xml = etree.tostring(c.latex_to_omml("P(A\\mid B)+P(C\\mid D)"), encoding="unicode")
    assert "<m:d>" not in xml or 'm:begChr m:val="|"' not in xml


@pytest.mark.parametrize("latex", ["x\\to0^{+}", "f\\to0^{-}", "a^{\\pm}", "x_{-}"])
def test_operator_only_scripts_are_text(latex):
    from lxml import etree
    root = c.latex_to_omml(latex)
    xml = etree.tostring(root, encoding="unicode")
    assert "<m:nor/>" in xml
    M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    order = {"lit": 0, "nor": 1, "scr": 1, "sty": 2, "brk": 3, "aln": 4}
    for rpr in root.iter(M + "rPr"):                      # OOXML schema CT_RPR: nor and scr/sty are alternatives
        tags = [el.tag.replace(M, "") for el in rpr]
        assert not ("nor" in tags and ("sty" in tags or "scr" in tags)), tags
        assert [order[t] for t in tags] == sorted(order[t] for t in tags), tags
