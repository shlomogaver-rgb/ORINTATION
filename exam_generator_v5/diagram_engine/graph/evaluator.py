"""Numerical evaluation helpers (real-valued, branch aware)."""
from __future__ import annotations

import numpy as np

from .. import safe_math as sm

real_rational_power = sm.real_rational_power


def sample(expr, lo: float, hi: float, n: int = 3001) -> tuple[np.ndarray, np.ndarray]:
    xs = np.linspace(lo, hi, n)
    return xs, sm.to_numpy(expr)(xs)


def split_branches(xs: np.ndarray, ys: np.ndarray, poles: list[float], jump: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Continuous finite pieces of the sampled graph (split at NaN, poles and big jumps)."""
    out, cur_x, cur_y = [], [], []
    for i in range(len(xs)):
        brk = not np.isfinite(ys[i])
        if not brk and cur_x:
            if abs(ys[i] - cur_y[-1]) > jump or any(cur_x[-1] < p < xs[i] for p in poles):
                brk = True
                out.append((np.array(cur_x), np.array(cur_y)))
                cur_x, cur_y = [], []
        if brk and not np.isfinite(ys[i]):
            if cur_x:
                out.append((np.array(cur_x), np.array(cur_y)))
            cur_x, cur_y = [], []
            continue
        cur_x.append(xs[i]); cur_y.append(ys[i])
    if cur_x:
        out.append((np.array(cur_x), np.array(cur_y)))
    return [b for b in out if len(b[0]) >= 3]


MAX_SAMPLES_PER_BRANCH = 6000


def branch_samples(expr, lo: float, hi: float, y_lo: float, y_hi: float, poles: list[float], base: int = 800):
    """Branch-aware adaptive sampling: split the domain at poles / domain gaps, refine where the function changes fast,
    clip to the viewport (with a margin) WITHOUT ever connecting two branches. Returns [(xs, ys)] per visible branch."""
    f = sm.to_numpy(expr)
    cuts = sorted({lo, hi, *[p for p in poles if lo < p < hi]})
    span = y_hi - y_lo
    out = []
    for a, b in zip(cuts, cuts[1:]):
        eps = 1e-9 * max(1.0, abs(b - a))
        xs = np.linspace(a + (eps if a in poles else 0), b - (eps if b in poles else 0), base)
        ys = f(xs)
        for _ in range(4):                                   # adaptive refinement (bounded)
            if len(xs) >= MAX_SAMPLES_PER_BRANCH:
                break
            dy = np.abs(np.diff(ys))
            fin = np.isfinite(dy)
            steep = np.where(fin & (dy > 0.02 * span))[0]
            if not len(steep):
                break
            mids = (xs[steep] + xs[steep + 1]) / 2
            xs = np.sort(np.concatenate([xs, mids]))[:MAX_SAMPLES_PER_BRANCH]
            ys = f(xs)
        finite = np.isfinite(ys)
        # domain gaps inside the interval split the branch too
        idx = np.where(finite)[0]
        if not len(idx):
            continue
        groups = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
        for gidx in groups:
            bx, by = xs[gidx], ys[gidx]
            margin = 0.05 * span
            vis = (by >= y_lo - margin) & (by <= y_hi + margin)
            if not vis.any():
                continue
            by = np.clip(by, y_lo - margin, y_hi + margin)           # clean clipping (direction kept, no giant spike)
            runs = np.split(np.arange(len(bx)), np.where(np.diff(vis.astype(int)) != 0)[0] + 1)
            for rr in runs:
                if vis[rr[0]] or len(rr) > 1:
                    seg = rr if vis[rr[0]] else rr[-1:]
                    lo_i, hi_i = max(0, seg[0] - 1), min(len(bx) - 1, seg[-1] + 1)
                    out.append((bx[lo_i:hi_i + 1], by[lo_i:hi_i + 1]))
    return out
