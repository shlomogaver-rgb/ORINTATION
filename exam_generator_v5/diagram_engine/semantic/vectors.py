"""Vectors: ONE entity with three faces - symbol (u), geometric edge (AB) and coordinates (B - A)."""
from __future__ import annotations

from dataclasses import dataclass, field

import sympy


@dataclass
class VectorSpace:
    points: dict = field(default_factory=dict)          # name -> sympy Matrix (2D/3D)
    symbols: dict = field(default_factory=dict)         # 'u' -> ('A', 'B')

    def define(self, name: str, a: str, b: str) -> None:
        self.symbols[name] = (a, b)

    def edge(self, a: str, b: str) -> sympy.Matrix:
        return self.points[b] - self.points[a]

    def value(self, name_or_edge) -> sympy.Matrix:
        if isinstance(name_or_edge, str) and name_or_edge in self.symbols:
            return self.edge(*self.symbols[name_or_edge])
        a, b = name_or_edge
        return self.edge(a, b)

    def combination(self, coeffs: dict) -> sympy.Matrix:
        return sum((sympy.nsimplify(c) * self.value(n) for n, c in coeffs.items()), sympy.zeros(len(next(iter(self.points.values()))), 1))

    def express(self, a: str, b: str, basis: list[str]) -> dict:
        """Coefficients of edge AB in the symbolic basis (u, v, w) - the geometric <-> symbolic link."""
        cs = sympy.symbols(f"c0:{len(basis)}")
        sol = sympy.solve(list(sum((c * self.value(n) for c, n in zip(cs, basis)), sympy.zeros(len(self.edge(a, b)), 1)) - self.edge(a, b)), cs, dict=True)
        return {n: sympy.nsimplify(sol[0][c]) for c, n in zip(cs, basis)} if sol else {}


def parallel(u, v) -> bool:
    return sympy.Matrix.hstack(u, v).rank() < 2


def angle(u, v):
    return sympy.acos(sympy.simplify(u.dot(v) / (u.norm() * v.norm())))
