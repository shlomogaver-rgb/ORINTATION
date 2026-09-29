from __future__ import annotations

from ..geometry import parser as gparser
from ..graph import formula_parser
from ..schemas import MixedSpec


def merge_text(mixed: MixedSpec, text: str, observed_curves: int | None) -> list[str]:
    w = formula_parser.merge_text(mixed.graph, text, observed_curves)
    w += gparser.merge_text(mixed.geometry, text)
    mixed.geometry.coordinate_axes = False   # axes come from the graph part
    return w
