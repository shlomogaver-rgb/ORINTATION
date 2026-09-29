"""Complex numbers: z = x + iy <-> Point2D(x, y) in the Gauss plane; polar form; De Moivre roots -> polygon."""
from __future__ import annotations

import sympy

I = sympy.I


def parse(z: str) -> sympy.Expr:
    """Safe parse of a complex literal ('3+4i', '2(1-i)', 'i^3'): whitelist of characters, implicit products made explicit."""
    import re
    s = (z or "").replace(" ", "").replace("−", "-").replace("·", "*")
    if not re.fullmatch(r"[0-9i+\-*/^().]+", s):
        raise ValueError(f"ביטוי מרוכב לא תקין: {z}")
    s = re.sub(r"(\d|\))(?=[i(])", r"\1*", s)
    s = re.sub(r"i(?=[\d(])", "i*", s).replace("^", "**").replace("i", "I")
    return sympy.sympify(s, locals={"I": I})


def to_point(z) -> tuple[float, float]:
    z = complex(sympy.N(z))
    return (z.real, z.imag)


def polar(z) -> tuple[sympy.Expr, sympy.Expr]:
    return sympy.Abs(z), sympy.arg(z)


def roots(n: int, w) -> list[sympy.Expr]:
    """All n solutions of z^n = w (De Moivre), ordered by argument."""
    r, t = sympy.Abs(w), sympy.arg(w)
    return [sympy.root(r, n) * sympy.exp(I * (t + 2 * sympy.pi * k) / n) for k in range(n)]


def polygon_spec(zs, labels: list[str] | None = None, closed: bool = True) -> dict:
    """Gauss-plane polygon as a GeometrySpec dict (fixed exact points, straight edges, coordinate axes Re/Im)."""
    pts = [to_point(z) for z in zs]
    labels = labels or [f"Z{k + 1}" for k in range(len(pts))]
    segs = [{"a": labels[k], "b": labels[(k + 1) % len(pts)]} for k in range(len(pts) if closed else len(pts) - 1)]
    return {"diagram_type": "geometry", "subtype": "analytic_geometry", "confidence": 1.0, "labels": [],
            "geometry": {"points": [{"id": l, "x": round(x, 12), "y": round(y, 12), "fixed": True, "source": "computed"} for l, (x, y) in zip(labels, pts)],
                         "segments": segs, "coordinate_axes": True}}


GREEK = ("theta", "alpha", "beta", "gamma", "phi", "varphi", "psi", "omega", "delta")


def parse_polar(text: str) -> tuple[sympy.Expr, sympy.Expr]:
    """'r(\\cos\\theta+i\\sin\\theta)' / 'r(cos(theta)+i sin(theta))' / '2(cos 60 + i sin 60)' -> (modulus, argument),
    both kept SYMBOLIC when they are parameters (never forced to floats)."""
    import re
    s = (text or "").replace("\\", "").replace("{", "(").replace("}", ")").replace(" ", "").replace("\\left", "").replace("\\right", "")
    s = s.replace("left", "").replace("right", "").replace("cdot", "")
    m = re.fullmatch(r"(.*?)\(?cos\(?([A-Za-z0-9.+\-*/^]+?)\)?\+i\*?sin\(?([A-Za-z0-9.+\-*/^]+?)\)?\)?", s)
    if not m or m.group(2) != m.group(3):
        raise ValueError(f"צורה קוטבית לא מזוהה: {text}")
    r_txt = m.group(1).rstrip("(").rstrip("*") or "1"

    def sym(t: str) -> sympy.Expr:
        if not re.fullmatch(r"[A-Za-z0-9.+\-*/^()]+", t) or re.search(r"[A-Za-z]{2,}", t) and t not in GREEK:
            raise ValueError(f"ביטוי לא נתמך: {t}")
        loc = {g: sympy.Symbol(g, real=True) for g in GREEK}
        loc.update({ch: sympy.Symbol(ch, positive=True) for ch in set(re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", t))})
        return sympy.sympify(t.replace("^", "**"), locals=loc)
    return sym(r_txt), sym(m.group(2))
