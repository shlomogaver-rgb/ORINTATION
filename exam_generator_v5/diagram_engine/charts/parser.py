"""Charts: numeric values written in the question take priority over bar heights read from pixels."""
from __future__ import annotations

import re

from ..schemas import ChartSpec

_ROW = re.compile(r"^\s*\|?\s*([^|:\-–\d][^|:\-–]*?)\s*(?:\||:|–|-)\s*(-?\d+(?:\.\d+)?)\s*\|?\s*$")


def values_from_text(text: str) -> list[tuple[str, float]]:
    rows = []
    for line in (text or "").splitlines():
        m = _ROW.match(line)
        if m:
            rows.append((m.group(1).strip(), float(m.group(2))))
    return rows if len(rows) >= 2 else []


def merge_text(chart: ChartSpec, text: str) -> list[str]:
    warnings: list[str] = []
    rows = values_from_text(text)
    if not rows or chart.kind in ("two_way_table",):
        return warnings
    cats = [c for c, _ in rows]
    vals = [v for _, v in rows]
    if chart.categories and [c.strip() for c in chart.categories] == cats:
        if [round(v, 9) for v in chart.values] != [round(v, 9) for v in vals]:
            warnings.append("ערכי התרשים שזוהו מהתמונה שונים מהערכים בנוסח השאלה — נעשה שימוש בערכי השאלה.")
        chart.values = vals
        chart.values_source = "text"
    elif not chart.categories or len(chart.categories) == len(cats):
        if chart.categories and [c.strip() for c in chart.categories] != cats:
            warnings.append("שמות הקטגוריות בתמונה שונים מהטקסט — נעשה שימוש בנוסח השאלה.")
        chart.categories, chart.values, chart.values_source = cats, vals, "text"
    return warnings
