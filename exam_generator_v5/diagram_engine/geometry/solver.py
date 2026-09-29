"""Layout solver: moves image-derived coordinates as little as possible so every constraint holds exactly.
Fixed points (exact coordinates from the text) are not variables. Unknown circle centres are hidden variables."""
from __future__ import annotations

import itertools
from typing import Callable

import numpy as np

from ..schemas import GeometrySpec, GPoint
from .constraints import _cross, residuals, size_of

TOL = 1e-7


def add_hidden_centres(geo: GeometrySpec) -> None:
    """A circle given only by points on it gets a hidden centre (initial guess: circumcentre of 3 of its points)."""
    ids = {p.id for p in geo.points}
    P = {p.id: np.array([p.x, p.y]) for p in geo.points}
    for i, c in enumerate(geo.circles):
        if c.center:
            continue
        if not c.id:
            c.id = f"circle_{i + 1}"
        hid = f"__c_{c.id}"
        if hid in ids:
            continue
        pts = [P[k] for k in c.through_points if k in P][:3]
        if len(pts) >= 3:
            a, b, cc = pts
            d = 2 * (a[0] * (b[1] - cc[1]) + b[0] * (cc[1] - a[1]) + cc[0] * (a[1] - b[1]))
            if abs(d) > 1e-12:
                ux = ((a @ a) * (b[1] - cc[1]) + (b @ b) * (cc[1] - a[1]) + (cc @ cc) * (a[1] - b[1])) / d
                uy = ((a @ a) * (cc[0] - b[0]) + (b @ b) * (a[0] - cc[0]) + (cc @ cc) * (b[0] - a[0])) / d
                guess = (float(ux), float(uy))
            else:
                guess = tuple(np.mean(pts, axis=0))
        elif pts:
            guess = tuple(np.mean(pts, axis=0) + 0.01)
        else:
            continue
        geo.points.append(GPoint(id=hid, x=guess[0], y=guess[1], label="", hidden=True, source="computed"))


def circle_membership(geo: GeometrySpec) -> list:
    """Implicit constraints: every point listed in circle.through_points lies on that circle."""
    from ..schemas import GConstraint

    out = []
    for _i, c in enumerate(geo.circles):
        cid = c.id or c.center
        for k in c.through_points:
            if k != c.through:
                out.append(GConstraint(type="on_circle", points=[k, c.center or f"__c_{c.id}"], circle=cid, source="image"))
    return out


def derived_points(geo: GeometrySpec, cons: list) -> dict[str, tuple]:
    """Symbolic/deterministic pre-resolution: a point fully determined by a construction (midpoint, ratio on segment)
    is COMPUTED from its parents instead of being an optimisation variable (fewer degrees of freedom).
    Returns {pid: (kind, a, b, ratio)} in dependency order; cycles stay numerical."""
    fixed = {p.id for p in geo.points if p.fixed}
    cand: dict[str, tuple] = {}
    for c in cons:
        pid = c.points[0]
        if pid in fixed or pid in cand:
            continue
        if c.type == "midpoint":
            cand[pid] = ("ratio", [c.points[1], c.points[2]], 0.5)
        elif c.type == "ratio_on_segment":
            cand[pid] = ("ratio", [c.points[1], c.points[2]], float(c.value if c.value is not None else 0.5))
        elif c.type == "intersection":
            cand[pid] = ("intersection", list(c.points[1:5]), None)
        elif c.type in ("perpendicular_foot", "centroid", "circumcenter", "incenter"):
            cand[pid] = (c.type, list(c.points[1:4]), None)
    for circ in geo.circles:                      # centre of a circle given by exactly 3 points = circumcentre (exact)
        hid = f"__c_{circ.id}" if circ.id else None
        if not circ.center and hid and len(circ.through_points) >= 3 and hid not in cand:
            cand[hid] = ("circumcenter", list(circ.through_points[:3]), None)
    order: dict[str, tuple] = {}
    for _ in range(len(cand) + 1):
        for pid, d in cand.items():
            if pid not in order and pid not in d[1] and all(q not in cand or q in order for q in d[1]):
                order[pid] = d
    return order


def solve(geo: GeometrySpec, curves: dict[str, Callable] | None = None, timeout_s: float | None = None) -> dict:
    import time

    from ..constants import SOLVER_COMPLEX_CONSTRAINTS, SOLVER_TIMEOUT_COMPLEX_S, SOLVER_TIMEOUT_SIMPLE_S

    add_hidden_centres(geo)
    ids = [p.id for p in geo.points]
    cons_all = [c for c in geo.constraints + circle_membership(geo) if all(q in ids for q in c.points) and c.type != "fixed"]
    derived = derived_points(geo, cons_all)
    var = [p.id for p in geo.points if not (p.fixed or p.pinned) and p.id not in derived]
    fixed = {p.id: np.array([p.x, p.y], float) for p in geo.points if p.fixed or p.pinned}
    budget = timeout_s if timeout_s is not None else (SOLVER_TIMEOUT_COMPLEX_S if len(cons_all) > SOLVER_COMPLEX_CONSTRAINTS
                                                       else SOLVER_TIMEOUT_SIMPLE_S)
    t0 = time.monotonic()
    x0 = np.array([v for pid in var for v in next((q.x, q.y) for q in geo.points if q.id == pid)], float)
    S = size_of(geo)
    cons = cons_all
    timed_out = False

    def unpack(x: np.ndarray) -> dict[str, np.ndarray]:
        P = dict(fixed)
        P.update({pid: x[2 * i:2 * i + 2] for i, pid in enumerate(var)})
        from .constraints import construct
        for pid, (kind, parents, r) in derived.items():    # exact constructions, not optimised
            if not all(q in P for q in parents):
                continue
            if kind == "ratio":
                P[pid] = P[parents[0]] + r * (P[parents[1]] - P[parents[0]])
            else:
                v = construct(kind, [P[q] for q in parents])
                if v is not None:
                    P[pid] = v
        return P

    def F(x: np.ndarray, w: float) -> np.ndarray:
        P = unpack(x)
        r: list[float] = []
        for c in cons:
            r.extend(residuals(c, P, geo, S, curves))
        if w > 0:
            r.extend(list(w * (x - x0) / S))
        return np.array(r, float)

    x = x0.copy()
    if cons and len(x):
        for w in (1e-1, 1e-2, 1e-3, 1e-4, 0.0):
            for _ in range(60):
                if time.monotonic() - t0 > budget:
                    timed_out = True
                    break
                r = F(x, w)
                if not len(r):
                    break
                h = 1e-7 * S
                J = np.empty((len(r), len(x)))
                for j in range(len(x)):
                    xp = x.copy()
                    xp[j] += h
                    J[:, j] = (F(xp, w) - r) / h
                if not np.all(np.isfinite(J)) or not np.all(np.isfinite(r)):
                    timed_out = False
                    x = x * np.nan                   # NaN never propagates silently: reported below as DEGENERATE_GEOMETRY
                    break
                dx, *_ = np.linalg.lstsq(J, -r, rcond=None)
                x = x + dx
                if np.linalg.norm(dx) < 1e-12 * S:
                    break
            if timed_out:
                break
    P = unpack(x)
    from ..constants import MAX_ABS_COORDINATE
    missing = [pid for pid in derived if pid not in P]
    bad = [k for k, v in P.items() if not np.all(np.isfinite(v)) or np.max(np.abs(v)) > MAX_ABS_COORDINATE * max(1.0, S)]
    if missing or bad:                           # e.g. intersection of parallel lines: never an arbitrary fallback
        return {"points": {k: (float(v[0]), float(v[1])) for k, v in P.items() if np.all(np.isfinite(v))}, "ok": False,
                "code": "DEGENERATE_GEOMETRY", "max_residual": float("inf"), "residuals": {}, "moved_fraction": 0.0, "flips": [],
                "derived": sorted(derived), "variables": len(var), "elapsed_s": round(time.monotonic() - t0, 4),
                "degenerate": missing + bad}
    res = {f"{c.type}:{''.join(c.points)}": max(abs(v) for v in residuals(c, P, geo, S, curves)) for c in cons}
    max_res = max(res.values()) if res else 0.0
    P0 = {p.id: np.array([p.x, p.y], float) for p in geo.points}
    moved = max((float(np.hypot(*(P[k] - P0[k]))) for k in P0 if k in P), default=0.0) / S
    visible = [p.id for p in geo.points if not p.hidden]
    flips = []
    for a, b, c in itertools.combinations(visible, 3):
        c0 = _cross(P0[b] - P0[a], P0[c] - P0[a])
        c1 = _cross(P[b] - P[a], P[c] - P[a])
        if abs(c0) > 0.02 * S * S and abs(c1) > 0.02 * S * S and c0 * c1 < 0:   # moved ONTO a line is not a flip
            flips.append(f"{c} עברה לצד השני של הישר {a}{b}")
    ok = max_res < TOL and not timed_out
    code = "" if ok else ("SOLVER_TIMEOUT" if timed_out else "SOLVER_CONVERGENCE_ERROR")
    return {"points": {k: (float(v[0]), float(v[1])) for k, v in P.items()}, "ok": ok, "code": code,
            "max_residual": max_res, "residuals": res, "moved_fraction": moved, "flips": flips,
            "derived": sorted(derived), "variables": len(var), "elapsed_s": round(time.monotonic() - t0, 4)}
