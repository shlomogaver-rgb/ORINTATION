"""LaTeX -> native Word equations (OMML) using pandoc's texmath engine.

All formulas of a document are converted in a single pandoc run, then the <m:oMath>
elements are lifted out of pandoc's document.xml in order.
"""
from __future__ import annotations

import copy
import tempfile
import zipfile
from pathlib import Path

import pypandoc
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# Symbols texmath may not know, mapped to ones it does.
_REPLACEMENTS = {
    r"\sphericalangle": "∢",
    r"\measuredangle": "∡",
    r"\degree": r"^{\circ}",
    r"\overarc": r"\overset{\frown}",
    r"\arc": r"\overset{\frown}",
}


def _normalize(latex: str) -> str:
    s = latex.strip()
    for k, v in _REPLACEMENTS.items():
        s = s.replace(k, v)
    return s


def latex_to_omml(formulas: list[str]) -> list[etree._Element | None]:
    """Return one <m:oMath> element per formula (None when conversion failed)."""
    if not formulas:
        return []
    marker = "§§"
    md = "\n\n".join(f"{marker}{i}{marker} ${_normalize(f)}$" for i, f in enumerate(formulas))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "m.docx"
        pypandoc.convert_text(md, "docx", format="markdown", outputfile=str(out),
                              extra_args=["--wrap=none"])
        with zipfile.ZipFile(out) as z:
            root = etree.fromstring(z.read("word/document.xml"))

    results: list[etree._Element | None] = [None] * len(formulas)
    for p in root.iter(f"{{{W}}}p"):
        text = "".join(t.text or "" for t in p.iter(f"{{{W}}}t"))
        if marker not in text:
            continue
        try:
            idx = int(text.split(marker)[1])
        except (IndexError, ValueError):
            continue
        maths = list(p.iter(f"{{{M}}}oMath"))
        if maths:
            results[idx] = copy.deepcopy(maths[0])
    return results
