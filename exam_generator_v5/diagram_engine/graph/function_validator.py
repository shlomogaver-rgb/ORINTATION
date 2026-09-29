"""Independent symbolic function validator (SymPy). It never edits the question: a claim that the algebra contradicts
becomes MATHEMATICAL_CONFLICT (the reconstruction is wrong) or SOURCE_CONFLICT (the source itself / its reading)."""
from __future__ import annotations

import re

import sympy

from .. import safe_math as sm
from ..text_utils import normalize_math_text

TOL = 1e-6


def _num(expr, x: float) -> float | None:
    try:
        v = complex(sm.numeric(expr).subs(sm.X, x).evalf())
        return v.real if abs(v.imag) < 1e-9 else None
    except Exception:
        return None


def classify_critical(expr, x: float) -> str | None:
    """'max' / 'min' / None (not a critical point) by f'(x)=0 and the sign change of f'."""
    d = sympy.diff(expr, sm.X)
    d0 = _num(d, x)
    if d0 is None or abs(d0) > 1e-6 * max(1.0, abs(x)):
        return None
    h = 1e-3 * max(1.0, abs(x))
    left, right = _num(d, x - h), _num(d, x + h)
    if left is None or right is None:
        return None
    if left > 0 > right:
        return "max"
    if left < 0 < right:
        return "min"
    return "stationary"


def check_points(expr, points) -> list[str]:
    out = []
    for p in points:
        if p.kind == "marked":
            continue
        y = _num(expr, p.x)
        name = p.name or f"({p.x:g},{p.y:g})"
        if y is None or abs(y - p.y) > TOL * max(1.0, abs(p.y)):
            out.append(f"MATHEMATICAL_CONFLICT: הנקודה {name} אינה על גרף הפונקצייה (f({p.x:g}) = {y}).")
            continue
        if p.kind == "root" and abs(y) > TOL:
            out.append(f"MATHEMATICAL_CONFLICT: {name} סומנה כנקודת חיתוך עם ציר x אך f({p.x:g}) = {y:g}.")
        elif p.kind == "y_intercept" and abs(p.x) > TOL:
            out.append(f"MATHEMATICAL_CONFLICT: {name} סומנה כחיתוך עם ציר y אך x ≠ 0.")
        elif p.kind == "inflection":
            lo_, hi_ = p.x - 1.0, p.x + 1.0
            if not any(abs(x - p.x) < 1e-6 for x in concavity(expr, lo_, hi_)["inflections"]):
                out.append(f"MATHEMATICAL_CONFLICT: {name} סומנה כנקודת פיתול אך הקעירות אינה מתחלפת שם.")
        elif p.kind in ("max", "min"):
            got = classify_critical(expr, p.x)
            if got != p.kind:
                he = {"max": "מקסימום", "min": "מינימום"}[p.kind]
                out.append(f"MATHEMATICAL_CONFLICT: {name} סומנה כנקודת {he} אך לפי הנגזרת היא "
                           f"{ {'max': 'מקסימום', 'min': 'מינימום', 'stationary': 'נקודה סטציונרית ללא קיצון'}.get(got, 'אינה נקודת קיצון') }.")
    return out


CLAIM = re.compile(r"(?:נקודת\s+)?(מקסימום|מינימום)(?:\s+מקומי)?\s*(?:בנקודה|ב)\s*-?\s*(?:x\s*=\s*(-?\d+(?:\.\d+)?)|\(\s*(-?\d+(?:\.\d+)?)\s*,)")


def text_claims(text: str, expr) -> list[str]:
    """Claims written in the question ('לפונקצייה נקודת מקסימום ב-x=3') checked algebraically -> SOURCE_CONFLICT."""
    out = []
    s = normalize_math_text(text or "").replace("−", "-")
    for m in CLAIM.finditer(s):
        kind = "max" if m.group(1) == "מקסימום" else "min"
        x = float(m.group(2) or m.group(3))
        got = classify_critical(expr, x)
        if got != kind:
            out.append(f"SOURCE_CONFLICT: בנוסח השאלה {m.group(0).strip()}, אך לפי חישוב הנגזרת של הפונקצייה אין {m.group(1)} ב-x={x:g}. "
                       f"השאלה לא שונתה — יש לבדוק את נוסח המקור או את זיהוי הנוסחה.")
    return out


def exact_critical_points(expr) -> list:
    """Exact critical points for polynomial/rational functions (reported to the teacher)."""
    try:
        num = sympy.numer(sympy.together(sympy.diff(expr, sm.X)))
        return sorted(sympy.real_roots(sympy.Poly(num, sm.X)))
    except Exception:
        return []


def concavity(expr, lo: float, hi: float, poles: list[float] | None = None) -> dict:
    """Concavity intervals and TRUE inflection points on [lo, hi]. f''=0 alone is not an inflection: the sign of f''
    must change there, the point must be in the domain and not a pole/discontinuity (e.g. x^4 at 0 or 1/x at 0)."""
    import numpy as np

    d2 = sympy.diff(expr, sm.X, 2)
    f2 = sm.to_numpy(d2)
    f0 = sm.to_numpy(expr)
    poles = sorted(p for p in (poles or []) if lo < p < hi)
    cands = set()
    try:
        num = sympy.numer(sympy.together(d2))
        for r in sympy.real_roots(sympy.Poly(num, sm.X)):
            v = float(r)
            if lo < v < hi:
                cands.add(round(v, 12))
    except Exception:
        xs = np.linspace(lo, hi, 4001)
        ys = f2(xs)
        s_ = np.sign(ys)
        for i in np.where((s_[:-1] * s_[1:] < 0) & np.isfinite(ys[:-1]) & np.isfinite(ys[1:]))[0]:
            cands.add(round(float((xs[i] + xs[i + 1]) / 2), 9))
    h = 1e-4 * max(1.0, hi - lo)
    infl = []
    for x0 in sorted(cands):
        if any(abs(x0 - p) < 10 * h for p in poles):
            continue
        yl, yr, yv = f2(np.array([x0 - h]))[0], f2(np.array([x0 + h]))[0], f0(np.array([x0]))[0]
        if np.isfinite(yl) and np.isfinite(yr) and np.isfinite(yv) and yl * yr < 0:
            infl.append(x0)
    cuts = sorted({lo, hi, *infl, *poles, *cands})
    intervals = []
    for a, b in zip(cuts, cuts[1:]):
        m = (a + b) / 2
        v = f2(np.array([m]))[0]
        if not np.isfinite(v):
            continue
        kind = "up" if v > 0 else ("down" if v < 0 else "linear")
        if intervals and intervals[-1][2] == kind and abs(intervals[-1][1] - a) < 1e-12 and a not in poles:
            intervals[-1] = (intervals[-1][0], b, kind)
        else:
            intervals.append((a, b, kind))
    return {"inflections": infl, "concavity": intervals}
