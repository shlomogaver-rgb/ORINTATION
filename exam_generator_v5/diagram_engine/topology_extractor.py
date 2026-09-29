"""Independent topology / object inventory (OpenCV): counts marked points (dots), circles, straight segments and
junctions in an image. Run on the SOURCE and on the RENDER and compared (no pixel matching).
Without OpenCV the extractor reports itself unavailable (nothing is verified by it)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

TOPOLOGY_VERSION = "topology/1.0"


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def _gray(png: bytes, max_side: int = 900) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as im:
        g = ImageOps.grayscale(im.convert("RGB"))
        if max(g.size) > max_side:
            g.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.asarray(g)


def extract(png: bytes) -> dict:
    import cv2

    g = _gray(png)
    H, W = g.shape
    bw = (g < 140).astype(np.uint8)
    # dots: isolated small filled round blobs (reliable for scatter plots; NOT for vertex dots touching lines - see compare())
    n, _, stats, cents = cv2.connectedComponentsWithStats(bw, connectivity=8)
    dots = []
    scale = min(H, W)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if 0.006 * scale <= w <= 0.035 * scale and 0.006 * scale <= h <= 0.035 * scale and 0.7 < w / h < 1.4 and area >= 0.6 * w * h:
            dots.append([float(cents[i][0]), float(cents[i][1])])
    # circles (large)
    blur = cv2.GaussianBlur(g, (5, 5), 1.5)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=0.25 * scale, param1=120, param2=55,
                               minRadius=int(0.12 * scale), maxRadius=int(0.6 * scale))
    circ = [] if circles is None else [[float(c[0]), float(c[1]), float(c[2])] for c in circles[0]]
    # straight segments (merged)
    edges = cv2.Canny(g, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=40, minLineLength=int(0.12 * scale), maxLineGap=6)
    segs = []
    for l in ([] if lines is None else lines[:, 0]):
        x1, y1, x2, y2 = map(float, l)
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        d = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))])
        off = float(abs(d[0] * mid[1] - d[1] * mid[0]))      # 2-D cross product (np.cross on 2-D vectors is deprecated)
        if not any(abs((ang - a + 90) % 180 - 90) < 4 and abs(off - o) < 0.02 * scale for a, o in segs):
            segs.append((ang, off))
    return {"version": TOPOLOGY_VERSION, "dots": len(dots), "circles": len(circ), "segments": len(segs), "size": [W, H]}


RELIABLE = {"geometry": ("circles",), "mixed_graph_geometry": ("circles",)}
# Measured on the real Bagrut crops (see AUDIT_V5_7_1): circle counts are right for plane geometry; Hough finds spurious
# circles in boxes/solids/scatter grids; isolated-dot counts are right only for scatter (handled by charts/scatter.py);
# vertex dots touching lines and segment counts are not reliable -> reported, never gating.


def compare(source: dict, render: dict, family: str) -> list[str]:
    out = []
    for key in RELIABLE.get(family, ()):
        if source[key] != render[key]:
            he = {"circles": "מעגלים", "dots": "נקודות מסומנות"}[key]
            out.append(f"OBJECT_COUNT_CONFLICT: במקור זוהו {source[key]} {he}, בשחזור {render[key]}.")
    return out


def junctions(png: bytes) -> dict:
    """Line-structure topology: merged straight segments (Hough), their pairwise intersections / shared endpoints
    clustered into junctions with a degree, and connected components of line ink (text/dots removed)."""
    import cv2

    g = _gray(png)
    H, W = g.shape
    scale = min(H, W)
    bw = (g < 140).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    keep = np.zeros_like(bw)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if max(w, h) >= 0.08 * scale:                  # drop letters, numbers and small marks
            keep[lab == i] = 1
    comps = cv2.connectedComponents(keep, connectivity=8)[0] - 1
    edges = cv2.Canny((255 - keep * 255).astype(np.uint8), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=40, minLineLength=int(0.1 * scale), maxLineGap=8)
    segs: list[tuple[np.ndarray, np.ndarray]] = []
    for l in ([] if lines is None else lines[:, 0]):
        a, b = np.array(l[:2], float), np.array(l[2:], float)
        d = (b - a) / (np.linalg.norm(b - a) or 1)
        dup = False
        for i, (p, q) in enumerate(segs):
            e = (q - p) / (np.linalg.norm(q - p) or 1)
            if abs(d[0] * e[1] - d[1] * e[0]) < 0.03 and abs((a - p)[0] * e[1] - (a - p)[1] * e[0]) < 0.015 * scale:
                ts = sorted([0.0, float((q - p) @ e), float((a - p) @ e), float((b - p) @ e)])
                segs[i] = (p + ts[0] * e, p + ts[-1] * e)
                dup = True
                break
        if not dup:
            segs.append((a, b))
    pts = []
    tol = 0.02 * scale
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (p, q), (r, s_) = segs[i], segs[j]
            u, v = q - p, s_ - r
            den = u[0] * v[1] - u[1] * v[0]
            if abs(den) < 1e-9:
                continue
            t = ((r - p)[0] * v[1] - (r - p)[1] * v[0]) / den
            w_ = ((r - p)[0] * u[1] - (r - p)[1] * u[0]) / den
            lu, lv = np.linalg.norm(u), np.linalg.norm(v)
            if -tol / lu <= t <= 1 + tol / lu and -tol / lv <= w_ <= 1 + tol / lv:
                pts.append((p + t * u, {i, j}))
    clusters: list[list] = []
    for p, members in pts:
        c = next((c for c in clusters if np.linalg.norm(c[0] - p) < tol), None)
        if c is None:
            clusters.append([p, set(members)])
        else:
            c[1] |= members
    return {"segments": len(segs), "junctions": len(clusters), "degrees": sorted(len(c[1]) for c in clusters),
            "components": int(comps)}


def compare_structure(source: dict, render: dict, family: str) -> list[str]:
    """Junction/connectivity gate: only for families where it was MEASURED reliable (see RELIABLE_STRUCTURE)."""
    out = []
    for key in RELIABLE_STRUCTURE.get(family, ()):
        if source[key] != render[key]:
            he = {"junctions": "צמתים", "components": "רכיבים מחוברים"}[key]
            out.append(f"TOPOLOGY_MISMATCH: במקור זוהו {source[key]} {he}, בשחזור {render[key]}.")
    return out


# Measured on the real Bagrut crops (AUDIT_V5_7_2): junction/degree/component counts matched exactly for generic plans (A06)
# and straight-line geometry (A08 lines); circles break Hough into chords (A14: 10 vs 5 on a CORRECT render) and dashed
# 3D edges fragment -> report-only there. A mismatch is REVIEW-level (not a hard block) because the sample is small.
RELIABLE_STRUCTURE: dict[str, tuple] = {"generic": ("junctions", "components"), "geometry_no_circles": ("junctions", "components")}
