"""Charts, tables and simple generic diagrams (values drawn exactly as given)."""
from __future__ import annotations

from matplotlib.patches import Ellipse, FancyArrowPatch, Rectangle
from matplotlib.ticker import MaxNLocator

from ..render_base import INK, export, new_figure
from ..schemas import DiagramSpec
from ..text_utils import visual


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    c = spec.chart
    cats = [visual(x) for x in c.categories]
    man: dict = {"kind": c.kind, "categories": list(c.categories), "values": list(c.values), "bars": 0}
    fig, ax = new_figure(6.0, 4.0)
    if c.kind in ("frequency_table", "two_way_table"):
        ax.axis("off")
        cells = [[visual(v) for v in row] for row in c.table]
        tbl = ax.table(cellText=cells, rowLabels=[visual(r) for r in c.row_labels] or None,
                       colLabels=[visual(x) for x in c.col_labels] or None, loc="center", cellLoc="center")
        tbl.scale(1, 1.6)
        man.update({"rows": len(c.table), "cols": len(c.table[0]) if c.table else 0})
    elif c.kind == "pie":
        ax.pie(c.values, labels=cats, autopct="%1.0f%%" if c.show_percentages else None, startangle=90,
               counterclock=False, wedgeprops=dict(edgecolor="white"), colors=["#4C78A8", "#F58518", "#54A24B", "#E45756",
               "#72B7B2", "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC"][: len(c.values)])
        ax.axis("equal")
        man["bars"] = len(c.values)
    elif c.kind == "histogram":
        widths = [b2 - b1 for b1, b2 in zip(c.bins, c.bins[1:])]
        ax.bar(c.bins[:-1], c.values, width=widths, align="edge", color="#9ecae1", edgecolor=INK)
        ax.set_xticks(c.bins)
        man["bars"] = len(c.values)
    elif c.kind == "line":
        ax.plot(cats, c.values, marker="o", color=INK)
        man["bars"] = len(c.values)
    else:
        ax.bar(cats, c.values, color="#9ecae1", edgecolor=INK)
        man["bars"] = len(c.values)
    if c.kind not in ("pie", "frequency_table", "two_way_table"):
        if all(float(v).is_integer() for v in c.values):
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(True, axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        if c.x_label:
            ax.set_xlabel(visual(c.x_label))
        if c.y_label:
            ax.set_ylabel(visual(c.y_label))
    if c.title:
        ax.set_title(visual(c.title))
    svg, png = export(fig)
    return svg, png, man


def render_generic(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    g = spec.generic
    fig, ax = new_figure(6.0, 6.0 * g.height / max(1e-6, g.width))
    ax.set_xlim(0, g.width)
    ax.set_ylim(g.height, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    man: dict = {"shapes": 0, "arrows": 0, "texts": []}
    for s in g.shapes:
        patch = (Rectangle((s.x, s.y), s.w, s.h) if s.kind == "rect" else Ellipse((s.x + s.w / 2, s.y + s.h / 2), s.w, s.h))
        patch.set_fill(False)
        patch.set_edgecolor(INK)
        patch.set_linewidth(1.4)
        ax.add_patch(patch)
        man["shapes"] += 1
        if s.text:
            ax.text(s.x + s.w / 2, s.y + s.h / 2, visual(s.text), ha="center", va="center", fontsize=10)
            man["texts"].append(s.text)
    for a in g.arrows:
        ax.add_patch(FancyArrowPatch((a.x1, a.y1), (a.x2, a.y2), arrowstyle="-|>", mutation_scale=14, color=INK, linewidth=1.3))
        man["arrows"] += 1
        if a.label:
            ax.text((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2 - 0.03 * g.height, visual(a.label), ha="center", fontsize=9)
            man["texts"].append(a.label)
    svg, png = export(fig)
    return svg, png, man


def render_scatter(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    import numpy as np

    from ..graph.renderer import draw_axes

    sc = spec.scatter
    fig, ax = new_figure(5.6, 4.2)
    draw_axes(ax, sc.axes)
    xs = [p[0] for p in sc.points]
    ys = [p[1] for p in sc.points]
    ax.plot(xs, ys, "o", color=INK, markersize=4.5, zorder=5)
    man = {"points": sorted([round(p[0], 6), round(p[1], 6)] for p in sc.points), "regression": None}
    if sc.regression:
        t = np.linspace(sc.axes.x_min, sc.axes.x_max, 50)
        ax.plot(t, sc.regression[0] * t + sc.regression[1], color=INK, linewidth=1.0)
        man["regression"] = list(sc.regression)
    if sc.title:
        ax.set_title(visual(sc.title), fontsize=10)
    svg, png = export(fig)
    return svg, png, man
