"""FunctionDependencyGraph (f', g = f*f', h = -g ...) verified symbolically, and piecewise PROCESS models (rule changes at an
event, e.g. growth until equality then decay)."""
from __future__ import annotations

import sympy

x, t = sympy.symbols("x t", real=True)
RELATIONS = {"DERIVATIVE_OF", "ANTIDERIVATIVE_OF", "NEGATIVE_OF", "VERTICAL_SCALE_OF", "TRANSLATION_OF", "COMPOSITION_OF",
             "MULTIPLICATIVE_TRANSFORM", "PARAMETERIZED_TRANSFORM"}


class FunctionDependencyGraph:
    def __init__(self) -> None:
        self.funcs: dict[str, sympy.Expr | None] = {}
        self.edges: list[tuple[str, str, str, dict]] = []

    def add(self, name, expr=None):
        self.funcs[name] = expr

    def relate(self, child, relation, parent, **params):
        assert relation in RELATIONS
        self.edges.append((child, relation, parent, params))

    def derive(self, child) -> sympy.Expr | None:
        """Compute a function from its relation when it is not given explicitly."""
        for c, rel, p, prm in self.edges:
            if c == child and self.funcs.get(p) is not None:
                f = self.funcs[p]
                return {"DERIVATIVE_OF": lambda: sympy.diff(f, x), "NEGATIVE_OF": lambda: -f,
                        "VERTICAL_SCALE_OF": lambda: prm.get("k", 1) * f, "TRANSLATION_OF": lambda: f.subs(x, x - prm.get("dx", 0)) + prm.get("dy", 0),
                        "MULTIPLICATIVE_TRANSFORM": lambda: prm["by"] * f, "ANTIDERIVATIVE_OF": lambda: sympy.integrate(f, x)}.get(rel, lambda: None)()
        return None

    def check(self) -> list[str]:
        """Every stated relation between two KNOWN functions is verified; violations are reported, never repaired."""
        out = []
        for c, rel, p, prm in self.edges:
            fc, fp = self.funcs.get(c), self.funcs.get(p)
            if fc is None or fp is None:
                continue
            want = self.derive(c) if rel != "ANTIDERIVATIVE_OF" else None
            ok = sympy.simplify(sympy.diff(fc, x) - fp) == 0 if rel == "ANTIDERIVATIVE_OF" else (want is not None and sympy.simplify(fc - want) == 0)
            if not ok:
                out.append(f"FUNCTION_RELATION_CONFLICT: {c} אינה {rel} של {p}.")
        return out


def process(phases: list[dict], t0: float = 0.0) -> list[dict]:
    """Piecewise process: phases [{"rule": 'A0*1.05**t' | callable-free expr in t with 'y0', "until": expr/event}].
    Each phase starts from the value where the previous ended (continuity); returns [{t0, t1, expr}]."""
    out, start, y0 = [], t0, None
    for ph in phases:
        rule = sympy.sympify(ph["rule"], locals={"t": t, "y0": sympy.Symbol("y0")})
        if y0 is not None:
            rule = rule.subs(sympy.Symbol("y0"), y0)
            rule = rule.subs(t, t - start)
        end = ph.get("until")
        t1 = float(end) if isinstance(end, (int, float)) else (float(sympy.nsolve(sympy.sympify(end, locals={"t": t}), t, start + 1)) if end else None)
        out.append({"t0": start, "t1": t1, "expr": rule})
        if t1 is not None:
            y0 = rule.subs(t, t1)
            start = t1
    return out
