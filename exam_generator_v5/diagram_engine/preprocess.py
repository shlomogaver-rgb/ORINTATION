"""Image preparation for comparison / archiving (no AI)."""
from __future__ import annotations

import hashlib
import io

import numpy as np
from PIL import Image, ImageOps


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _otsu(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total, sum_total = gray.size, float(np.dot(np.arange(256), hist))
    w_b = sum_b = 0.0
    best_t, best = 127, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        var = w_b * w_f * ((sum_b / w_b) - (sum_total - sum_b) / w_f) ** 2
        if var > best:
            best, best_t = var, t
    return best_t


def ink_mask(img: Image.Image, size: int = 160) -> np.ndarray:
    """Binary ink mask, cropped to content and resized to size x size (aspect kept, padded)."""
    g = ImageOps.grayscale(img.convert("RGB"))
    arr = np.asarray(g, dtype=np.uint8)
    blur = np.asarray(g.resize((max(1, g.width // 16), max(1, g.height // 16))).resize(g.size, Image.Resampling.BILINEAR), dtype=np.int16)
    flat = np.clip(arr.astype(np.int16) - blur + 200, 0, 255).astype(np.uint8)
    ink = flat < min(_otsu(flat), 185)
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return np.zeros((size, size), bool)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = Image.fromarray((ink * 255).astype(np.uint8))
    im.thumbnail((size, size), Image.Resampling.BILINEAR)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return np.asarray(canvas) > 60


def cleaned_png(data: bytes) -> bytes:
    """Clean black-on-white version of the source crop (archive / comparison)."""
    with Image.open(io.BytesIO(data)) as im:
        g = ImageOps.grayscale(im.convert("RGB"))
    arr = np.asarray(g, dtype=np.uint8)
    blur = np.asarray(g.resize((max(1, g.width // 16), max(1, g.height // 16))).resize(g.size, Image.Resampling.BILINEAR), dtype=np.int16)
    flat = np.clip(arr.astype(np.int16) - blur + 200, 0, 255).astype(np.uint8)
    out = np.where(flat < min(_otsu(flat), 185), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="PNG")
    return buf.getvalue()
