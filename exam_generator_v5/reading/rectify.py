"""Photo -> flat, evenly lit page image, before ANY reading (AI, second reader, OCR, diagram crops).

A phone photo of an exam page has perspective distortion, a background around the sheet, shadows / uneven light and a
small tilt. All three hurt every reader (measured on real Bagrut pages: Tesseract fell from ~90 % to ~50 % of the Hebrew
words and ~30 % of the numbers). This module undoes them deterministically:

1. page quad  - the sheet is the largest bright convex quadrilateral; its 4 corners are mapped to a rectangle
                 (perspective correction at FULL resolution). Refused (image kept) when the quad is implausible.
2. lighting   - every channel is divided by a smooth background estimate (shadow / gradient removal, colours kept).
3. residual   - the remaining tilt is measured on the text lines and rotated away.

Every step is optional and reported in `info`; a step that cannot be done safely is skipped, never guessed."""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

RECTIFY_VERSION = "rectify/1.0"
MIN_PAGE_FRACTION = 0.25     # the sheet must cover at least a quarter of the photo
FULL_FRAME = 0.96            # a quad covering ~the whole frame = already a scan / crop -> no warp
MAX_WORK_SIDE = 1100         # detection runs on a small copy; the warp is applied to the full image
TARGET_WIDTH = 2400          # flattened page width in px (A4 ~290 dpi): small text stays readable for every reader
MAX_UPSCALE = 2.0


def _cv2():
    import cv2  # opencv-python-headless (already a dependency for the OCR channel)
    return cv2


def _order(pts: np.ndarray) -> np.ndarray:
    """tl, tr, br, bl."""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_page_quad(rgb: np.ndarray) -> np.ndarray | None:
    """Corners (full-resolution pixel coords, tl/tr/br/bl) of the sheet, or None."""
    cv2 = _cv2()
    h, w = rgb.shape[:2]
    k = min(1.0, MAX_WORK_SIDE / max(h, w))
    small = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (7, 7), 0)
    area_img = small.shape[0] * small.shape[1]
    candidates = []
    # (a) paper is brighter than the background; (b) paper edges
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((5, 5), np.uint8))
    for mask in (bright, edges):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            hull = cv2.convexHull(c)
            if cv2.contourArea(hull) < MIN_PAGE_FRACTION * area_img:
                continue
            peri = cv2.arcLength(hull, True)
            for eps in (0.02, 0.03, 0.05):
                approx = cv2.approxPolyDP(hull, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    candidates.append(approx.reshape(4, 2).astype(np.float32))
                    break
    if not candidates:
        return None
    quad = max(candidates, key=lambda q: cv2.contourArea(q))
    return _order(quad / k)


def _plausible(quad: np.ndarray, w: int, h: int) -> bool:
    tl, tr, br, bl = quad
    wid = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    hei = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    if wid < 50 or hei < 50:
        return False
    ratio = hei / wid
    if not 0.35 <= ratio <= 2.8:            # A4 portrait 1.41, landscape 0.71, a cut question strip can be wide
        return False
    # opposite sides of a photographed rectangle stay within a sane length ratio
    for a, b in ((np.linalg.norm(tr - tl), np.linalg.norm(br - bl)), (np.linalg.norm(bl - tl), np.linalg.norm(br - tr))):
        if min(a, b) / max(a, b) < 0.6:
            return False
    return True


def _covers_frame(quad: np.ndarray, w: int, h: int) -> bool:
    cv2 = _cv2()
    return cv2.contourArea(quad) >= FULL_FRAME * w * h


def warp_to_quad(rgb: np.ndarray, quad: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    tl, tr, br, bl = quad
    wid0 = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    hei0 = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    up = min(MAX_UPSCALE, max(1.0, TARGET_WIDTH / max(wid0, 1.0)))
    wid, hei = int(round(wid0 * up)), int(round(hei0 * up))
    dst = np.array([[0, 0], [wid - 1, 0], [wid - 1, hei - 1], [0, hei - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    return cv2.warpPerspective(rgb, m, (wid, hei), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


def needs_illumination_fix(rgb: np.ndarray) -> bool:
    """Uneven background: the paper brightness varies by more than ~12 % across the page."""
    cv2 = _cv2()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    bg = cv2.dilate(small, np.ones((7, 7), np.uint8))          # paper level (text removed)
    lo, hi = np.percentile(bg, 5), np.percentile(bg, 95)
    return (hi > 0 and (hi - lo) / hi > 0.12) or hi < 200


def normalize_illumination(rgb: np.ndarray) -> np.ndarray:
    """Divide by a smooth estimate of the paper (text removed by a large closing): shadows and gradients vanish,
    ink keeps its colour. Output paper is white."""
    cv2 = _cv2()
    h, w = rgb.shape[:2]
    k = max(15, (min(h, w) // 40) | 1)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 2).astype(np.float32)
    bg = np.maximum(bg, 30.0)
    out = rgb.astype(np.float32) * (255.0 / bg)[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def residual_skew(rgb: np.ndarray, max_angle: float = 6.0) -> float:
    """Tilt of the text lines in degrees (projection-profile search), 0 when unsure."""
    cv2 = _cv2()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    k = min(1.0, 900 / max(gray.shape))
    small = cv2.resize(gray, (int(gray.shape[1] * k), int(gray.shape[0] * k)), interpolation=cv2.INTER_AREA)
    ink = (small < 140).astype(np.float32)
    if ink.mean() < 0.003:
        return 0.0
    h, w = ink.shape
    centre = (w / 2, h / 2)
    best, best_score, scores = 0.0, -1.0, []
    for ang in np.arange(-max_angle, max_angle + 0.01, 0.25):
        m = cv2.getRotationMatrix2D(centre, ang, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST)
        prof = rot.sum(1)
        score = float(np.var(prof))
        scores.append(score)
        if score > best_score:
            best, best_score = float(ang), score
    if best_score <= 0 or best_score < 1.05 * float(np.median(scores)):
        return 0.0                                       # no clear line structure (e.g. a figure only)
    return best


def rectify_array(rgb: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    cv2 = _cv2()
    info: dict[str, Any] = {"version": RECTIFY_VERSION, "perspective": False, "illumination": False, "skew_deg": 0.0}
    h, w = rgb.shape[:2]
    quad = find_page_quad(rgb)
    if quad is not None and _plausible(quad, w, h) and not _covers_frame(quad, w, h):
        rgb = warp_to_quad(rgb, quad)
        info["perspective"] = True
        info["corners"] = [[round(float(x), 1), round(float(y), 1)] for x, y in quad]
    if needs_illumination_fix(rgb):
        rgb = normalize_illumination(rgb)
        info["illumination"] = True
    ang = residual_skew(rgb)
    if abs(ang) >= 0.3:
        hh, ww = rgb.shape[:2]
        m = cv2.getRotationMatrix2D((ww / 2, hh / 2), ang, 1.0)
        rgb = cv2.warpAffine(rgb, m, (ww, hh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        info["skew_deg"] = round(ang, 2)
    info["changed"] = info["perspective"] or info["illumination"] or bool(info["skew_deg"])
    return rgb, info


def rectify_photo_bytes(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """PNG/JPEG bytes -> (PNG bytes of the flattened page, info). On any failure the input is returned unchanged."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        rgb = np.asarray(img.convert("RGB"))
        out, info = rectify_array(rgb)
        if not info["changed"]:
            return data, info
        buf = io.BytesIO()
        Image.fromarray(out).save(buf, format="PNG", optimize=True)
        return buf.getvalue(), info
    except Exception as exc:                                  # never block the teacher's upload
        return data, {"version": RECTIFY_VERSION, "changed": False, "error": str(exc)[:200]}
