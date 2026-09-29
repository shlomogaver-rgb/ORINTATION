"""Full-resolution master pipeline: no destructive early downsampling; ROI from the master; edit replay; provenance;
DPI/scale invariance of the independent evidence."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import exam_core as c  # noqa: E402
from image_store import ImageItem  # noqa: E402

FIX = ROOT / "tests" / "diagram_engine" / "acceptance" / "fixtures"


def big_photo(w=5200, h=3900) -> bytes:
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((300, 300, 900, 800), fill="black")                       # blot to erase
    d.ellipse((3000, 2000, 3040, 2040), fill="black")                      # tiny mark (lost when downsampled 2x)
    d.line((2500, 1800, 4500, 3500), fill="black", width=3)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_keeps_full_resolution_master(tmp_path):
    raw = big_photo()
    master = c.image_to_png_bytes(raw, max_side=None)
    working = c.pil_to_png_bytes(c.png_bytes_to_pil(master))
    assert c.png_bytes_to_pil(master).size == (5200, 3900) and max(c.png_bytes_to_pil(working).size) == c.MAX_IMAGE_SIDE
    item = ImageItem(str(tmp_path), master, working, "i1")
    assert item["master"] == master and item["current"] == working and not item["history"]


def test_edit_chain_replayed_on_master_and_roi_is_full_resolution(tmp_path):
    master = c.image_to_png_bytes(big_photo(), max_side=None)
    working = c.pil_to_png_bytes(c.png_bytes_to_pil(master))
    item = ImageItem(str(tmp_path), master, working, "i1")
    W, H = c.png_bytes_to_pil(working).size
    scale = 2.0                                                            # display = working / 2
    box = {"left": 1100 / scale * W / 5200, "top": 900 / scale * H / 3900, "width": 3800 / scale * W / 5200, "height": 2800 / scale * H / 3900}
    rect = c.crop_box_to_normalized(item["current"], box, scale)
    item.push(c.crop_full_resolution(item["current"], box, scale), {"type": "crop", "rect": rect})
    mask = np.zeros((int(c.png_bytes_to_pil(item["current"]).height / 2), int(c.png_bytes_to_pil(item["current"]).width / 2), 4), np.uint8)
    buf = io.BytesIO()
    Image.fromarray(mask, "RGBA").save(buf, format="PNG")
    me = item.master_current()
    img = c.png_bytes_to_pil(me)
    assert abs(img.width - 3800) <= 2 and abs(img.height - 2800) <= 2        # crop replayed at FULL resolution
    prov = item.provenance()
    assert prov["master_available"] and prov["master_edited_hash"] and prov["ops"][0]["type"] == "crop"
    # ROI from the master: the tiny mark keeps its full detail
    from exam_core import FigureRef
    fig = FigureRef(description="d", source_image_index=1, bbox=[250, 450, 450, 650], figure_type="source_crop")
    roi_master = c.figure_source_crop(fig, [item["current"]], [me])
    roi_preview = c.figure_source_crop(fig, [item["current"]])
    assert c.png_bytes_to_pil(roi_master).width > 1.9 * c.png_bytes_to_pil(roi_preview).width
    assert item.undo() and item["current"] == working and item.master_current() == master


def test_unknown_edit_marks_master_unavailable_never_guesses(tmp_path):
    master = c.image_to_png_bytes(big_photo(800, 600), max_side=None)
    item = ImageItem(str(tmp_path), master, master, "i1")
    item["current"] = master[:]                                            # raw replacement without a recorded op
    assert item.master_current() is None and not item.provenance()["master_available"]


@pytest.mark.parametrize("factor", [0.5, 2.0, 4.0])
def test_independent_evidence_is_scale_invariant(factor):
    """Same real crop at ~85/340/680 dpi: scatter points and table numbers must not change (or fail closed)."""
    from diagram_engine import ocr
    from diagram_engine.charts import scatter
    from diagram_engine.schemas import GraphAxes

    def scaled(name):
        im = Image.open(FIX / name).convert("RGB")
        im = im.resize((int(im.width * factor), int(im.height * factor)), Image.Resampling.LANCZOS)
        b = io.BytesIO()
        im.save(b, format="PNG")
        return b.getvalue()

    A = GraphAxes(x_min=0, x_max=30, y_min=0, y_max=60, x_step=5, y_step=10)
    r = scatter.detect(scaled("q16_p3_2.png"), A)
    truth = [[5, 50], [10, 40], [15, 30], [15, 20], [20, 30], [25, 10]]
    if r["stable"]:
        assert scatter.match(truth, r["points"], A) == []
    if ocr.available():
        t = ocr.table_cells(scaled("q18_p12_4.png"))
        if t["ok"]:
            nums = [c_["numeric"] or c_["text"] for row in t["rows"][1:] for c_ in row[1:]]
            import re as _re
            wrong = [n for n in nums if n and _re.fullmatch(r"-?\d+(?:\.\d+)?%?", n) and n not in {"60", "150", "180", "210", "5", "21", "9", "10"}]
            assert not wrong, (factor, nums)                              # may be unread, never a WRONG number
