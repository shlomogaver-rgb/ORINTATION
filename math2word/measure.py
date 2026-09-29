"""Rough width estimates, used to keep every source line on a single Word line."""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path

from PIL import ImageFont

_FALLBACK_FILES = [
    r"C:\Windows\Fonts\david.ttf",
    "/Library/Fonts/David.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@functools.lru_cache(maxsize=8)
def _font(family: str, size: int = 100):
    candidates = []
    if shutil.which("fc-match"):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", family], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
            if path:
                candidates.append(path)
        except (OSError, subprocess.SubprocessError):
            pass
    candidates += _FALLBACK_FILES
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return None


def text_width_pt(text: str, family: str, size_pt: float, bold: bool = False) -> float:
    f = _font(family)
    if f is None:
        w = 0.5 * len(text) * size_pt
    else:
        w = f.getlength(text) / 100 * size_pt
    return w * (1.06 if bold else 1.0)


_CMD_ONE_CHAR = re.compile(r"\\[a-zA-Z]+")


def _math_chars(latex: str) -> float:
    """Approximate the rendered width of a formula in 'em' units."""
    s = latex
    s = re.sub(r"\\(left|right|big|Big|bigg|Bigg)\b", "", s)
    s = re.sub(r"\\(mathrm|text|mathbf|mathit|operatorname)\{([^{}]*)\}", r"\2", s)
    # \frac{a}{b} -> the wider of a and b
    frac = re.compile(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}")
    while True:
        m = frac.search(s)
        if not m:
            break
        a, b = m.group(1), m.group(2)
        s = s[:m.start()] + (a if len(a) >= len(b) else b) + s[m.end():]
    # superscripts/subscripts are small
    small = 0.0
    for m in re.finditer(r"[\^_]\{([^{}]*)\}|[\^_](\\?[a-zA-Z0-9])", s):
        small += 0.6 * len(m.group(1) or m.group(2) or "")
    s = re.sub(r"[\^_]\{[^{}]*\}|[\^_]\\?[a-zA-Z0-9]", "", s)
    s = _CMD_ONE_CHAR.sub("x", s)
    s = s.replace("{", "").replace("}", "").replace(" ", "")
    wide = sum(1 for ch in s if ch in "=<>+-−≤≥∼~⊥")   # relations/operators get spacing
    return 0.62 * (len(s) - wide) + 1.1 * wide + small


def math_width_pt(latex: str, size_pt: float) -> float:
    return _math_chars(latex) * size_pt


def line_width_pt(line: list, family: str, size_pt: float) -> float:
    total = 0.0
    for seg in line:
        if seg["type"] == "math":
            total += math_width_pt(seg["value"], size_pt)
        else:
            total += text_width_pt(seg["value"].replace("\t", "    "), family, size_pt, seg.get("bold", False))
    return total
