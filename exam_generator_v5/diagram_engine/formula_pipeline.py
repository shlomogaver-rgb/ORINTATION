"""Formula pipeline: LaTeX (from PASS 1 or the teacher) -> safe parse -> ExpressionAST -> validation -> status; and
cross-validation against INDEPENDENT evidence (PDF text layer of the same region). Uncertain math is never trusted silently."""
from __future__ import annotations

import re

import sympy

from . import safe_math as sm
from .semantic import expression_ast as ea

ALLOWED = re.compile(r"^[0-9A-Za-z+\-*/^().,=<>!| \t']+$")
MATH_SEG = re.compile(r"\$([^$]+)\$")
NUM = re.compile(r"\d+(?:\.\d+)?")


def analyse(latex: str) -> dict:
    """STRUCTURE first (latex_ast: every exam notation), then an optional SYMBOLIC check (SymPy) for algebraic formulas.
    {"status": OK | UNPARSED | INVALID, "ast_root": kind, "symbolic": bool, "numbers": [...], "problems": [...]}"""
    from . import latex_ast
    try:
        tree = latex_ast.parse(latex or "")
        probs = ea.validate(tree)
        sym = _symbolic(latex)
        return {"status": "OK" if not probs else "INVALID", "ast_root": tree.kind, "symbolic": sym["status"] == "OK",
                "numbers": NUM.findall(re.sub(r"\\[A-Za-z]+", " ", latex or "")), "problems": probs}
    except latex_ast.LatexError as exc:
        return {"status": "UNPARSED", "ast_root": "", "symbolic": False, "numbers": NUM.findall(latex or ""), "problems": [str(exc)]}
    except Exception as exc:
        return {"status": "UNPARSED", "ast_root": "", "symbolic": False, "numbers": NUM.findall(latex or ""), "problems": [type(exc).__name__]}


def _symbolic(latex: str) -> dict:
    """Algebraic formulas only: safe SymPy parse (a CHECK, not the representation)."""
    # split on relations FIRST (latex_to_plain drops a leading "f(x)=" definition), then convert every side
    # relation commands must be WHOLE commands: "\\le" must not match the start of "\\left"
    sides = re.split(r"(\\le(?![a-zA-Z])|\\ge(?![a-zA-Z])|\\neq(?![a-zA-Z])|<=|>=|=|<|>)", latex or "")
    try:
        rel_sides = [sm.latex_to_plain(p_) if i % 2 == 0 else {"\\le": "<=", "\\ge": ">=", "\\neq": "!="}.get(p_, p_)
                     for i, p_ in enumerate(sides)]
    except Exception as exc:                                  # never crash: an unreadable formula is UNPARSED, shown as-is
        return {"status": "UNPARSED", "ast_root": "", "numbers": NUM.findall(latex or ""), "problems": [type(exc).__name__]}
    rel_sides = [re.sub(r"^\s*[a-zA-Z]\(\s*[a-zA-Z]\s*\)\s*$", "", x) or x for x in rel_sides]
    plain = "".join(rel_sides)
    nums = NUM.findall(plain)
    if not plain.strip():
        return {"status": "UNPARSED", "ast_root": "", "numbers": nums, "problems": ["ריק"]}
    if not ALLOWED.fullmatch(plain):
        return {"status": "UNPARSED", "ast_root": "", "numbers": nums, "problems": ["תווים שאינם נתמכים בניתוח הסמלי"]}
    try:
        parts = re.split(r"(<=|>=|!=|=|<|>)", plain)
        exprs = [p for i, p in enumerate(parts) if i % 2 == 0]
        exprs = [e for e in exprs if not re.fullmatch(r"\s*[a-zA-Z]\s*\(\s*[a-zA-Z]\s*\)\s*", e)] + \
                [e for e in exprs if re.fullmatch(r"\s*[a-zA-Z]\s*\(\s*[a-zA-Z]\s*\)\s*", e)][:0]
        is_rel = len(parts) > 1
        syms = {c: sympy.Symbol(c) for c in set(re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", plain))}
        with sm.symbol_context({k: {} for k in syms if k not in ("x", "e")}, {k: 1.0 for k in syms}):
            parsed = [sm.parse_expression(e.strip()) for e in exprs if e.strip()]
        if is_rel:
            root = ea.Node("Equation" if "=" in parts[1::2][0] and parts[1::2][0] in ("=",) else "Inequality",
                           children=[ea.from_sympy(p) for p in parsed])
        else:
            root = ea.from_sympy(parsed[0])
        probs = ea.validate(root)
        return {"status": "OK" if not probs else "INVALID", "ast_root": root.kind, "numbers": nums, "problems": probs}
    except Exception as exc:
        return {"status": "UNPARSED", "ast_root": "", "numbers": nums, "problems": [type(exc).__name__]}


def question_formulas(texts: list[str]) -> list[dict]:
    out = []
    for t in texts:
        for m in MATH_SEG.finditer(t or ""):
            out.append({"latex": m.group(1), **analyse(m.group(1))})
    return out


VALIDATOR_VERSION = "formula/2.0-local-structural"

# ---------------------------------------------------------------- context-aware numeric tokens (Task 3)
_COORD = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*(?:,\s*(-?\d+(?:\.\d+)?)\s*)?\)")
_THOUSANDS = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d])")
_NUMBER = re.compile(r"(?<![A-Za-z\d])-?\d+(?:\.\d+)?|\d+(?:\.\d+)?")


def numeric_tokens(text: str) -> list[str]:
    """Numbers in reading order WITHOUT destroying structure: '(3,4)' -> 3, 4 (a coordinate pair); '1,000,000' -> 1000000
    (thousands separators); '−' is a minus. A comma is never deleted globally."""
    t = (text or "").replace("−", "-").replace("–", "-")
    out: list[tuple[int, str]] = []
    taken = []
    for m in _COORD.finditer(t):
        for g in range(1, 4):
            if m.group(g) is not None:
                out.append((m.start(g), m.group(g)))
        taken.append((m.start(), m.end()))
    for m in _THOUSANDS.finditer(t):
        if not any(a <= m.start() < b for a, b in taken):
            out.append((m.start(), m.group(0).replace(",", "")))
            taken.append((m.start(), m.end()))
    for m in re.finditer(r"-?\d+(?:\.\d+)?", t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        v = m.group(0)
        if v.startswith("-") and m.start() > 0 and (t[m.start() - 1].isalnum() or t[m.start() - 1] in ")]}"):
            v = v[1:]                                    # binary minus ("2x-1"), not a negative number
        out.append((m.start() + (len(m.group(0)) - len(v)), v))
    return [v for _, v in sorted(out)]


# ---------------------------------------------------------------- flat token signature (for LOCAL alignment)
def _flat(node) -> list[str]:
    """Reading-order leaves and sign/relation operators of an AST (superscripts/fractions flattened like a PDF text layer)."""
    k = node.kind
    if k == "Number":
        return [node.value]
    if k == "Symbol":
        return [node.value]
    if k == "Negative":
        return ["-"] + _flat(node.children[0])
    if k == "Sum":
        out = []
        for i_, ch in enumerate(node.children):
            if i_ and ch.kind != "Negative":
                out.append("+")
            out += _flat(ch)
        return out
    if k in ("Equation", "Inequality", "Relation"):
        out = []
        for i_, ch in enumerate(node.children):
            if i_:
                out.append(node.value[i_ - 1] if node.value and len(node.value) >= i_ else "=")
            out += _flat(ch)
        return out
    if k == "Group":
        return ["("] + [t for ch in node.children for t in _flat(ch)] + [")"]
    if k == "FunctionApplication":
        return _flat(node.children[0]) + (_flat(node.children[1]) if len(node.children) > 1 else [])
    if k == "List":
        out = []
        for i_, ch in enumerate(node.children):
            if i_:
                out.append(",")
            out += _flat(ch)
        return out
    return [t for ch in node.children for t in _flat(ch)]


_TEXT_TOK = re.compile(r"\d+(?:\.\d+)?|[A-Za-z]|[+\-=<>(),]")


def _text_fragments(text_layer: str) -> list[list[str]]:
    """Math fragments of the PDF text layer: runs of math tokens separated by Hebrew words."""
    t = (text_layer or "").replace("−", "-").replace("–", "-")
    frags, cur = [], []
    for piece in re.split(r"([\u0590-\u05FF]+)", t):
        if re.fullmatch(r"[\u0590-\u05FF]+", piece or ""):
            if cur:
                frags.append(cur)
            cur = []
            continue
        for m in re.finditer(r"\d{1,3}(?:,\d{3})+|" + _TEXT_TOK.pattern, piece):
            cur.append(m.group(0).replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", m.group(0)) else m.group(0))
    if cur:
        frags.append(cur)
    return frags


def _kind(tok: str) -> str:
    return "num" if re.fullmatch(r"\d+(?:\.\d+)?", tok) else ("sign" if tok in "+-" else ("rel" if tok in "=<>" else
                                                                                       ("sym" if tok.isalpha() else "punct")))


def local_conflicts(latex: str, text_layer: str) -> list[str]:
    """Align the formula with the MOST SIMILAR local fragment of the text layer (never with numbers found anywhere else).
    Only same-kind substitutions count (number<->number, sign<->sign, symbol<->symbol, relation<->relation); insertions or
    deletions are layout artefacts of flattening. No similar fragment -> no evidence (never a false 'verified')."""
    import difflib

    from . import latex_ast
    try:
        sig = _flat(latex_ast.parse(latex))
    except Exception:
        return []
    if len(sig) < 5 or not any(_kind(t_) == "num" or t_ in "+-=<>" for t_ in sig):
        return []                     # too short / only entity names: an alignment would be ambiguous, not evidence
    best, best_r = None, 0.0
    for frag in _text_fragments(text_layer):
        for cand in (frag, list(reversed(frag))):                    # RTL text layers may reverse math runs
            for i in range(0, max(1, len(cand) - len(sig) + 1)):
                win = cand[i:i + len(sig) + 2]
                r = difflib.SequenceMatcher(None, sig, win, autojunk=False).ratio()
                if r > best_r:
                    best_r, best = r, win
    if best is None or best_r < 0.7:
        return []
    out = []
    sm = difflib.SequenceMatcher(None, sig, best, autojunk=False)
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "replace" and a1 - a0 == b1 - b0:
            for x, y in zip(sig[a0:a1], best[b0:b1]):
                if _kind(x) == _kind(y) and x != y and _kind(x) in ("num", "sign", "sym", "rel"):
                    what = {"num": "ערך", "sign": "סימן", "sym": "משתנה", "rel": "יחס"}[_kind(x)]
                    out.append(f"{what}: בזיהוי '{x}', במקור '{y}'")
    return out


def cross_check(formulas: list[dict], text_layer: str | None) -> list[str]:
    """LOCAL + STRUCTURAL: each formula is compared with its own counterpart in the source text layer."""
    if not text_layer:
        return []
    out = []
    for f in formulas:
        diffs = local_conflicts(f["latex"], text_layer)
        if diffs:
            out.append(f"FORMULA_UNCERTAIN: בנוסחה ${f['latex']}$ — " + "; ".join(diffs[:3]) + " — יש לאשר.")
    return out


# ---------------------------------------------------------------- AST-to-AST structural comparison (two readings)
def compare_structure(a: str, b: str) -> list[str]:
    """Structural differences between two readings of a formula (sign, operator, fraction orientation, power/root/log scope,
    integral bounds, symbol identity, numbers). Not a proof of equivalence - a recognition-conflict detector."""
    from . import latex_ast
    try:
        ta, tb = latex_ast.parse(a), latex_ast.parse(b)
    except Exception as exc:
        return [f"לא ניתן לנתח: {exc}"]
    out: list[str] = []

    def walk(x, y, path):
        if x.kind != y.kind:
            if {x.kind, y.kind} == {"Sum", "Negative"} or "Negative" in (x.kind, y.kind):
                out.append(f"sign @{path}")
            else:
                out.append(f"structure @{path}: {x.kind} ≠ {y.kind}")
            return
        if x.kind == "Fraction" and len(x.children) == 2 and len(y.children) == 2:
            if _same(x.children[0], y.children[1]) and _same(x.children[1], y.children[0]) and not _same(x.children[0], y.children[0]):
                out.append(f"fraction numerator/denominator swapped @{path}")
                return
        if x.kind == "Integral" and len(x.children) == 3 and len(y.children) == 3:
            if _same(x.children[1], y.children[2]) and _same(x.children[2], y.children[1]) and not _same(x.children[1], y.children[1]):
                out.append(f"integral bounds swapped @{path}")
                return
        if x.kind in ("Number", "Symbol") and x.value != y.value:
            out.append(f"{'number' if x.kind == 'Number' else 'symbol'} {x.value}≠{y.value} @{path}")
            return
        if x.value != y.value and x.kind not in ("Number", "Symbol"):
            out.append(f"operator {x.value}≠{y.value} @{path}")
        if len(x.children) != len(y.children):
            out.append(f"structure @{path}: {len(x.children)} ≠ {len(y.children)} operands")
            return
        for i_, (cx_, cy_) in enumerate(zip(x.children, y.children)):
            walk(cx_, cy_, f"{path}/{x.kind}[{i_}]")
    walk(ta, tb, "")
    return out


def _same(x, y) -> bool:
    return x.kind == y.kind and x.value == y.value and len(x.children) == len(y.children) and all(_same(a, b) for a, b in zip(x.children, y.children))


# ---------------------------------------------------------------- validation fingerprint (Task 4)
def math_fingerprint(texts: list[str], source_hashes: list[str] | None = None) -> str:
    """Bound to the exact MATHEMATICAL content: every $...$ segment (whitespace-free) and every number of the plain text,
    plus the source evidence hashes and the validator version. Hebrew wording changes do not alter it."""
    import hashlib
    parts = [VALIDATOR_VERSION]
    for t in texts:
        t = t or ""
        parts += [re.sub(r"\s+", "", m.group(1)) for m in MATH_SEG.finditer(t)]
        parts += numeric_tokens(MATH_SEG.sub(" ", t))
    parts += list(source_hashes or [])
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
