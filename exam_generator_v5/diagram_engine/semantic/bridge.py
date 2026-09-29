"""PRODUCTION bridge: typed SemanticSpec (from PASS 2 or the teacher) -> semantic engines -> (a) BUILD the drawing when the
proposal has none, (b) VERIFY the proposal's drawing when it has one. Conflicts are critical; unsupported input goes to the
teacher. Nothing is invented."""
from __future__ import annotations

import math
import re

import sympy

from ..schemas import DiagramSpec
from . import complex_numbers as cx
from . import conics as cn
from . import expression_ast as ea
from . import functions as fn
from . import space3d as s3
from . import vectors as vx

TOL = 1e-6
EQ_OK = re.compile(r"^[0-9A-Za-z+\-*/^().=\s]+$")


def _safe_eq(text: str) -> sympy.Eq:
    """Whitelisted canonical-conic parser: x, y and SINGLE-LETTER parameters (a, b, R, p ... declared positive, as in
    school canonical forms). No function names, no attribute access, one '='."""
    s = (text or "").replace("−", "-").replace(" ", "").replace("{", "(").replace("}", ")").replace("\\", "")
    if not EQ_OK.fullmatch(s) or s.count("=") != 1 or re.search(r"sin|cos|tan|log|ln|sqrt|exp|import|lambda", s):
        raise ValueError(f"משוואה לא נתמכת: {text}")
    s = re.sub(r"(?<=[0-9A-Za-z)])(?=[A-Za-z(])", "*", s).replace("^", "**")      # "2px" = 2*p*x (single-letter parameters)
    params = sorted(set(re.findall(r"[A-Za-z]", s)) - {"x", "y"})
    loc = {"x": cn.x, "y": cn.y, **{p_: sympy.Symbol(p_, positive=True) for p_ in params}}
    lhs, rhs = s.split("=")
    return sympy.Eq(sympy.sympify(lhs, locals=loc), sympy.sympify(rhs, locals=loc))


def conic_from_text(eq: str) -> dict:
    """Canonical conic (numeric OR symbolic). Symbolic parameters are KEPT (never replaced by guessed numbers)."""
    con = cn.from_equation(_safe_eq(eq))
    free = set()
    for key in ("a", "b", "p", "h", "k"):
        v = con.get(key)
        if isinstance(v, sympy.Expr):
            free |= v.free_symbols
    con["parameters"] = sorted(str(f) for f in free)
    con["symbolic"] = bool(free)
    return con


def _plane_eq(text: str):
    s = (text or "").replace("−", "-").replace(" ", "")
    if not re.fullmatch(r"[0-9xyz+\-*/.()=]+", s) or s.count("=") != 1:
        raise ValueError(f"משוואת מישור לא נתמכת: {text}")
    s = re.sub(r"(\d)(?=[xyz(])", r"\1*", s)
    X, Y, Z = sympy.symbols("x y z")
    lhs, rhs = s.split("=")
    e = sympy.expand(sympy.sympify(lhs, locals={"x": X, "y": Y, "z": Z}) - sympy.sympify(rhs, locals={"x": X, "y": Y, "z": Z}))
    n = [e.coeff(v) for v in (X, Y, Z)]
    d = -e.subs({X: 0, Y: 0, Z: 0})
    return s3.plane(n, d)


def apply(spec: DiagramSpec) -> dict:
    """Mutates `spec` only to ADD a missing drawing built from the semantics. Returns
    {"built": [...], "verified": [...], "conflicts": [...], "unsupported": [...], "formulas": [...]}"""
    out = {"built": [], "verified": [], "conflicts": [], "unsupported": [], "formulas": [], "symbolic": []}
    sem = spec.semantics
    if sem is None:
        return out
    # ---- complex numbers -> Gauss-plane points / polygon
    if sem.complex_plane is not None:
        try:
            cp = sem.complex_plane
            zs, labels = [], []
            if cp.roots_of is not None:
                zs = cx.roots(cp.roots_of.n, cx.parse(cp.roots_of.w))
                labels = [f"z{k + 1}" for k in range(len(zs))]
            symbolic = []
            for it in cp.numbers:
                if it.polar:
                    r_, t_ = cx.parse_polar(it.polar)
                    if (r_.free_symbols | t_.free_symbols):
                        symbolic.append({"label": it.label, "modulus": str(r_), "argument": str(t_)})
                        continue
                    z = r_ * sympy.exp(sympy.I * t_)
                else:
                    z = cx.parse(it.value) if it.value else it.r * sympy.exp(sympy.I * sympy.rad(it.theta_deg))
                zs.append(z)
                labels.append(it.label)
            if symbolic:
                out["symbolic"] += [{"complex": s_} for s_ in symbolic]
                if not zs and (spec.geometry is None or not spec.geometry.points):
                    out["unsupported"].append("complex_plane: מודול/ארגומנט סמליים — אין מיקום מספרי בלי להמציא ערכים")
                    raise StopIteration
            pts = {l: cx.to_point(z) for l, z in zip(labels, zs)}
            if spec.geometry is None or not spec.geometry.points:
                built = DiagramSpec.model_validate(cx.polygon_spec(zs, labels, closed=cp.polygon))
                spec.geometry, spec.diagram_type = built.geometry, "geometry"
                spec.subtype = spec.subtype or "analytic_geometry"
                out["built"].append("complex_plane")
            else:
                P = {p.id: (p.x, p.y) for p in spec.geometry.points}
                for l, (x, y) in pts.items():
                    if l in P and (abs(P[l][0] - x) > 1e-3 * max(1, abs(x)) or abs(P[l][1] - y) > 1e-3 * max(1, abs(y))):
                        out["conflicts"].append(f"COMPLEX_POINT_CONFLICT: {l} צריך להיות ({x:.4g}, {y:.4g}) לפי המספר המרוכב, בשרטוט {P[l]}.")
                out["verified"].append("complex_plane")
        except StopIteration:
            pass
        except Exception as exc:
            out["unsupported"].append(f"complex_plane: {exc}")
    # ---- conics
    for c in sem.conics:
        try:
            con = conic_from_text(c.equation)
            if c.claimed_kind and c.claimed_kind != con["kind"]:
                out["conflicts"].append(f"CONIC_KIND_CONFLICT: המשוואה {c.equation} היא {con['kind']}, לא {c.claimed_kind}.")
            if con["symbolic"]:
                # symbolic canonical form: represented and preserved; a numeric drawing would need invented values
                out["symbolic"].append({"conic": con["kind"], "equation": c.equation, "parameters": con["parameters"]})
                if spec.graph is None or not spec.graph.curves:
                    out["unsupported"].append(f"conic {c.equation}: פרמטרים סמליים ({', '.join(con['parameters'])}) — "
                                              "אין שרטוט מספרי בלי להמציא ערכים")
                continue
            if spec.graph is None or not spec.graph.curves:
                built = DiagramSpec.model_validate(cn.graph_spec(con))
                spec.graph, spec.diagram_type = built.graph, "graph"
                spec.subtype = spec.subtype or "formula_graph"
                out["built"].append(f"conic:{con['kind']}")
            else:
                foci = [(float(a), float(b)) for a, b in con["foci"]]
                for p in spec.graph.points:
                    if p.name.upper().startswith("F") and not any(math.hypot(p.x - a, p.y - b) < 1e-3 * max(1, abs(a) + abs(b)) for a, b in foci):
                        out["conflicts"].append(f"CONIC_FOCUS_CONFLICT: המוקד {p.name}=({p.x:g},{p.y:g}) אינו מוקד של {c.equation}.")
                out["verified"].append(f"conic:{con['kind']}")
        except Exception as exc:
            out["unsupported"].append(f"conic {c.equation}: {exc}")
    # ---- vectors
    if sem.vectors is not None:
        try:
            V = vx.VectorSpace(points={p.id: sympy.Matrix([sympy.nsimplify(p.x), sympy.nsimplify(p.y), sympy.nsimplify(p.z)])
                                       for p in sem.vectors.points})
            for v in sem.vectors.vectors:
                V.define(v.name, v.from_point, v.to_point)
            _claims(out, sem.vectors.claims, V, None)
            out["verified"].append("vectors")
        except Exception as exc:
            out["unsupported"].append(f"vectors: {exc}")
    # ---- analytic 3D
    if sem.space3d is not None:
        try:
            P3 = {p.id: [sympy.nsimplify(p.x), sympy.nsimplify(p.y), sympy.nsimplify(p.z)] for p in sem.space3d.points}
            lines = {l.id: s3.line(P3[l.through[0]], sympy.Matrix(P3[l.through[1]]) - sympy.Matrix(P3[l.through[0]])) for l in sem.space3d.lines}
            planes = {pl.id: (_plane_eq(pl.equation) if pl.equation else s3.plane_from_points(*[P3[k] for k in pl.through]))
                      for pl in sem.space3d.planes}
            _claims(out, sem.space3d.claims, None, (P3, lines, planes))
            out["verified"].append("space3d")
        except Exception as exc:
            out["unsupported"].append(f"space3d: {exc}")
    # ---- function relations (on the curves of the graph)
    if sem.function_relations:
        try:
            from .. import safe_math as sm
            G = fn.FunctionDependencyGraph()
            curves = {c.id: c for c in (spec.graph.curves if spec.graph else [])}
            if spec.multi_graph is not None:
                for o in spec.multi_graph.options:
                    if o.formula is not None:
                        curves.update({c.id: c for c in o.formula.curves})
            for cid, c in curves.items():
                G.add(cid, sm.parse_expression(c.expression).subs(sm.X, fn.x) if c.expression else None)
            for r in sem.function_relations:
                prm = {k: v for k, v in (("k", r.k), ("dx", r.dx), ("dy", r.dy), ("by", r.k)) if v is not None}
                G.relate(r.child, r.relation, r.parent, **prm)
            out["conflicts"] += G.check()
            out["verified"].append("function_relations")
        except Exception as exc:
            out["unsupported"].append(f"function_relations: {exc}")
    # ---- formulas -> ExpressionAST
    for f in sem.formulas:
        out["formulas"].append(formula_status(f.latex, f.id))
    return out


def formula_status(latex: str, fid: str = "") -> dict:
    from ..formula_pipeline import analyse
    return {"id": fid, **analyse(latex)}


def _claims(out, claims, V, space):
    for c in claims:
        ok = None
        if V is not None:
            a = V.value(c.refs[0]) if c.refs else None
            b = V.value(c.refs[1]) if len(c.refs) > 1 else None
            if c.kind == "parallel":
                ok = vx.parallel(a, b)
            elif c.kind == "perpendicular":
                ok = sympy.simplify(a.dot(b)) == 0
            elif c.kind == "ratio" and c.value is not None:
                ok = sympy.simplify(a - sympy.nsimplify(c.value) * b) == sympy.zeros(len(a), 1)
            elif c.kind == "combination":
                comb = V.combination(dict(zip(c.refs[1:], c.coeffs)))
                ok = sympy.simplify(a - comb) == sympy.zeros(len(a), 1)
        elif space is not None:
            P3, lines, planes = space
            if c.kind == "on_plane":
                pl = planes[c.refs[1]]
                ok = sympy.simplify(pl["n"].dot(sympy.Matrix(P3[c.refs[0]])) - pl["d"]) == 0
            elif c.kind == "angle_lines":
                ok = abs(float(sympy.deg(s3.angle_lines(lines[c.refs[0]], lines[c.refs[1]]))) - c.value) < 1e-3
            elif c.kind == "angle_line_plane":
                ok = abs(float(sympy.deg(s3.angle_line_plane(lines[c.refs[0]], planes[c.refs[1]]))) - c.value) < 1e-3
            elif c.kind == "angle_planes":
                ok = abs(float(sympy.deg(s3.angle_planes(planes[c.refs[0]], planes[c.refs[1]]))) - c.value) < 1e-3
            elif c.kind == "distance_point_plane":
                ok = abs(float(s3.distance_point_plane(P3[c.refs[0]], planes[c.refs[1]])) - c.value) < 1e-6
        if ok is None:
            out["unsupported"].append(f"claim {c.kind} {c.refs}")
        elif not ok:
            out["conflicts"].append(f"SEMANTIC_CLAIM_CONFLICT: {c.kind}({', '.join(c.refs)}) אינו מתקיים לפי הקואורדינטות.")


_unused = (ea,)
