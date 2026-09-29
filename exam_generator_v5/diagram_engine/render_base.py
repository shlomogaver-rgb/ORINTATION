"""Deterministic SVG + PNG export for all renderers (same figure -> byte-identical SVG)."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
from matplotlib import rc_context  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

RC = {"svg.hashsalt": "exam-generator-diagram-engine", "svg.fonttype": "path", "font.family": "DejaVu Sans",
      "path.simplify": False}
INK = "#111111"


def new_figure(w: float, h: float):
    with rc_context(RC):
        fig = Figure(figsize=(w, h), dpi=100)
        ax = fig.subplots()
    return fig, ax


def export(fig) -> tuple[str, bytes]:
    with rc_context(RC):
        s = io.StringIO()
        fig.savefig(s, format="svg", bbox_inches="tight", facecolor="white", metadata={"Date": None, "Creator": None})
        p = io.BytesIO()
        fig.savefig(p, format="png", dpi=300, bbox_inches="tight", facecolor="white")
    return s.getvalue(), p.getvalue()
