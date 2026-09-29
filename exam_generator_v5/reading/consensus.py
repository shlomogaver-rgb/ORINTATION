"""Compare reader A (the reconstruction that goes into the Word file) with reader B (independent line-by-line reading
of the photo, or the PDF text layer) - word by word, number by number, formula by formula.

Every disagreement is reported with the line it came from (so the UI can show the photo crop next to both readings).
Nothing is resolved automatically: a disagreement blocks export until the text is corrected (the comparison is recomputed
on every edit) or the teacher confirms the question.

Tokens:
  W  Hebrew word (outside math), normalized: no niqqud, no geresh/gershayim/quote marks, maqaf splits words
  M  "math atom": a LaTeX segment, or a Latin/number token written outside $...$ (readers disagree on what is math)
  N  every number, from text AND formulas (thousands separators removed)
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

CONSENSUS_VERSION = "consensus/1.0"
MATH_SEG = re.compile(r"\$\$(.+?)\$\$|\$([^$]+)\$", re.S)
HEB_WORD = re.compile(r"[\u05D0-\u05EA][\u05D0-\u05EA\u05F3\u05F4\"'׳״]*")
LATIN_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,'′()^_+\-=<>/|]*")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
NIQQUD = re.compile(r"[\u0591-\u05C7]")
LABEL = re.compile(r"^\s*(?:[א-ת]\.|\(\d+\)|\d{1,2}\.|[IVX]+\.)\s*")
MIN_COVERAGE = 0.7           # below this, B did not see the whole question (segmentation / crop problem)
LINE_BELONGS = 0.4           # a B line belongs to the question if >= 40 % of its Hebrew words were matched in A


@dataclass
class Conflict:
    kind: str                # word | number | formula | missing_in_photo | extra_in_photo | unreadable | incomplete
    a: str = ""
    b: str = ""
    line: int | None = None
    image_index: int | None = None
    norm_bbox: list[int] = field(default_factory=list)
    detail: str = ""

    def message(self) -> str:
        where = f" (שורה {self.line + 1} בצילום)" if self.line is not None else ""
        if self.kind == "word":
            return f"READING_CONFLICT: בשחזור '{self.a}', בקריאה השנייה של הצילום '{self.b}'{where}"
        if self.kind == "number":
            return f"READING_CONFLICT: מספר — בשחזור {self.a or '—'}, בצילום {self.b or '—'}{where}"
        if self.kind == "formula":
            return f"READING_CONFLICT: נוסחה — בשחזור ${self.a}$, בצילום ${self.b}${where}" + (f" [{self.detail}]" if self.detail else "")
        if self.kind == "missing_in_photo":
            return f"READING_CONFLICT: '{self.a}' מופיע בשחזור אך לא נמצא בצילום{where}"
        if self.kind == "extra_in_photo":
            return f"READING_CONFLICT: '{self.b}' מופיע בצילום אך חסר בשחזור{where}"
        if self.kind == "unreadable":
            return f"READING_CONFLICT: שורה שהקורא השני לא הצליח לקרוא בוודאות{where}: '{self.b}'"
        return f"READING_INCOMPLETE: {self.detail}"


def norm_word(w: str) -> str:
    w = NIQQUD.sub("", w)
    return re.sub(r"[\"'׳״]", "", w)


def norm_number(n: str) -> str:
    n = n.replace("{,}", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", n):          # 7,350 -> 7350
        n = n.replace(",", "")
    return n.replace(",", ".")


def norm_math(s: str) -> str:
    s = s.strip().strip("$")
    s = re.sub(r"\\(left|right|big|Big|bigg|Bigg)(?![A-Za-z])", "", s)
    s = re.sub(r"\\[,;:!> ]|~|\\quad|\\qquad", "", s)
    s = re.sub(r"\\(mathrm|text|mathit|operatorname)\{([^{}]*)\}", r"\2", s)
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = s.replace("\\cdot", "·").replace("\\times", "×").replace("−", "-").replace("–", "-")
    s = s.replace("\\le", "≤").replace("\\ge", "≥").replace("\\neq", "≠").replace("\\ne", "≠")
    s = s.replace("{,}", ",")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"([_^])\{(\w)\}", r"\1\2", s)                      # x^{2} == x^2
    s = re.sub(r"\{([^{}\\])\}", r"\1", s)                          # {A} == A
    return s.rstrip(".,")


def tokenize(text: str) -> list[tuple[str, str, str]]:
    """-> [(kind, normalized, original)] in reading order. kind: W (Hebrew word) / M (math atom)."""
    out: list[tuple[str, str, str]] = []
    text = text or ""
    pos = 0
    for m in MATH_SEG.finditer(text):
        out += _plain_tokens(text[pos:m.start()])
        latex = m.group(1) or m.group(2) or ""
        if latex.strip():
            out.append(("M", norm_math(latex), latex.strip()))
        pos = m.end()
    out += _plain_tokens(text[pos:])
    return out


def _plain_tokens(s: str) -> list[tuple[str, str, str]]:
    out = []
    for m in re.finditer(r"[\u05D0-\u05EA][\u05D0-\u05EA\u05F3\u05F4\"'׳״]*|[A-Za-z0-9][A-Za-z0-9.,'′^_+\-=<>/|]*", s):
        tok = m.group(0)
        if HEB_WORD.fullmatch(tok):
            if tok.endswith(("'", '"')) and len(tok) > 2:
                tok = tok  # keep gershayim-abbreviations (ס"מ) as one word
            out.append(("W", norm_word(tok), tok))
        else:
            tok = tok.rstrip(".,")
            if tok:
                out.append(("M", norm_math(tok), tok))
    return out


def numbers_in(text: str) -> Counter:
    return Counter(norm_number(n) for n in NUMBER.findall((text or "").replace("{,}", ",")))


def _strip_label(line: str) -> str:
    return LABEL.sub("", line or "", count=1)


def compare(a_texts: list[str], b_lines: list[dict[str, Any]], reader: str = "", check_formulas: bool = True) -> dict[str, Any]:
    """a_texts: stem + subparts (with $LaTeX$). b_lines: [{"text", "unreadable", "image_index", "norm_bbox"}] in reading
    order. Returns the report (JSON-serializable)."""
    a_tok = [t for txt in a_texts for t in tokenize(_strip_label_lines(txt))]
    b_tok: list[tuple[str, str, str, int]] = []
    for li, bl in enumerate(b_lines):
        for k, n, o in tokenize(_strip_label(bl.get("text", ""))):
            b_tok.append((k, n, o, li))

    conflicts: list[Conflict] = []
    a_words = [t for t in a_tok if t[0] == "W"]
    b_words = [t for t in b_tok if t[0] == "W"]
    sm = difflib.SequenceMatcher(None, [t[1] for t in a_words], [t[1] for t in b_words], autojunk=False)
    matched_b = Counter()
    matched_a = 0
    for blk in sm.get_matching_blocks():
        matched_a += blk.size
        for j in range(blk.b, blk.b + blk.size):
            matched_b[b_words[j][3]] += 1
    words_per_line = Counter(t[3] for t in b_words)
    anchors = [li for li in range(len(b_lines)) if words_per_line[li] and matched_b[li] >= LINE_BELONGS * words_per_line[li]]
    # Every line between the first and the last anchored line belongs to the question (a line whose words were mostly
    # DROPPED by the reconstruction is exactly what must be reported); lines outside that span are running headers,
    # footers ("המשך בעמוד") or neighbouring questions.
    span = range(min(anchors), max(anchors) + 1) if anchors else range(0)
    in_question = set(span) | {li for li in range(len(b_lines)) if words_per_line[li] == 0}
    # math-only lines belong to the question when at least one of their atoms appears in A
    a_math = Counter(t[1] for t in a_tok if t[0] == "M")
    for li in list(in_question):
        if words_per_line[li] == 0:
            atoms = [t[1] for t in b_tok if t[3] == li and t[0] == "M"]
            if atoms and not any(a_math[x] for x in atoms):
                in_question.discard(li)

    coverage = matched_a / max(1, len(a_words))

    def line_info(li):
        bl = b_lines[li] if li is not None and 0 <= li < len(b_lines) else {}
        return dict(line=li, image_index=bl.get("image_index"), norm_bbox=list(bl.get("norm_bbox") or []))

    # --- Hebrew words
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a_seg = [a_words[i][2] for i in range(i1, i2)]
        b_seg = [b_words[j] for j in range(j1, j2) if b_words[j][3] in in_question]
        li = b_words[j1][3] if j1 < len(b_words) and j1 < j2 else (b_words[j1 - 1][3] if j1 > 0 else None)
        if op == "replace" and b_seg:
            conflicts.append(Conflict("word", " ".join(a_seg), " ".join(t[2] for t in b_seg), **line_info(b_seg[0][3])))
        elif op in ("delete", "replace") and a_seg:
            conflicts.append(Conflict("missing_in_photo", " ".join(a_seg), "", **line_info(li)))
        elif op == "insert" and b_seg:
            conflicts.append(Conflict("extra_in_photo", "", " ".join(t[2] for t in b_seg), **line_info(b_seg[0][3])))

    # --- formulas (structure), aligned by sequence
    a_m = [t for t in a_tok if t[0] == "M"]
    b_m = [t for t in b_tok if t[0] == "M" and t[3] in in_question]
    fm = difflib.SequenceMatcher(None, [t[1] for t in a_m], [t[1] for t in b_m], autojunk=False)
    for op, i1, i2, j1, j2 in (fm.get_opcodes() if check_formulas else []):
        if op != "replace":
            continue                         # atoms missing on one side are caught by the word/number checks or coverage
        for k in range(max(i2 - i1, j2 - j1)):
            if i1 + k >= i2 or j1 + k >= j2:
                break
            a_t, b_t = a_m[i1 + k], b_m[j1 + k]
            detail = ", ".join(_structure_diff(a_t[2], b_t[2])[:2])
            if _same_after_split(a_t[1], b_t[1]):
                continue
            conflicts.append(Conflict("formula", a_t[2], b_t[2], detail=detail, **line_info(b_t[3])))

    # --- numbers (text and formulas together: readers disagree on what is "math").
    # Numbers already explained by a formula conflict are not repeated; the rest are paired a<->b in reading order.
    covered_a, covered_b = Counter(), Counter()
    for c in conflicts:
        if c.kind == "formula":
            covered_a += numbers_in(c.a)
            covered_b += numbers_in(c.b)
    a_nums = numbers_in(" ".join(a_texts_no_labels(a_texts)))
    b_nums = Counter()
    for li in in_question:
        b_nums += numbers_in(_strip_label(b_lines[li].get("text", "")))
    only_a = list(((a_nums - b_nums) - covered_a).elements())
    only_b = list(((b_nums - a_nums) - covered_b).elements())

    def b_line_of(n):
        return next((i for i in sorted(in_question) if n in numbers_in(_strip_label(b_lines[i].get("text", "")))), None)
    for k in range(max(len(only_a), len(only_b))):
        a_n = only_a[k] if k < len(only_a) else ""
        b_n = only_b[k] if k < len(only_b) else ""
        conflicts.append(Conflict("number", a_n, b_n, **line_info(b_line_of(b_n) if b_n else None)))

    for li in sorted(in_question):
        if b_lines[li].get("unreadable") or "[?]" in (b_lines[li].get("text") or ""):
            conflicts.append(Conflict("unreadable", "", b_lines[li].get("text", ""), **line_info(li)))

    if a_words and coverage < MIN_COVERAGE:
        conflicts.insert(0, Conflict("incomplete", detail=f"הקריאה השנייה כיסתה רק {coverage:.0%} מהמילים — "
                                                          "ייתכן שהתמונה חתוכה או שהשורות לא זוהו; יש לבדוק ידנית."))
    status = "AGREED" if not conflicts else ("INCOMPLETE" if conflicts[0].kind == "incomplete" else "CONFLICTS")
    return {
        "version": CONSENSUS_VERSION, "reader": reader, "status": status, "coverage": round(coverage, 3),
        "lines_total": len(b_lines), "lines_in_question": len(in_question),
        "conflicts": [asdict(c) | {"message": c.message()} for c in _dedupe(conflicts)],
    }


def _strip_label_lines(txt: str) -> str:
    return "\n".join(_strip_label(l) for l in (txt or "").split("\n"))


def a_texts_no_labels(a_texts: list[str]) -> list[str]:
    return [_strip_label_lines(t) for t in a_texts]


def _structure_diff(a: str, b: str) -> list[str]:
    try:
        from diagram_engine.formula_pipeline import compare_structure
        return compare_structure(a, b)
    except Exception:
        return []


def _same_after_split(a: str, b: str) -> bool:
    """'f(x)=x^2' vs 'f(x)' + '=x^2' style splits are alignment artefacts, not misreads."""
    return a.replace(" ", "") == b.replace(" ", "")


def _dedupe(cs: list[Conflict]) -> list[Conflict]:
    seen, out = set(), []
    for c in cs:
        key = (c.kind, c.a, c.b, c.line)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def messages(report: dict[str, Any] | None, limit: int = 6) -> list[str]:
    if not report:
        return []
    return [c["message"] for c in report.get("conflicts", [])][:limit]
