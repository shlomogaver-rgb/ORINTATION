"""Realistic phone-photo degradation of a clean page (for the photo test set and the tests).

A page rendered from a Bagrut PDF keeps its text layer = ground truth; the degraded copy is what a teacher's phone
produces: the sheet lies on a table (background), is seen at an angle (perspective), is lit unevenly (shadow), slightly
out of focus, noisy and JPEG-compressed."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

LEVELS = {
    "mild":   dict(tilt=0.04, rot=2.0, shadow=0.20, blur=0.6, noise=4, jpeg=80, scale=0.9),
    "medium": dict(tilt=0.08, rot=4.0, shadow=0.35, blur=1.0, noise=7, jpeg=65, scale=0.8),
    "hard":   dict(tilt=0.12, rot=7.0, shadow=0.50, blur=1.4, noise=10, jpeg=50, scale=0.7),
}


def phone_photo(page: Image.Image, level: str = "medium", seed: int = 0) -> Image.Image:
    import cv2
    p = LEVELS[level]
    rng = np.random.default_rng(seed)
    src = np.asarray(page.convert("RGB"))
    h, w = src.shape[:2]
    W, H = int(w * 1.35), int(h * 1.3)                              # the table around the sheet
    table = np.full((H, W, 3), (95, 82, 70), np.float32) + rng.normal(0, 6, (H, W, 3))
    ox, oy = (W - w) / 2, (H - h) / 2
    j = lambda s: rng.uniform(-s, s) * w                            # noqa: E731
    t = p["tilt"]
    dst = np.float32([[ox + j(t), oy + j(t)], [ox + w + j(t), oy + j(t) * 1.5],
                      [ox + w + j(t), oy + h + j(t)], [ox - j(t) * 0.5, oy + h + j(t)]])
    # rotate the whole quad a little
    ang = np.deg2rad(rng.uniform(-p["rot"], p["rot"]))
    c = dst.mean(0)
    rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]], np.float32)
    dst = ((dst - c) @ rot.T + c).astype(np.float32)
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst)
    sheet = cv2.warpPerspective(src.astype(np.float32), m, (W, H), flags=cv2.INTER_LINEAR, borderValue=(-1, -1, -1))
    mask = sheet[..., 0] >= 0
    out = np.where(mask[..., None], sheet, table)
    yy, xx = np.mgrid[0:H, 0:W]
    gx, gy = rng.uniform(0.3, 1.0), rng.uniform(0.0, 0.6)
    light = 1.0 - p["shadow"] * np.clip((xx / W) * gx + (yy / H) * gy, 0, 1)   # a soft shadow from one side
    out = out * light[..., None] * rng.uniform(0.85, 1.0) + rng.normal(0, p["noise"], out.shape)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(p["blur"]))
    img = img.resize((int(W * p["scale"]), int(H * p["scale"])), Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=p["jpeg"])
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
