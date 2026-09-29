"""Unit tests for exam_core.  Run:  python -m pytest -q tests"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import exam_core as c  # noqa: E402
import mock_gemini  # noqa: E402


# ---------------------------------------------------------------- fixtures

def approve_figures(exam):
    """EXAM_QUALITY: every figure needs a teacher decision before export (test helper = teacher approves all)."""
    import diagram_engine as de
    for q in exam.questions:
        for fig in q.figures:
            assert de.approve(q.diagrams[fig.figure_id]), fig.figure_id

def page_image(angle: float = 0.0) -> bytes:
    img = Image.new("RGB", (1400, 1800), "white")
    d = ImageDraw.Draw(img)
    for y in range(150, 1500, 70):
        d.rectangle([150, y, 1250, y + 18], fill=(25, 25, 25))
    d.ellipse([300, 900, 360, 960], fill=(40, 40, 160))
    if angle:
        img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))
    return c.pil_to_png_bytes(img)


def meta(n: int = 2, language: str = "עברית") -> dict:
    return {"school_name": "מקיף", "exam_name": "מבחן", "grade": "י'", "level": "5", "teacher_name": "", "duration": 90,
            "num_questions": n, "language": language, "date": "2026-10-05",
            "instructions": "• הוראה", "choice_groups": [{"questions": list(range(1, n + 1)), "required": n}], "logo_bytes": None}


@pytest.fixture()
def analyzed():
    mock_gemini.install()
    imgs = [page_image(), page_image()]
    qd = [{"question_number": 1, "points": 50.0, "images": [imgs[0]]},
          {"question_number": 2, "points": 50.0, "images": [imgs[1]]}]
    exam, notes = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=True)
    return exam, qd


# ---------------------------------------------------------------- Gemini
def test_schemas_accepted_by_sdk_in_api_key_mode():
    from google import genai
    from google.genai import _transformers as t

    client = genai.Client(api_key="x")
    for model in (c.QuestionAI, c.ExamHeaderAI, c.VerificationAI):
        t.t_schema(client._api_client, model)  # raises on additionalProperties


def test_full_analysis_with_mock(analyzed):
    exam, qd = analyzed
    assert [q.question_number for q in exam.questions] == [1, 2]
    assert exam.questions[0].points == 50 and exam.questions[0].sections[0].section_id == "א"
    errors, warnings = c.validate_exam(exam, meta(), qd)
    assert len(errors) == 2 and all("נדרשת החלטת מורה" in e for e in errors)   # EXAM_QUALITY: undecided figures block export
    approve_figures(exam)
    errors, warnings = c.validate_exam(exam, meta(), qd)
    assert errors == []


def test_non_hebrew_header_translated():
    mock_gemini.install()
    qd = [{"question_number": 1, "points": 50.0, "images": [page_image()]},
          {"question_number": 2, "points": 50.0, "images": [page_image()]}]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(language="אנגלית"), qd, verify=False)
    assert exam.labels.question == "Question"


def test_verification_disagreement_blocks_until_teacher_confirms():
    mock_gemini.install(disagree=True)
    qd = [{"question_number": 1, "points": 50.0, "images": [page_image()]},
          {"question_number": 2, "points": 50.0, "images": [page_image()]}]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=True)
    errors, _ = c.validate_exam(exam, meta(), qd)
    assert any("הבדיקה העצמאית" in e for e in errors)
    for q in exam.questions:
        q.teacher_verified = True
    approve_figures(exam)
    assert c.validate_exam(exam, meta(), qd)[0] == []


class _ErrClient:
    """Fails with the given codes first, then delegates to the mock."""

    def __init__(self, codes):
        self.codes = list(codes)
        self.inner = mock_gemini.FakeClient()
        self.models = SimpleNamespace(generate_content=self._gen, list=self.inner.models.list)
        self.models_seen = []

    def _gen(self, model, contents, config):
        self.models_seen.append(model)
        if self.codes:
            code = self.codes.pop(0)
            err = Exception(f"{code} error")
            err.code = code
            raise err
        return self.inner.models.generate_content(model, contents, config)


def test_model_fallback_on_404_and_retry_on_429(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    client = _ErrClient([404, 429])
    svc = c.GeminiService("k", model="gemini-9-missing", client=client)
    q = c.analyze_question(svc, meta(), {"question_number": 1, "points": 50, "images": [page_image()]})
    assert q.sections and client.models_seen[0] == "gemini-9-missing"
    assert svc.model == "gemini-3.8-flash"


def test_failed_question_is_reported_not_crashing(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    monkeypatch.setattr(c, "make_client", lambda k: _ErrClient([400] * 50))
    qd = [{"question_number": 1, "points": 100.0, "images": [page_image()]}]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(1), qd, verify=True)
    assert exam.questions[0].analysis_error
    assert any("לפענח אותה מחדש" in e for e in c.validate_exam(exam, meta(1), qd)[0])


# ---------------------------------------------------------------- scoring
@pytest.mark.parametrize("n", range(1, 13))
def test_suggested_points_always_valid(n):
    m = meta(n)
    pts = c.suggested_points(m)
    assert c.validate_points_structure(m, pts) == []


def test_choice_groups_with_rounding():
    m = meta(7)
    m["choice_groups"] = [{"questions": list(range(1, 8)), "required": 7}]
    assert c.validate_points_structure(m, {q: 14.29 for q in range(1, 8)}) == []
    m["choice_groups"] = [{"questions": [1, 2, 3], "required": 2}, {"questions": [4, 5], "required": 1}]
    assert c.validate_points_structure(m, {1: 33.33, 2: 33.33, 3: 33.33, 4: 33.34, 5: 33.34}) == []
    assert c.validate_points_structure(m, {1: 30, 2: 33.33, 3: 33.33, 4: 33.34, 5: 33.34})  # unequal in group


def test_rebalance_exact(analyzed):
    exam, _ = analyzed
    q = exam.questions[0]
    q.sections[0].points = 7
    q.rubric_steps[0].percentage = 3
    c.rebalance_question(q)
    assert abs(sum(s.points for s in q.sections) - q.points) < 1e-9
    assert abs(sum(r.percentage for r in q.rubric_steps) - 100) < 1e-9


def test_unreadable_marker_blocks(analyzed):
    exam, qd = analyzed
    exam.questions[1].text += " [דרוש אימות מורה]"
    assert any("דרוש אימות מורה" in e for e in c.validate_exam(exam, meta(), qd)[0])


def test_empty_verification_cannot_pass(analyzed):
    exam, qd = analyzed
    q = exam.questions[0]
    q.verification = c.VerificationAI(
        items=[], source_reconstruction_agrees=True, reasoning_agrees=True, overall_agrees=True, notes=""
    )
    errors, _ = c.validate_exam(exam, meta(), qd)
    assert any("אינה מכסה בדיוק" in e for e in errors)


def test_verification_failure_blocks_until_manual_confirmation(analyzed):
    exam, qd = analyzed
    q = exam.questions[0]
    q.verification = None
    q.verification_error = "האימות נכשל"
    errors, _ = c.validate_exam(exam, meta(), qd)
    assert any("נדרש אימות ידני" in e for e in errors)
    q.teacher_verified = True
    assert not any("האימות נכשל" in e for e in c.validate_exam(exam, meta(), qd)[0])


def test_missing_final_answer_blocks(analyzed):
    exam, qd = analyzed
    q = exam.questions[0]
    for step in q.solution_steps:
        step.final_answer = ""
    errors, _ = c.validate_exam(exam, meta(), qd)
    assert any("חסרה תשובה סופית" in e for e in errors)


# ---------------------------------------------------------------- images
@pytest.mark.parametrize("angle", [-6.0, -2.5, 3.0, 4.0])
def test_deskew(angle):
    fixed, found = c.auto_straighten_bytes(page_image(angle))
    assert abs(found + angle) <= 0.3


def test_straight_page_untouched():
    data = page_image()
    fixed, found = c.auto_straighten_bytes(data)
    assert found == 0.0 and fixed == data


def test_crop_is_full_resolution():
    full = page_image()
    disp, scale = c.fit_for_editor(c.png_bytes_to_pil(full))
    out = c.png_bytes_to_pil(c.crop_full_resolution(full, {"left": 10, "top": 10, "width": 300, "height": 200}, scale))
    assert out.width == pytest.approx(300 * scale, abs=2) and out.width > 300


def test_erase_mask_only_touches_marked_area():
    full = page_image()
    img = c.png_bytes_to_pil(full)
    disp, scale = c.fit_for_editor(img)
    layer = np.zeros((disp.height, disp.width, 4), np.uint8)
    y0, x0 = int(895 / scale), int(295 / scale)
    y1, x1 = int(965 / scale) + 1, int(365 / scale) + 1
    layer[y0:y1, x0:x1] = (255, 0, 110, 115)  # semi-transparent pink, like the app
    out, fraction = c.apply_erase_mask(full, layer)
    a, b = np.asarray(img), np.asarray(c.png_bytes_to_pil(out))
    assert b[930, 330].tolist() == [255, 255, 255] and a[930, 330].tolist() != [255, 255, 255]
    assert np.array_equal(a[150:170, 800:1200], b[150:170, 800:1200])
    assert fraction < 0.01
    with pytest.raises(ValueError):
        c.apply_erase_mask(full, np.full((disp.height, disp.width, 4), 255, np.uint8))


def test_rotation_expands_canvas():
    full = page_image()
    w, h = c.png_bytes_to_pil(full).size
    assert c.png_bytes_to_pil(c.rotate_image_bytes(full, 90)).size == (h, w)
    assert c.png_bytes_to_pil(c.rotate_image_bytes(full, 5)).size[0] > w


# ---------------------------------------------------------------- safe parser
@pytest.mark.parametrize("expr,fn", [
    (r"\frac{x^{2}-1}{x+2}", lambda x: (x**2 - 1) / (x + 2)), (r"\sqrt[3]{x}", np.cbrt), ("2x+1", lambda x: 2 * x + 1),
    (r"\left|x-2\right|", lambda x: abs(x - 2)), (r"\log_{2}(x)", np.log2), (r"\ln(x)+\log(x)", lambda x: np.log(x) + np.log10(x)),
    ("(x+1)(x-2)", lambda x: (x + 1) * (x - 2)), (r"e^{x}", np.exp), (r"2\pi x", lambda x: 2 * np.pi * x), ("5", lambda x: 5 + 0 * x),
])
def test_safe_function(expr, fn):
    xs = np.linspace(1, 4, 7)
    assert np.allclose(c.safe_function(expr)(xs), fn(xs))


@pytest.mark.parametrize("expr,expected", [
    (r"\sqrt[3]{x}", [-2, -1, 0, 1, 2]),
    ("x^(1/3)", [-2, -1, 0, 1, 2]),
    ("x^(2/3)", [4, 1, 0, 1, 4]),
    ("(x-2)^(1/3)", [np.cbrt(-10), np.cbrt(-3), np.cbrt(-2), np.cbrt(-1), np.cbrt(6)]),
])
def test_safe_function_odd_roots_are_real_on_negative_inputs(expr, expected):
    xs = np.array([-8.0, -1.0, 0.0, 1.0, 8.0])
    assert np.allclose(c.safe_function(expr)(xs), np.asarray(expected, dtype=float))


@pytest.mark.parametrize("bad", ["np.__loader__", "x.__class__", "__import__('os')", "open('x')", "lambda: 1",
                                 "x.conjugate()", "9^9^9^9", "9^(9^9)", "y+x"])
def test_safe_function_blocks(bad):
    with pytest.raises(Exception):
        c.safe_function(bad)(np.linspace(1, 2, 3))


# ---------------------------------------------------------------- figures + bidi
def test_visual_text_reverses_hebrew_only():
    assert c.visual_text("abc") == "abc"
    assert c.visual_text("שלום") == "םולש"


def test_figures_go_through_diagram_engine(analyzed):
    exam, qd = analyzed
    for q in exam.questions:
        for fig in q.figures:
            rec = q.diagrams[fig.figure_id]
            assert rec.spec is not None and rec.validation.ok, rec.validation.errors
            assert rec.review.status == "pending"          # never used before approval (auto-approve is off)
    q2 = exam.questions[1]
    rec = q2.diagrams[q2.figures[0].figure_id]
    assert rec.manifest["right_angle_marks"] == 1 and rec.manifest["length_labels"] == ["5", "12"]


def _docx_images(data: bytes) -> list[bytes]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return [z.read(n) for n in z.namelist() if n.startswith("word/media/")]


def _docx_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


def test_acceptance_10_document_uses_only_approved_reconstruction(analyzed):
    """V5.7 EXAM_QUALITY: pending -> visible placeholder (no automatic raster); approved -> reconstruction;
    explicit teacher raster override -> original crop (audited); any source change invalidates both."""
    import diagram_engine as de

    exam, qd = analyzed
    q1 = exam.questions[0]
    fig = q1.figures[0]
    rec = q1.diagrams[fig.figure_id]
    _, rendered_png, _ = de.render_spec(rec.spec)
    crop = c.figure_source_crop(fig, qd[0]["images"])
    data = c.create_word_document(exam, meta(), qd, "exam")[0]
    before = _docx_images(data)
    assert crop not in before and rendered_png not in before and "ממתין להחלטת מורה" in _docx_xml(data)
    assert de.approve(rec)
    after = _docx_images(c.create_word_document(exam, meta(), qd, "exam")[0])
    assert rendered_png in after and crop not in after
    rec.spec.graph.points[0].y = 1.0                                # spec changed after approval -> void
    assert "ממתין להחלטת מורה" in _docx_xml(c.create_word_document(exam, meta(), qd, "exam")[0])
    de.raster_override(rec, "בדיקה")
    data = c.create_word_document(exam, meta(), qd, "exam")[0]
    assert crop in _docx_images(data) and rec.audit["raster_overrides"]


def test_approval_invalidated_after_crop_change_same_spec(analyzed):
    """P0 regression: approve -> change the crop region -> same AI spec -> the old approval must NOT survive."""
    import diagram_engine as de

    exam, qd = analyzed
    q = exam.questions[0]
    fig = q.figures[0]
    assert de.approve(q.diagrams[fig.figure_id]) and de.usable_in_document(q.diagrams[fig.figure_id])
    fig.bbox = [100, 100, 900, 900]
    c.attach_diagrams(q, qd[0]["images"])
    rec = q.diagrams[fig.figure_id]
    assert rec.review.status != "approved" and not de.usable_in_document(rec)
    assert c.figure_decision_pending(rec)


def test_approval_invalidated_after_image_edit_and_integrity_error(analyzed):
    """Erase/rotate after the analysis: new image bytes -> approval void AND the AI saw a different image ->
    PIPELINE_INTEGRITY_ERROR until the question is re-analysed."""
    import diagram_engine as de
    from PIL import Image, ImageDraw

    exam, qd = analyzed
    q = exam.questions[0]
    fig = q.figures[0]
    assert de.approve(q.diagrams[fig.figure_id])
    with Image.open(io.BytesIO(qd[0]["images"][0])) as im:
        im = im.convert("RGB")
        ImageDraw.Draw(im).rectangle((10, 10, 60, 60), fill=(123, 45, 67))    # the pixels really change
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    edited = [buf.getvalue()]
    c.attach_diagrams(q, edited)
    rec = q.diagrams[fig.figure_id]
    assert not de.usable_in_document(rec) and rec.decision.action == "original"
    assert "PIPELINE_INTEGRITY_ERROR" in rec.decision.reasons[0]


def test_broken_diagram_never_breaks_document(analyzed, monkeypatch):
    import diagram_engine as de

    exam, qd = analyzed
    q1 = exam.questions[0]
    assert de.approve(q1.diagrams[q1.figures[0].figure_id])
    monkeypatch.setattr(de, "render_spec", lambda spec: (_ for _ in ()).throw(RuntimeError("boom")))
    data, warnings = c.create_word_document(exam, meta(), qd, "exam")
    assert data and any("שחזור השרטוט נכשל" in w or "ממתין להחלטת מורה" in w for w in warnings)


# ---------------------------------------------------------------- Word
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()


@pytest.mark.parametrize("latex", [r"\sqrt{169}", r"\sqrt[3]{x}", r"\vec{v}", r"\overrightarrow{AB}", r"\bar{x}",
                                   r"\begin{cases}x>0\\y<1\end{cases}", r"\int_0^1 f(x)\,dx", r"\angle ABC=60^\circ"])
def test_latex_to_omml_valid_structure(latex):
    root = c.latex_to_omml(latex)
    for rad in root.iter(f"{M}rad"):
        assert rad.find(f"{M}deg") is not None
    assert not list(root.iter(f"{M}box"))


def test_word_documents(analyzed):
    exam, qd = analyzed
    approve_figures(exam)
    m = meta()
    for kind in ("exam", "solution", "rubric"):
        data, warnings = c.create_word_document(exam, m, qd, kind)
        assert warnings == []
        xml = _xml(data)
        assert "<m:oMath" in xml
        assert "w:bCs" in xml and "w:szCs" in xml  # Hebrew bold/size
        assert "<w:bidi/>" in xml
        if kind == "exam":
            assert "GeoGebra" not in xml  # teacher-only info never reaches the student
            assert "פונקציה ריבועית" not in xml  # topic hidden by default
        if kind == "solution":
            assert "GeoGebra" in xml


def test_bidivisual_position(analyzed):
    exam, qd = analyzed
    xml = _xml(c.create_word_document(exam, meta(), qd, "rubric")[0])
    import re

    for tbl_pr in re.findall(r"<w:tblPr>.*?</w:tblPr>", xml):
        assert tbl_pr.index("bidiVisual") < tbl_pr.index("tblW")


@pytest.mark.skipif(c.soffice_executable() is None, reason="LibreOffice not installed")
def test_pdf_conversion(analyzed):
    exam, qd = analyzed
    pdf, err = c.docx_to_pdf_bytes(c.create_word_document(exam, meta(), qd, "exam")[0], "t")
    assert pdf and pdf[:4] == b"%PDF", err


# ---------------------------------------------------------------- free-tier quota (429) handling
import free_tier_sim as ft  # noqa: E402


def _quota_run(monkeypatch, n, verify=True, daily=None):
    clock = ft.FakeClock()
    monkeypatch.setattr(c.time, "monotonic", clock.monotonic)
    client = ft.FreeTierClient(clock, rpm=5, daily=daily)
    svc = c.GeminiService("k", client=client, sleep=clock.sleep)
    qd = [{"question_number": i, "points": 100 / n, "images": [page_image()]} for i in range(1, n + 1)]
    exam, notes = c.run_full_analysis(svc, meta(n), qd, verify=verify)
    return exam, notes, svc, client, clock


def test_quota_error_parsing_matches_real_google_error():
    info = c.parse_quota_error(ft.quota_error("gemini-3.8-flash"))
    assert info == {"per_day": False, "limit": 5, "retry_after": 6.0, "free_tier": True}
    assert "5 בקשות בדקה" in c.friendly_error(ft.quota_error("gemini-3.8-flash"))
    assert "המכסה היומית" in c.friendly_error(ft.quota_error("gemini-3.8-flash", per_day=True))


@pytest.mark.parametrize("n", [1, 4, 12])
def test_free_tier_all_questions_succeed(monkeypatch, n):
    exam, notes, svc, client, clock = _quota_run(monkeypatch, n)
    assert not [q for q in exam.questions if q.analysis_error or q.verification_error]
    assert client.accepted == 3 * n and client.rejected <= 1     # analysis + verification + PASS-2 diagram call
    if 2 * n > 5:
        assert svc.rpm == 5 and notes  # learned the limit and told the teacher


def test_daily_quota_switches_model(monkeypatch):
    exam, _, svc, _, _ = _quota_run(monkeypatch, 3, daily={"gemini-3.8-flash": 2})
    assert not [q for q in exam.questions if q.analysis_error] and svc.model == "gemini-3.7-flash"


def test_all_quotas_exhausted_gives_clear_message(monkeypatch):
    exam, *_ = _quota_run(monkeypatch, 2, daily={m: 0 for m in c.FALLBACK_MODELS})
    assert all("המכסה היומית" in q.analysis_error for q in exam.questions)
    assert all("RESOURCE_EXHAUSTED" in q.error_detail for q in exam.questions)  # raw text kept for details


def test_retry_only_failed_questions(monkeypatch):
    mock_gemini.install()
    qd = [{"question_number": i, "points": 50.0, "images": [page_image()]} for i in (1, 2)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=False)
    exam.questions[1] = c.empty_question(2, 50.0, "הפענוח נכשל: x")
    client = mock_gemini.FakeClient()
    exam2, _ = c.run_full_analysis(c.GeminiService("k", client=client), meta(), qd, verify=False, existing=exam, only={2})
    assert [q.analysis_error for q in exam2.questions] == ["", ""]
    assert [c_ for c_ in client.calls if c_[1] == "QuestionAI"] and len([c_ for c_ in client.calls if c_[1] == "QuestionAI"]) == 1  # question 1 not re-sent
    assert exam2.questions[0] is exam.questions[0]


def test_limiter_reports_waiting_status(monkeypatch):
    clock = ft.FakeClock()
    monkeypatch.setattr(c.time, "monotonic", clock.monotonic)
    seen = []
    svc = c.GeminiService("k", client=mock_gemini.FakeClient(), rpm=1, sleep=lambda s: (seen.append(svc.status), clock.sleep(s)))
    svc._acquire()
    svc._acquire()  # second call in the same minute must wait
    assert any("ממתין למכסת Gemini" in s for s in seen)


# ---------------------------------------------------------------- overloaded model (503) -> fallback
class _OverloadedClient(mock_gemini.FakeClient):
    def __init__(self, overloaded: set[str]):
        super().__init__()
        self.overloaded = overloaded
        inner = self.models.generate_content

        def generate_content(model, contents, config):
            from google.genai import errors

            if model in self.overloaded:
                raise errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE",
                                                         "message": "The model is overloaded. Please try again later."}})
            return inner(model, contents, config)

        self.models.generate_content = generate_content


def test_overloaded_model_falls_back(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    client = _OverloadedClient({"gemini-3.8-flash"})
    monkeypatch.setattr(c, "make_client", lambda k: client)
    qd = [{"question_number": i, "points": 25.0, "images": [page_image()]} for i in range(1, 5)]
    svc = c.GeminiService("k")
    svc._sleep = lambda s: None
    exam, notes = c.run_full_analysis(svc, meta(4), qd, verify=True)
    assert not [q for q in exam.questions if q.analysis_error or q.verification_error]
    assert exam.model_used == "gemini-3.7-flash"
    assert any("עמוס" in n and "gemini-3.7-flash" in n for n in notes)


def test_all_models_overloaded_message(monkeypatch):
    client = _OverloadedClient(set(c.FALLBACK_MODELS))
    svc = c.GeminiService("k", client=client, sleep=lambda s: None)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    with pytest.raises(c.GeminiError) as info:
        c.analyze_question(svc, meta(1), {"question_number": 1, "points": 100, "images": [page_image()]})
    assert "עמוס" in c.friendly_error(info.value)



# ---------------------------------------------------------------- 5.3 regression tests
def test_giant_power_rejected_quickly():
    import time as _t

    start = _t.monotonic()
    for bad in ("9^9^9^9", "9^(9^9)", "(x+1)^(9^9)"):
        with pytest.raises(Exception):
            c.safe_function(bad)(np.linspace(1, 2, 3))
    assert _t.monotonic() - start < 5  # 5.2-audited hung forever here (simplify ran before the guard)


@pytest.mark.parametrize("returned", [("א", "ב"), ("א.", "ב."), ("סעיף א", "סעיף ב"), ("א)", "ב)")])
def test_verification_section_ids_normalized(analyzed, returned):
    exam, qd = analyzed
    q = exam.questions[1]
    q.verification = c.VerificationAI(
        items=[c.VerificationItem(section_id=s, independent_final_answer="x", agrees=True, reasoning_agrees=True,
                                  source_text_agrees=True) for s in returned],
        overall_agrees=True, reasoning_agrees=True, source_reconstruction_agrees=True)
    approve_figures(exam)
    assert not [e for e in c.validate_exam(exam, meta(), qd)[0] if "שאלה 2" in e]


def test_verification_still_catches_missing_section(analyzed):
    exam, qd = analyzed
    q = exam.questions[1]
    q.verification = c.VerificationAI(
        items=[c.VerificationItem(section_id="א", independent_final_answer="x", agrees=True, reasoning_agrees=True,
                                  source_text_agrees=True)],
        overall_agrees=True, reasoning_agrees=True, source_reconstruction_agrees=True)
    assert any("חסרים: ב" in e for e in c.validate_exam(exam, meta(), qd)[0])
