"""Qualitative graphs: topology only. No equation is ever created. The drawn curve is a monotone cubic
(Fritsch-Carlson) through the landmarks, so it can NOT introduce extrema that are not landmarks."""
from __future__ import annotations

import numpy as np

from ..schemas import Branch, GraphTopologySpec


def monotone_cubic(xn: np.ndarray, yn: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Fritsch-Carlson monotone cubic Hermite interpolation: monotone between nodes, extrema only at nodes."""
    h = np.diff(xn)
    d = np.diff(yn) / h
    m = np.zeros_like(yn)
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, len(xn) - 1):
        if d[k - 1] * d[k] <= 0:
            m[k] = 0.0
        else:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    for k in range(len(d)):
        if d[k] == 0:
            m[k] = m[k + 1] = 0.0
        else:  # limit slopes (guarantees monotonicity)
            a, b = m[k] / d[k], m[k + 1] / d[k]
            if a < 0:
                m[k] = 0.0
            if b < 0:
                m[k + 1] = 0.0
            r = a * a + b * b
            if r > 9:
                t = 3 / np.sqrt(r)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    idx = np.clip(np.searchsorted(xn, xs, side="right") - 1, 0, len(h) - 1)
    t = (xs - xn[idx]) / h[idx]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return h00 * yn[idx] + h10 * h[idx] * m[idx] + h01 * yn[idx + 1] + h11 * h[idx] * m[idx + 1]


def branch_nodes(topo: GraphTopologySpec, br: Branch) -> tuple[np.ndarray, np.ndarray]:
    """Landmarks of the branch + deterministic end extensions (toward asymptote / infinity / stop)."""
    a = topo.axes
    lms = sorted((topo.landmarks[i] for i in br.landmarks), key=lambda l: l.x)
    pts = [(l.x, l.y) for l in lms]
    span_y = a.y_max - a.y_min
    x_lo = a.x_min if br.x_from is None else br.x_from
    x_hi = a.x_max if br.x_to is None else br.x_to
    out = list(pts)
    hyp = _hyperbola_tails(br, pts, lms, x_lo, x_hi)
    if hyp is not None:
        left, right = hyp
        out = left + out + right
        return np.array([p[0] for p in out], float), np.array([p[1] for p in out], float)
    for side in ("left", "right"):
        e = getattr(br, side)
        x0, y0 = (out[0] if side == "left" else out[-1])
        extremum = (lms[0] if side == "left" else lms[-1]).kind in ("max", "min")
        edge = x_lo if side == "left" else x_hi
        sgn = -1 if side == "left" else 1
        ts = np.array([0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0])
        if e.toward == "asymptote" and e.value is not None:            # horizontal asymptote y = value
            far = edge
            shape = (lambda t: float(np.exp(-4.0 * t * t))) if extremum else (lambda t: float(np.exp(-3.0 * t)))
            ext = [(x0 + t * (far - x0), e.value + (y0 - e.value) * shape(t)) for t in ts]
        elif e.toward in ("plus_inf", "minus_inf"):
            target = a.y_max + 0.05 * span_y if e.toward == "plus_inf" else a.y_min - 0.05 * span_y
            far = (e.value - sgn * 1e-3 * (a.x_max - a.x_min)) if e.value is not None else edge
            if e.value is not None:   # vertical asymptote: steepens like 1/(x-c)
                g = (lambda t: t ** 4) if extremum else (lambda t: (1 / (1 - 0.9 * t) - 1) / 9)
            else:
                g = (lambda t: t ** 2) if extremum else (lambda t: t ** 1.3)
            ext = [(x0 + t * (far - x0), y0 + (target - y0) * float(g(t))) for t in ts]
        else:
            ext = []
        if side == "left":
            out = list(reversed(ext)) + out
        else:
            out = out + ext
    xn = np.array([p[0] for p in out], float)
    yn = np.array([p[1] for p in out], float)
    return xn, yn


def _hyperbola_tails(br: Branch, pts, lms, x_lo: float, x_hi: float):
    """Branch between a vertical asymptote x=v and a horizontal asymptote y=h through ONE non-extremal landmark:
    both tails follow the same hyperbola y = h + (y0-h)*|x0-v|/|x-v| (smooth, monotone, no shoulder)."""
    if len(pts) != 1 or lms[0].kind in ("max", "min"):
        return None
    sides = {"left": br.left, "right": br.right}
    vert = [(k, e) for k, e in sides.items() if e.toward in ("plus_inf", "minus_inf") and e.value is not None]
    horz = [(k, e) for k, e in sides.items() if e.toward == "asymptote" and e.value is not None]
    if len(vert) != 1 or len(horz) != 1:
        return None
    (vside, ve), (hside, he) = vert[0], horz[0]
    x0, y0 = pts[0]
    v, h = ve.value, he.value
    if (ve.toward == "plus_inf") != (y0 > h) or (vside == "left") != (v < x0):
        return None
    d0 = abs(x0 - v)
    vs = [(v + (x0 - v) * s, h + (y0 - h) / s) for s in (0.8, 0.6, 0.45, 0.32, 0.22, 0.14, 0.08, 0.04)]
    edge = x_lo if hside == "left" else x_hi
    hs = [(x, h + (y0 - h) * d0 / abs(x - v)) for x in np.linspace(x0, edge, 9)[1:]]
    vs_sorted = sorted(vs)
    hs_sorted = sorted(hs)
    return (vs_sorted, hs_sorted) if vside == "left" else (hs_sorted, vs_sorted)


def validate(topo: GraphTopologySpec) -> list[str]:
    """Deterministic consistency: order, extremum types, intercepts on the axis, ends vs asymptotes."""
    errs: list[str] = []
    a = topo.axes
    if not (a.x_min < a.x_max and a.y_min < a.y_max):
        errs.append("טווח צירים לא חוקי בגרף האיכותני.")
        return errs
    if not topo.branches:
        errs.append("בגרף האיכותני אין ענפים.")
    used: list[int] = []
    h_asy = {s.value for s in topo.asymptotes if s.kind == "horizontal"}
    v_asy = {s.value for s in topo.asymptotes if s.kind == "vertical"}
    for bi, br in enumerate(topo.branches):
        if any(i < 0 or i >= len(topo.landmarks) for i in br.landmarks):
            errs.append(f"ענף {bi + 1}: הפניה לנקודה לא קיימת.")
            continue
        used += br.landmarks
        lms = [topo.landmarks[i] for i in br.landmarks]
        xs = [l.x for l in lms]
        if any(x2 <= x1 for x1, x2 in zip(xs, xs[1:])):
            errs.append(f"ענף {bi + 1}: הנקודות אינן מסודרות משמאל לימין.")
            continue
        for e, name in ((br.left, "שמאל"), (br.right, "ימין")):
            if e.toward == "asymptote" and (e.value is None or (e.value not in h_asy and e.value != 0)):   # y=0 is the x-axis
                errs.append(f"ענף {bi + 1}: התנהגות ב{name} מתייחסת לאסימפטוטה אופקית שאינה מוגדרת.")
            if e.toward in ("plus_inf", "minus_inf") and e.value is not None and e.value not in v_asy:
                errs.append(f"ענף {bi + 1}: התנהגות ב{name} מתייחסת לאסימפטוטה אנכית שאינה מוגדרת.")
        if errs:
            continue
        xn, yn = branch_nodes(topo, br)
        if any(x2 <= x1 for x1, x2 in zip(xn, xn[1:])):
            errs.append(f"ענף {bi + 1}: התנהגות הקצוות אינה עקבית עם מיקום הנקודות.")
            continue
        node_idx = {round(topo.landmarks[i].x, 9): i for i in br.landmarks}
        for k in range(1, len(xn) - 1):
            turn = (yn[k] - yn[k - 1]) * (yn[k + 1] - yn[k])
            lm = topo.landmarks[node_idx[round(xn[k], 9)]] if round(xn[k], 9) in node_idx else None
            if turn < 0 and (lm is None or lm.kind not in ("max", "min")):
                errs.append(f"שינוי כיוון בנקודה ({xn[k]:g},{yn[k]:g}) שאינה מסומנת כקיצון — אסור להמציא קיצון.")
            if lm is not None and lm.kind == "max" and not (yn[k] > yn[k - 1] and yn[k] > yn[k + 1]):
                errs.append(f"הנקודה {lm.label or k} מסומנת כמקסימום אך אינה גבוהה משכנותיה.")
            if lm is not None and lm.kind == "min" and not (yn[k] < yn[k - 1] and yn[k] < yn[k + 1]):
                errs.append(f"הנקודה {lm.label or k} מסומנת כמינימום אך אינה נמוכה משכנותיה.")
    # the topology itself must not force an UNMARKED root: count forced sign changes vs marked x-intercepts
    for bi, br in enumerate(topo.branches):
        if any(i < 0 or i >= len(topo.landmarks) for i in br.landmarks):
            continue
        lms = sorted((topo.landmarks[i] for i in br.landmarks), key=lambda l: l.x)
        seq = []
        for e in (br.left,):
            seq.append({"plus_inf": 1, "minus_inf": -1}.get(e.toward, (e.value if e.toward == "asymptote" and e.value else None)))
        seq += [l.y for l in lms]
        seq.append({"plus_inf": 1, "minus_inf": -1}.get(br.right.toward, (br.right.value if br.right.toward == "asymptote" and br.right.value else None)))
        signs = [(1 if v > 0 else -1) for v in seq if v is not None and abs(v) > 1e-12]
        forced = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
        marked = sum(1 for l in lms if l.kind == "x_intercept")
        if forced > marked:
            errs.append(f"SCHEMATIC_ROOT_MISMATCH: ענף {bi + 1} חייב לחצות את ציר x {forced} פעמים אך מסומנות {marked} נקודות חיתוך — "
                        "אסור להמציא שורש; יש לסמן את נקודת החיתוך או לתקן את הטופולוגיה.")
    for i, l in enumerate(topo.landmarks):
        if l.kind == "x_intercept" and abs(l.y) > 1e-9:
            errs.append(f"נקודת חיתוך עם ציר x ({l.label}) אינה על הציר.")
        if l.kind == "y_intercept" and abs(l.x) > 1e-9:
            errs.append(f"נקודת חיתוך עם ציר y ({l.label}) אינה על הציר.")
        if i not in used and l.style != "none":
            errs.append(f"הנקודה {l.label or i} אינה שייכת לאף ענף.")
    return errs


def topology_summary(topo: GraphTopologySpec) -> dict:
    """Facts comparable with the source signature."""
    kinds = [l.kind for l in topo.landmarks]
    return {"branches": len(topo.branches), "maxima": kinds.count("max"), "minima": kinds.count("min"),
            "x_intercepts": sorted(round(l.x, 6) for l in topo.landmarks if l.kind == "x_intercept"),
            "vertical_asymptotes": sorted(s.value for s in topo.asymptotes if s.kind == "vertical"),
            "horizontal_asymptotes": sorted(s.value for s in topo.asymptotes if s.kind == "horizontal"),
            "labels": sorted(l.label for l in topo.landmarks if l.label),
            "open": sum(1 for l in topo.landmarks if l.style == "open")}


def curve_points(topo: GraphTopologySpec, br: Branch, n: int = 900) -> tuple[np.ndarray, np.ndarray]:
    xn, yn = branch_nodes(topo, br)
    if len(xn) < 2:
        return xn, yn
    xs = np.linspace(xn[0], xn[-1], n)
    return xs, monotone_cubic(xn, yn, xs)


