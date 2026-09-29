"""Graphs: explicit functions from the question text take priority over anything read from pixels.

Pixel-level curve extraction is intentionally NOT done: without an explicit formula the curve stays an
'image' source with capped confidence, which forces teacher review (see decision.py)."""
from __future__ import annotations

import re

import sympy

from .. import safe_math as sm
from ..schemas import GraphCurve, GraphSpec

FUNC_RE = re.compile(r"(?:(?<![A-Za-z])([fghp])\s*\(\s*x\s*\)|(?<![A-Za-z])(y))\s*=\s*([^=\n]+)")
_STOP = re.compile(r"(?:[,;]\s|\s[,;]|\$|[\u0590-\u05FF]|\.\s|\.$|\s+ו|\s+and\s)")


def functions_from_text(text: str) -> list[tuple[str, str, sympy.Expr]]:
    """[(name, expression_text, sympy_expr)] for every explicit function in the question text."""
    found: list[tuple[str, str, sympy.Expr]] = []
    chunks = re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", text or "", flags=re.S)
    candidates = [a or b for a, b in chunks] + [re.sub(r"\$[^$]*\$", " ", text or "")]
    seen: set[str] = set()
    for chunk in candidates:
        for m in FUNC_RE.finditer(chunk):
            name = m.group(1) or "y"
            raw = m.group(3)
            cut = _STOP.search(raw)
            expr_text = (raw[:cut.start()] if cut else raw).strip().rstrip(".")
            if not expr_text or "x" not in expr_text:
                continue
            try:
                expr = sm.parse_expression(expr_text)
            except Exception:
                continue
            key = f"{name}:{sympy.srepr(expr)}"
            if key not in seen:
                seen.add(key)
                found.append((name, expr_text, expr))
    return found


def merge_text(graph: GraphSpec, text: str, observed_curves: int | None) -> list[str]:
    """Replace/confirm curve expressions with the ones stated in the question. Returns warnings (Hebrew)."""
    warnings: list[str] = []
    funcs = functions_from_text(text)
    if not funcs:
        return warnings
    lo, hi = graph.axes.x_min, graph.axes.x_max
    by_name = {n: (t, e) for n, t, e in funcs}
    for curve in graph.curves:
        match = None
        key = (curve.label or curve.id or "").strip()
        key = re.sub(r"\(x\)$", "", key).strip()
        if key in by_name:
            match = by_name[key]
        elif len(graph.curves) == 1 and len(funcs) == 1:
            match = (funcs[0][1], funcs[0][2])
        if match is None or curve.pieces:
            continue
        text_expr, text_sym = match
        try:
            same = bool(curve.expression) and sm.equivalent(sm.parse_expression(curve.expression), text_sym, lo, hi)
        except Exception:
            same = False
        if curve.expression and not same:
            warnings.append(f"הביטוי שזוהה בשרטוט ({curve.expression}) שונה מנוסח השאלה — נעשה שימוש בנוסח השאלה ({text_expr}).")
        curve.expression = text_expr
        curve.source = "text"
        curve.confidence = max(curve.confidence, 0.97)
    if not graph.curves and (observed_curves or 0) >= 1 and len(funcs) == 1:
        name, text_expr, _ = funcs[0]
        graph.curves.append(GraphCurve(id=name, label=f"{name}(x)" if name != "y" else "", expression=text_expr,
                                       source="text", confidence=0.97))
        warnings.append("הפונקציה נלקחה מנוסח השאלה.")
    return warnings


