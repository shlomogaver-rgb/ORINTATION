"""Graph-specific source-vs-candidate checks (critical mismatches are Hebrew strings)."""
from __future__ import annotations

from ..schemas import DiagramSpec
from .qualitative_parser import topology_summary


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def check_formula(spec: DiagramSpec, manifest: dict, feats: dict | None, check) -> None:
    o, g = spec.observed, spec.graph
    tol = max(0.15, 0.3 * g.axes.x_step)
    if o.num_curves is not None:
        check(len(g.curves) == o.num_curves, f"במקור {o.num_curves} עקומות, בשחזור {len(g.curves)}.")
    feats = feats or {}
    if o.x_intercepts is not None and feats:
        roots = feats.get("roots", [])
        ok = len(roots) == len(o.x_intercepts) and all(_close(a, b, tol) for a, b in zip(sorted(roots), sorted(o.x_intercepts)))
        check(ok, f"נקודות החיתוך עם ציר x השתנו (מקור: {o.x_intercepts}; מחושב: {[round(v, 3) for v in roots]}).")
    if o.y_intercept is not None and feats:
        yi = feats.get("y_intercept")
        check(yi is not None and _close(yi, o.y_intercept, max(0.15, 0.3 * g.axes.y_step)),
              f"נקודת החיתוך עם ציר y השתנתה (מקור: {o.y_intercept}; מחושב: {yi}).")
    if o.vertical_asymptotes is not None and feats:
        va = sorted(feats.get("vertical_asymptotes", []) + [s.value for s in g.asymptotes if s.kind == "vertical"])
        va = sorted({round(v, 6) for v in va})
        ok = len(va) == len(o.vertical_asymptotes) and all(_close(a, b, tol) for a, b in zip(va, sorted(o.vertical_asymptotes)))
        check(ok, f"האסימפטוטות האנכיות השתנו (מקור: {o.vertical_asymptotes}; מחושב: {va}).")
    if o.num_branches is not None and feats:
        check(feats.get("branches") == o.num_branches, f"מספר ענפי הגרף השתנה (מקור: {o.num_branches}; מחושב: {feats.get('branches')}).")
    drawn = [(e[1], e[2], e[3]) for e in manifest.get("endpoints", [])] + [(p[1], p[2], p[3]) for p in manifest.get("points", [])]
    for kind, obs in (("open", o.open_endpoints), ("closed", o.closed_endpoints)):
        for pt in obs or []:
            ok = any(_close(x, pt[0], tol) and _close(y, pt[1], tol) and k == kind for x, y, k in drawn)
            check(ok, f"נקודה {'פתוחה' if kind == 'open' else 'סגורה'} ב-({pt[0]:g},{pt[1]:g}) שבמקור אינה מופיעה כך בשחזור.")


def check_topology(topo, observed, check) -> None:
    s = topology_summary(topo)
    o = observed
    if o.num_branches is not None:
        check(s["branches"] == o.num_branches, f"מספר הענפים השתנה (מקור {o.num_branches}, שחזור {s['branches']}).")
    if o.num_maxima is not None:
        check(s["maxima"] == o.num_maxima, f"מספר נקודות המקסימום השתנה (מקור {o.num_maxima}, שחזור {s['maxima']}).")
    if o.num_minima is not None:
        check(s["minima"] == o.num_minima, f"מספר נקודות המינימום השתנה (מקור {o.num_minima}, שחזור {s['minima']}).")
    if o.vertical_asymptotes is not None:
        check(len(s["vertical_asymptotes"]) == len(o.vertical_asymptotes), "מספר האסימפטוטות האנכיות השתנה.")
    if o.horizontal_asymptotes is not None:
        check(len(s["horizontal_asymptotes"]) == len(o.horizontal_asymptotes), "מספר האסימפטוטות האופקיות השתנה.")
    if o.x_intercepts is not None:
        check(len(s["x_intercepts"]) == len(o.x_intercepts), "מספר נקודות החיתוך עם ציר x השתנה.")
    if o.point_labels is not None:
        check(sorted(o.point_labels) == s["labels"], f"תוויות הנקודות שונות מהמקור ({', '.join(s['labels'])}).")


def match_options(target: dict, options: dict[str, dict]) -> list[str]:
    """Deterministic option matching: labels of options whose topology summary equals the target facts (subset keys)."""
    out = []
    for label, summ in options.items():
        if all(summ.get(k) == v for k, v in target.items()):
            out.append(label)
    return out


def option_transformations(a, b) -> list[str]:
    """Relations between two INDEPENDENTLY analysed options, reported only with evidence (all landmarks + asymptotes agree):
    SIGN_INVERSION (y -> -y), REFLECTION_Y (x -> -x), SHIFT_X(d), SHIFT_Y(d)."""
    import numpy as np

    def pts(t):
        return sorted((l.x, l.y, l.kind) for l in t.landmarks)

    def asy(t):
        return sorted((s.kind, s.value) for s in t.asymptotes)

    pa, pb = pts(a), pts(b)
    if len(pa) != len(pb) or not pa:
        return []
    out = []
    flip = {"max": "min", "min": "max"}
    if all(np.isclose(x1, x2) and np.isclose(y1, -y2) and flip.get(k1, k1) == k2 for (x1, y1, k1), (x2, y2, k2) in zip(pa, sorted(pb))) \
            and asy(b) == sorted((k, -v if k == "horizontal" else v) for k, v in asy(a)):
        out.append("SIGN_INVERSION")
    mir = sorted((-x, y, k) for x, y, k in pa)
    if all(np.isclose(x1, x2) and np.isclose(y1, y2) and k1 == k2 for (x1, y1, k1), (x2, y2, k2) in zip(mir, pb)) \
            and asy(b) == sorted((k, -v if k == "vertical" else v) for k, v in asy(a)):
        out.append("REFLECTION_Y")
    dx = {round(x2 - x1, 9) for (x1, _, _), (x2, _, _) in zip(pa, pb)}
    dy = {round(y2 - y1, 9) for (_, y1, _), (_, y2, _) in zip(pa, pb)}
    kinds_same = all(k1 == k2 for (_, _, k1), (_, _, k2) in zip(pa, pb))
    if kinds_same and len(dx) == 1 and len(dy) == 1:
        (ddx,), (ddy,) = dx, dy
        if abs(ddx) > 1e-9 and abs(ddy) < 1e-9:
            out.append(f"SHIFT_X({ddx:g})")
        if abs(ddy) > 1e-9 and abs(ddx) < 1e-9:
            out.append(f"SHIFT_Y({ddy:g})")
    return out
