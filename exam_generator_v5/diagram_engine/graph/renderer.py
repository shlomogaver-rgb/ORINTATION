"""Graph rendering: formula graphs, qualitative (topology) sketches and multiple-choice sets I-IV.
Every drawn object is recorded in the manifest (anti-hallucination)."""
from __future__ import annotations

import numpy as np
from matplotlib.ticker import FuncFormatter, MultipleLocator, NullLocator

from .. import safe_math as sm
from ..ocr_labels import display
from ..render_base import INK, export, new_figure
from ..schemas import DiagramSpec, GraphAxes, GraphSpec, GraphTopologySpec
from ..text_utils import visual
from .feature_detector import features
from .qualitative_parser import curve_points


def draw_axes(ax, a: GraphAxes, equal: bool = False, man: dict | None = None) -> tuple[float, float]:
    ax.set_xlim(a.x_min, a.x_max)
    ax.set_ylim(a.y_min, a.y_max)
    if equal:
        ax.set_aspect("equal")
    x0 = 0.0 if a.x_min <= 0 <= a.x_max else a.x_min
    y0 = 0.0 if a.y_min <= 0 <= a.y_max else a.y_min
    ax.spines["left"].set_position(("data", x0))
    ax.spines["bottom"].set_position(("data", y0))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(INK)
        ax.spines[sp].set_linewidth(1.1)
    ax.plot(1, y0, ">", color=INK, transform=ax.get_yaxis_transform(), clip_on=False, markersize=6)
    ax.plot(x0, 1, "^", color=INK, transform=ax.get_xaxis_transform(), clip_on=False, markersize=6)
    if a.show_numbers:
        ax.xaxis.set_major_locator(MultipleLocator(a.x_step))
        ax.yaxis.set_major_locator(MultipleLocator(a.y_step))

        def fmt(step: float, n: float) -> FuncFormatter:
            every = max(1, int(np.ceil(n / 12)))
            return FuncFormatter(lambda v, _: "" if abs(v) < 1e-12 or round(v / step) % every else f"{v:g}")

        ax.xaxis.set_major_formatter(fmt(a.x_step, (a.x_max - a.x_min) / a.x_step))
        ax.yaxis.set_major_formatter(fmt(a.y_step, (a.y_max - a.y_min) / a.y_step))
        ax.tick_params(labelsize=8, colors=INK, length=3)
        if x0 == 0 and y0 == 0:
            ax.annotate("0", xy=(0, 0), xytext=(-9, -11), textcoords="offset points", fontsize=8)
    else:
        ax.xaxis.set_major_locator(NullLocator())
        ax.yaxis.set_major_locator(NullLocator())
    if a.show_grid:
        ax.grid(True, color="#bbbbbb", linewidth=0.5, alpha=0.6)
    if man is not None:
        man.setdefault("axis_labels", []).extend([t for t in (a.x_label, a.y_label) if t])
    ax.annotate(visual(a.x_label), xy=(1, y0), xycoords=ax.get_yaxis_transform(), xytext=(4, -12),
                textcoords="offset points", fontsize=10, annotation_clip=False)
    ax.annotate(visual(a.y_label), xy=(x0, 1), xycoords=ax.get_xaxis_transform(), xytext=(6, 0),
                textcoords="offset points", fontsize=10, annotation_clip=False)
    return x0, y0


def _cut(xs: np.ndarray, ys: np.ndarray, y_lo: float, y_hi: float, poles: list[float]) -> np.ndarray:
    span = y_hi - y_lo
    ys = ys.copy()
    ys[(ys < y_lo - 3 * span) | (ys > y_hi + 3 * span)] = np.nan
    jump = np.abs(np.diff(ys)) > 0.75 * span
    for p in poles:
        jump |= (xs[:-1] < p) & (xs[1:] > p)
    ys[1:][jump] = np.nan
    return ys


def draw_formula(ax, g: GraphSpec, spec: DiagramSpec, man: dict) -> None:
    a = g.axes
    man.setdefault("curves", []), man.setdefault("points", []), man.setdefault("asymptotes", [])
    man.setdefault("endpoints", []), man.setdefault("labels", [])
    poles = [s.value for s in g.asymptotes if s.kind == "vertical"]
    for c in g.curves:
        items = [(p.expression, p.x_from, p.x_to, p.left_closed, p.right_closed) for p in c.pieces] or \
                [(c.expression, None, None, None, None)]
        last = None
        for expr, lo, hi, lc, rc in items:
            parsed = sm.parse_expression(expr)
            f = sm.to_numpy(parsed)
            lo2 = a.x_min if lo is None else max(a.x_min, lo)
            hi2 = a.x_max if hi is None else min(a.x_max, hi)
            if hi2 <= lo2:
                continue
            try:
                extra = features(parsed, lo2, hi2)["vertical_asymptotes"]
            except Exception:
                extra = []
            from .evaluator import branch_samples
            for bx, by in branch_samples(parsed, lo2, hi2, a.y_min, a.y_max, poles + extra):
                ax.plot(bx, by, color=INK, linewidth=1.6, solid_capstyle="round", clip_on=True)   # each branch separately
                inside = (by >= a.y_min) & (by <= a.y_max)
                if inside.any():
                    last = (bx[inside][-1], by[inside][-1])
                man.setdefault("branch_paths", []).append([round(float(bx[0]), 6), round(float(bx[-1]), 6)])
            for xe, closed in ((lo, lc), (hi, rc)):
                if xe is None or closed is None:
                    continue
                ye = float(f(np.array([xe]))[0])
                if np.isfinite(ye):
                    ax.plot([xe], [ye], "o", markersize=5.5, markeredgecolor=INK, markeredgewidth=1.2,
                            markerfacecolor=INK if closed else "white", zorder=5)
                    man["endpoints"].append([c.id, round(xe, 9), round(ye, 9), "closed" if closed else "open"])
        man["curves"].append(c.id)
        if c.label and last is not None:
            ax.annotate(visual(display(c.label, spec)), xy=last, xytext=(-18, 6), textcoords="offset points", fontsize=10)
            man["labels"].append(display(c.label, spec))
    for s in g.asymptotes:
        (ax.axvline if s.kind == "vertical" else ax.axhline)(s.value, color=INK, linestyle=(0, (5, 4)), linewidth=0.9)
        man["asymptotes"].append([s.kind, s.value])
    for p in g.points:
        ax.plot([p.x], [p.y], "o", markersize=5, markeredgecolor=INK, markeredgewidth=1.2,
                markerfacecolor=INK if p.style == "closed" else "white", zorder=6)
        name = display(p.name, spec)
        text = f"{name}({p.x:g},{p.y:g})" if p.show_coordinates and name else name
        if text:
            ax.annotate(visual(text), xy=(p.x, p.y), xytext=(5 + p.label_dx, 5 + p.label_dy), textcoords="offset points", fontsize=10)
            man["labels"].append(name)
        man["points"].append([name, round(p.x, 9), round(p.y, 9), p.style])


def draw_topology(ax, topo: GraphTopologySpec, spec: DiagramSpec, man: dict) -> None:
    man.update({"branches": 0, "landmarks": [], "asymptotes": [], "labels": [], "curves": []})
    for s in topo.asymptotes:
        (ax.axvline if s.kind == "vertical" else ax.axhline)(s.value, color=INK, linestyle=(0, (5, 4)), linewidth=0.9)
        man["asymptotes"].append([s.kind, s.value])
    for br in topo.branches:
        xs, ys = curve_points(topo, br)
        ax.plot(xs, ys, color=INK, linewidth=1.5, clip_on=True)
        man["branches"] += 1
    for l in topo.landmarks:
        if l.style != "none":
            ax.plot([l.x], [l.y], "o", markersize=4.5, markeredgecolor=INK, markeredgewidth=1.1,
                    markerfacecolor=INK if l.style == "closed" else "white", zorder=6)
        if l.label:
            txt = display(l.label, spec)
            dy = -14 if l.kind == "min" else 7
            ax.annotate(visual(txt), xy=(l.x, l.y), xytext=(0, dy), textcoords="offset points", fontsize=10, ha="center")
            man["labels"].append(txt)
        man["landmarks"].append([l.kind, l.style, display(l.label, spec)])
    if topo.function_label:
        man["labels"].append(topo.function_label)


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    if spec.multi_graph is not None and spec.subtype == "multi_choice_graphs":
        return render_multi(spec)
    man: dict = {}
    fig, ax = new_figure(5.6, 4.4)
    if spec.graph_topology is not None and spec.subtype == "qualitative_graph":
        t = spec.graph_topology
        if t.function_label:
            t = t.model_copy(update={"axes": t.axes.model_copy(update={"y_label": t.function_label})})
        draw_topology(ax, t, spec, man)
        draw_axes(ax, t.axes, man=man)
    else:
        draw_axes(ax, spec.graph.axes, man=man)
        draw_formula(ax, spec.graph, spec, man)
        draw_illustrations(ax, spec.graph, man)
    svg, png = export(fig)
    return svg, png, man


def draw_illustrations(ax, g, man: dict) -> None:
    """HybridDiagram illustration layer: simple vector icons anchored in math space, drawn AFTER the mathematics and
    recorded separately - the mathematical manifest is unchanged by it."""
    from matplotlib.patches import Circle, Rectangle
    for il in g.illustrations:
        s_ = il.size
        if il.kind == "ball":
            ax.add_patch(Circle((il.x, il.y), 0.15 * s_, fill=False, lw=1.2))
        elif il.kind == "basket":
            ax.add_patch(Rectangle((il.x - 0.25 * s_, il.y - 0.1 * s_), 0.5 * s_, 0.2 * s_, fill=False, lw=1.2))
            ax.plot([il.x - 0.2 * s_, il.x - 0.1 * s_, il.x + 0.1 * s_, il.x + 0.2 * s_], [il.y - 0.1 * s_, il.y - 0.4 * s_, il.y - 0.4 * s_, il.y - 0.1 * s_], lw=1)
        elif il.kind == "person":
            ax.add_patch(Circle((il.x, il.y + 0.9 * s_), 0.15 * s_, fill=False, lw=1.2))
            ax.plot([il.x, il.x], [il.y + 0.75 * s_, il.y + 0.2 * s_], lw=1.2)
            ax.plot([il.x - 0.2 * s_, il.x, il.x + 0.2 * s_], [il.y - 0.3 * s_, il.y + 0.2 * s_, il.y - 0.3 * s_], lw=1.2)
        else:
            ax.add_patch(Rectangle((il.x - 0.3 * s_, il.y - 0.3 * s_), 0.6 * s_, 0.6 * s_, fill=False, lw=1.0, linestyle=":"))
        if il.label:
            ax.text(il.x, il.y - 0.55 * s_, il.label, ha="center", fontsize=9)
        man.setdefault("illustrations", []).append([il.kind, il.x, il.y])


def render_multi(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    opts = spec.multi_graph.options
    cols = max(1, min(spec.multi_graph.columns, len(opts)))
    rows = (len(opts) + cols - 1) // cols
    fig, _ = new_figure(3.3 * cols, 3.0 * rows)
    fig.clf()
    man: dict = {"options": [], "option_manifests": {}}
    for i, o in enumerate(opts):
        r_, c_ = divmod(i, cols)
        slot = r_ * cols + ((cols - 1 - c_) if spec.multi_graph.rtl else c_)      # RTL: first option on the RIGHT
        ax = fig.add_subplot(rows, cols, slot + 1)
        man.setdefault("option_slots", []).append([o.label, slot])
        sub: dict = {}
        if o.formula is not None:
            draw_axes(ax, o.formula.axes)
            draw_formula(ax, o.formula, spec, sub)
        elif o.topology is not None:
            t = o.topology
            if t.function_label:
                t = t.model_copy(update={"axes": t.axes.model_copy(update={"y_label": t.function_label})})
            draw_axes(ax, t.axes)
            draw_topology(ax, t, spec, sub)
        ax.set_title(o.label, y=-0.22, fontsize=12, fontweight="bold")
        man["options"].append(o.label)
        man["option_manifests"][o.label] = sub
    fig.subplots_adjust(hspace=0.45, wspace=0.3)
    svg, png = export(fig)
    return svg, png, man
