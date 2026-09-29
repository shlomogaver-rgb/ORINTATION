from __future__ import annotations

import numpy as np
from matplotlib.patches import Ellipse, FancyArrowPatch, Polygon, Rectangle

from ..render_base import INK, export, new_figure
from ..schemas import DiagramSpec
from ..text_utils import visual


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    g = spec.generic
    fig, ax = new_figure(6.4, max(1.6, 6.4 * g.height / max(1e-6, g.width)))
    ax.set_xlim(0, g.width)
    ax.set_ylim(g.height, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    man: dict = {"shapes": 0, "polygons": 0, "arrows": 0, "lines": 0, "texts": [], "labels": [], "dimensions": []}
    for s in g.shapes:
        patch = Rectangle((s.x, s.y), s.w, s.h) if s.kind == "rect" else Ellipse((s.x + s.w / 2, s.y + s.h / 2), s.w, s.h)
        patch.set_fill(False)
        patch.set_edgecolor(INK)
        patch.set_linewidth(1.3)
        ax.add_patch(patch)
        man["shapes"] += 1
        if s.text:
            ax.text(s.x + s.w / 2, s.y + s.h / 2, visual(s.text), ha="center", va="center", fontsize=9)
            man["texts"].append(s.text)
    for p in g.polygons:
        ax.add_patch(Polygon(p.points, closed=True, fill=False, edgecolor=INK, linewidth=1.3))
        man["polygons"] += 1
        if p.text:
            c = np.mean(np.array(p.points), axis=0)
            ax.text(c[0], c[1], visual(p.text), ha="center", va="center", fontsize=9)
            man["texts"].append(p.text)
    for a in g.arrows:
        ax.add_patch(FancyArrowPatch((a.x1, a.y1), (a.x2, a.y2), arrowstyle="-|>", mutation_scale=12, color=INK, linewidth=1.2))
        man["arrows"] += 1
        if a.label:
            ax.text((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2 - 0.03 * g.height, visual(a.label), ha="center", fontsize=9)
            man["texts"].append(a.label)
    for l in g.lines:
        ax.plot([l.x1, l.x2], [l.y1, l.y2], color=INK, linewidth=1.2)
        man["lines"] += 1
    for d in g.dimensions:
        ax.add_patch(FancyArrowPatch((d.x1, d.y1), (d.x2, d.y2), arrowstyle="<|-|>", mutation_scale=11, color=INK, linewidth=1.0))
        v = np.array([d.x2 - d.x1, d.y2 - d.y1], float)
        n = np.array([-v[1], v[0]]) / max(1e-9, float(np.hypot(*v)))
        mid = np.array([(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2]) + n * 0.045 * g.height * (1 if n[1] >= 0 else -1)
        ax.text(mid[0], mid[1], visual(d.text), ha="center", va="center", fontsize=9)
        man["dimensions"].append([d.text, list(d.attach)])
    for lb in g.labels:
        ax.text(lb.x, lb.y, visual(lb.text), ha="center", va="center", fontsize=10)
        man["labels"].append(lb.text)
    man["labels"].sort()
    svg, png = export(fig)
    return svg, png, man
