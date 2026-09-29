"""Structural LaTeX -> ExpressionAST parser (recursive descent). Covers exam notation generally - not only algebra:
entities (ABC, A'B), function application f'(x), greek, sub/superscripts, \\frac with braced or single-token arguments,
roots, abs, binomials, integrals/sums/limits, relations (=, <, \\le, \\sim, \\parallel, \\perp ...), angles/triangles/vectors,
degrees, lists and \\dots. Unknown commands or broken structure -> an explicit error (never a silent guess)."""
from __future__ import annotations

import re

from .semantic.expression_ast import Node

GREEK = {"alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "theta", "vartheta", "lambda", "mu", "sigma", "rho", "phi",
         "varphi", "omega", "pi", "tau", "eta", "kappa", "nu", "xi", "zeta", "chi", "psi", "Delta", "Omega", "Sigma", "Gamma",
         "Phi", "Theta", "Lambda", "Pi"}
FUNCS = {"sin", "cos", "tan", "cot", "ln", "log", "exp", "arcsin", "arccos", "arctan", "sec", "csc"}
OPERATORS = {"max", "min", "deg", "det", "gcd", "arg", "Re", "Im"}
RELS = {"=": "=", "<": "<", ">": ">", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "approx": "≈",
        "sim": "∼", "parallel": "∥", "perp": "⊥", "cong": "≅", "equiv": "≡", "to": "→", "Rightarrow": "⇒", "in": "∈", "subset": "⊂",
        "mid": "|", "Leftrightarrow": "⇔", "notin": "∉", ":": ":"}
ADD = {"+": "+", "-": "-", "pm": "±", "mp": "∓"}
MUL = {"cdot": "·", "times": "×", "div": "÷", "/": "/", "cap": "∩", "cup": "∪", "setminus": "∖"}
SPACES = {",", ";", "!", "quad", "qquad", " ", ":"}
IGNORED = {"displaystyle", "textstyle", "limits", "mathrm", "text", "mathbf", "operatorname", "left", "right", "big", "Big",
           "bigl", "bigr", "Bigl", "Bigr"}
TOKEN = re.compile(r"\\([A-Za-z]+|.)|(\d+(?:\.\d+)?)|([A-Za-z])|('+)|(\S)")


class LatexError(ValueError):
    pass


def tokenize(s: str) -> list[tuple[str, str]]:
    s = re.sub(r"(?<=\d)\{,\}(?=\d{3})", "", s or "")        # 44{,}307 = 44307 (LaTeX thousands separator)
    out = []
    for m in TOKEN.finditer(s or ""):
        cmd, num, let, prime, sym = m.groups()
        if cmd is not None:
            if cmd in SPACES:
                continue
            out.append(("cmd", cmd))
        elif num is not None:
            out.append(("num", num))
        elif let is not None:
            out.append(("let", let))
        elif prime is not None:
            out.append(("prime", prime))
        else:
            out.append(("sym", sym))
    return out


class Parser:
    def __init__(self, s: str):
        self.t = tokenize(s)
        self.i = 0
        self.abs_depth = 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", "")

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, kind, val):
        tok = self.take()
        if tok != (kind, val):
            raise LatexError(f"צפוי '{val}' ונמצא '{tok[1]}'")

    # ---- grammar
    def parse(self) -> Node:
        n = self.relation()
        if self.peek()[0] != "eof":
            raise LatexError(f"תו לא צפוי '{self.peek()[1]}'")
        return n

    def relation(self) -> Node:
        items = [self.listing()]
        ops = []
        while self._rel_op():
            ops.append(self._rel_op_take())
            items.append(self.listing())
        if not ops:
            return items[0]
        kind = "Equation" if all(o == "=" for o in ops) else ("Inequality" if all(o in "<>≤≥≠" for o in ops) else "Relation")
        return Node(kind, "".join(ops), items)

    def _rel_op(self):
        k, v = self.peek()
        return (k == "sym" and v in "=<>:") or (k == "cmd" and v in RELS)

    def _rel_op_take(self):
        k, v = self.take()
        return RELS.get(v, v)

    def listing(self) -> Node:
        items = [self.sum_()]
        while self.peek() == ("sym", ","):
            self.take()
            items.append(self.sum_())
        return items[0] if len(items) == 1 else Node("List", children=items)

    def sum_(self) -> Node:
        terms = []
        sign = ""
        if (self.peek()[0] == "sym" and self.peek()[1] in "+-") or (self.peek()[0] == "cmd" and self.peek()[1] in ("pm", "mp")):
            sign = ADD[self.take()[1]]
        first = self.product()
        terms.append(Node("Negative", children=[first]) if sign == "-" else first)
        while (self.peek()[0] == "sym" and self.peek()[1] in "+-") or (self.peek()[0] == "cmd" and self.peek()[1] in ("pm", "mp")):
            op = ADD[self.take()[1]]
            t = self.product()
            terms.append(Node("Negative", children=[t]) if op == "-" else (Node("PlusMinus", children=[t]) if op in "±∓" else t))
        return terms[0] if len(terms) == 1 else Node("Sum", children=terms)

    def product(self) -> Node:
        factors = [self.postfix()]
        while True:
            k, v = self.peek()
            if (k == "cmd" and v in MUL) or (k == "sym" and v == "/"):
                self.take()
                rhs = self.postfix()
                if v in ("/", "div"):
                    factors.append(Node("Fraction", children=[factors.pop(), rhs]))
                elif v in ("cap", "cup", "setminus"):
                    factors.append(Node("SetOperation", MUL[v], [factors.pop(), rhs]))
                else:
                    factors.append(rhs)
                continue
            if self._starts_atom():
                factors.append(self.postfix())
                continue
            break
        return factors[0] if len(factors) == 1 else Node("Product", children=factors)

    def _starts_atom(self) -> bool:
        k, v = self.peek()
        if k in ("num", "let"):
            return True
        if k == "sym" and v in "({[":
            return True
        if k == "sym" and v == "|":
            return self.abs_depth == 0              # inside |...| a bar CLOSES the absolute value
        if k == "cmd" and v not in RELS and v not in MUL and v not in {"pm", "mp", "right", "dots", "ldots", "cdots"}:
            return True
        return False

    def postfix(self) -> Node:
        n = self.atom()
        while True:
            k, v = self.peek()
            if k == "prime":
                self.take()
                n = Node("Prime", str(len(v)), [n])
            elif k == "sym" and v == "^":
                self.take()
                sup = self.arg()
                n = Node("Degrees", children=[n]) if sup.kind == "Symbol" and sup.value == "circ" else Node("Power", children=[n, sup])
            elif k == "sym" and v == "_":
                self.take()
                n = Node("Subscript", children=[n, self.arg()])
            elif k == "sym" and v == "!":
                self.take()
                n = Node("Factorial", children=[n])
            elif k == "sym" and v == "(" and n.kind in ("Symbol", "Prime", "Subscript") and self._looks_like_call(n):
                n = Node("FunctionApplication", "", [n, self.atom()])
            else:
                return n

    def _looks_like_call(self, n: Node) -> bool:
        base = n
        while base.kind in ("Prime", "Subscript"):
            base = base.children[0]
        return base.kind == "Symbol" and base.value in ("f", "g", "h", "k", "p", "q", "F", "G", "H", "S", "P", "A", "V")

    def arg(self) -> Node:
        """A LaTeX argument: {group} or ONE token (\\frac43, x^2, a_1)."""
        k, v = self.peek()
        if (k, v) == ("sym", "{"):
            return self.atom()
        tok = self.take()
        if tok[0] == "num":
            return Node("Number", tok[1][0]) if len(tok[1]) > 1 and "." not in tok[1] and self._split_digits(tok) else Node("Number", tok[1])
        if tok[0] == "let":
            return Node("Symbol", tok[1])
        if tok[0] == "cmd":
            self.i -= 1
            return self.atom()
        raise LatexError(f"ארגומנט חסר ('{tok[1]}')")

    def _split_digits(self, tok) -> bool:
        """\\frac43 : a single-token argument takes ONE digit; the rest is pushed back as the next token."""
        rest = tok[1][1:]
        self.t.insert(self.i, ("num", rest))
        return True

    def atom(self) -> Node:
        k, v = self.take()
        if k == "num":
            return Node("Number", v)
        if k == "let":
            return Node("Symbol", v)
        if k == "sym" and v in "({[":
            close = {"(": ")", "{": "}", "[": "]"}[v]
            if self.peek() == ("sym", close):
                self.take()
                return Node("Group", v + close, [])
            inner = self.relation()
            if self.peek() == ("cmd", "right"):
                self.take()
            self.expect("sym", close)
            return inner if v == "{" else Node("Group", v + close, [inner])
        if k == "sym" and v == "|":
            self.abs_depth += 1
            try:
                inner = self.sum_()
            finally:
                self.abs_depth -= 1
            if self.peek() == ("cmd", "right"):
                self.take()
            self.expect("sym", "|")
            return Node("AbsoluteValue", children=[inner])
        if k == "sym" and v == "%":
            return Node("Symbol", "%")
        if k == "cmd":
            return self.command(v)
        raise LatexError(f"תו לא צפוי '{v}'")

    def command(self, v: str) -> Node:
        if v in ("text", "mbox", "textrm"):
            # free text (Hebrew words inside math): consume raw tokens up to the matching brace
            self.expect("sym", "{")
            depth, words = 1, []
            while depth:
                tok = self.take()
                if tok[0] == "eof":
                    raise LatexError("\\text ללא סוגר")
                depth += (tok == ("sym", "{")) - (tok == ("sym", "}"))
                if depth:
                    words.append(tok[1])
            return Node("Text", "".join(words))
        if v in OPERATORS:
            sub = None
            if self.peek() == ("sym", "_"):
                self.take()
                sub = self.arg()
            arg_ = self.postfix() if self._starts_atom() else None
            return Node("Operator", v, [x for x in (arg_, sub) if x is not None])
        if v in IGNORED:
            if v in ("mathrm", "mathbf", "operatorname"):
                g = self.arg()
                return Node("Text", children=[g])
            return self.atom() if v in ("left",) else (self.atom() if self._starts_atom() else Node("Group", "", []))
        if v in ("frac", "dfrac", "tfrac"):
            return Node("Fraction", children=[self.arg(), self.arg()])
        if v == "binom":
            return Node("Binomial", children=[self.arg(), self.arg()])
        if v == "sqrt":
            idx = None
            if self.peek() == ("sym", "["):
                self.take()
                idx = self.sum_()
                self.expect("sym", "]")
            return Node("Root", "2" if idx is None else "n", [self.arg()] + ([idx] if idx else []))
        if v in GREEK:
            return Node("Symbol", v)
        if v in ("infty",):
            return Node("Symbol", "∞")
        if v in ("dots", "ldots", "cdots"):
            return Node("Ellipsis")
        if v in ("circ", "degree"):
            return Node("Symbol", "circ")
        if v in FUNCS:
            base = None
            if self.peek() == ("sym", "_"):
                self.take()
                base = self.arg()
            power = None
            if self.peek() == ("sym", "^"):
                self.take()
                power = self.arg()
            argn = self.postfix()
            node = Node("Log" if v in ("ln", "log") else ("Exp" if v == "exp" else "TrigFunction"), v,
                        [argn] + ([base] if base is not None else []))
            return Node("Power", children=[node, power]) if power is not None else node
        if v in ("int", "sum", "prod", "lim", "iint"):
            lo = hi = None
            while self.peek() in (("sym", "_"), ("sym", "^")):
                which = self.take()[1]
                if which == "_":
                    lo = self.arg()
                else:
                    hi = self.arg()
            body = self.product() if self._starts_atom() else Node("Group", "", [])
            kind = {"int": "Integral", "iint": "Integral", "sum": "Sum_", "prod": "Product_", "lim": "Limit"}[v]
            return Node(kind, v, [body] + [x for x in (lo, hi) if x is not None])
        if v in ("angle", "measuredangle", "sphericalangle"):
            return Node("Angle", children=[self.postfix()])
        if v in ("triangle", "bigtriangleup", "square", "odot"):
            return Node("Figure", v, [self.postfix()])
        if v in ("overline", "underline", "vec", "overrightarrow", "overleftarrow", "hat", "bar", "widehat", "tilde", "boldsymbol", "mathbf"):
            return Node("Vector" if v in ("vec", "overrightarrow") else "Decorated", v, [self.arg()])
        if v == "%":
            return Node("Symbol", "%")
        raise LatexError(f"פקודת LaTeX לא מוכרת: \\{v}")


def parse(latex: str) -> Node:
    return Parser(latex).parse()
