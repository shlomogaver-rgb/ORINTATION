"""V5.7.6: student presentation (no internal points), text structure (paragraphs / subsections / soft wraps / display
formulas), punctuation fidelity and the TEXT_STRUCTURE gate."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import exam_core as c  # noqa: E402
import text_structure as ts  # noqa: E402
from test_v575_closure import _exam, _meta  # noqa: E402


def _docx_paragraphs(q, kind="exam", keep_lines=False):
    q.solution_steps = q.solution_steps or [c.SolutionStep(section_id=s.section_id, step_title="t", content="c", final_answer="a")
                                            for s in q.sections] or [c.SolutionStep(section_id="", step_title="t", content="c", final_answer="a")]
    data, _ = c.create_word_document(_exam([q]), {**_meta(), "preserve_source_lines": keep_lines},
                                     [{"question_number": 1, "points": q.points, "images": []}], kind)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        t = "".join(re.findall(r"<(?:w|m):t[^>]*>([^<]*)</(?:w|m):t>", p))
        if t.strip():
            paras.append((t, p.count("<w:br/>")))
    return paras, xml


def _q(text, sections=(), total=20):
    ai = c.QuestionAI(topic="t", text=text, sections=[c.QuestionSection(section_id=a, text=b, points=p) for a, b, p in sections])
    return c.postprocess_question(ai, 1, total, 1)


# ---------------------------------------------------------------- scoring presentation
def test_student_exam_has_no_point_values_but_the_rubric_does():
    q = _q("שאלה עם ארבעה סעיפים.", [(s, "מצאו את $x$.", 5) for s in "אבגד"])
    paras, xml = _docx_paragraphs(q)
    txt = "".join(t for t, _ in paras)
    assert "נקודות" not in txt and "(5" not in txt
    assert [t.strip()[:2] for t, _ in paras if t.strip()[:2] in ("א.", "ב.", "ג.", "ד.")] == ["א.", "ב.", "ג.", "ד."]
    q.rubric_steps = [c.RubricStep(section_id=s_, stage_desc="d", percentage=25, full_credit="f", partial_credit="p", zero_credit="z")
                      for s_ in "אבגד"]
    r, _ = _docx_paragraphs(q, "rubric")
    assert any(t.strip() in ("5", "5.0", "5.00") for t, _ in r) and any("20 נקודות" in t for t, _ in r)   # rubric keeps scoring


def test_question_points_only_on_explicit_template_request():
    q = _q("שאלה.", [("א", "מצאו.", 20)])
    q.solution_steps = [c.SolutionStep(section_id="א", step_title="t", content="c", final_answer="a")]
    meta = {**_meta(), "show_question_points": True}
    data, _ = c.create_word_document(_exam([q]), meta, [{"question_number": 1, "points": 20, "images": []}], "exam")
    txt = "".join(re.findall(r"<w:t[^>]*>([^<]+)</w:t>", zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()))
    assert "(20 נקודות)" in txt and "א. (20" not in txt


# ---------------------------------------------------------------- structure (A-G)
def test_A_comma_after_math_preserved():
    paras, _ = _docx_paragraphs(_q("נתון כי $AB=AC$, הנקודה D נמצאת על BC."))
    assert any("AB=AC, הנקודה D" in t for t, _ in paras)


def test_B_commas_between_givens_preserved():
    paras, _ = _docx_paragraphs(_q("נתון: $AB=5$, $AC=7$."))
    assert any("AB=5, AC=7." in t for t, _ in paras)


def test_C_sections_are_separate_word_paragraphs():
    paras, _ = _docx_paragraphs(_q("במשולש ABC.", [("א", "מצאו את $x$.", 10), ("ב", "הוכיחו כי $AB=AC$.", 10)]))
    starts = [t.strip() for t, _ in paras]
    assert any(s_.startswith("א.") and "מצאו" in s_ for s_ in starts) and any(s_.startswith("ב.") and "הוכיחו" in s_ for s_ in starts)
    assert not any("מצאו" in s_ and "הוכיחו" in s_ for s_ in starts)


@pytest.mark.parametrize("sec_text", ["(1) מצאו את $AD$.\n(2) הוכיחו כי $AD\\perp BC$.",
                                      "(1) מצאו את $AD$. (2) הוכיחו כי $AD\\perp BC$."])   # the second one arrives flattened
def test_D_subsections_are_their_own_paragraphs(sec_text):
    paras, _ = _docx_paragraphs(_q("במשולש ABC.", [("ב", sec_text, 20)]))
    starts = [t.strip() for t, _ in paras]
    assert any(s_.startswith("ב.") and "(1) מצאו" in s_ for s_ in starts)
    assert any(s_.startswith("(2) הוכיחו") for s_ in starts) and not any("(1)" in s_ and "(2)" in s_ for s_ in starts)
    assert all(br == 0 for _, br in paras)                                        # no w:br emulation


def test_E_soft_wrap_is_one_paragraph():
    paras, _ = _docx_paragraphs(_q("נתון כי הנקודה A נמצאת על גרף\nהפונקציה."))
    assert any(t.strip() == "נתון כי הנקודה A נמצאת על גרף הפונקציה." for t, _ in paras)


def test_F_real_paragraph_break_is_two_paragraphs():
    for text in ("נתון כי $AB=AC$.\n\nהנקודה D נמצאת על BC.", "נתון כי $AB=AC$.\nהנקודה D נמצאת על BC."):
        paras, _ = _docx_paragraphs(_q(text))
        starts = [t.strip() for t, _ in paras]
        assert "נתון כי AB=AC." in starts and "הנקודה D נמצאת על BC." in starts


def test_G_display_formula_is_a_separate_block():
    b = ts.blocks("נתונה הפונקציה:\n$$f(x)=\\frac{x^2}{x-1}$$\nמצאו את תחום ההגדרה.")
    assert [x.block_type for x in b] == ["PARAGRAPH", "DISPLAY_FORMULA", "PARAGRAPH"]


@pytest.mark.parametrize("text,n", [("שורה ראשונה, ממשיכה\nבשורה שנייה", 1), ("משפט.\nמשפט שני.", 2), ("א\n\nב", 2),
                                    ("נתון: AB=5,\nAC=7.", 1), ("(1) א.\n(2) ב.\n(3) ג.", 3)])
def test_line_break_classification_variants(text, n):
    b = ts.blocks(text)
    assert len(b) == n and "".join(x.text for x in b).count(",") == text.count(",")     # punctuation never changes


# ---------------------------------------------------------------- TEXT_STRUCTURE gate
def _gate(q, layer, reliable=True):
    q.text_structure_source = {"text": layer, "reliable_commas": reliable}
    q.solution_steps = [c.SolutionStep(section_id=s.section_id, step_title="t", content="c", final_answer="a") for s in q.sections]
    return [e for e in c.validate_exam(_exam([q]), _meta(), [{"question_number": 1, "images": []}])[0] if "TEXT_STRUCTURE" in e]


def test_structure_gate_flags_lost_sections_subsections_and_commas():
    layer = "נתון כי AB=AC, D על BC, E על AC.\nא. מצאו.\nב. (1) חשבו.\n(2) הוכיחו.\nג. מצאו."
    good = _q("נתון כי $AB=AC$, D על BC, E על AC.", [("א", "מצאו.", 5), ("ב", "(1) חשבו.\n(2) הוכיחו.", 10), ("ג", "מצאו.", 5)])
    assert _gate(good, layer) == []
    lost_sec = _q("נתון כי $AB=AC$, D על BC, E על AC.", [("א", "מצאו.", 10), ("ב", "(1) חשבו.\n(2) הוכיחו.", 10)])
    assert any("סעיפים" in e for e in _gate(lost_sec, layer))
    lost_commas = _q("נתון כי $AB=AC$ D על BC E על AC.", [("א", "מצאו.", 5), ("ב", "(1) חשבו.\n(2) הוכיחו.", 10), ("ג", "מצאו.", 5)])
    assert any("פסיקים" in e for e in _gate(lost_commas, layer))
    assert not any("פסיקים" in e for e in _gate(lost_commas, layer, reliable=False))   # OCR commas are not trusted


def test_flattened_sections_inside_the_stem_are_flagged():
    q = _q("במשולש ABC. א. מצאו את x. ב. הוכיחו כי AB=AC.")
    assert any("המבנה שוטח" in e for e in _gate(q, None))



# ---------------------------------------------------------------- V5.7.8: source line layout (default ON in the product)
def test_source_line_breaks_are_line_breaks_inside_the_paragraph():
    paras, xml = _docx_paragraphs(_q("נתון כי הנקודה A נמצאת על גרף\nהפונקציה.\nהנקודה B על הישר."), keep_lines=True)
    stem = [p for p in paras if "נתון כי" in p[0]]
    assert len(stem) == 1 and stem[0][1] == 2                     # ONE paragraph, the two source line breaks kept as w:br


def test_subsections_stay_paragraphs_in_source_line_mode():
    paras, _ = _docx_paragraphs(_q("במשולש ABC.", [("ב", "(1) מצאו את $AD$.\n(2) הוכיחו כי\n$AD\\perp BC$.", 20)]), keep_lines=True)
    starts = [t.strip() for t, _ in paras]
    assert any(s_.startswith("(2) הוכיחו") for s_ in starts) and not any("(1)" in s_ and "(2)" in s_ for s_ in starts)
