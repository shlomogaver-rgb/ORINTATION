"""GRAPH SOURCE FIDELITY: the reconstruction must correspond to the graph in the SOURCE, not merely be plausible.
Panels (one per axes pair) are detected in the source crop and in the rendered preview, ordered the Hebrew way (rows top ->
bottom, right -> left) so option I / א is bound to its own panel; per panel a scale-free feature inventory is compared."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

FIDELITY_VERSION = "graphfid/1.0"


def _gray(png: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as im:
        return np.asarray(ImageOps.grayscale(im.convert("RGB")))


def panels(png: bytes) -> list[dict]:
    """Axis crosses -> panels [{bbox, ax_row, ax_col}] in RTL reading order."""
    import cv2
    g = _gray(png)
    H, W = g.shape
    bw = (g < 200).astype(np.uint8)            # axes are often thin light-grey lines in screenshots / scans
    hk = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(0.12 * W)), 1)))
    vk = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(0.12 * H)))))
    # a FRAME line touches the border AND spans (almost) the whole image; an axis may touch the border (axes at the edge)
    hs_all = [tuple(int(v) for v in st[:4]) for st in cv2.connectedComponentsWithStats(hk)[2][1:] if st[2] >= 0.12 * W and st[3] <= 6]
    full_h = [h_ for h_ in hs_all if h_[2] >= 0.97 * W]
    boxed_h = len([h_ for h_ in full_h if h_[1] <= 0.05 * H]) and len([h_ for h_ in full_h if h_[1] + h_[3] >= 0.95 * H])
    # a FRAME is a rectangle: full-width lines at BOTH the top and the bottom; one edge-to-edge line is an axis (tight crop)
    border = lambda x, y, w, h: bool(boxed_h) and w >= 0.97 * W and (y <= 0.05 * H or y + h >= 0.95 * H)  # noqa: E731
    hs = [h_ for h_ in hs_all if not border(*h_)]
    vs = [tuple(int(v) for v in st[:4]) for st in cv2.connectedComponentsWithStats(vk)[2][1:]
          if st[3] >= 0.12 * H and st[2] <= 6 and not border(*st[:4])]
    # an axis interrupted by a marker at the crossing (open circle, dot) is ONE line: merge collinear pieces with small gaps
    ink_len: dict = {}

    def _merge(segs, vertical):
        segs = sorted(segs, key=lambda s_: (s_[0], s_[1]) if vertical else (s_[1], s_[0]))
        merged = []
        for sg in segs:
            if merged:
                m = merged[-1]
                if vertical and abs(sg[0] - m[0]) <= 3 and sg[1] - (m[1] + m[3]) <= 0.04 * H:
                    new = (min(m[0], sg[0]), m[1], max(m[2], sg[2]), max(m[1] + m[3], sg[1] + sg[3]) - m[1])
                    ink_len[new] = ink_len.pop(m, m[3]) + sg[3]
                    merged[-1] = new
                    continue
                if not vertical and abs(sg[1] - m[1]) <= 3 and sg[0] - (m[0] + m[2]) <= 0.04 * W:
                    merged[-1] = (m[0], min(m[1], sg[1]), max(m[0] + m[2], sg[0] + sg[2]) - m[0], max(m[3], sg[3]))
                    continue
            merged.append(sg)
        return merged
    vs_all = [tuple(int(v) for v in st[:4]) for st in cv2.connectedComponentsWithStats(vk)[2][1:] if st[2] <= 6]
    # an AXIS is a SOLID line: a dashed asymptote merged from its dashes has a low ink ratio (a marker gap does not)
    vs_m = [v for v in _merge(vs_all, True) if v[3] >= 0.12 * H and ink_len.get(v, v[3]) >= 0.85 * v[3]]
    full_v = [v for v in vs_m if v[3] >= 0.97 * H]
    boxed_v = len([v for v in full_v if v[0] <= 0.05 * W]) and len([v for v in full_v if v[0] + v[2] >= 0.95 * W])
    vs = [v for v in vs_m if not (boxed_v and v[3] >= 0.97 * H and (v[0] <= 0.05 * W or v[0] + v[2] >= 0.95 * W))]
    out = []
    for hx, hy, hw, hh in hs:
        # an AXIS crosses the other axis: it extends clearly above AND at least a little below it (a steep curve that
        # only touches the x-axis and rises does not); a shared x-axis line is split between all y-axes crossing it
        corner = 6

        def is_axis(v):
            vx, vy, vw, vh = v
            if not (hx - 3 <= vx <= hx + hw + 3 and hy - vy >= 0.3 * vh):
                return False
            below = (vy + vh) - hy >= max(2, 0.02 * vh)
            both_sides = (vx - hx) >= 0.03 * hw and (hx + hw - vx) >= 0.03 * hw
            at_end = abs(vx - hx) <= corner or abs(hx + hw - vx) <= corner
            # a full cross, or an L / T whose corner is at an END of the x-axis (a curve rising from the middle of the
            # x-axis is not an axis)
            return (below and both_sides) or (at_end and (below or abs((vy + vh) - hy) <= corner))
        axes = sorted(v for v in vs if is_axis(v))
        for j, (vx, vy, vw, vh) in enumerate(axes):
            left = hx if j == 0 else (axes[j - 1][0] + vx) // 2
            right = hx + hw if j == len(axes) - 1 else (vx + axes[j + 1][0]) // 2
            out.append({"bbox": [left, vy, right, max(vy + vh, hy + hh)], "ax_row": hy + hh // 2, "ax_col": vx + vw // 2})
    rows: list[list[dict]] = []
    for p in sorted(out, key=lambda p: p["bbox"][1]):
        if rows and abs(rows[-1][0]["bbox"][1] - p["bbox"][1]) < 0.25 * (p["bbox"][3] - p["bbox"][1]):
            rows[-1].append(p)
        else:
            rows.append([p])
    return [p for r in rows for p in sorted(r, key=lambda p: -p["bbox"][0])]          # right -> left


def features(png: bytes, panel: dict) -> dict:
    """Scale-free inventory of one panel: where the curve lives (quadrants), branches, x-axis contacts."""
    import cv2

    from . import graph_cv
    g = _gray(png)
    x0, y0, x1, y1 = panel["bbox"]
    pad = 4
    crop = g[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    b = io.BytesIO()
    Image.fromarray(crop).save(b, format="PNG")
    cv_ = graph_cv.analyse(b.getvalue())
    bw = (crop < 170).astype(np.uint8)
    ar, ac = panel["ax_row"] - max(0, y0 - pad), panel["ax_col"] - max(0, x0 - pad)
    band = 3
    bw[max(0, ar - band):ar + band + 1, :] = 0
    bw[:, max(0, ac - band):ac + band + 1] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    keep = np.zeros_like(bw)
    for i in range(1, n):
        if max(st[i][2], st[i][3]) >= 0.08 * min(crop.shape):
            keep[lab == i] = 1
    ys, xs = np.nonzero(keep)
    tot = max(1, len(xs))
    trend = float(np.corrcoef(xs, -ys)[0, 1]) if len(xs) > 30 and xs.std() > 0 and ys.std() > 0 else 0.0   # + rising, - falling
    q = {"UR": int(((xs > ac) & (ys < ar)).sum()), "UL": int(((xs < ac) & (ys < ar)).sum()),
         "LL": int(((xs < ac) & (ys > ar)).sum()), "LR": int(((xs > ac) & (ys > ar)).sum())}
    return {"quadrants": {k: round(v / tot, 3) for k, v in q.items()}, "ink": tot, "trend": round(trend, 3),
            "branches": cv_.get("branches"), "x_axis_contacts": cv_.get("x_axis_contacts"), "cv_ok": cv_.get("ok", False)}


def compare(src: dict, ren: dict) -> tuple[str, list[str]]:
    """PASS | LOW_CONFIDENCE | MISMATCH for one panel."""
    if not src["ink"] or not ren["ink"] or src["ink"] < 50 or ren["ink"] < 50:
        return "LOW_CONFIDENCE", ["אין מספיק עקומה לזיהוי"]
    reasons = []
    for k in ("UR", "UL", "LL", "LR"):
        a, b = src["quadrants"][k], ren["quadrants"][k]
        if (a >= 0.2 and b <= 0.02) or (b >= 0.2 and a <= 0.02):
            reasons.append(f"ברביע {k}: במקור {a:.0%} מהעקומה, בשחזור {b:.0%}")
    ta, tb = src.get("trend", 0.0), ren.get("trend", 0.0)
    if abs(ta) >= 0.5 and abs(tb) >= 0.5 and ta * tb < 0:
        reasons.append(f"מגמה הפוכה: במקור {'עולה' if ta > 0 else 'יורדת'}, בשחזור {'עולה' if tb > 0 else 'יורדת'}")
    if reasons:
        return "MISMATCH", reasons
    soft = []
    for k in ("UR", "UL", "LL", "LR"):
        if abs(src["quadrants"][k] - ren["quadrants"][k]) > 0.35:
            soft.append(f"ברביע {k}: {src['quadrants'][k]:.0%} מול {ren['quadrants'][k]:.0%}")
    return ("LOW_CONFIDENCE", soft) if soft else ("PASS", [])


def check(source_png: bytes, render_png: bytes, n_expected: int) -> dict:
    """Panel-by-panel comparison; option i of the reconstruction is compared ONLY with source panel i."""
    sp, rp = panels(source_png), panels(render_png)
    res = {"version": FIDELITY_VERSION, "source_panels": len(sp), "render_panels": len(rp), "per_option": []}
    if len(sp) != n_expected or len(rp) != n_expected:
        res["decision"] = "LOW_CONFIDENCE"
        res["reasons"] = [f"זוהו {len(sp)} גרפים במקור ו-{len(rp)} בשחזור (צפויים {n_expected})"]
        return res
    worst = "PASS"
    for i, (a, b) in enumerate(zip(sp, rp)):
        fa, fb = features(source_png, a), features(render_png, b)
        d, why = compare(fa, fb)
        res["per_option"].append({"index": i, "decision": d, "reasons": why, "source": fa["quadrants"], "render": fb["quadrants"]})
        worst = {"PASS": 0, "LOW_CONFIDENCE": 1, "MISMATCH": 2}
        worst = max((res.get("decision_", "PASS"), d), key=lambda x: {"PASS": 0, "LOW_CONFIDENCE": 1, "MISMATCH": 2}[x])
        res["decision_"] = worst
    res["decision"] = res.pop("decision_", "PASS")
    return res
