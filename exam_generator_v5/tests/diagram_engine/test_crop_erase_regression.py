"""Crop / Erase / Rotate / Straighten / Undo regression at function level (the browser E2E covers the UI).
Also proves that the bytes sent to the AI (and to the diagram engine) are the LAST edited version."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import exam_core as c  # noqa: E402


def page() -> bytes:
    im = Image.new("RGB", (1200, 900), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((100, 100, 300, 250), fill="black")          # blot to erase
    d.rectangle((700, 500, 1000, 800), outline="black", width=6)   # content to keep
    d.text((720, 520), "x^2-4", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def arr(b: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(b)).convert("L"))


def mask_for(size, box, display_scale=2.0) -> np.ndarray:
    """Canvas RGBA layer at DISPLAY size (full size / scale) with the box painted."""
    w, h = int(size[0] / display_scale), int(size[1] / display_scale)
    m = np.zeros((h, w, 4), np.uint8)
    x0, y0, x1, y1 = (int(v / display_scale) for v in box)
    m[y0:y1, x0:x1] = [255, 0, 0, 255]
    return m


def crop(b: bytes, box, scale=2.0) -> bytes:
    x0, y0, x1, y1 = box
    return c.crop_full_resolution(b, {"left": x0 / scale, "top": y0 / scale, "width": (x1 - x0) / scale, "height": (y1 - y0) / scale}, scale)


def test_crop_full_resolution():
    out = crop(page(), (600, 400, 1100, 900))
    assert Image.open(io.BytesIO(out)).size == (500, 500)


def test_erase_whitens_only_marked_region():
    b = page()
    out, frac = c.apply_erase_mask(b, mask_for((1200, 900), (90, 90, 310, 260)))
    a = arr(out)
    assert a[150:200, 150:250].min() > 240 and a[500:506, 700:1000].max() < 60 and 0 < frac < 0.1


def test_crop_then_erase():
    b = crop(page(), (50, 50, 1100, 850))                      # 1050 x 800, blot now at (50..250, 50..200)
    out, _ = c.apply_erase_mask(b, mask_for((1050, 800), (40, 40, 260, 210)))
    a = arr(out)
    assert a.shape == (800, 1050) and a[80:180, 80:230].min() > 240


def test_erase_then_crop():
    b, _ = c.apply_erase_mask(page(), mask_for((1200, 900), (90, 90, 310, 260)))
    out = crop(b, (50, 50, 1100, 850))
    a = arr(out)
    assert a.shape == (800, 1050) and a[80:180, 80:230].min() > 240 and a[450:456, 650:950].max() < 60


def test_rotate_then_erase_and_erase_then_rotate():
    r = c.rotate_image_bytes(page(), 90)
    assert Image.open(io.BytesIO(r)).size == (900, 1200)
    # after a 90° CCW rotation the blot (x 100..300, y 100..250) is at x 100..250, y 900..1100
    out, _ = c.apply_erase_mask(r, mask_for((900, 1200), (90, 890, 260, 1110)))
    assert arr(out)[950:1050, 120:230].min() > 240
    e, _ = c.apply_erase_mask(page(), mask_for((1200, 900), (90, 90, 310, 260)))
    r2 = arr(c.rotate_image_bytes(e, 90))
    assert r2[950:1050, 120:230].min() > 240


def test_straighten_then_crop():
    tilted = c.rotate_image_bytes(page(), 4)
    straight, angle = c.auto_straighten_bytes(tilted)
    assert abs(angle) > 1
    w, h = Image.open(io.BytesIO(straight)).size
    out = crop(straight, (0, 0, w // 2, h // 2))
    assert Image.open(io.BytesIO(out)).size == (w // 2, h // 2)


def test_undo_history_semantics_like_app():
    """app.update_item keeps at most 3 frames; undo restores the previous bytes exactly."""
    item = {"original": page(), "current": page(), "history": []}
    frames = [item["current"]]
    for k in range(4):
        new = crop(item["current"], (0, 0, 1000 - 50 * k, 800 - 50 * k))
        item["history"] = (item["history"] + [item["current"]])[-3:]
        item["current"] = new
        frames.append(new)
    assert len(item["history"]) == 3
    item["current"] = item["history"].pop()
    assert item["current"] == frames[-2]


def test_edited_bytes_are_what_the_ai_and_diagram_engine_receive(monkeypatch):
    import mock_gemini
    from test_core import meta

    mock_gemini.install()
    sent: list[str] = []
    orig = c._image_parts

    def spy(question):
        parts = orig(question)
        sent.extend(c.image_digest(img) for img in question["images"])
        return parts

    monkeypatch.setattr(c, "_image_parts", spy)
    edited, _ = c.apply_erase_mask(crop(page(), (50, 50, 1100, 850)), mask_for((1050, 800), (40, 40, 260, 210)))
    qd = [{"question_number": 1, "points": 50.0, "images": [edited]}, {"question_number": 2, "points": 50.0, "images": [edited]}]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=False)
    assert set(sent) == {c.image_digest(edited)}
    for q in exam.questions:
        for fig in q.figures:
            rec = q.diagrams[fig.figure_id]
            assert rec.spec.source_image_hash == __import__("hashlib").sha256(c.figure_source_crop(fig, [edited])).hexdigest()


def test_approved_table_becomes_native_docx_table():
    import json
    import zipfile

    import diagram_engine as de
    import mock_gemini
    from test_core import meta

    mock_gemini.install()
    qd = [{"question_number": i, "points": 50.0, "images": [page()]} for i in (1, 2)]
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=False)
    q = exam.questions[0]
    fig = q.figures[0]
    rows = [["סוג", "ילדים"], ["המחיר (בשקלים)", "60"]]
    spec = {"diagram_type": "table", "subtype": "numeric_table", "confidence": 0.93, "labels": [],
            "table": {"header_rows": 1, "header_columns": 1, "rows": [[{"text": x} for x in r] for r in rows]},
            "observed": {"table_shape": [2, 2], "table_cells": rows}}
    from diagram_engine.schemas import DiagramSpec
    q.diagram_specs[fig.figure_id] = DiagramSpec.model_validate(spec)          # PASS-2 typed spec
    c.attach_diagrams(q, qd[0]["images"])
    rec = q.diagrams[fig.figure_id]
    xml_before = zipfile.ZipFile(io.BytesIO(c.create_word_document(exam, meta(), qd, "exam")[0])).read("word/document.xml").decode()
    assert "המחיר (בשקלים)" not in xml_before                      # not approved -> source image
    assert de.approve(rec)
    xml = zipfile.ZipFile(io.BytesIO(c.create_word_document(exam, meta(), qd, "exam")[0])).read("word/document.xml").decode()
    assert "המחיר (בשקלים)" in xml and xml.count("<w:tbl>") >= 1 and "60" in xml
