"""V5.7.8: the new exam reproduces the SOURCE line layout (teacher request): line-break transfer from the source's visual
lines, line breaks inside the paragraph, hanging subpart labels, and a font/column fit so Word does not re-wrap."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import exam_core as c  # noqa: E402
import text_structure as ts  # noqa: E402

SRC = ["נתונות הפונקציות f(x) , f'(x) ו־ f''(x) , המוגדרות לכל x ! 0 .",
       "בסרטוט שלפניכם מתואר הגרף של פונקציית הנגזרת השנייה f''(x) .",
       "לגרף הפונקצייה f''(x) יש שלוש נקודות חיתוך עם ציר ה־ x ,",
       "ושיעוריהן הם (a , 0) , (b , 0) , (d , 0) ."]
MODEL = ("נתונות הפונקציות $f(x)$, $f'(x)$ ו־$f''(x)$, המוגדרות לכל $x\\neq0$. בסרטוט שלפניכם מתואר הגרף של פונקציית הנגזרת "
         "השנייה $f''(x)$. לגרף הפונקצייה $f''(x)$ יש שלוש נקודות חיתוך עם ציר ה־$x$, ושיעוריהן הם $(a,0)$, $(b,0)$, $(d,0)$.")


def test_breaks_are_transferred_exactly_where_the_source_broke():
    out = ts.transfer_line_breaks(MODEL, SRC).split("\n")
    assert len(out) == 4
    assert out[0].endswith("$x\\neq0$.") and out[1].startswith("בסרטוט") and out[2].endswith("ה־$x$,") and out[3].startswith("ושיעוריהן")


def test_reversed_text_layer_lines_still_align():
    rev = [" ".join(reversed(l.split())) for l in SRC]
    assert len(ts.transfer_line_breaks(MODEL, rev).split("\n")) == 4


def test_unrelated_source_changes_nothing():
    assert ts.transfer_line_breaks(MODEL, ["שאלה אחרת לגמרי על משולשים", "וזוויות במעגל"]) == MODEL


def test_characters_are_never_changed_only_whitespace():
    out = ts.transfer_line_breaks(MODEL, SRC)
    assert out.replace("\n", " ").split() == MODEL.split()


def test_font_fit_keeps_long_source_lines_on_one_word_line():
    long_line = "ענו על שניים מארבעת הסעיפים א–ד שלפניכם. אם תענו על יותר משני סעיפים, ייבדקו רק שתי התשובות הראשונות"
    q = c.postprocess_question(c.QuestionAI(topic="t", text=long_line + "\nשבמחברתכם."), 1, 25, 1)
    ex = c.ExamAnalysis(translated_exam_name="", translated_grade="", translated_level="", translated_instructions="",
                        labels=c.HEBREW_LABELS, questions=[q])
    scale = c.fit_scale_for_source_lines(ex)
    assert c.MIN_FIT_PT / 11 <= scale <= 1.0
    short = c.postprocess_question(c.QuestionAI(topic="t", text="שורה קצרה.\nועוד אחת."), 1, 25, 1)
    ex.questions = [short]
    assert c.fit_scale_for_source_lines(ex) == 1.0                   # never shrinks without need


@pytest.mark.parametrize("stem,shown", [("ענו על שניים מארבעת הסעיפים א–ד שלפניכם.", False), ("שאלות קצרות.", True)])
def test_choice_rule_is_not_repeated_when_the_stem_states_it(stem, shown):
    q = c.empty_question(1, 20, "")
    q.text = stem
    q.sections = [c.QuestionSection(section_id=s, text="t", points=10, selection_group="g") for s in "אבגד"]
    q.selection_groups = [c.SelectionGroup(group_id="g", choose_k=2)]
    assert bool(c.student_choice_note(q)) == shown


def test_real_pdf_visual_lines():
    pytest.importorskip("pymupdf")
    pdf = ROOT / "tests" / "documents" / "dev" / "questionnaire (22).pdf"
    from document import build_document
    from document.reconstruct import questions_data
    qd = questions_data(pdf.read_bytes(), build_document(pdf.read_bytes()))
    lines = qd[0]["document"]["source_lines"]
    assert 5 <= len(lines) <= 60 and sum(any("\u05d0" <= ch <= "\u05ea" for ch in l) for l in lines) >= 0.6 * len(lines)
