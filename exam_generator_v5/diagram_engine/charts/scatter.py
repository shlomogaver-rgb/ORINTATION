"""Deterministic scatter-plot reading: grid/axis line detection -> pixel->value mapping -> dot centres.
No OpenCV needed (numpy only). If the mapping is not stable the result says so and the engine keeps the original."""
from __future__ import annotations

import io
from collections import deque

import numpy as np
from PIL import Image, ImageOps

from ..schemas import GraphAxes


def _lines(mask: np.ndarray, axis: int, min_frac: float) -> list[int]:
    """Indices of rows (axis=1) / columns (axis=0) that contain a long dark run."""
    n = mask.shape[axis]
    need = int(min_frac * n)
    idx = []
    lines = mask if axis == 1 else mask.T
    for i, row in enumerate(lines):
        best = cur = 0
        for v in row:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        if best >= need:
            idx.append(i)
    groups, out = [], []
    for i in idx:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    for g in groups:
        out.append(int(round(sum(g) / len(g))))
    return out


def _components(mask: np.ndarray) -> list[tuple[float, float, int, int, int]]:
    seen = np.zeros_like(mask, bool)
    H, W = mask.shape
    out = []
    for y in range(H):
        for x in range(W):
            if mask[y, x] and not seen[y, x]:
                q = deque([(y, x)])
                seen[y, x] = True
                pts = []
                while q:
                    cy, cx = q.popleft()
                    pts.append((cy, cx))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
                ys, xs = zip(*pts)
                out.append((float(np.mean(xs)), float(np.mean(ys)), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(pts)))
    return out


def _runs(line: np.ndarray) -> int:
    best = cur = 0
    for v in line:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def _tick_mapping(g: np.ndarray, axes: GraphAxes, nx: int, ny: int):
    """Axes = the longest dark vertical/horizontal lines; ticks = short dark marks crossing them at a regular spacing.
    Returns synthetic 'grid' positions (x_min..x_max columns, y_max..y_min rows) or None when not stable."""
    dark = g < 110
    H, W = dark.shape
    col_len = [_runs(dark[:, x]) for x in range(W)]
    row_len = [_runs(dark[y, :]) for y in range(H)]
    ax_x = int(np.argmax(col_len))
    ax_y = int(np.argmax(row_len))
    if col_len[ax_x] < 0.3 * H or row_len[ax_y] < 0.3 * W:
        return None

    def marks(profile_idx, along, across, length):
        pos = []
        for i in along:
            seg = profile_idx(i)
            if seg.sum() >= 3:
                pos.append(i)
        groups = []
        for i in pos:
            if groups and i - groups[-1][-1] <= 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        return [int(round(sum(gr) / len(gr))) for gr in groups]

    xs = marks(lambda x: dark[min(H - 1, ax_y + 2):min(H, ax_y + 9), x], range(ax_x + 3, W), None, None)
    ys = marks(lambda y: dark[y, max(0, ax_x - 8):max(0, ax_x - 1)], range(0, ax_y - 2), None, None)
    for arr, _n in ((xs, nx), (ys, ny)):
        if len(arr) < 2:
            return None
        d = np.diff(arr)
        if np.max(np.abs(d - np.median(d))) > 0.06 * np.median(d) + 1.5:
            return None
    sx, sy = float(np.median(np.diff(xs))), float(np.median(np.diff(ys)))
    if abs((xs[0] - ax_x) - sx) > 0.1 * sx + 2 or abs((ax_y - ys[-1]) - sy) > 0.1 * sy + 2:
        return None
    if not (nx - 1 <= len(xs) <= nx and ny - 1 <= len(ys) <= ny):
        return None
    cols = [ax_x] + xs
    rows = ys + [ax_y]
    return cols, rows


def detect(png: bytes, axes: GraphAxes) -> dict:
    """Returns {"stable": bool, "points": [[x, y], ...], "reason": str, "grid": {...}}."""
    with Image.open(io.BytesIO(png)) as im:
        g = np.asarray(ImageOps.grayscale(im.convert("RGB")), dtype=np.uint8)
    dark = g < 110                 # dots / axes
    ink = g < 215                  # includes light-gray grid lines
    cols = _lines(ink, 0, 0.45)    # vertical lines (y-axis + vertical grid)
    rows = _lines(ink, 1, 0.45)    # horizontal lines (x-axis + horizontal grid)
    nx = int(round((axes.x_max - axes.x_min) / axes.x_step))
    ny = int(round((axes.y_max - axes.y_min) / axes.y_step))
    res = {"stable": False, "points": [], "reason": "", "grid": {"cols": cols, "rows": rows}, "method": "grid"}
    if len(cols) < 2 or len(rows) < 2 or not (nx - 1 <= len(cols) - 1 <= nx and ny - 1 <= len(rows) - 1 <= ny):
        ticks = _tick_mapping(g, axes, nx, ny)       # V2 fallback: axes + tick marks, no grid needed
        if ticks is None:
            res["reason"] = "לא זוהו רשת או שנתות יציבות — המיפוי אינו יציב"
            return res
        cols, rows = ticks
        res["method"] = "ticks"
        res["grid"] = {"cols": cols, "rows": rows}
    dxs, dys = np.diff(cols), np.diff(rows)
    sx, sy = float(np.median(dxs)), float(np.median(dys))
    if np.max(np.abs(dxs - sx)) > 0.06 * sx + 1.5 or np.max(np.abs(dys - sy)) > 0.06 * sy + 1.5:
        res["reason"] = "מרווחי הרשת אינם אחידים — המיפוי אינו יציב"
        return res
    x0_px, y0_px = cols[0], rows[-1]
    px_x, px_y = sx / axes.x_step, sy / axes.y_step
    plot = dark.copy()   # grid lines are lighter than the dots; only the (black) axes are removed
    for c in cols:
        if dark[:, c].mean() > 0.3:
            plot[:, max(0, c - 1):c + 2] = False
    for r in rows:
        if dark[r, :].mean() > 0.3:
            plot[max(0, r - 1):r + 2, :] = False
    x_end = int(cols[0] + nx * sx) + 3
    plot[:, :cols[0] + 2] = False
    plot[:, x_end:] = False
    plot[rows[-1] - 1:, :] = False
    plot[:max(0, int(rows[-1] - ny * sy) - 3), :] = False
    comps = _components(plot)
    r_expect = max(2.0, 0.08 * min(sx, sy))
    pts = []
    for cx, cy, w, h, area in comps:
        if w < 2 * r_expect * 0.6 or h < 2 * r_expect * 0.6 or w > 6 * r_expect or h > 6 * r_expect:
            continue
        if not 0.5 < w / h < 2.0 or area < 0.35 * w * h:
            continue
        pts.append([round(axes.x_min + (cx - x0_px) / px_x, 3), round(axes.y_min + (y0_px - cy) / px_y, 3)])
    res.update({"stable": True, "points": sorted(pts)})
    return res


def match(spec_points: list[list[float]], detected: list[list[float]], axes: GraphAxes) -> list[str]:
    """Critical mismatches between the spec points and the deterministically detected dots."""
    tol_x, tol_y = 0.2 * axes.x_step, 0.2 * axes.y_step
    errs = []
    left = list(detected)
    for p in spec_points:
        hit = next((d for d in left if abs(d[0] - p[0]) <= tol_x and abs(d[1] - p[1]) <= tol_y), None)
        if hit is None:
            errs.append(f"הנקודה ({p[0]:g},{p[1]:g}) לא נמצאה במקור.")
        else:
            left.remove(hit)
    for d in left:
        errs.append(f"במקור יש נקודה ב-({d[0]:g},{d[1]:g}) שחסרה בשחזור.")
    return errs
