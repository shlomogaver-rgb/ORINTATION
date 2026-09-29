"""Small text helpers shared by the parsers/renderers (no dependency on exam_core)."""
from __future__ import annotations

import re
from typing import Any

try:
    from bidi import get_display as _bidi
except Exception:  # pragma: no cover
    try:
        from bidi.algorithm import get_display as _bidi
    except Exception:
        _bidi = None
try:
    import arabic_reshaper
except Exception:  # pragma: no cover
    arabic_reshaper = None

RTL = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<"}
_OPEN, _CLOSE = "([{<", ")]}>"
LATIN = re.compile(r"[A-Za-z]")


def _strong_before(s: str, i: int) -> str | None:
    for ch in reversed(s[:i]):
        if RTL.match(ch):
            return "R"
        if LATIN.match(ch):
            return "L"
    return None


def mirror_brackets(line: str) -> str:
    """python-bidi reorders but does NOT mirror brackets (UAX #9 rule L4). Pre-mirror, in LOGICAL order, every bracket
    whose pair resolves to RTL: content has an RTL letter -> R; content has a Latin letter -> L (e.g. f(x));
    otherwise the preceding strong character (default: the RTL paragraph direction)."""
    if not RTL.search(line):
        return line
    chars = list(line)
    stack, pairs = [], {}
    for i, ch in enumerate(line):
        if ch in _OPEN:
            stack.append(i)
        elif ch in _CLOSE and stack and _OPEN.index(line[stack[-1]]) == _CLOSE.index(ch):
            pairs[stack.pop()] = i
    decided: dict[int, bool] = {}
    for i, j in pairs.items():
        content = line[i + 1:j]
        if RTL.search(content):
            rtl = True
        elif LATIN.search(content):
            rtl = False
        else:
            rtl = _strong_before(line, i) != "L"
        decided[i] = decided[j] = rtl
    for i, ch in enumerate(line):
        if ch in MIRROR and i not in decided:
            decided[i] = _strong_before(line, i) != "L"
    for i, rtl in decided.items():
        if rtl:
            chars[i] = MIRROR[chars[i]]
    return "".join(chars)


def visual(text: Any) -> str:
    """Logical -> visual order for matplotlib (which has no bidi support)."""
    s = str(text or "")
    if not RTL.search(s):
        return s
    if ARABIC.search(s) and arabic_reshaper is not None:
        s = arabic_reshaper.reshape(s)
    return "\n".join(_bidi(mirror_brackets(line)) for line in s.split("\n")) if _bidi else s


def normalize_math_text(text: str) -> str:
    """LaTeX-ish question text -> plain text with math symbols, for relation extraction."""
    s = text or ""
    s = re.sub(r"\\(?:overline|overrightarrow|vec|bar|mathrm|text)\s*\{([^{}]*)\}", r"\1", s)
    for a, b in ((r"\parallel", "∥"), (r"\perp", "⊥"), (r"\angle", "∠"), (r"\measuredangle", "∠"), (r"\sphericalangle", "∠"),
                 (r"\triangle", "משולש "), (r"\cdot", "*"), (r"\circ", "°"), ("^°", "°"), ("^{°}", "°"), (r"\,", " "), ("$", " "),
                 ("∢", "∠"), ("⦣", "∠"), ("||", "∥"), ("//", "∥")):
        s = s.replace(a, b)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", s)
