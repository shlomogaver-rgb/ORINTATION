"""Independent second reading of the source (reading/): photo rectification, line splitting, reader B, comparison,
figure labels, the READING_CONFLICT export gate, the PDF text-layer mode and the Claude back-end."""
from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import exam_core as c  # noqa: E402
import mock_gemini  # noqa: E402
import reading  # noqa: E402
from reading import consensus, lines, rectify, second_reader, simulate  # noqa: E402
from test_core import meta, page_image  # noqa: E402

DOCS = ROOT / "tests" / "documents"


def bagrut_page(pdf: str = "questionnaire (14).pdf", page: int = 1, dpi: int = 200) -> tuple[Image.Image, str]:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(DOCS / pdf)
    p = doc[page]
    return Image.open(io.BytesIO(p.get_pixmap(dpi=dpi).tobytes("png"))).convert("RGB"), p.get_text()


def jpeg(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "JPEG", quality=92)
    return b.getvalue()


# ------------------------------------------------------------------ rectification
def test_photo_is_flattened_to_the_page():
    page, _ = bagrut_page()
    photo = simulate.phone_photo(page, "hard", seed=3)
    out, info = rectify.rectify_photo_bytes(jpeg(photo))
    assert info["perspective"] and info["illumination"]
    flat = Image.open(io.BytesIO(out))
    assert abs(flat.height / flat.width - page.height / page.width) < 0.08        # A4 proportions recovered
    # the table around the sheet is gone: the border of the result is paper, not dark background
    g = flat.convert("L")
    mx, my = int(0.03 * g.width), int(0.03 * g.height)               # just inside the sheet edge
    border = [g.getpixel((x, my)) for x in range(mx, g.width - mx, 50)] + [g.getpixel((mx, y)) for y in range(my, g.height - my, 50)]
    assert sum(border) / len(border) > 180


def test_clean_scan_is_not_warped():
    page, _ = bagrut_page()
    _, info = rectify.rectify_photo_bytes(jpeg(page))
    assert not info["perspective"]


def test_garbage_input_is_returned_unchanged():
    data = b"not an image"
    out, info = rectify.rectify_photo_bytes(data)
    assert out == data and not info["changed"] and "error" in info


@pytest.mark.skipif(not __import__("diagram_engine.ocr.engine", fromlist=["available"]).available(), reason="no tesseract")
def test_rectification_improves_ocr_on_hard_photos():
    import pytesseract
    heb = re.compile(r"[א-ת]{2,}")
    page, truth = bagrut_page()

    def acc(text):
        a, b = Counter(heb.findall(truth)), Counter(heb.findall(text))
        return sum((a & b).values()) / max(1, sum(a.values()))
    photo = simulate.phone_photo(page, "hard", seed=1)
    fixed, _ = rectify.rectify_photo_bytes(jpeg(photo))
    before = acc(pytesseract.image_to_string(photo, lang="heb+eng", config="--psm 4"))
    after = acc(pytesseract.image_to_string(Image.open(io.BytesIO(fixed)), lang="heb+eng", config="--psm 4"))
    assert after >= before + 0.03, (before, after)


# ------------------------------------------------------------------ lines
def test_lines_of_a_page_and_figures_blanked():
    page, _ = bagrut_page()
    b = io.BytesIO()
    page.save(b, "PNG")
    found = lines.split_lines(b.getvalue(), 1)
    assert len(found) >= 8
    assert all(l.crop_png and len(l.norm_bbox) == 4 for l in found)
    assert [l.bbox[1] for l in found] == sorted(l.bbox[1] for l in found)        # reading order: top to bottom
    blanked = lines.split_lines(b.getvalue(), 1, [[0, 0, 1000, 1000]])           # the whole page is "a figure"
    assert blanked == []


# ------------------------------------------------------------------ comparison
A = ["נתונה הפונקציה $f(x)=-0.25x^{2}+3x+7$ .\nציר ה־$x$ מתאר את המרחק האופקי מן הנקודה $A$ .",
     "מצאו את גובה נקודת ההתחלה של קטע המסילה מעל הקרקע (הנקודה $A$).",
     "נתון כי שיעור ה־$x$ של הנקודה $B$ הוא $13$ ."]
B_OK = ["נתונה הפונקציה $f(x) = -0.25x^2 + 3x + 7$ .", "ציר ה־x מתאר את המרחק האופקי מן הנקודה A .",
        "א. מצאו את גובה נקודת ההתחלה של קטע המסילה", "מעל הקרקע (הנקודה A).", "ג. נתון כי שיעור ה־x של הנקודה B הוא 13 .",
        "/המשך בעמוד 11/"]


def bl(texts):
    return [{"text": t, "unreadable": False, "image_index": 1, "norm_bbox": [i * 40, 0, i * 40 + 30, 1000]}
            for i, t in enumerate(texts)]


def test_same_content_different_formatting_agrees():
    r = consensus.compare(A, bl(B_OK))
    assert r["status"] == "AGREED", r["conflicts"]
    assert r["coverage"] == 1.0


@pytest.mark.parametrize("mutate, kind", [
    (lambda t: t.replace("האופקי", "האנכי"), "word"),                       # a Hebrew word misread
    (lambda t: t.replace("$13$", "$18$"), "formula"),                        # a digit misread
    (lambda t: t.replace("+3x+7", "+3x-7"), "formula"),                      # a sign misread
    (lambda t: t.replace("הנקודה $B$", "הנקודה $D$"), "formula"),          # a point label misread
    (lambda t: t.replace(" מעל הקרקע", ""), "extra_in_photo"),              # words dropped by the reconstruction
    (lambda t: t.replace("קטע המסילה", "קטע המסילה החדשה"), "missing_in_photo"),   # words invented
])
def test_every_kind_of_misread_is_caught(mutate, kind):
    r = consensus.compare([mutate(t) for t in A], bl(B_OK))
    assert r["status"] == "CONFLICTS"
    assert kind in {c_["kind"] for c_ in r["conflicts"]}, r["conflicts"]
    assert all(c_["message"].startswith("READING_") for c_ in r["conflicts"])


def test_thousands_separator_and_label_are_not_conflicts():
    r = consensus.compare(["מספר ההאזנות היה $7,350$ ."], bl(["ב. מספר ההאזנות היה 7,350 ."]))
    assert r["status"] == "AGREED", r["conflicts"]


def test_unreadable_line_blocks():
    lines_ = bl(B_OK)
    lines_[4]["text"] = "ג. נתון כי שיעור ה־x של הנקודה B הוא 1[?] ."
    lines_[4]["unreadable"] = True
    r = consensus.compare(A, lines_)
    assert "unreadable" in {c_["kind"] for c_ in r["conflicts"]}


def test_cut_photo_is_reported_incomplete():
    r = consensus.compare(A, bl(B_OK[:1]))
    assert r["status"] == "INCOMPLETE"


def test_figure_labels_compared():
    out = reading.figure_label_conflicts("q1f1", ["A", "B", "(5, 0)"], ["A", "8", "(5,0)"])
    assert {(x["a"], x["b"]) for x in out} == {("B", ""), ("", "8")}


# ------------------------------------------------------------------ pipeline + export gate
def _run(misread=False, images=None):
    mock_gemini.install(misread=misread)
    qd = [{"question_number": 1, "points": 100.0, "images": images or [page_image()]}]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(1), qd, verify=True)
    return exam, qd


def test_pipeline_runs_reader_b_and_agreeing_readings_pass_the_gate():
    exam, qd = _run()
    q = exam.questions[0]
    assert q.reading_check["mode"] == "photo" and q.reading_check["reader"] == "gemini-lines"
    assert q.reading_check["report"]["status"] == "AGREED", q.reading_check["report"]
    assert q.reading_check["figure_labels"]                                    # figure labels were read again
    errors, _ = c.validate_exam(exam, meta(1), qd)
    assert not [e for e in errors if "READING_" in e], errors


def test_misread_blocks_export_until_fixed_or_confirmed():
    exam, qd = _run(misread=True)
    q = exam.questions[0]
    errors, _ = c.validate_exam(exam, meta(1), qd)
    assert any("READING_CONFLICT" in e for e in errors), errors
    # the teacher corrects the stem to what is printed -> recomputed from the stored readings, no API call
    q.text = q.text.replace("x^{2}-4", "x^{2}-9")
    errors, _ = c.validate_exam(exam, meta(1), qd)
    assert not [e for e in errors if "READING_" in e], errors


def test_teacher_confirmation_clears_the_gate():
    exam, qd = _run(misread=True)
    c.mark_teacher_verified(exam.questions[0])
    errors, _ = c.validate_exam(exam, meta(1), qd)
    assert not [e for e in errors if "READING_" in e]


def test_reader_failure_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(second_reader.GeminiLineReader, "read_lines", boom)
    exam, qd = _run()
    q = exam.questions[0]
    assert q.reading_check.get("error") and not q.analysis_error              # the analysis itself survives
    errors, _ = c.validate_exam(exam, meta(1), qd)
    assert any("READING_CHECK_FAILED" in e for e in errors)


def test_pdf_questions_are_checked_against_the_text_layer():
    q = c.empty_question(1, 100.0)
    q.text = "נתונה הפונקצייה $f(x)$ ועליו כתובים כל שיעורי נקודות החיתוך."
    question = {"images": [], "document": {"text_layer": "x", "source_lines": [
        "נתונה הפונקצייה f(x) ועליו כתובים כל שיעורי נקודות החיתוך."]}}
    reading.run_reading_check(None, q, question)
    assert q.reading_check["reader"] == "pdf-text-layer" and q.reading_check["report"]["status"] == "AGREED"
    q.text = q.text.replace("הפונקצייה", "הפונקציה")                         # the classic spelling slip
    assert any("הפונקציה" in m for m in reading.gate_messages(q))


# ------------------------------------------------------------------ Claude back-end (request shape, parsing)
class _FakeAnthropic:
    def __init__(self, payload):
        self.payload, self.requests = payload, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload, ensure_ascii=False))])


def test_claude_reader_request_and_parsing():
    fake = _FakeAnthropic({"lines": [{"index": 0, "text": "שורה $x$", "unreadable": False},
                                     {"index": 1, "text": "שנייה", "unreadable": False}]})
    r = second_reader.ClaudeLineReader(client=fake)
    got = r.read_lines([b"png0", b"png1"])
    assert [g.text for g in got] == ["שורה $x$", "שנייה"]
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["thinking"] == {"type": "adaptive"}
    schema = req["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False and set(schema["required"]) == {"lines"}
    item = schema["$defs"]["LineReading"]
    assert item["additionalProperties"] is False and set(item["required"]) == {"index", "text", "unreadable"}
    images = [b_ for b_ in req["messages"][0]["content"] if b_["type"] == "image"]
    assert len(images) == 2


def test_reader_selection():
    assert isinstance(second_reader.make_reader(object(), {}), second_reader.GeminiLineReader)
    assert isinstance(second_reader.make_reader(object(), {"SECOND_READER": "claude"}), second_reader.GeminiLineReader)  # no key
