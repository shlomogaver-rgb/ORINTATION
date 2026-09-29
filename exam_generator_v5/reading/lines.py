"""Split a (rectified) question image into its printed text lines, for the second, line-by-line reader.

Line GEOMETRY is reliable even where Tesseract's RECOGNITION is not, so Tesseract's layout analysis is used when it is
installed; otherwise a horizontal projection profile. Figure regions are blanked first, so labels inside a drawing never
become "lines" (the drawing's labels are checked separately)."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

MIN_LINE_PX = 8
TARGET_LINE_HEIGHT = 64      # crops are upscaled so the x-height is comfortable for any reader


@dataclass
class Line:
    image_index: int                 # 1-based, like FigureRef.source_image_index
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels of that image
    norm_bbox: list[int] = field(default_factory=list)   # [ymin, xmin, ymax, xmax] 0..1000 (the project's convention)
    crop_png: bytes = b""


def _blank_figures(img: Image.Image, figure_boxes: list[list[int]]) -> Image.Image:
    """figure_boxes: [ymin, xmin, ymax, xmax] 0..1000."""
    if not figure_boxes:
        return img
    out = img.copy()
    w, h = out.size
    from PIL import ImageDraw
    d = ImageDraw.Draw(out)
    for b in figure_boxes:
        if len(b) != 4:
            continue
        y0, x0, y1, x1 = b
        d.rectangle([x0 * w / 1000 - 4, y0 * h / 1000 - 4, x1 * w / 1000 + 4, y1 * h / 1000 + 4], fill="white")
    return out


def _tesseract_lines(gray: Image.Image) -> list[tuple[int, int, int, int]] | None:
    try:
        from diagram_engine.ocr import engine
        if not engine.available():
            return None
        import pytesseract
        d = pytesseract.image_to_data(gray, lang="heb+eng" if "heb" in engine.languages() else "eng",
                                      config="--psm 3", output_type=pytesseract.Output.DICT, timeout=60)
    except Exception:
        return None
    boxes = []
    for i, lvl in enumerate(d["level"]):
        if lvl == 4 and d["width"][i] > 10 and d["height"][i] >= MIN_LINE_PX:
            boxes.append((d["left"][i], d["top"][i], d["left"][i] + d["width"][i], d["top"][i] + d["height"][i]))
    return boxes


def _profile_lines(gray: Image.Image) -> list[tuple[int, int, int, int]]:
    a = np.asarray(gray)
    ink = a < 150
    rows = ink.sum(1) > max(2, 0.002 * a.shape[1])
    boxes, y = [], 0
    while y < len(rows):
        if not rows[y]:
            y += 1
            continue
        y0 = y
        while y < len(rows) and rows[y]:
            y += 1
        if y - y0 >= MIN_LINE_PX:
            cols = np.where(ink[y0:y].any(0))[0]
            if len(cols):
                boxes.append((int(cols[0]), y0, int(cols[-1]) + 1, y))
    return boxes


def _merge(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Tesseract sometimes splits one printed line around a formula: pieces that overlap vertically are one line."""
    boxes = sorted(boxes, key=lambda b: (b[1], -b[2]))
    out: list[list[int]] = []
    for b in boxes:
        for m in out:
            ov = min(m[3], b[3]) - max(m[1], b[1])
            if ov > 0.5 * min(m[3] - m[1], b[3] - b[1]):
                m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            out.append(list(b))
    return [tuple(m) for m in sorted(out, key=lambda m: m[1])]


def split_lines(image_png: bytes, image_index: int = 1, figure_boxes: list[list[int]] | None = None) -> list[Line]:
    img = Image.open(io.BytesIO(image_png)).convert("RGB")
    w, h = img.size
    gray = _blank_figures(img, figure_boxes or []).convert("L")
    boxes = _tesseract_lines(gray)
    if not boxes:
        boxes = _profile_lines(gray)
    if not boxes:
        return []
    # drop page-size / border artefacts BEFORE merging (one giant box would swallow every line)
    med0 = float(np.median([b[3] - b[1] for b in boxes]))
    boxes = [b for b in boxes if (b[3] - b[1]) <= 5 * med0 and (b[2] - b[0]) < 0.995 * w]
    boxes = _merge(boxes)
    if not boxes:
        return []
    med = float(np.median([b[3] - b[1] for b in boxes]))
    lines = []
    for x0, y0, x1, y1 in boxes:
        hh = y1 - y0
        if hh < 0.45 * med or hh > 5 * med or (x1 - x0) < 1.2 * hh:
            continue                                   # specks, rules, stray tall marks
        pad_y, pad_x = int(0.35 * hh) + 2, 12
        box = (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y))
        crop = img.crop(box)
        k = max(1.0, min(3.0, TARGET_LINE_HEIGHT / max(1, med)))
        if k > 1.0:
            crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format="PNG", optimize=True)
        lines.append(Line(image_index, box, [int(box[1] * 1000 / h), int(box[0] * 1000 / w),
                                             int(box[3] * 1000 / h), int(box[2] * 1000 / w)], buf.getvalue()))
    return lines
