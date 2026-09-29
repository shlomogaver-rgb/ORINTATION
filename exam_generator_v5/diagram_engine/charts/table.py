"""Tables are rebuilt as real tables (native DOCX table on export). One wrong number is a critical mismatch."""
from __future__ import annotations

import re

from ..render_base import export, new_figure
from ..schemas import TableSpec
from ..text_utils import visual


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(",", "").replace("\u200f", "").replace("\u200e", "")).strip()


def validate(t: TableSpec) -> list[str]:
    errs = []
    if not t.rows:
        return ["הטבלה ריקה."]
    widths = {len(r) for r in t.rows}
    if len(widths) != 1:
        errs.append("הטבלה אינה מלבנית (מספר תאים שונה בשורות).")
    n_r, n_c = len(t.rows), max(widths)
    if not (0 <= t.header_rows <= n_r and 0 <= t.header_columns <= n_c):
        errs.append("מספר שורות/עמודות הכותרת אינו חוקי.")
    for m in t.merged:
        if len(m) != 4 or not (0 <= m[0] <= m[2] < n_r and 0 <= m[1] <= m[3] < n_c):
            errs.append(f"מיזוג תאים לא חוקי: {m}.")
    for r, row in enumerate(t.rows):
        for c, cell in enumerate(row):
            if cell.value is not None and norm(cell.text) and re.fullmatch(r"-?\d+(?:\.\d+)?", norm(cell.text)):
                if abs(float(norm(cell.text)) - cell.value) > 1e-9:
                    errs.append(f"בתא ({r + 1},{c + 1}) הטקסט '{cell.text}' אינו תואם את הערך {cell.value}.")
    return errs


def cells(t: TableSpec) -> list[list[str]]:
    return [[norm(c.text) for c in row] for row in t.rows]


def compare_cells(t: TableSpec, observed: list[list[str]]) -> list[str]:
    got = cells(t)
    obs = [[norm(x) for x in row] for row in observed]
    if len(got) != len(obs) or any(len(a) != len(b) for a, b in zip(got, obs)):
        return [f"מבנה הטבלה שונה מהמקור ({len(obs)} שורות במקור, {len(got)} בשחזור)."]
    return [f"תא ({r + 1},{c + 1}): במקור '{obs[r][c]}', בשחזור '{got[r][c]}'."
            for r in range(len(obs)) for c in range(len(obs[r])) if obs[r][c] != got[r][c]]


def render(t: TableSpec) -> tuple[str, bytes, dict]:
    n_c = len(t.rows[0])
    fig, ax = new_figure(min(7.5, 1.35 * n_c + 0.6), 0.45 * len(t.rows) + 0.4)
    ax.axis("off")
    def wrap(text: str) -> str:
        if len(text) <= 14 or " " not in text:
            return text
        mid = len(text) // 2
        cut = min((i for i, ch in enumerate(text) if ch == " "), key=lambda i: abs(i - mid))
        return text[:cut] + "\n" + text[cut + 1:]

    data = [[visual(wrap(c.text)) for c in (reversed(row) if t.rtl else row)] for row in t.rows]
    tbl = ax.table(cellText=data, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 2.1 if any("\n" in x for row in data for x in row) else 1.5)
    for (r, c), cell in tbl.get_celld().items():
        src_c = (n_c - 1 - c) if t.rtl else c
        if r < t.header_rows or src_c < t.header_columns:
            cell.set_text_props(fontweight="bold")
        if t.rows[r][src_c].fill:
            cell.set_facecolor("#808080")
    svg, png = export(fig)
    return svg, png, {"rows": len(t.rows), "cols": n_c, "cells": cells(t)}


def semantic_cells(t) -> list[dict]:
    """header_cell <-> data_cell mapping (not only row/column indices): each data cell with its row and column headers."""
    out = []
    hr, hc = t.header_rows, t.header_columns
    for r, row in enumerate(t.rows):
        for c, cell in enumerate(row):
            if r < hr or c < hc:
                continue
            col_head = " / ".join(norm(t.rows[i][c].text) for i in range(hr)) if hr else ""
            row_head = " / ".join(norm(t.rows[r][j].text) for j in range(hc)) if hc else ""
            out.append({"row_header": row_head, "column_header": col_head, "text": norm(cell.text), "value": cell.value,
                        "row": r, "col": c})
    return out


FREQ_WORDS = re.compile(r"שכיחות|מספר\s+ה|כמות|frequency|count", re.I)


def semantic_model(t) -> dict:
    """table_type + confidence + a semantic view. A value/category <-> frequency table is mapped as such; any other
    table keeps the generic header<->data mapping (no over-interpretation)."""
    cells = semantic_cells(t)
    rows = [[norm(c.text) for c in r] for r in t.rows]
    numeric = lambda x: bool(re.fullmatch(r"-?\d+(?:\.\d+)?", x.replace(",", "")))  # noqa: E731
    # frequency by ROW: one header row labelled like "שכיחות / מספר ה..." whose data cells are all numbers
    if t.header_columns >= 1:
        for _r, row in enumerate(rows):
            if FREQ_WORDS.search(row[0]) and all(numeric(x) for x in row[1:]) and len(row) > 2:
                keys_row = next((rr for rr in rows if rr is not row), None)
                if keys_row is not None:
                    model = [{"value": keys_row[c], "frequency": float(row[c])} for c in range(1, len(row))]
                    return {"table_type": "frequency", "confidence": 0.9, "frequency_label": row[0], "model": model, "cells": cells}
    # frequency by COLUMN
    if t.header_rows >= 1:
        head = rows[0]
        for c, h in enumerate(head):
            if FREQ_WORDS.search(h) and all(numeric(r[c]) for r in rows[1:]) and len(rows) > 2:
                key_c = 0 if c != 0 else 1
                model = [{"value": r[key_c], "frequency": float(r[c])} for r in rows[1:]]
                return {"table_type": "frequency", "confidence": 0.9, "frequency_label": h, "model": model, "cells": cells}
    return {"table_type": "generic", "confidence": 0.6, "model": [], "cells": cells}
