"""ExpressionAST: canonical, typed tree of a formula (semantic source of truth) -> LaTeX -> Word OMML."""
from __future__ import annotations

from dataclasses import dataclass, field

import sympy


@dataclass
class Node:
    kind: str
    value: str = ""
    children: list = field(default_factory=list)


def from_sympy(e) -> Node:
    if e.is_Integer or e.is_Float:
        return Node("Number", str(e))
    if e.is_Rational:
        return Node("Fraction", children=[Node("Number", str(e.p)), Node("Number", str(e.q))])
    if e == sympy.I:
        return Node("ComplexNumber", "i")
    if e.is_Symbol:
        return Node("Symbol", str(e))
    if isinstance(e, sympy.Add):
        return Node("Sum", children=[from_sympy(a) for a in e.args])
    if isinstance(e, sympy.Mul):
        num, den = e.as_numer_denom()
        if den != 1:
            return Node("Fraction", children=[from_sympy(num), from_sympy(den)])
        return Node("Product", children=[from_sympy(a) for a in e.args])
    if isinstance(e, sympy.Pow):
        if e.exp == sympy.Rational(1, 2):
            return Node("Root", "2", [from_sympy(e.base)])
        if e.base == sympy.E:
            return Node("Exp", children=[from_sympy(e.exp)])
        return Node("Power", children=[from_sympy(e.base), from_sympy(e.exp)])
    if isinstance(e, sympy.Abs):
        return Node("AbsoluteValue", children=[from_sympy(e.args[0])])
    if isinstance(e, sympy.exp):
        return Node("Exp", children=[from_sympy(e.args[0])])
    if isinstance(e, sympy.log):
        return Node("Log", children=[from_sympy(a) for a in e.args])
    if isinstance(e, (sympy.sin, sympy.cos, sympy.tan)):
        return Node("TrigFunction", type(e).__name__, [from_sympy(e.args[0])])
    if isinstance(e, sympy.Derivative):
        return Node("Derivative", children=[from_sympy(e.expr), *[Node("Symbol", str(v)) for v, _ in e.variable_count]])
    if isinstance(e, sympy.Integral):
        return Node("Integral", children=[from_sympy(e.function), *[Node("Symbol", str(l[0])) for l in e.limits]])
    if isinstance(e, sympy.Eq):
        return Node("Equation", children=[from_sympy(e.lhs), from_sympy(e.rhs)])
    if isinstance(e, sympy.core.relational.Relational):
        return Node("Inequality", e.rel_op, [from_sympy(e.lhs), from_sympy(e.rhs)])
    if isinstance(e, sympy.Piecewise):
        return Node("PiecewiseExpression", children=[Node("Case", children=[from_sympy(ex), from_sympy(c)]) for ex, c in e.args])
    if isinstance(e, sympy.Function) or isinstance(e, sympy.core.function.AppliedUndef):
        return Node("FunctionApplication", str(e.func), [from_sympy(a) for a in e.args])
    return Node("Unknown", str(e))


def to_sympy_latex(e) -> str:
    return sympy.latex(e)


def validate(ast: Node) -> list[str]:
    """Structural checks (no Unknown nodes; fractions have 2 children...)."""
    out = []
    def walk(n):
        if n.kind == "Unknown":
            out.append(f"צומת לא מזוהה בנוסחה: {n.value}")
        if n.kind == "Fraction" and len(n.children) != 2:
            out.append("שבר פגום")
        for c in n.children:
            walk(c)
    walk(ast)
    return out


def to_omml(e) -> str:
    """Word OMML through the existing (tested) LaTeX -> OMML path of the document generator."""
    import exam_core as core
    return core.latex_to_omml(to_sympy_latex(e)) if hasattr(core, "latex_to_omml") else ""
