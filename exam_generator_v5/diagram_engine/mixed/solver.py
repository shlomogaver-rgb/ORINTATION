from __future__ import annotations

from .. import safe_math as sm
from ..geometry.solver import solve as solve_geometry
from ..schemas import MixedSpec


def curve_functions(mixed: MixedSpec) -> dict:
    out = {}
    for c in mixed.graph.curves:
        if c.expression and not c.pieces:
            out[c.id] = sm.safe_function(c.expression)
    return out


def solve(mixed: MixedSpec) -> dict:
    return solve_geometry(mixed.geometry, curve_functions(mixed))
