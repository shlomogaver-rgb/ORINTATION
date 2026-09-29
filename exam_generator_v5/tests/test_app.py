"""Headless UI tests (Streamlit AppTest) with Gemini mocked.  Run:  python -m pytest -q tests"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import exam_core as c  # noqa: E402
from test_core import page_image  # noqa: E402

RUNNER = str(ROOT / "tests" / "run_mock_app.py")


def _to_step2(n=3):
    at = AppTest.from_file(RUNNER, default_timeout=120).run()
    at.number_input(key="s1_n").set_value(n).run()
    at.button[[b.label for b in at.button].index("המשך להעלאת שאלות ⬅️")].click().run()
    assert not at.exception, at.exception
    return at


def test_switch_questions_after_adding_images():
    at = _to_step2(3)
    img = page_image()
    at.session_state.image_store = {1: [{"id": "a", "original": img, "current": img, "history": []}]}
    at.run()
    assert not at.exception, at.exception
    for q in ("2", "3", "1", "2"):
        at.radio(key="s2_sel").set_value(q).run()
        assert not at.exception, at.exception
        assert at.subheader[0].value == f"שאלה {q}"
    # adding an image to the selected question must not break the selector
    at.session_state.image_store = {1: at.session_state.image_store[1], 2: [{"id": "b", "original": img, "current": img, "history": []}]}
    at.run()
    assert not at.exception, at.exception
    assert at.radio(key="s2_sel").value == "2"


def test_editor_tools_render_for_every_question():
    at = _to_step2(2)
    img = page_image()
    at.session_state.image_store = {q: [{"id": f"i{q}", "original": img, "current": img, "history": []}] for q in (1, 2)}
    at.run()
    for q in ("1", "2"):
        at.radio(key="s2_sel").set_value(q).run()
        for tool in ("✂️ חיתוך", "🧽 מחיקת סימנים", "🔄 סיבוב ויישור"):
            at.radio(key=f"tool_{q}").set_value(tool).run()
            assert not at.exception, (q, tool, at.exception)
        at.button(key=f"rl_i{q}").click().run()  # rotate 90° on the selected question
        assert c.png_bytes_to_pil(at.session_state.image_store[int(q)][0]["current"]).size == (1800, 1400)



def test_step4_selector_survives_reanalysis():
    """A question that failed and was re-analyzed changes its warning state; the selector must not crash."""
    import mock_gemini
    from test_core import meta

    mock_gemini.install()
    qd = [{"question_number": i, "points": 50.0, "images": [page_image()]} for i in (1, 2)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=True)
    good = exam.questions[1]
    exam.questions[1] = c.empty_question(2, 50.0, "הפענוח נכשל: עומס")
    at = AppTest.from_file(RUNNER, default_timeout=120)
    at.session_state.exam_meta = meta()
    at.session_state.questions_data = qd
    at.session_state.processed_exam = exam
    at.session_state.step = 4
    at.session_state.api_key = "k"
    at.run()
    key = [r.key for r in at.radio if r.key and r.key.startswith("quality_question")][0]
    at.radio(key=key).set_value("2").run()
    assert not at.exception, at.exception
    exam.questions[1] = good
    at.session_state.processed_exam = exam
    at.run()
    assert not at.exception, at.exception
    assert at.radio(key=key).value == "2"


def _step4_app():
    import mock_gemini
    from test_core import meta

    mock_gemini.install()
    qd = [{"question_number": i, "points": 50.0, "images": [page_image()]} for i in (1, 2)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=True)
    at = AppTest.from_file(RUNNER, default_timeout=120)
    at.session_state.exam_meta = meta()
    at.session_state.questions_data = qd
    at.session_state.processed_exam = exam
    at.session_state.step = 4
    at.session_state.api_key = "k"
    at.run()
    assert not at.exception, at.exception
    return at


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _rec(at, q=0):
    q = at.session_state.processed_exam.questions[q]
    return q.diagrams[q.figures[0].figure_id]


def test_review_buttons_change_state_and_document_source():
    at = _step4_app()
    assert _rec(at).review.status == "pending"
    _btn(at, "✅ אשר שחזור").click().run()
    assert not at.exception, at.exception
    assert _rec(at).review.status == "approved" and _rec(at).review.approved_by == "teacher"
    assert _btn(at, "📷 השתמש בסריקה (חריג)").disabled          # needs the explicit confirmation first
    next(cb for cb in at.checkbox if cb.label == "אני מאשר/ת שימוש חריג בסריקה").check().run()
    _btn(at, "📷 השתמש בסריקה (חריג)").click().run()
    assert _rec(at).review.status == "raster_override" and _rec(at).audit["raster_overrides"]
    _btn(at, "🗑 דחה שחזור").click().run()
    assert _rec(at).review.status == "rejected"


def test_graph_editor_applies_edit_and_requires_new_approval():
    at = _step4_app()
    _btn(at, "✅ אשר שחזור").click().run()
    _btn(at, "✏️ ערוך שחזור").click().run()
    assert not at.exception, at.exception
    nx = next(n for n in at.number_input if n.label == "x מקסימום")
    nx.set_value(5.0)
    _btn(at, "💾 החל שינויים ובדוק מחדש").click().run()
    assert not at.exception, at.exception
    rec = _rec(at)
    assert rec.spec.graph.axes.x_max == 5.0
    assert rec.review.status == "pending" and len(rec.review.teacher_edits) == 1   # edit voids the earlier approval
    assert rec.validation.ok


def test_geometry_editor_renders():
    at = _step4_app()
    at.radio(key=[r.key for r in at.radio if r.key and r.key.startswith("quality_question")][0]).set_value("2").run()
    _btn(at, "✏️ ערוך שחזור").click().run()
    assert not at.exception, at.exception
    _btn(at, "💾 החל שינויים ובדוק מחדש").click().run()   # unchanged submit keeps a valid, re-checked record
    assert not at.exception, at.exception
    rec = _rec(at, 1)
    assert rec.validation.ok and rec.manifest["right_angle_marks"] == 1
