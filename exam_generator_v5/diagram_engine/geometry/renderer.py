"""Geometry: deterministic drawing of exactly the objects in the (solved) GeometrySpec."""
from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Arc, Circle

from matplotlib.patches import Polygon as MplPolygon

from ..ocr_labels import display
from ..render_base import INK, export, new_figure
from ..schemas import DiagramSpec, GeometrySpec
from ..text_utils import visual


def _u(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(*v))
    return v / n if n > 1e-12 else np.array([0.0, 1.0])


def _radius(c, P) -> float:
    ref = c.through or (c.through_points[0] if c.through_points else None)
    ctr = P[c.center or f"__c_{c.id}"]
    return float(np.hypot(*(P[ref] - ctr))) if ref else float(c.radius or 0)


def bounds(geo: GeometrySpec) -> tuple[list[float], list[float]]:
    P = {p.id: np.array([p.x, p.y], float) for p in geo.points}
    vis = [P[p.id] for p in geo.points if not p.hidden]
    xs, ys = [v[0] for v in vis], [v[1] for v in vis]
    for c in geo.circles:
        ctr = P.get(c.center or f"__c_{c.id}")
        if ctr is None:
            continue
        r = _radius(c, P)
        xs += [ctr[0] - r, ctr[0] + r]
        ys += [ctr[1] - r, ctr[1] + r]
    if geo.coordinate_axes:
        xs.append(0.0)
        ys.append(0.0)
    return xs, ys


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    geo = spec.geometry
    xs, ys = bounds(geo)
    S = max(1e-6, max(xs) - min(xs), max(ys) - min(ys))
    w = max(3.2, min(6.0, 5.0 * (max(xs) - min(xs)) / S + 1.0))
    h = max(2.6, min(5.5, 5.0 * (max(ys) - min(ys)) / S + 1.0))
    fig, ax = new_figure(w, h)
    pad = 0.14 * S
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    man: dict = {}
    if geo.coordinate_axes:
        draw_coordinate_axes(ax, min(xs) - pad * 0.7, max(xs) + pad * 0.7, min(ys) - pad * 0.7, max(ys) + pad * 0.7, man)
    draw_geometry(ax, spec, geo, man, S)
    svg, png = export(fig)
    return svg, png, man


def draw_coordinate_axes(ax, x0: float, x1: float, y0: float, y1: float, man: dict) -> None:
    ax.annotate("", xy=(x1, 0), xytext=(x0, 0), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.0))
    ax.annotate("", xy=(0, y1), xytext=(0, y0), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.0))
    ax.text(x1, 0, "  x", va="center", fontsize=11)
    ax.text(0, y1, " y", va="bottom", fontsize=11)
    man["axes"] = True
    man["axis_labels"] = ["x", "y"]


def draw_geometry(ax, spec: DiagramSpec, geo: GeometrySpec, man: dict, S: float) -> None:
    P = {p.id: np.array([p.x, p.y], float) for p in geo.points}
    visible = [p for p in geo.points if not p.hidden]
    cen = np.array([np.mean([P[p.id][0] for p in visible]), np.mean([P[p.id][1] for p in visible])])
    man.update({"axis_labels": man.get("axis_labels", []), "points": sorted(p.id for p in visible), "labels": [], "segments": [], "lines": [], "rays": [], "circles": 0,
                "arcs": 0, "angle_marks": 0, "right_angle_marks": 0, "angle_values": [], "equal_mark_groups": 0,
                "parallel_mark_groups": 0, "length_labels": [], "equal_angle_groups": 0, "polygons": 0, "texts": [],
                "dimensions": []})
    ls = {"solid": "-", "dashed": (0, (5, 4))}
    for poly in geo.polygons:
        pts = [P[v] for v in poly.vertices]
        ax.add_patch(MplPolygon(pts, closed=True, facecolor="#c8c8c8" if poly.fill else "none", edgecolor="none", zorder=0))
        man["polygons"] += 1
    for s in geo.segments:
        ax.plot(*zip(P[s.a], P[s.b]), color=INK, linewidth=1.5, linestyle=ls[s.style], solid_capstyle="round")
        man["segments"].append("".join(sorted((s.a, s.b))))
    big = 20 * S
    for s in geo.lines:
        d = _u(P[s.b] - P[s.a])
        ax.plot(*zip(P[s.a] - d * big, P[s.a] + d * big), color=INK, linewidth=1.3, linestyle=ls[s.style])
        man["lines"].append("".join(sorted((s.a, s.b))))
    for s in geo.rays:
        d = _u(P[s.b] - P[s.a])
        ax.plot(*zip(P[s.a], P[s.a] + d * big), color=INK, linewidth=1.3, linestyle=ls[s.style])
        man["rays"].append(s.a + s.b)
    for c in geo.circles:
        ax.add_patch(Circle(P[c.center or f"__c_{c.id}"], _radius(c, P), fill=False, edgecolor=INK, linewidth=1.4, linestyle=ls[c.style]))
        man["circles"] += 1
    for a in geo.arcs:
        r = float(np.hypot(*(P[a.start] - P[a.center])))
        t1 = math.degrees(math.atan2(*(P[a.start] - P[a.center])[::-1]))
        t2 = math.degrees(math.atan2(*(P[a.end] - P[a.center])[::-1]))
        ax.add_patch(Arc(P[a.center], 2 * r, 2 * r, theta1=t1, theta2=t2, color=INK, linewidth=1.4))
        man["arcs"] += 1
    rr = 0.07 * S
    for m in geo.angle_marks:
        v = P[m.vertex]
        u1, u2 = _u(P[m.a] - v), _u(P[m.b] - v)
        if m.kind == "right":
            s = 0.055 * S
            sq = [v + u1 * s, v + u1 * s + u2 * s, v + u2 * s]
            ax.plot(*zip(*sq), color=INK, linewidth=1.1)
            man["right_angle_marks"] += 1
            bis = _u(u1 + u2)
            label_at = v + bis * s * 2.3
        else:
            a1 = math.degrees(math.atan2(u1[1], u1[0]))
            a2 = math.degrees(math.atan2(u2[1], u2[0]))
            lo, hi = sorted((a1, a2))
            if hi - lo > 180:
                lo, hi = hi, lo + 360
            for k in range(max(1, m.arcs)):
                rk = rr * (1 + 0.22 * k)
                ax.add_patch(Arc(v, 2 * rk, 2 * rk, theta1=lo, theta2=hi, color=INK, linewidth=1.1))
            man["angle_marks"] += 1
            mid = math.radians((lo + hi) / 2)
            label_at = v + np.array([math.cos(mid), math.sin(mid)]) * rr * 2.0
        if m.value:
            txt = display(m.value, spec)
            shown = f"{txt}°" if txt.replace(".", "", 1).isdigit() else txt
            ax.text(*label_at, visual(shown), ha="center", va="center", fontsize=10)
            man["angle_values"].append(txt)
    for m in geo.equal_marks:
        for sg in m.segments:
            A, B = P[sg[0]], P[sg[1]]
            d = _u(B - A)
            n = np.array([-d[1], d[0]])
            mid = (A + B) / 2
            for k in range(max(1, m.ticks)):
                off = (k - (m.ticks - 1) / 2) * 0.018 * S
                c0 = mid + d * off
                ax.plot(*zip(c0 - n * 0.025 * S, c0 + n * 0.025 * S), color=INK, linewidth=1.2)
        man["equal_mark_groups"] += 1
    for m in geo.parallel_marks:
        for sg in m.segments:
            A, B = P[sg[0]], P[sg[1]]
            d = _u(B - A)
            n = np.array([-d[1], d[0]])
            mid = (A + B) / 2
            for k in range(max(1, m.arrows)):
                tip = mid + d * ((k - (m.arrows - 1) / 2) * 0.03 * S + 0.012 * S)
                wing = tip - d * 0.028 * S
                ax.plot(*zip(wing + n * 0.018 * S, tip, wing - n * 0.018 * S), color=INK, linewidth=1.2)
        man["parallel_mark_groups"] += 1
    for l in geo.length_labels:
        A, B = P[l.a], P[l.b]
        mid = (A + B) / 2
        d = _u(B - A)
        n = np.array([-d[1], d[0]])
        if np.dot(n, mid - cen) < 0:
            n = -n
        txt = display(l.text, spec)
        ax.text(*(mid + n * 0.05 * S), visual(txt), ha="center", va="center", fontsize=10,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none"))
        man["length_labels"].append(txt)
    for m in geo.equal_angle_marks:
        for ang in m.angles:
            v = P[ang[1]]
            u1, u2 = _u(P[ang[0]] - v), _u(P[ang[2]] - v)
            a1, a2 = math.degrees(math.atan2(u1[1], u1[0])), math.degrees(math.atan2(u2[1], u2[0]))
            lo, hi = sorted((a1, a2))
            if hi - lo > 180:
                lo, hi = hi, lo + 360
            for k in range(max(1, m.arcs)):
                rk = rr * (0.8 + 0.2 * k)
                ax.add_patch(Arc(v, 2 * rk, 2 * rk, theta1=lo, theta2=hi, color=INK, linewidth=1.0))
        man["equal_angle_groups"] += 1
    for d in geo.dimensions:
        A, B = P[d.a], P[d.b]
        dd = _u(B - A)
        n = np.array([-dd[1], dd[0]])
        if np.dot(n, (A + B) / 2 - cen) < 0:
            n = -n
        A2, B2 = A + n * d.offset * S, B + n * d.offset * S
        ax.annotate("", xy=B2, xytext=A2, arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.0, shrinkA=0, shrinkB=0))
        ax.text(*((A2 + B2) / 2 + n * 0.035 * S), visual(display(d.text, spec)), ha="center", va="center", fontsize=10)
        man["dimensions"].append([d.a, d.b, display(d.text, spec)])
    for t in geo.texts:
        ax.text(t.x, t.y, visual(display(t.text, spec)), ha="center", va="center", fontsize=10)
        man["texts"].append(display(t.text, spec))
    for p in visible:
        v = P[p.id]
        ax.plot([v[0]], [v[1]], "o", color=INK, markersize=3.2, zorder=5)
        label = p.id if p.label is None else p.label
        if label:
            off = _u(v - cen) if np.hypot(*(v - cen)) > 1e-9 else np.array([0.0, 1.0])
            txt = display(label, spec)
            ax.text(*(v + off * 0.055 * S), visual(txt), ha="center", va="center", fontsize=12)
            man["labels"].append(txt)
    man["segments"].sort()
    man["lines"].sort()
    man["labels"].sort()
