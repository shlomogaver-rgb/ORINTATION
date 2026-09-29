"""MODE B on the second batch of real exams (development set 20, 21-scanned, 22, 24). Ground truth written by hand."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
sys_path_added = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from document import build_document  # noqa: E402

DEV = ROOT / "tests" / "documents" / "dev"
EXP = json.loads((DEV / "expected_structure.json").read_text(encoding="utf-8"))
PDFS = [k for k in EXP if k.endswith(".pdf")]


@pytest.fixture(scope="module")
def models():
    return {n: build_document((DEV / n).read_bytes()) for n in PDFS}


@pytest.mark.parametrize("name", PDFS)
def test_questions_declared_and_continuity(models, name):
    m, e = models[name], EXP[name]
    assert [q.number for q in m.questions] == list(range(1, e["questions"] + 1))
    assert m.declared_question_count == e["declared"] and not m.warnings
    for qn, pages in e["multi_page"].items():
        assert next(q for q in m.questions if q.number == int(qn)).pages == pages


@pytest.mark.parametrize("name", PDFS)
def test_visuals_bound_and_option_groups(models, name):
    m, e = models[name], EXP[name]
    for exp in e["visuals"]:
        q = next(q for q in m.questions if q.number == exp["question"])
        on_page = [v for v in q.visual_objects if v.page == exp["page"]]
        assert on_page, (name, exp)
        if exp["kind"] == "OPTION_GROUP":
            grp = [v for v in on_page if v.semantic_model.get("type") == "GraphOptionGroup"]
            assert grp and len(grp[0].semantic_model["options"]) == exp["options"], (name, exp, [v.semantic_model for v in on_page])
    if e.get("scanned"):
        assert m.metadata.get("scanned_numbering")


def test_mode_b_pdf_to_questions_to_docx_with_mock():
    """PDF -> structure -> per-question full-resolution regions -> PASS 1/2 (mock) -> approval -> DOCX."""
    import io
    import zipfile

    import mock_gemini
    import diagram_engine as de
    import exam_core as c
    from document.reconstruct import questions_data
    from PIL import Image
    sys.path.insert(0, str(ROOT / "tests"))
    from test_core import meta
    pdf = (DEV / "questionnaire (20).pdf").read_bytes()
    m = build_document(pdf)
    data = questions_data(pdf, m)
    assert [d["question_number"] for d in data] == [1, 2, 3, 4, 5]
    for d in data:
        with Image.open(io.BytesIO(d["images"][0])) as im:
            assert im.width >= 1600                                  # full-resolution page render, not a thumbnail
    mock_gemini.install()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), data, verify=False)
    assert len(exam.questions) == 5
    for q in exam.questions:
        for f in q.figures:
            de.approve(q.diagrams[f.figure_id])
    docx, _ = c.create_word_document(exam, meta(), data, "exam")
    names = zipfile.ZipFile(io.BytesIO(docx)).namelist()
    assert any(n.endswith(".svg") for n in names)                   # vector reconstruction, not the scan


def test_app_import_full_document_function_exists():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def import_full_document" in src and 'type=["pdf"]' in src


def test_response_templates_become_empty_native_word_tables():
    """Unseen synthetic page: a question, a row of 5 empty answer boxes and an empty 3x4 grid -> empty Word tables."""
    import io
    import zipfile

    import mock_gemini
    import pymupdf
    import exam_core as c
    from document.reconstruct import questions_data
    sys.path.insert(0, str(ROOT / "tests"))
    from test_core import meta
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((545, 120), "1.", fontname="helv", fontsize=12)
    for k in range(5):
        page.draw_rect(pymupdf.Rect(100 + 70 * k, 300, 150 + 70 * k, 330), color=(0, 0, 0), width=1)
    for i in range(4):                                  # grid 3 rows x 4 cols
        page.draw_line((100, 500 + 30 * i), (340, 500 + 30 * i), color=(0, 0, 0), width=0.8)
    for j in range(5):
        page.draw_line((100 + 60 * j, 500), (100 + 60 * j, 590), color=(0, 0, 0), width=0.8)
    pdf = doc.tobytes()
    m = build_document(pdf)
    data = questions_data(pdf, m)
    kinds = sorted((t.get("kind", t["role"]), tuple(t["grid"])) for t in data[0]["document"]["response_templates"])
    assert kinds == [("RESPONSE_TEMPLATE", (3, 4)), ("box_row", (1, 5))], kinds
    mock_gemini.install()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), data, verify=False)
    docx, _ = c.create_word_document(exam, meta(), data, "exam")
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    import re
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)
    empty = [t_ for t_ in tables if not re.findall(r"<w:t[^>]*>([^<]+)</w:t>", t_)]
    assert len(empty) >= 2                                   # the templates are EMPTY (never filled with a solution)
