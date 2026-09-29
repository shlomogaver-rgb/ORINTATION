"""Dynamic Safe Symbol Table: parameters exist ONLY if the question text declares them (e.g. 'R הוא פרמטר חיובי').
Names are validated (one Latin letter, optional digit/prime-free) and never executed; unknown names are rejected, not guessed."""
from __future__ import annotations

import re

from .text_utils import normalize_math_text

RESERVED = {"x", "y", "e", "E", "i", "I", "f", "g", "h", "p"}   # variable / constant / function names
NAME = r"([A-Za-z])"


def extract(text: str) -> dict[str, dict]:
    """{name: {"positive": bool, "negative": bool, "nonzero": bool, "source": raw}} from the question text."""
    s = normalize_math_text(text or "").replace("−", "-")
    out: dict[str, dict] = {}

    def put(name: str, raw: str, **assume: bool) -> None:
        if name in RESERVED:
            return
        d = out.setdefault(name, {"positive": False, "negative": False, "nonzero": False, "source": raw})
        for k, v in assume.items():
            d[k] = d[k] or v

    for m in re.finditer(NAME + r"\s*(?:הוא|היא)?\s*(?:פרמטר|קבוע|מספר)\s*(חיובי|שלילי|השונה מאפס|שונה מ-?0)?", s):
        kind = m.group(2) or ""
        put(m.group(1), m.group(0), positive="חיובי" in kind, negative="שלילי" in kind, nonzero="שונה" in kind)
    for m in re.finditer(r"(?:פרמטר|הפרמטר)\s*" + NAME, s):
        put(m.group(1), m.group(0))
    for m in re.finditer(r"(?<![A-Za-z])" + NAME + r"\s*(>|<|≠|!=)\s*0(?![\d.])", s):
        put(m.group(1), m.group(0), positive=m.group(2) == ">", negative=m.group(2) == "<", nonzero=m.group(2) in "≠!=")
    for m in re.finditer(r"(?<![A-Za-z])" + NAME + r"\s*>\s*(\d+(?:\.\d+)?)", s):
        put(m.group(1), m.group(0), positive=float(m.group(2)) >= 0)
    return out


def layout_value(name: str, info: dict) -> float:
    """Deterministic value used ONLY to draw a parametric curve (axes numbers are then hidden)."""
    return -2.0 if info.get("negative") else 2.0


def classify(text: str, expression: str = "") -> dict:
    """Separate independent variables, parameters, constants, functions, point names and units."""
    s = normalize_math_text(text or "")
    funcs = sorted(set(re.findall(r"(?<![A-Za-z])([a-z])\s*\(\s*([a-z])\s*\)", s + " " + expression)))
    variables = sorted({v for _, v in funcs} or ({"x"} if "x" in expression else set()))
    params = extract(text)
    letters = set(re.findall(r"[A-Za-z]", re.sub(r"sqrt|cbrt|sin|cos|tan|log|ln|exp|abs|pi", "", expression)))
    undeclared = sorted(letters - set(variables) - set(params) - {"e"})
    return {"independent_variables": variables, "parameters": sorted(params), "constants": sorted({"pi", "e"} & set(re.findall(r"pi|e", expression))),
            "functions": sorted({f for f, _ in funcs}), "point_names": sorted(set(re.findall(r"(?<![A-Za-z])[A-Z](?![a-z])", s))),
            "units": sorted(set(re.findall(r'(?<![\u0590-\u05FF])(?:סמ"ר|סמ"ק|ס"מ|מ"מ|מטרים|מטר)(?![\u0590-\u05FF])', s.replace("״", '"')))), "undeclared": undeclared}
