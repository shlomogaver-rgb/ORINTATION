"""Read a cube structure (number diagram) FROM THE DRAWING by analysis-by-synthesis, and prove it.

1. calibrate the parallel projection from the drawing itself (plate corners, top-face size, front-face height);
2. render a candidate structure in that SAME projection with occlusion (painter's order) as a face-label image;
3. search the heights that reproduce the source drawing face-by-face (top / front / right / plate);
4. uniqueness: a cell whose height can change without changing the drawing (a hidden cube) makes the structure
   NOT determined by the drawing -> teacher review. Only a unique, matching structure is accepted automatically."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

LINE, BG, TOP, FRONT, RIGHT, PLATE = -1, 0, 1, 2, 3, 4
VERSION = "voxelfit/1.0"


def classify(png: bytes) -> np.ndarray:
    """Face label per pixel from the gray level (top = white inside the silhouette, front / right = two grays, plate =
    very light gray, lines = dark). Levels are found from the image histogram, not fixed."""
    import cv2
    g = np.asarray(Image.open(io.BytesIO(png)).convert("L")).astype(int)
    ink = (g < 250).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    if n < 2:
        return np.full(g.shape, BG)
    big = 1 + int(np.argmax(st[1:, 4]))
    # INSIDE = everything the background cannot reach from the image border without crossing the drawing
    # (white top faces are enclosed by their outlines)
    wall = (lab == big).astype(np.uint8)
    reach = np.zeros((g.shape[0] + 2, g.shape[1] + 2), np.uint8)
    flood = (1 - wall).astype(np.uint8).copy()
    cv2.floodFill(flood, reach, (0, 0), 2)
    sil = ((flood != 2) | (wall > 0)).astype(np.uint8)
    vals = g[(sil > 0) & (g > 60) & (g < 250)]
    hist = np.bincount(vals, minlength=256).astype(float)
    peaks = sorted(v for v in range(61, 250) if hist[v] > 0.02 * max(1, len(vals)) and hist[v] == hist[max(0, v - 6):v + 7].max())
    out = np.full(g.shape, BG)
    out[(sil > 0) & (g >= 250)] = TOP
    if len(peaks) >= 3:
        dark, mid, light = peaks[0], peaks[-2], peaks[-1]
        cut1, cut2 = (dark + mid) / 2, (mid + light) / 2
        out[(sil > 0) & (g > 60) & (g < cut1)] = RIGHT
        out[(sil > 0) & (g >= cut1) & (g < cut2)] = FRONT
        out[(sil > 0) & (g >= cut2) & (g < 250)] = PLATE
    out[g <= 60] = LINE
    return out


def calibrate(lab: np.ndarray, n_hint: int | None = None) -> dict | None:
    """Projection from the drawing: plate corners L (left), B (bottom = front corner), R (right); cube edge lengths from
    the top faces (rhombus u x v) and the front faces (parallelogram u x w)."""
    import cv2
    sil = (lab != BG).astype(np.uint8)
    ys, xs = np.nonzero(sil)
    if len(xs) < 100:
        return None
    L = np.array([xs.min(), ys[xs == xs.min()].mean()], float)
    B = np.array([xs[ys == ys.max()].mean(), ys.max()], float)
    R = np.array([xs.max(), ys[xs == xs.max()].mean()], float)
    du, dv = (B - L) / np.linalg.norm(B - L), (R - B) / np.linalg.norm(R - B)
    n1, l1, s1, _ = cv2.connectedComponentsWithStats((lab == TOP).astype(np.uint8), 4)
    tops = [s1[i] for i in range(1, n1) if s1[i][4] > 40]
    if not tops:
        return None
    area = np.median([t[4] for t in tops])
    full = [t for t in tops if t[4] >= 0.6 * area]
    wbox = np.median([t[2] for t in full])
    # a CUBE: |u| = |v|. (Width and height of a symmetric rhombus cannot separate the two - the 2x2 system is singular.)
    a = b = wbox / (du[0] + dv[0])
    tot_u, tot_v = np.linalg.norm(B - L) / a, np.linalg.norm(R - B) / b

    def split(tot):
        n = n_hint or int(np.floor(tot - 0.15))
        return n, (tot - n) / 2
    nu, mu = split(tot_u)
    nv, mv = split(tot_v)
    u, v = du * a, dv * b
    n2, l2, s2, _ = cv2.connectedComponentsWithStats((lab == FRONT).astype(np.uint8), 4)
    fr = [s2[i] for i in range(1, n2) if s2[i][4] > 40 and abs(s2[i][2] - u[0]) < 0.25 * u[0]]
    c = (np.median([f[3] for f in fr]) - u[1]) if fr else a
    G = L + mu * u + mv * v
    return {"G": G, "u": u, "v": v, "w": np.array([0.0, -float(c)]), "n": (nu, nv), "margin": (mu, mv)}


def render(heights: np.ndarray, p: dict, shape: tuple) -> np.ndarray:
    """Face-label image of a structure (heights[r][k], r = 0 FRONT row, k = 0 left) in the calibrated projection."""
    import cv2
    img = np.zeros(shape, np.int16)
    G, u, v, w = p["G"], p["u"], p["v"], p["w"]
    nu, nv = p["n"]
    mu, mv = p["margin"]
    P = lambda k, r, z: G + k * u + r * v + z * w  # noqa: E731
    plate = [P(-mu, -mv, 0), P(nu + mu, -mv, 0), P(nu + mu, nv + mv, 0), P(-mu, nv + mv, 0)]
    cv2.fillPoly(img, [np.round(plate).astype(np.int32)], PLATE)
    cubes = [(k, r, z) for r in range(heights.shape[0]) for k in range(heights.shape[1]) for z in range(int(heights[r][k]))]
    cubes.sort(key=lambda t: (-t[0] + t[1] - t[2]), reverse=True)     # far (left, back, low) first
    for k, r, z in cubes:
        for face, lab_ in ((((k, r, z), (k + 1, r, z), (k + 1, r, z + 1), (k, r, z + 1)), FRONT),
                           (((k + 1, r, z), (k + 1, r + 1, z), (k + 1, r + 1, z + 1), (k + 1, r, z + 1)), RIGHT),
                           (((k, r, z + 1), (k + 1, r, z + 1), (k + 1, r + 1, z + 1), (k, r + 1, z + 1)), TOP)):
            cv2.fillPoly(img, [np.round([P(*q) for q in face]).astype(np.int32)], lab_)
    return img


def _score(src: np.ndarray, care: np.ndarray, ren: np.ndarray) -> float:
    return float((src[care] == ren[care]).mean())


def fit(png: bytes, init: list[list[int]] | None = None, max_h: int = 6, n_hint: int | None = None) -> dict:
    """{"ok", "heights" (rows FRONT->back), "score", "ambiguous_cells", "params"}; ok only for a unique, matching fit."""
    import cv2
    lab = classify(png)
    ys, xs = np.nonzero(lab != BG)
    if len(xs) and (xs.min() <= 1 or ys.min() <= 1 or xs.max() >= lab.shape[1] - 2 or ys.max() >= lab.shape[0] - 2):
        return {"ok": False, "reason": "the drawing is cut by the crop (plate corners missing)", "version": VERSION,
                "heights": [], "score": 0.0, "ambiguous_cells": []}
    p = calibrate(lab, n_hint)
    if p is None:
        return {"ok": False, "reason": "no calibration", "version": VERSION, "heights": [], "score": 0.0, "ambiguous_cells": []}
    # compare at half resolution, ignoring pixels near drawn lines (antialiasing / line width)
    lines = cv2.dilate((lab == LINE).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    care_full = ~lines
    sub = (slice(None, None, 2), slice(None, None, 2))
    src, care = lab[sub], care_full[sub]
    ph = dict(p, G=p["G"] / 2, u=p["u"] / 2, v=p["v"] / 2, w=p["w"] / 2)
    nu, nv = p["n"]
    H = np.zeros((nv, nu), int)
    if init is not None:
        a = np.array(init, int)
        H[:min(nv, a.shape[0]), :min(nu, a.shape[1])] = a[:nv, :nu]
    sc = lambda Hc, pp=None: _score(src, care, render(Hc, pp or ph, src.shape))  # noqa: E731
    best = sc(H)

    def ascend(H, best, pp):
        for _ in range(6):
            improved = False
            for r in range(nv):
                for k in range(nu):
                    cur = H[r, k]
                    for h in range(max_h + 1):
                        if h == cur:
                            continue
                        H[r, k] = h
                        s = sc(H, pp)
                        if s > best + 1e-9:
                            best, cur, improved = s, h, True
                    H[r, k] = cur
            if not improved:
                break
        return H, best
    H, best = ascend(H, best, ph)
    # refine the calibration (origin / vertical scale) around the first fit, then refit
    cand = []
    for dx in (-0.12, -0.06, 0, 0.06, 0.12):
        for dy in (-0.12, -0.06, 0, 0.06, 0.12):
            for cs in (0.94, 1.0, 1.06):
                pp = dict(ph, G=ph["G"] + dx * ph["u"] + dy * ph["v"], w=ph["w"] * cs)
                cand.append((sc(H, pp), dx, dy, cs, pp))
    s0, dx, dy, cs, pp = max(cand, key=lambda t: t[0])
    H, best = ascend(H, s0, pp)
    # uniqueness: any single-cell change that leaves the drawing (almost) unchanged = not determined by the drawing
    tol = 0.0008
    amb = []
    for r in range(nv):
        for k in range(nu):
            cur = H[r, k]
            for h in range(max_h + 1):
                if h == cur:
                    continue
                H[r, k] = h
                if sc(H, pp) >= best - tol:
                    amb.append({"row_from_front": r, "col_from_left": k, "fitted": int(cur), "alternative": h})
            H[r, k] = cur
    ok = best >= 0.93 and not amb
    full = dict(p, G=pp["G"] * 2, u=pp["u"] * 2, v=pp["v"] * 2, w=pp["w"] * 2)
    return {"ok": ok, "heights": H.tolist(), "score": round(best, 4), "ambiguous_cells": amb, "version": VERSION,
            "params": {"n": list(p["n"]), "margin": [round(x, 3) for x in p["margin"]], "u": np.round(full["u"], 2).tolist(),
                       "v": np.round(full["v"], 2).tolist(), "w": np.round(full["w"], 2).tolist(), "G": np.round(full["G"], 1).tolist()},
            "reason": "" if ok else ("drawing does not determine the structure" if amb else f"low agreement {best:.3f}")}
