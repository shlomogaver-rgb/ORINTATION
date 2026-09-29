"""Pixel-level graph evidence (verification only, never mathematical truth): axes, curve branches (connected curve ink
after removing axes, text and dashed guides) and x-axis crossing/touch points."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

GRAPH_CV_VERSION = "graphcv/1.0"


def analyse(png: bytes) -> dict:
    try:
        import cv2
    except Exception:
        return {"ok": False, "reason": "OpenCV לא זמין"}
    with Image.open(io.BytesIO(png)) as im:
        g = np.asarray(ImageOps.grayscale(im.convert("RGB")))
    H, W = g.shape
    scale = min(H, W)
    dark = (g < 120).astype(np.uint8)
    rows = dark.sum(axis=1)
    cols = dark.sum(axis=0)
    ax_row, ax_col = int(np.argmax(rows)), int(np.argmax(cols))
    if rows[ax_row] < 0.5 * W or cols[ax_col] < 0.4 * H:
        return {"ok": False, "reason": "לא זוהו צירים"}
    band = max(2, int(0.006 * scale))
    curve = dark.copy()
    # remove the axes as THIN lines only: where curve ink touches the axis band (just above/below it) the band is kept,
    # so a curve running along / through an axis stays one connected branch
    r0, r1 = max(0, ax_row - band), min(H, ax_row + band + 1)
    flank_r = dark[max(0, r0 - 3):r0, :].any(axis=0) | dark[r1:min(H, r1 + 3), :].any(axis=0)
    curve[r0:r1, ~flank_r] = 0
    c0, c1 = max(0, ax_col - band), min(W, ax_col + band + 1)
    flank_c = dark[:, max(0, c0 - 3):c0].any(axis=1) | dark[:, c1:min(W, c1 + 3)].any(axis=1)
    curve[~flank_c, c0:c1] = 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(curve, connectivity=8)
    comps = [i for i in range(1, n) if max(stats[i][2], stats[i][3]) >= 0.12 * scale and stats[i][4] >= 0.1 * scale]
    # re-join pieces of one branch split only by the removed axis band
    parent = {i: i for i in comps}

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i in comps:
        for j in comps:
            if i < j:
                a, b = lab == i, lab == j
                ya, xa = np.nonzero(a)
                yb, xb = np.nonzero(b)
                near_row = (np.abs(ya - ax_row) <= band + 3).any() and (np.abs(yb - ax_row) <= band + 3).any()
                near_col = (np.abs(xa - ax_col) <= band + 3).any() and (np.abs(xb - ax_col) <= band + 3).any()
                gap = max(3, int(0.06 * scale))       # a crossing at a shallow angle leaves a longer gap in the axis band
                if near_row and np.min(np.abs(xa[np.abs(ya - ax_row) <= band + 3][:, None] - xb[np.abs(yb - ax_row) <= band + 3][None, :])) <= gap:
                    parent[find(j)] = find(i)
                elif near_col and np.min(np.abs(ya[np.abs(xa - ax_col) <= band + 3][:, None] - yb[np.abs(xb - ax_col) <= band + 3][None, :])) <= gap:
                    parent[find(j)] = find(i)
    # generic re-join: two curve pieces whose pixels come within a small gap are ONE branch (axis crossings, dashes)
    gap2 = (0.035 * scale) ** 2
    pts = {i: np.column_stack(np.nonzero(lab == i))[::7] for i in comps}
    for i in comps:
        for j in comps:
            if i < j and find(i) != find(j):
                a, b = pts[i], pts[j]
                d2 = ((a[:, None, :] - b[None, :, :]) ** 2).sum(-1).min() if len(a) and len(b) else 1e18
                if d2 <= gap2:
                    parent[find(j)] = find(i)
    branches = len({find(i) for i in comps})
    # x-axis crossings / touches: curve ink right next to the axis band
    near = np.zeros(W, bool)
    for i in comps:
        ys, xs = np.nonzero(lab == i)
        near[xs[np.abs(ys - ax_row) <= band + 2]] = True
    near[max(0, ax_col - 3 * band):ax_col + 3 * band + 1] = False
    xs_hit = np.nonzero(near)[0]
    crossings = 0 if not len(xs_hit) else 1 + int(np.sum(np.diff(xs_hit) > max(3, int(0.03 * scale))))   # one crossing = one cluster
    return {"ok": True, "branches": branches, "x_axis_contacts": crossings, "axes": [ax_row, ax_col]}


def compare(cv: dict, expected_branches: int | None, expected_contacts: int | None) -> list[str]:
    if not cv.get("ok"):
        return []
    out = []
    if expected_branches is not None and cv["branches"] != expected_branches:
        out.append(f"VISUAL_GRAPH_CONFLICT: בתמונה זוהו {cv['branches']} ענפים, במודל {expected_branches}.")
    if expected_contacts is not None and cv["x_axis_contacts"] != expected_contacts:
        out.append(f"VISUAL_GRAPH_CONFLICT: בתמונה {cv['x_axis_contacts']} נקודות מגע/חיתוך עם ציר x, במודל {expected_contacts}.")
    return out


def expected_from_spec(spec, features: dict | None = None) -> tuple[int | None, int | None]:
    """(branches, x-axis contacts) the MODEL predicts inside the viewport; None = not checkable (e.g. asymptote y=0)."""
    if spec.graph is not None and len(spec.graph.curves) == 1 and features:
        f = next(iter(features.values()))
        a = spec.graph.axes
        roots = [r for r in f.get("roots", []) if a.x_min < r < a.x_max]
        h0 = any(abs(v) < 1e-9 for v in f.get("horizontal_asymptotes", []) + symbolic_horizontal_asymptotes(spec))
        return f.get("branches"), (None if h0 else len(roots))
    t = spec.graph_topology
    if t is not None:
        h0 = any(x.kind == "horizontal" and abs(x.value) < 1e-9 for x in t.asymptotes)
        n = sum(1 for l in t.landmarks if l.kind == "x_intercept")
        return len(t.branches), (None if h0 else n)
    return None, None


def symbolic_horizontal_asymptotes(spec) -> list[float]:
    """lim x->+-inf by SymPy (e.g. exp(x) -> 0 as x -> -inf): an approach to the axis is not a crossing."""
    import sympy
    from .. import safe_math as sm
    out = []
    try:
        e = sm.numeric(sm.parse_expression(spec.graph.curves[0].expression))
        for side in (sympy.oo, -sympy.oo):
            v = sympy.limit(e, sm.X, side)
            if v.is_finite:
                out.append(float(v))
    except Exception:
        pass
    return out
