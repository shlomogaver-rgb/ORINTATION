"""The curve is drawn from its equation FIRST, then the construction is drawn on top in the same coordinates."""
from __future__ import annotations

from ..geometry.renderer import draw_geometry
from ..graph.renderer import draw_axes, draw_formula
from ..render_base import export, new_figure
from ..schemas import DiagramSpec


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    m = spec.mixed
    a = m.graph.axes
    w = 5.8
    h = max(2.8, min(6.5, w * (a.y_max - a.y_min) / max(1e-9, a.x_max - a.x_min)))
    fig, ax = new_figure(w, h)
    man: dict = {}
    draw_axes(ax, a, equal=True, man=man)
    draw_formula(ax, m.graph, spec, man)
    gman: dict = {}
    S = max(a.x_max - a.x_min, a.y_max - a.y_min) * 0.6
    draw_geometry(ax, spec, m.geometry, gman, S)
    man["geometry"] = gman
    svg, png = export(fig)
    return svg, png, man
