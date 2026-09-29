"""MODE-B state flow through the REAL app (AppTest): PDF import -> step 1 -> step 2 -> step 3 (questions_data rebuilt)
-> analysis (mock) -> DOCX. Document semantics (response templates, pages, subparts) must survive every transition."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
RUNNER = str(ROOT / "tests" / "run_mock_app.py")


def _synthetic_pdf(tmp_path) -> Path:
    import pymupdf
    doc = pymupdf.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((545, 120), "1.", fontname="helv", fontsize=12)
    p1.insert_text((100, 140), "Question one text", fontname="helv", fontsize=11)
    for k in range(5):
        p1.draw_rect(pymupdf.Rect(100 + 70 * k, 300, 150 + 70 * k, 330), color=(0, 0, 0), width=1)
    p1.insert_text((545, 500), "2.", fontname="helv", fontsize=12)
    for i in range(4):
        p1.draw_line((100, 560 + 30 * i), (340, 560 + 30 * i), color=(0, 0, 0), width=0.8)
    for j in range(5):
        p1.draw_line((100 + 60 * j, 560), (100 + 60 * j, 650), color=(0, 0, 0), width=0.8)
    path = tmp_path / "exam.pdf"
    path.write_bytes(doc.tobytes())
    return path


def _btn(at, label):
    return at.button[[b.label for b in at.button].index(label)]


def test_mode_b_document_semantics_survive_the_real_ui_flow(tmp_path):
    import exam_core as c
    pdf = _synthetic_pdf(tmp_path)
    at = AppTest.from_file(RUNNER, default_timeout=180)
    at.session_state["_test_import_pdf"] = str(pdf)
    at.run()
    assert not at.exception, at.exception
    assert at.session_state.document_model["questions"] and len(at.session_state.image_store) == 2
    _btn(at, "המשך להעלאת שאלות ⬅️").click().run()                  # step 1 -> 2
    assert not at.exception, at.exception
    _btn(at, "אישור ומעבר לפענוח ⬅️").click().run()                 # step 2 -> 3: questions_data is REBUILT here
    assert not at.exception, at.exception
    qd = at.session_state.questions_data
    kinds = {d["question_number"]: sorted((t.get("kind", t["role"]), tuple(t["grid"])) for t in d["document"]["response_templates"])
             for d in qd}
    assert kinds[1] == [("box_row", (1, 5))] and kinds[2] == [("RESPONSE_TEMPLATE", (3, 4))], kinds
    assert all(d["document"]["pages"] == [1] for d in qd)
    # analysis (mock model) on exactly this state, then the document
    import mock_gemini
    from test_core import meta
    mock_gemini.install()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(2), qd, verify=False)
    data, _ = c.create_word_document(exam, meta(2), qd, "exam")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)
    empty = [t for t in tables if not re.findall(r"<w:t[^>]*>([^<]+)</w:t>", t)]
    assert len(empty) >= 2                                       # both response templates reached the DOCX, still EMPTY


def test_pdf_master_evidence_is_high_resolution(tmp_path):
    from document import build_document
    from document.reconstruct import questions_data
    from PIL import Image
    vec = (ROOT / "tests" / "documents" / "dev" / "questionnaire (22).pdf").read_bytes()
    data = questions_data(vec, build_document(vec))
    with Image.open(io.BytesIO(data[0]["masters"][0])) as im:
        assert im.width >= 595 / 72 * 400                         # vector PDF ROI rendered at >= 400 dpi, not a 200-dpi page
    assert data[0]["source_evidence"][0]["source"] == "vector_pdf_render"
    scan = (ROOT / "tests" / "documents" / "dev" / "questionnaire (21).pdf").read_bytes()
    sdata = questions_data(scan, build_document(scan))
    ev = sdata[0]["source_evidence"][0]
    assert ev["source"] == "embedded_raster"                       # the ORIGINAL scan pixels, not a re-sampled render
    import pymupdf
    native = pymupdf.open(stream=scan, filetype="pdf").extract_image(pymupdf.open(stream=scan, filetype="pdf")[1].get_images()[0][0])
    assert ev["native_px"][0] == native["width"]


def test_full_pdf_to_docx_structural_e2e():
    """REAL exam PDF (20-page booklet) -> document model -> high-res regions -> PASS 1/2 (mock) -> approval -> DOCX,
    then the DOCX is reopened and checked structurally."""
    import diagram_engine as de
    import exam_core as c
    import mock_gemini
    from document import build_document
    from document.reconstruct import questions_data
    from test_core import meta
    pdf = (ROOT / "tests" / "documents" / "regression_ex_holdout" / "questionnaire (23).pdf").read_bytes()
    model = build_document(pdf)
    qd = questions_data(pdf, model)
    assert [d["question_number"] for d in qd] == [1, 2, 3, 4, 5, 6]
    assert any(d["document"]["response_templates"] for d in qd if d["question_number"] in (3, 5))
    mock_gemini.install()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(6), qd, verify=False)
    for q in exam.questions:
        for f in q.figures:
            de.approve(q.diagrams[f.figure_id])
    data, _ = c.create_word_document(exam, meta(6), qd, "exam")
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("word/document.xml").decode()
    texts = re.findall(r"<w:t[^>]*>([^<]+)</w:t>", xml)
    assert sum(len(t) for t in texts) > 500                                   # question text exists
    assert "<m:oMath" in xml                                                   # equations as OMML
    assert any(n.endswith(".svg") for n in z.namelist())                       # reconstructed vector figures
    pics = re.findall(r"<pic:pic>.*?</pic:pic>", xml, re.S)
    body_pics = [p for p in pics if "svgBlip" in p]
    assert pics and len(body_pics) == len(pics) - xml.count("logo")           # every figure is a vector reconstruction
    heads = re.findall(r"שאלה (\d+)", "".join(texts))
    order = [int(h) for i, h in enumerate(heads) if i == 0 or h != heads[i - 1]]
    assert order[:6] == [1, 2, 3, 4, 5, 6] and len(set(order[:6])) == 6       # order kept, no question duplicated
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)
    assert any(not re.findall(r"<w:t[^>]*>([^<]+)</w:t>", t) for t in tables)  # response templates, EMPTY


def test_teacher_picks_questions_from_a_pdf_into_a_mixed_exam():
    """PRIMARY product flow: an exam built from a pasted image (question 1) + two questions PICKED from a Bagrut PDF
    (source questions 3 and 1, one of them a cross-page question) -> the same question pipeline -> one clean DOCX."""
    import exam_core as c
    import mock_gemini
    from test_app import page_image
    from test_core import meta
    pdf = ROOT / "tests" / "documents" / "questionnaire (14).pdf"         # Q1 spans pages 2-3
    at = AppTest.from_file(RUNNER, default_timeout=240).run()
    at.number_input(key="s1_n").set_value(1).run()
    img = page_image()
    at.session_state.image_store = {1: [{"id": "a", "original": img, "current": img, "history": []}]}
    at.session_state["_test_pick_pdf"] = (str(pdf), [3, 1])
    at.run()
    assert not at.exception, at.exception
    assert int(at.session_state.s1_n) == 3 and set(at.session_state.image_store) == {1, 2, 3}
    assert len(at.session_state.image_store[3]) == 2                        # the cross-page question kept BOTH page regions
    _btn(at, "המשך להעלאת שאלות ⬅️").click().run()
    _btn(at, "אישור ומעבר לפענוח ⬅️").click().run()
    assert not at.exception, at.exception
    qd = at.session_state.questions_data
    assert "document" not in qd[0] and qd[1]["document"]["source_question"] == 3 and qd[2]["document"]["pages"] == [2, 3]
    mock_gemini.install()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(3), qd, verify=False)
    data, _ = c.create_word_document(exam, meta(3), qd, "exam")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert "שאלה 3" in "".join(re.findall(r"<w:t[^>]*>([^<]+)</w:t>", xml))
