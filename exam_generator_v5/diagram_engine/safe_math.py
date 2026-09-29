"""Safe parsing of AI/teacher supplied mathematical expressions (no eval of raw text) + real-valued evaluation.

- whitelist of identifiers and characters, expression-size limits, huge-power guard BEFORE any simplification
- odd roots are real: (-8)^(1/3) = -2, (-8)^(2/3) = 4, cbrt(x) / cuberoot(x) / \\sqrt[3]{x}
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

import numpy as np
import sympy
from sympy.parsing.sympy_parser import (
    convert_xor, implicit_multiplication_application, parse_expr, standard_transformations,
)

X = sympy.Symbol("x", real=True)
ALLOWED_IDENTIFIERS = {
    "x", "sin", "cos", "tan", "cot", "asin", "acos", "atan", "arcsin", "arccos", "arctan",
    "sqrt", "cbrt", "cuberoot", "root", "log", "ln", "exp", "abs", "Abs", "pi", "e", "E",
}
# expression-tree whitelist (checked AFTER parsing: nothing else can survive)
_ALLOWED_FUNCS = (sympy.sin, sympy.cos, sympy.tan, sympy.cot, sympy.asin, sympy.acos, sympy.atan, sympy.log, sympy.exp,
                  sympy.Abs, sympy.sign, sympy.Piecewise, sympy.Min, sympy.Max)
MAX_LEN = 300


class ExpressionError(ValueError):
    pass


# ---- dynamic safe symbol table (parameters declared in the question text only) ----
import contextvars
from contextlib import contextmanager

_SYMBOLS: contextvars.ContextVar[dict | None] = contextvars.ContextVar("declared_symbols", default=None)
_VALUES: contextvars.ContextVar[dict | None] = contextvars.ContextVar("layout_values", default=None)
PARAM_NAME = re.compile(r"[A-Za-z]")


@contextmanager
def symbol_context(symbols: dict | None, values: dict | None = None):
    """Activate declared parameters (e.g. {"R": {"positive": True}}) and their layout values for drawing."""
    ok = {k: v for k, v in (symbols or {}).items() if PARAM_NAME.fullmatch(k) and k not in ("x", "e")}
    t1, t2 = _SYMBOLS.set(ok), _VALUES.set(dict(values or {}))
    try:
        yield
    finally:
        _SYMBOLS.reset(t1)
        _VALUES.reset(t2)


def declared_symbol(name: str) -> sympy.Symbol:
    info = (_SYMBOLS.get() or {}).get(name, {})
    kw = {"real": True}
    if info.get("positive"):
        kw["positive"] = True
    elif info.get("negative"):
        kw["negative"] = True
    if info.get("nonzero"):
        kw["nonzero"] = True
    return sympy.Symbol(name, **kw)


# ------------------------------------------------------------------ LaTeX -> calculator syntax
def _read_group(s: str, i: int, open_ch: str = "{", close_ch: str = "}") -> tuple[str, int]:
    if i >= len(s) or s[i] != open_ch:
        raise ExpressionError("expected group")
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_ch:
            depth += 1
        elif s[j] == close_ch:
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    raise ExpressionError("סוגריים לא מאוזנים")


def _latex_structures(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s.startswith("\\frac", i):
            j = i + 5
            while j < len(s) and s[j] == " ":
                j += 1
            num, j = _read_group(s, j)
            while j < len(s) and s[j] == " ":
                j += 1
            den, j = _read_group(s, j)
            out.append(f"(({_latex_structures(num)})/({_latex_structures(den)}))")
            i = j
        elif s.startswith("\\sqrt", i):
            j = i + 5
            root = None
            if j < len(s) and s[j] == "[":
                root, j = _read_group(s, j, "[", "]")
            body, j = _read_group(s, j)
            body = _latex_structures(body)
            if root is None:
                out.append(f"sqrt({body})")
            elif root.strip() == "3":
                out.append(f"cbrt({body})")
            else:
                out.append(f"root({body},{_latex_structures(root)})")
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _convert_log_bases(s: str) -> str:
    pattern = re.compile(r"log_\(?([0-9.]+|[a-z])\)?\s*\(")
    while True:
        m = pattern.search(s)
        if not m:
            return s
        base = m.group(1)
        arg, end = _read_group(s, m.end() - 1, "(", ")")
        s = s[:m.start()] + f"(ln({arg})/ln({base}))" + s[end:]


def latex_to_plain(expr: str) -> str:
    s = (expr or "").strip().strip("$").strip()
    s = re.sub(r"^\s*(?:y|[fghp]\s*\(\s*x\s*\))\s*=", "", s)
    for token in ("\\left", "\\right", "\\displaystyle"):
        s = s.replace(token, "")
    for sp in ("\\,", "\\;", "\\!", "\\:", "\\ ", "~"):
        s = s.replace(sp, " ")
    s = s.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = _latex_structures(s)
    s = re.sub(r"\\(arcsin|arccos|arctan|sin|cos|tan|cot|ln|log|exp|pi)(?![a-z])", r" \1 ", s)
    s = s.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    s = re.sub(r"\|([^|]+)\|", r"abs(\1)", s)
    s = s.replace("−", "-").replace("·", "*").replace("×", "*").replace("π", "pi").replace("√", "sqrt").replace("∛", "cbrt")
    s = s.replace("²", "^2").replace("³", "^3").replace("⁴", "^4")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("log _", "log_").replace(" _", "_")
    return _convert_log_bases(s.replace("log_ ", "log_"))


# ------------------------------------------------------------------ guards
def _const_float(node: Any) -> float:
    if node.is_Number:
        return float(node)
    if node is sympy.pi:
        return math.pi
    if node is sympy.E:
        return math.e
    if node.is_Add:
        return sum(_const_float(a) for a in node.args)
    if node.is_Mul:
        r = 1.0
        for a in node.args:
            r *= _const_float(a)
        return r
    if node.is_Pow:
        base, exp = _const_float(node.base), _const_float(node.exp)
        if abs(exp) > 100:
            raise ExpressionError("חזקה גדולה מדי")
        try:
            return float(abs(base) ** exp)
        except (OverflowError, ZeroDivisionError):
            raise ExpressionError("חזקה גדולה מדי") from None
    return 1.0


def _check_exponents(expr: Any) -> None:
    for node in sympy.preorder_traversal(expr):
        if getattr(node, "is_Pow", False) and not node.exp.free_symbols:
            if abs(_const_float(node.exp)) > 100:
                raise ExpressionError("חזקה גדולה מדי")
    if sympy.count_ops(expr, visual=False) > 200:
        raise ExpressionError("הביטוי מורכב מדי")


def _real_root(a: Any, n: Any = 2) -> Any:
    return sympy.real_root(a, n)


def _real_odd_powers(expr: Any) -> Any:
    """x^(p/q) with odd q -> real_root(x, q)^p so that negative bases stay real."""
    def is_odd(node: Any) -> bool:
        if not isinstance(node, sympy.Pow) or node.exp.free_symbols:
            return False
        exp = node.exp
        if not isinstance(exp, sympy.Rational):
            try:
                exp = sympy.nsimplify(_const_float(exp), rational=True, tolerance=1e-12)
            except Exception:
                return False
        return isinstance(exp, sympy.Rational) and int(exp.q) > 1 and int(exp.q) % 2 == 1

    def to_root(node: Any) -> Any:
        exp = node.exp if isinstance(node.exp, sympy.Rational) else sympy.nsimplify(_const_float(node.exp), rational=True)
        return sympy.real_root(node.base, int(exp.q)) ** int(exp.p)

    return expr.replace(is_odd, to_root)


# ------------------------------------------------------------------ public API
_NAMES = sorted((n for n in ALLOWED_IDENTIFIERS if len(n) > 1), key=len, reverse=True)


def split_implicit(text: str, declared: dict | None = None) -> str:
    """'2ax' -> '2*a*x', 'abx' -> 'a*b*x', 'asqrt(x)' -> 'a*sqrt(x)', 'pir' -> 'pi*r'.
    A letter run is split ONLY into whitelisted names and declared single-letter symbols; anything else is left intact
    (and then rejected) - never guessed."""
    singles = {"x", "e"} | {k for k in (declared or {}) if len(k) == 1}

    def split(run: str) -> str | None:
        if run in ALLOWED_IDENTIFIERS or run in (declared or {}):
            return run
        out, i = [], 0
        while i < len(run):
            name = next((n for n in _NAMES if run.startswith(n, i)), None)
            if name:
                out.append(name)
                i += len(name)
            elif run[i] in singles:
                out.append(run[i])
                i += 1
            else:
                return None
        return "*".join(out)

    def repl(m: re.Match) -> str:
        res = split(m.group(0))
        return res if res is not None else m.group(0)

    return re.sub(r"[A-Za-z]+", repl, text)


def parse_expression(expr: str) -> sympy.Expr:
    text = latex_to_plain(expr)
    if not text:
        raise ExpressionError("ביטוי ריק")
    if len(text) > MAX_LEN:
        raise ExpressionError("הביטוי ארוך מדי")
    if "\\" in text:
        raise ExpressionError(f"פקודת LaTeX לא נתמכת: {expr}")
    if not re.fullmatch(r"[0-9A-Za-z\s.+\-*/^(),]*", text):
        raise ExpressionError(f"תווים לא חוקיים בביטוי: {expr}")
    declared = (_SYMBOLS.get() or {})
    text = split_implicit(text, declared)
    for ident in re.findall(r"[A-Za-z]+", text):
        if ident not in ALLOWED_IDENTIFIERS and ident not in declared:
            raise ExpressionError(f"שם לא מוכר בביטוי: {ident} (פרמטר שלא הוגדר בנוסח השאלה — לא מנחשים)")
    local = {
        "x": X, "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan, "cot": sympy.cot,
        "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
        "arcsin": sympy.asin, "arccos": sympy.acos, "arctan": sympy.atan,
        "sqrt": sympy.sqrt, "cbrt": lambda a, **_k: _real_root(a, 3), "cuberoot": lambda a, **_k: _real_root(a, 3),
        "root": lambda a, n=2, **_k: _real_root(a, n),
        "ln": sympy.log, "log": lambda a, b=10, **_k: sympy.log(a, b),
        "exp": sympy.exp, "abs": sympy.Abs, "Abs": sympy.Abs, "pi": sympy.pi, "e": sympy.E, "E": sympy.E,
    }
    for name in declared:
        local[name] = declared_symbol(name)
    global_dict: dict[str, Any] = {"__builtins__": {}}
    for name in ("Integer", "Float", "Rational", "Symbol", "Add", "Mul", "Pow"):
        global_dict[name] = getattr(sympy, name)
    transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
    try:
        parsed = parse_expr(text, local_dict=local, global_dict=global_dict, transformations=transformations, evaluate=False)
    except ExpressionError:
        raise
    except Exception as exc:
        raise ExpressionError(f"לא ניתן לפענח את הביטוי '{expr}': {exc}") from None
    if not isinstance(parsed, sympy.Basic):
        raise ExpressionError("הביטוי אינו ביטוי מתמטי")
    allowed_syms = {X} | {declared_symbol(n) for n in declared}
    if parsed.free_symbols - allowed_syms:
        raise ExpressionError("הביטוי מכיל משתנים שלא הוגדרו")
    _check_exponents(parsed)              # guard first: simplification of 9^(9^9) would never return
    parsed = _real_odd_powers(parsed)
    _check_exponents(parsed)
    validate_tree(parsed)
    return parsed


def validate_tree(expr: Any) -> None:
    """AST whitelist: only numbers, x, pi, E, +, *, ^ and whitelisted functions (incl. real_root's Piecewise/sign)."""
    for node in sympy.preorder_traversal(expr):
        if node.is_Symbol:
            if node != X and str(node) not in (_SYMBOLS.get() or {}):
                raise ExpressionError(f"סמל לא מורשה: {node}")
        elif node.is_Number or node in (sympy.pi, sympy.E, sympy.S.true, sympy.S.false) or node.is_Add or node.is_Mul \
                or node.is_Pow or isinstance(node, (sympy.Tuple, sympy.core.relational.Relational, sympy.logic.boolalg.BooleanFunction,
                                                   sympy.functions.elementary.piecewise.ExprCondPair)):
            continue
        elif isinstance(node, _ALLOWED_FUNCS):
            continue
        else:
            raise ExpressionError(f"פעולה לא מורשית בביטוי: {type(node).__name__}")


def numeric(expr: sympy.Expr) -> sympy.Expr:
    """Substitute layout values of declared parameters (drawing only). Missing value -> error (never guessed)."""
    params = [s for s in expr.free_symbols if s != X]
    if not params:
        return expr
    vals = (_VALUES.get() or {})
    missing = [str(s) for s in params if str(s) not in vals]
    if missing:
        raise ExpressionError(f"אין ערך שרטוט לפרמטר {', '.join(missing)}")
    return expr.subs({s: vals[str(s)] for s in params})


def to_numpy(expr: sympy.Expr) -> Callable[[np.ndarray], np.ndarray]:
    expr = numeric(expr)
    fn = sympy.lambdify(X, expr, modules=["numpy"])

    def evaluate(xs: np.ndarray) -> np.ndarray:
        xs = np.asarray(xs, dtype=float)
        with np.errstate(all="ignore"):
            try:
                ys = fn(xs)
            except (ZeroDivisionError, OverflowError, ValueError, TypeError):
                ys = np.array([_scalar(fn, v) for v in xs])
        ys = np.asarray(ys)
        if ys.shape != xs.shape:
            ys = np.full(xs.shape, complex(ys).real if np.iscomplexobj(ys) else float(ys))
        if np.iscomplexobj(ys):
            ys = np.where(np.abs(ys.imag) < 1e-9, ys.real, np.nan)
        return ys.astype(float)

    return evaluate


def _scalar(fn: Callable, v: float) -> float:
    try:
        r = complex(fn(v))
        return r.real if abs(r.imag) < 1e-9 else float("nan")
    except Exception:
        return float("nan")


def safe_function(expr: str) -> Callable[[np.ndarray], np.ndarray]:
    return to_numpy(parse_expression(expr))


def real_rational_power(base: np.ndarray | float, p: int, q: int) -> np.ndarray:
    """Real value of base^(p/q) (fraction reduced first). Defined for negative bases when q is odd:
    (-8)^(1/3) = -2, (-8)^(2/3) = 4, (-8)^(-1/3) = -0.5. 0 to a negative power -> nan."""
    from math import gcd

    if q == 0:
        raise ValueError("q must be non-zero")
    if q < 0:
        p, q = -p, -q
    g = gcd(abs(p), q) or 1
    p, q = p // g, q // g
    b = np.asarray(base, dtype=float)
    with np.errstate(all="ignore"):
        if q % 2 == 1:
            r = np.sign(b) * np.abs(b) ** (1.0 / q)
        else:
            r = np.where(b >= 0, np.abs(b) ** (1.0 / q), np.nan)
        out = r ** p
        return np.where(np.isfinite(out), out, np.nan)


real_power = real_rational_power  # backward-compatible name (v5.4)


def equivalent(e1: sympy.Expr, e2: sympy.Expr, lo: float = -10, hi: float = 10) -> bool:
    """Numerical equivalence on sample points (+ symbolic check when cheap)."""
    xs = np.linspace(lo, hi, 97) + 0.0137
    a, b = to_numpy(e1)(xs), to_numpy(e2)(xs)
    both = np.isfinite(a) & np.isfinite(b)
    if (np.isfinite(a) != np.isfinite(b)).sum() > 2 or both.sum() < 5:
        return False
    return bool(np.allclose(a[both], b[both], rtol=1e-7, atol=1e-9))


def semicircle(expr: sympy.Expr) -> dict | None:
    """Recognise y = sqrt(c - x^2) (c free of x, c > 0): upper semicircle x^2 + y^2 = c, domain [-sqrt(c), sqrt(c)]."""
    try:
        c = sympy.simplify(expr ** 2 + X ** 2)
        if c.free_symbols - (expr.free_symbols - {X}) or X in c.free_symbols:
            return None
        if not (expr.is_nonnegative or (isinstance(expr, sympy.Pow) and expr.exp == sympy.Rational(1, 2))):
            return None
        r = sympy.sqrt(c)
        if r.is_positive is False:
            return None
        r = sympy.simplify(r)
        return {"shape": "upper_semicircle", "radius": r, "equation": sympy.Eq(X ** 2 + sympy.Symbol("y") ** 2, c),
                "domain": (-r, r)}
    except Exception:
        return None


def domain(expr: sympy.Expr):
    """Real domain in x; works with declared parameters (e.g. R > 0 gives [-R, R] for sqrt(R^2 - x^2)). None if unknown."""
    from sympy.calculus.util import continuous_domain
    from sympy.solvers.inequalities import solve_univariate_inequality

    if not (expr.free_symbols - {X}):
        return continuous_domain(expr, X, sympy.S.Reals)
    sc = semicircle(expr)
    if sc is not None:
        return sympy.Interval(*sc["domain"])
    dom = sympy.S.Reals
    try:
        for node in sympy.preorder_traversal(expr):
            if isinstance(node, sympy.Pow) and isinstance(node.exp, sympy.Rational) and node.exp.q % 2 == 0:
                dom = dom.intersect(solve_univariate_inequality(node.base >= 0, X, relational=False))
            elif isinstance(node, sympy.log):
                dom = dom.intersect(solve_univariate_inequality(node.args[0] > 0, X, relational=False))
        return dom
    except Exception:
        return None
