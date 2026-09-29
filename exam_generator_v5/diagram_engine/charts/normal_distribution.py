"""Schematic normal curve with region labels, dividing lines and answer boxes (a template, never 'fitted')."""
from __future__ import annotations

import numpy as np

from ..render_base import INK, export, new_figure
from ..schemas import NormalDistSpec
from ..text_utils import visual


def validate(n: NormalDistSpec) -> list[str]:
    errs = []
    k = len(n.percentages)
    if k < 2:
        errs.append("בתרשים ההתפלגות חייבים להיות לפחות שני אזורים.")
    if any(i < 0 or i >= k for i in n.boxed_regions):
        errs.append("אזור מסומן בתיבה אינו קיים.")
    if n.answer_boxes not in (0, k - 1, k):
        errs.append(f"מספר תיבות התשובה ({n.answer_boxes}) אינו תואם את מספר האזורים ({k}).")
    return errs


def render(n: NormalDistSpec) -> tuple[str, bytes, dict]:
    k = len(n.percentages)
    half = (k - 2) / 2 * 0.5 + 0.5          # regions are half-sigma wide, tails extend beyond
    edges = [(-half + 0.5) + 0.5 * i for i in range(k - 1)]
    fig, ax = new_figure(7.2, 3.2)
    xs = np.linspace(-half - 0.6, half + 0.6, 1200)
    pdf = np.exp(-xs ** 2 / 2)
    ax.plot(xs, pdf, color=INK, linewidth=1.4)
    ax.annotate("", xy=(half + 0.9, 0), xytext=(-half - 0.8, 0), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.0))
    ax.text(half + 0.95, -0.02, visual(n.axis_label), fontsize=10, va="top")
    for e in edges:
        ax.plot([e, e], [0, float(np.exp(-e * e / 2))], color=INK, linewidth=0.8)
    centres = [edges[0] - 0.35] + [(a + b) / 2 for a, b in zip(edges, edges[1:])] + [edges[-1] + 0.35]
    man = {"regions": k, "labels": [], "lines": len(edges), "boxes": 0, "callouts": 0}
    for i, (c, lab) in enumerate(zip(centres, n.percentages)):
        h = float(np.exp(-c * c / 2))
        if i in n.boxed_regions:
            side = -1 if i < k / 2 else 1
            ty = 0.16 + 0.07 * (min(i, k - 1 - i) == 0)
            ax.annotate(visual(lab), xy=(c, 0.01), xytext=(c + side * (0.35 if min(i, k - 1 - i) == 0 else 0.15), ty),
                        fontsize=7, ha="center", arrowprops=dict(arrowstyle="-", color=INK, lw=0.6),
                        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=INK, lw=0.6))
            man["callouts"] += 1
        else:
            ax.text(c, h * 0.45, visual(lab), fontsize=8, ha="center", va="center")
        man["labels"].append(lab)
    boxes = n.answer_boxes
    positions = edges if boxes == len(edges) else centres[:boxes]
    for j, e in enumerate(positions):
        ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle((e - 0.18, -0.13), 0.36, 0.08, fill=False, edgecolor=INK, lw=0.8))
        if j < len(n.box_labels) and n.box_labels[j]:
            ax.text(e, -0.09, visual(n.box_labels[j]), fontsize=7, ha="center", va="center")
        man["boxes"] += 1
    ax.set_xlim(-half - 1.0, half + 1.1)
    ax.set_ylim(-0.17, 1.08)
    ax.axis("off")
    man["symmetric_labels"] = n.percentages == list(reversed(n.percentages))
    if n.axis_label:
        man["axis_labels"] = [n.axis_label]                  # the axis name is drawn (structural, verifiable)
    svg, png = export(fig)
    return svg, png, man
