"""Independent bar-chart reader (OpenCV + OCR ticks): plot region, axes/baseline, tick values (OCR), pixel->value
calibration (least squares, never 'nearest tick'), rectangular bars, orientation, values. Unstable -> no evidence."""
from __future__ import annotations

import io
import re

import numpy as np
from PIL import Image, ImageOps

BAR_CV_VERSION = "barcv/1.0"


def _gray(png: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as im:
        return np.asarray(ImageOps.grayscale(im.convert("RGB")))


def _longest(mask: np.ndarray, axis: int) -> tuple[int, int]:
    arr = mask if axis == 1 else mask.T
    best_i, best = 0, 0
    for i, row in enumerate(arr):
        cur = run = 0
        for v in row:
            cur = cur + 1 if v else 0
            run = max(run, cur)
        if run > best:
            best, best_i = run, i
    return best_i, best


def detect(png: bytes) -> dict:
    try:
        import cv2
    except Exception:
        return {"stable": False, "reason": "OpenCV לא זמין", "bars": []}
    from ..ocr import engine as ocr
    g = _gray(png)
    H, W = g.shape
    dark = g < 110
    ax_row, row_len = _longest(dark, 1)          # horizontal axis (baseline candidate)
    ax_col, col_len = _longest(dark, 0)          # vertical axis
    # ANY bar style: black / dark / light / white-with-outline. Ink -> close -> fill holes (an outline bar closed by the axis
    # becomes solid) -> THEN cut the axis lines, which separates the bars from each other and from the axes.
    ink = (g < 235).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    flood = ink.copy() * 255
    mask = np.zeros((H + 2, W + 2), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 128)
    fill = ((flood != 128)).astype(np.uint8)                   # ink + enclosed areas
    band = max(2, int(0.004 * min(H, W)))
    fill[max(0, ax_row - band):ax_row + band + 1, :] = 0
    fill[:, max(0, ax_col - band):ax_col + band + 1] = 0
    fill = cv2.morphologyEx(fill, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))   # drop text strokes / thin lines
    n, _, stats, _ = cv2.connectedComponentsWithStats(fill, connectivity=4)
    rects = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w >= 0.02 * W and h >= 0.01 * H and area >= 0.85 * w * h and not (w > 0.8 * W and h > 0.6 * H):   # frame, not a bar
            rects.append((int(x), int(y), int(x + w), int(y + h)))
    if not rects:
        return {"stable": False, "reason": "לא זוהו עמודות", "bars": []}
    # orientation: vertical bars share the baseline row (their bottoms/tops touch ax_row)
    tb = max(2, int(0.004 * min(H, W))) + 4
    touch_row = sum(1 for r in rects if abs(r[3] - ax_row) <= tb or abs(r[1] - ax_row) <= tb)
    touch_col = sum(1 for r in rects if abs(r[0] - ax_col) <= tb or abs(r[2] - ax_col) <= tb)
    vertical = touch_row >= touch_col
    toks = ocr.numbers(png) if ocr.available() else []
    if vertical:
        ticks = [(t["cy"], float(t["text"].rstrip("%"))) for t in toks if t["cx"] < ax_col - 2 and "%" not in t["text"]]
    else:
        ticks = [(t["cx"], float(t["text"].rstrip("%"))) for t in toks if t["cy"] > ax_row + 2 and "%" not in t["text"]]
    if len({v for _, v in ticks}) < 2:
        return {"stable": False, "reason": "לא נקראו מספיק ערכי שנתות לכיול", "bars": [], "orientation": "VERTICAL" if vertical else "HORIZONTAL"}
    def fit(tk):
        px_ = np.array([p for p, _ in tk], float)
        val_ = np.array([v for _, v in tk], float)
        a_, b_ = np.polyfit(px_, val_, 1)
        ss_ = float(np.sum((val_ - val_.mean()) ** 2)) or 1.0
        return a_, b_, 1 - float(np.sum((val_ - (a_ * px_ + b_)) ** 2)) / ss_
    a, b, r2 = fit(ticks)
    zero = next((p for p, v in ticks if v == 0), None)
    if r2 < 0.999 and zero is not None:
        # the typographic minus (U+2212) is often lost by OCR: ticks on the far side of the ZERO tick are negative
        # (below it on a vertical value axis, left of it on a horizontal one); accepted only if the result is linear
        signed = [(p, -abs(v) if (p > zero if vertical else p < zero) else abs(v)) for p, v in ticks]
        a2, b2, r22 = fit(signed)
        if r22 >= 0.999:
            ticks, a, b, r2 = signed, a2, b2, r22
    if r2 < 0.999:
        return {"stable": False, "reason": f"כיול הציר אינו יציב (R²={r2:.4f})", "bars": [], "orientation": "VERTICAL" if vertical else "HORIZONTAL"}
    base_val = a * (ax_row if vertical else ax_col) + b
    bars = []
    for r in sorted(rects, key=lambda r: r[0] if vertical else -r[3]):   # the AXIS direction: left->right / bottom->top
        if vertical:
            end = r[1] if abs(r[3] - ax_row) <= tb else r[3]         # bar above baseline: top; below: bottom
            bars.append({"bbox": list(r), "value": round(float(a * end + b), 6)})
        else:
            end = r[2] if abs(r[0] - ax_col) <= tb else r[0]
            bars.append({"bbox": list(r), "value": round(float(a * end + b), 6)})
    # category OCR next to each bar (below it for vertical bars, left of the axis for horizontal ones)
    if ocr.available():
        base = Image.fromarray(g)
        lang = "heb+eng" if "heb" in ocr.languages() else "eng"
        for bar in bars:
            x0, y0, x1, y1 = bar["bbox"]
            box = (max(0, x0 - 6), min(H - 1, ax_row + 3), min(W, x1 + 6), min(H, ax_row + int(0.12 * H))) if vertical else \
                  (0, max(0, y0 - 2), max(1, ax_col - 3), min(H, y1 + 2))
            try:
                crop = base.crop(box)
                crop = ImageOps.expand(crop.resize((max(1, crop.width * 3), max(1, crop.height * 3))), 20, fill=255)
                toks = ocr._data(crop, lang, 7)
                bar["category_ocr"] = " ".join(t["text"] for t in toks).strip()
                bar["category_conf"] = min((t["conf"] for t in toks), default=0.0)
            except Exception:
                bar["category_ocr"], bar["category_conf"] = "", 0.0
    return {"stable": True, "orientation": "VERTICAL" if vertical else "HORIZONTAL", "calibration": {"a": a, "b": b, "r2": r2},
            "baseline_value": round(float(base_val), 6), "bars": bars, "reason": ""}


def _norm_cat(t: str) -> str:
    return re.sub(r"[\s\u200e\u200f.,:;()\[\]\\/|'\"-]", "", (t or "").lower())


def bind_categories(categories: list[str], det: dict) -> tuple[dict[str, float], int]:
    """category <-> bar binding from OCR'd category text (not from the order of the values)."""
    import difflib
    bound, used = {}, set()
    for cat in categories:
        best, score = None, 0.0
        for i, bar in enumerate(det["bars"]):
            if i in used:
                continue
            r = difflib.SequenceMatcher(None, _norm_cat(cat), _norm_cat(bar.get("category_ocr", ""))).ratio()
            if r > score:
                best, score = i, r
        if best is not None and score >= 0.75:
            bound[cat] = det["bars"][best]["value"]
            used.add(best)
    return bound, len(bound)


def verify(categories: list[str], spec_values: list[float], det: dict, tick_step: float) -> dict:
    """-> {"status": BAR_CV_UNAVAILABLE | VERIFIED | PARTIAL_BAR_VERIFICATION | CONFLICT, "conflicts": [...], "verified": {...}}
    No reverse-order acceptance without category evidence."""
    if not det.get("stable"):
        return {"status": "BAR_CV_UNAVAILABLE", "conflicts": [], "verified": {}, "reason": det.get("reason", "")}
    got = [bar["value"] for bar in det["bars"]]
    if len(got) != len(spec_values):
        return {"status": "CONFLICT", "verified": {},
                "conflicts": [f"BAR_COUNT_CONFLICT: במקור זוהו {len(got)} עמודות, בשחזור {len(spec_values)}."]}
    px_val = abs(det.get("calibration", {}).get("a", 0.0))              # value per pixel of the calibrated axis
    tol = lambda s_: max(0.02 * abs(tick_step), 0.03 * max(abs(s_), 1), 6 * px_val, 1e-6)  # noqa: E731  (stroke width)
    bound, n = bind_categories(categories, det) if categories else ({}, 0)
    if categories and n == len(categories):
        conf = [f"BAR_VALUE_CONFLICT: '{c_}': ניתוח התמונה {s_:g}, מדידה עצמאית {bound[c_]:.3g}."
                for c_, s_ in zip(categories, spec_values) if abs(s_ - bound[c_]) > tol(s_)]
        return {"status": "CONFLICT" if conf else "VERIFIED", "conflicts": conf, "verified": {} if conf else dict(bound)}
    # categories not readable: values checked in the ORDER of the axis only; the binding stays unverified
    conf = [f"BAR_VALUE_CONFLICT: עמודה {i + 1}: ניתוח התמונה {s_:g}, מדידה עצמאית {v:.3g}."
            for i, (s_, v) in enumerate(zip(spec_values, got)) if abs(s_ - v) > tol(s_)]
    return {"status": "CONFLICT" if conf else "PARTIAL_BAR_VERIFICATION", "conflicts": conf, "verified": {}}


def compare(spec_values: list[float], det: dict, tick_step: float) -> list[str]:
    """Back-compatible helper (values only, axis order)."""
    return verify([], spec_values, det, tick_step)["conflicts"]
