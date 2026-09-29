"""Tesseract-based independent OCR: numbers/percentages, table cells (grid-detected, per-cell), point labels.

If Tesseract is not installed the channel reports itself unavailable and nothing is verified by it (fail closed:
facts then stay AI-only and require the teacher)."""
from __future__ import annotations

import io
import re
import shutil
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

NUM = re.compile(r"^-?\d+(?:[.,]\d+)?%?$")


@lru_cache(maxsize=1)
def available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


@lru_cache(maxsize=1)
def languages() -> tuple[str, ...]:
    try:
        import pytesseract
        return tuple(pytesseract.get_languages(config=""))
    except Exception:
        return ()


OCR_NORMALIZED_MAX_SIDE = 1600      # OCR derivative: resolution-normalized, so decisions do not depend on the DPI


def _img(png: bytes) -> Image.Image:
    with Image.open(io.BytesIO(png)) as im:
        g = ImageOps.grayscale(im.convert("RGB"))
    if max(g.size) > OCR_NORMALIZED_MAX_SIDE:
        g.thumbnail((OCR_NORMALIZED_MAX_SIDE, OCR_NORMALIZED_MAX_SIDE), Image.Resampling.LANCZOS)
    return g


def _data(im: Image.Image, lang: str, psm: int, whitelist: str = "") -> list[dict]:
    import pytesseract
    cfg = f"--psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    d = pytesseract.image_to_data(im, lang=lang, config=cfg, output_type=pytesseract.Output.DICT, timeout=20)
    out = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        if t:
            out.append({"text": t, "conf": float(d["conf"][i]) / 100.0,
                        "bbox": [d["left"][i], d["top"][i], d["width"][i], d["height"][i]]})
    return out


def text_regions(g: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Character-sized connected components grouped into words (lines/curves/frames are excluded).
    Needs OpenCV; without it returns [] (channel unavailable -> nothing verified)."""
    try:
        import cv2
    except Exception:
        return []
    bw = (g < 150).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 5 <= h <= 45 and 1 <= w <= 45 and area >= 4 and not (w > 3 * h and h < 6):
            boxes.append([x, y, x + w, y + h])
    boxes.sort()
    words: list[list[int]] = []
    for b in boxes:
        h = b[3] - b[1]
        tgt = next((wd for wd in words if b[0] - wd[2] < max(4, 0.7 * h) and b[0] >= wd[0] - 2
                    and min(b[3], wd[3]) - max(b[1], wd[1]) > 0.4 * min(h, wd[3] - wd[1])), None)
        if tgt is None:
            words.append(list(b))
        else:
            tgt[0], tgt[1], tgt[2], tgt[3] = min(tgt[0], b[0]), min(tgt[1], b[1]), max(tgt[2], b[2]), max(tgt[3], b[3])
    return [tuple(w) for w in words if (w[3] - w[1]) >= 6]


def _read_regions(png: bytes, whitelist: str, pattern: re.Pattern, min_conf: float) -> list[dict]:
    import time

    from ..constants import OCR_MAX_PSM_ATTEMPTS, OCR_MAX_REGIONS, OCR_TOTAL_BUDGET_SECONDS
    if not available():
        return []
    g = np.asarray(_img(png))
    base = Image.fromarray(g)
    out = []
    t0 = time.monotonic()
    regions = text_regions(g)[:OCR_MAX_REGIONS]
    for x0, y0, x1, y1 in regions:
        if time.monotonic() - t0 > OCR_TOTAL_BUDGET_SECONDS:
            break                                   # budget exhausted: remaining regions are simply not evidence
        crop = base.crop((max(0, x0 - 3), max(0, y0 - 3), x1 + 3, y1 + 3))
        f = max(1.0, min(5.0, 64.0 / max(1, crop.height)))
        crop = ImageOps.expand(crop.resize((int(crop.width * f), int(crop.height * f)), Image.Resampling.LANCZOS), 24, fill=255)
        best = None
        for psm in (7, 8)[:OCR_MAX_PSM_ATTEMPTS]:
            toks = _data(crop, "eng", psm, whitelist)
            t = "".join(tok["text"] for tok in toks).replace(",", ".")
            c = min((tok["conf"] for tok in toks), default=0.0)
            if pattern.fullmatch(t) and c >= min_conf and (best is None or c > best["conf"]):
                best = {"text": t, "conf": c, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2}
        if best:
            out.append(best)
    return out


def _cached(kind: str, png: bytes, fn):
    """OCR is expensive (external process): results are cached by image hash + OCR version (thread-safe LRU)."""
    from .. import cache
    return cache.OCR.get_or_compute(cache.key("ocr", kind, _config_key(), cache_image_hash(png)), fn)


def cache_image_hash(png: bytes) -> str:
    import hashlib
    return hashlib.sha256(png).hexdigest()


OCR_VERSION = "ocr/1.2"


def _config_key() -> str:
    from ..constants import OCR_MAX_PSM_ATTEMPTS, OCR_MAX_REGIONS, OCR_TOTAL_BUDGET_SECONDS
    return f"{OCR_VERSION}|{OCR_MAX_REGIONS}|{OCR_MAX_PSM_ATTEMPTS}|{OCR_TOTAL_BUDGET_SECONDS}|{','.join(languages())}"


def numbers(png: bytes) -> list[dict]:
    """Numeric tokens (incl. percentages): isolated word regions read one by one."""
    return [dict(t) for t in _cached("numbers", png, lambda: _read_regions(png, "0123456789.%-", NUM, 0.55))]


ANGLE = re.compile(r"^(\d{1,3}(?:\.\d+)?)(?:°|º|o|O)?$")


def angle_numbers(png: bytes) -> list[dict]:
    """Numbers that may carry a degree sign. Common OCR substitutions of ° ('o', 'º', a trailing '0') are normalised:
    a token 'NN0' is returned with alternatives {NN0, NN} - the matcher decides, never a silent rewrite."""
    toks = [dict(t) for t in _cached("angles", png, lambda: _read_regions(png, "0123456789.°º", re.compile(r"\d{1,4}(?:\.\d+)?[°º]?"), 0.55))]
    for t in toks:
        raw = t["text"].replace("º", "°")
        t["degree"] = raw.endswith("°")
        v = raw.rstrip("°")
        t["alternatives"] = [v] + ([v[:-1]] if not t["degree"] and len(v) >= 2 and v.endswith("0") else [])
    return toks


def labels(png: bytes) -> list[dict]:
    """Single upper-case letters (point labels)."""
    return [dict(t) for t in _cached("labels", png, lambda: _read_regions(png, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", re.compile(r"[A-Z]"), 0.6))]


def _lines(mask: np.ndarray, axis: int, frac: float) -> list[int]:
    arr = mask if axis == 1 else mask.T
    need = int(frac * arr.shape[1])
    idx = [i for i, row in enumerate(arr) if row.sum() >= need]
    groups: list[list[int]] = []
    for i in idx:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [int(round(sum(g) / len(g))) for g in groups]


def table_cells(png: bytes, rtl: bool = True) -> dict:
    import copy
    return copy.deepcopy(_cached(f"table{int(rtl)}", png, lambda: _table_cells(png, rtl)))


def _table_cells(png: bytes, rtl: bool = True) -> dict:
    """Grid lines -> cells -> per-cell OCR. Returns {"ok", "rows": [[{"text","conf","numeric"}]], "reason"}.
    Rows/columns are returned in reading order (column 0 = rightmost when rtl)."""
    if not available():
        return {"ok": False, "rows": [], "reason": "OCR לא זמין"}
    g = np.asarray(_img(png))
    dark = g < 160
    # the table's extent = the span of its long vertical rules (text lines above/below are not rules)
    H = dark.shape[0]
    runs = []
    for x in range(dark.shape[1]):
        col, best, cur, start, bstart = dark[:, x], 0, 0, 0, 0
        for y in range(H):
            if col[y]:
                if cur == 0:
                    start = y
                cur += 1
                if cur > best:
                    best, bstart = cur, start
            else:
                cur = 0
        if best >= 0.3 * H:
            runs.append((x, bstart, bstart + best))
    if len(runs) < 2:
        return {"ok": False, "rows": [], "reason": "לא זוהו קווי טבלה"}
    top = int(np.median([r[1] for r in runs]))
    bottom = int(np.median([r[2] for r in runs]))
    rows = [r for r in _lines(dark, 1, 0.5) if top - 3 <= r <= bottom + 3]
    if len(rows) < 2:
        return {"ok": False, "rows": [], "reason": "לא זוהו שורות טבלה"}
    cols = _lines(dark[top:bottom + 1], 0, 0.85)          # columns measured INSIDE the table band
    if len(cols) < 2:
        return {"ok": False, "rows": [], "reason": "לא זוהו עמודות"}
    lang = "heb+eng" if "heb" in languages() else "eng"
    base = Image.fromarray(g)
    out = []
    for r0, r1 in zip(rows, rows[1:]):
        row = []
        for c0, c1 in zip(cols, cols[1:]):
            cell = base.crop((c0 + 3, r0 + 3, c1 - 2, r1 - 2))
            if cell.width < 4 or cell.height < 4:
                row.append({"text": "", "conf": 0.0, "numeric": None})
                continue
            f = max(1.0, min(4.0, 120.0 / max(1, cell.height)))         # target cell height (resolution-normalized, not a fixed 3x)
            cell = cell.resize((int(cell.width * f), int(cell.height * f)), Image.Resampling.LANCZOS)
            cell = ImageOps.expand(cell, 20, fill=255)
            toks = _data(cell, "eng", 7, "0123456789.%-")
            num = "".join(t["text"] for t in toks) if toks else ""
            conf = min((t["conf"] for t in toks), default=0.0)
            numeric = num if NUM.match(num or "x") and conf >= 0.45 else None
            text = num
            if numeric is None and "heb" in lang:
                ht = _data(cell, lang, 7)
                text = " ".join(t["text"] for t in ht)
                conf = min((t["conf"] for t in ht), default=0.0)
            row.append({"text": text, "conf": conf, "numeric": numeric})
        out.append(list(reversed(row)) if rtl else row)
    return {"ok": True, "rows": out, "reason": ""}
