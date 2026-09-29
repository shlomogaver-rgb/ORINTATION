"""Custom Streamlit components."""
from __future__ import annotations

from pathlib import Path

_DRAG = None


def geo_drag(points, segments, circles, width, height, nonce, key):
    """Constraint-aware geometry editor front-end: select a point, drag it, release -> {event, id, x, y} (canvas units).
    The solver (not the widget) decides the final position."""
    global _DRAG
    import streamlit.components.v1 as components
    if _DRAG is None:
        _DRAG = components.declare_component("geo_drag", path=str(Path(__file__).parent / "geo_drag"))
    return _DRAG(points=points, segments=segments, circles=circles, width=width, height=height, nonce=nonce, key=key, default=None)
