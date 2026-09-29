"""Canonical TEXT STRUCTURE (recognition -> DOCX). A text field is split into TextBlocks instead of being written as one
string: SOFT_WRAP line breaks (page width) are joined, HARD paragraphs / SUBSECTIONS / DISPLAY formulas stay separate blocks.
Punctuation is content: it is never added, removed or moved here."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TERMINAL = ".:;?!"
SUBSECTION = re.compile(r"^\s*(?:\(\s*(\d{1,2}|[ivx]{1,4}|[אבגדהוזח])\s*\)|(\d{1,2})\.(?=\s))\s*")   # (1) (iii) (א) 1.
SECTION = re.compile(r"^\s*(?:סעיף\s+)?([אבגדהוזחט])[.)]\s+")             # א.  ב)
DISPLAY = re.compile(r"^\s*\$\$.*\$\$\s*$")
INLINE_SUB = re.compile(r"(?<=[.:;?!])\s+(?=\(\s*\d{1,2}\s*\)\s)")          # "... . (2) ..." = a flattened subsection
INLINE_SEC = re.compile(r"(?<=[.:;?!])\s+(?=[אבגדהו]\.\s)")                 # "... . ב. ..." = a flattened section


@dataclass
class TextBlock:
    block_type: str                     # PARAGRAPH | SUBSECTION | DISPLAY_FORMULA
    text: str
    paragraph_id: int
    subsection_id: str = ""
    terminal_punctuation: str = ""
    source_lines: list[int] = field(default_factory=list)


def blocks(text: str, preserve_lines: bool = False) -> list[TextBlock]:
    """Line-break classification:
    blank line -> HARD paragraph; line starting with (n) -> SUBSECTION; $$...$$ line -> DISPLAY_FORMULA;
    previous line ends with . : ; ? ! -> HARD paragraph (a new sentence on its own line);
    otherwise -> SOFT_WRAP (joined with one space; no character is removed)."""
    text = INLINE_SUB.sub("\n", text or "")                                 # restore subsections flattened inline
    out: list[TextBlock] = []
    pid = 0
    cur: TextBlock | None = None
    lines = text.replace("\r\n", "\n").split("\n")
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            cur = None                                                      # HARD paragraph boundary
            continue
        m = SUBSECTION.match(line)
        if DISPLAY.match(line):
            pid += 1
            out.append(TextBlock("DISPLAY_FORMULA", line.strip(), pid, source_lines=[i]))
            cur = None
            continue
        if m:
            pid += 1
            cur = TextBlock("SUBSECTION", line.strip(), pid, subsection_id=m.group(1) or m.group(2), source_lines=[i])
            out.append(cur)
            continue
        if preserve_lines and cur is not None and cur.text and cur.block_type in ("PARAGRAPH", "SUBSECTION"):
            cur.text = cur.text + "\n" + line.strip()                        # SOURCE LINE BREAK kept (w:br in Word)
            cur.source_lines.append(i)
            continue
        if cur is not None and cur.text and cur.text[-1] not in TERMINAL and not cur.text.rstrip().endswith("$"):
            cur.text = cur.text + " " + line.strip()                         # SOFT_WRAP (never right after a formula)
            cur.source_lines.append(i)
            continue
        if cur is not None and cur.block_type == "SUBSECTION" and cur.text[-1] in TERMINAL and not line.strip()[:1].isdigit():
            pass
        pid += 1
        cur = TextBlock("PARAGRAPH", line.strip(), pid, source_lines=[i])
        out.append(cur)
    for b in out:
        b.terminal_punctuation = b.text[-1] if b.text and b.text[-1] in TERMINAL else ""
    return out


_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_COORD_PAIR = re.compile(r"\(\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*(?:,\s*-?\d+(?:\.\d+)?\s*)?\)")


def punctuation_commas(text: str) -> int:
    """Commas that are PUNCTUATION of the Hebrew text: a Hebrew word within a short window on either side. Thousands
    separators (2,100), coordinate commas ((3,4), (a,0)), commas between formulas and garbled PDF math ('( , )') are not."""
    t = (text or "").replace("{,}", "")
    t = _COORD_PAIR.sub("()", t)
    t = _THOUSANDS_COMMA.sub("", t)
    t = re.sub(r"\$[^$]*\$", lambda m: "x" * len(m.group(0)), t)          # math content never counts as Hebrew context
    n = 0
    heb = re.compile(r"[\u0590-\u05FF]{2,}")
    for m in re.finditer(",", t):
        before = t[:m.start()].split()
        after = t[m.end():].split()
        prev_tok = before[-1] if before else ""
        # punctuation of the Hebrew text: the previous word is Hebrew, or Hebrew follows within the next two words
        # ("AB=AC, D על BC"); a list of math items ("a1 , a2 , a3", "$a$, $b$") is not punctuation
        nxt = after[0] if after else ""
        point_name = bool(re.fullmatch(r"[A-Z](?:'|′)?[.,]?", nxt))
        if heb.search(prev_tok) or heb.search(nxt) or (point_name and len(after) > 1 and heb.search(after[1])):
            n += 1
    return n


def structure_summary(q) -> dict:
    """What the reconstruction contains (compared with source evidence by the fidelity gate)."""
    subs = sum(1 for s in q.sections for b in blocks(s.text) if b.block_type == "SUBSECTION")
    disp = sum(1 for t in [q.text] + [s.text for s in q.sections] for b in blocks(t) if b.block_type == "DISPLAY_FORMULA")
    commas = sum(punctuation_commas(t) for t in [q.text] + [s.text for s in q.sections])
    return {"sections": len(q.sections), "subsections": subs, "display_formulas": disp, "commas": commas,
            "flattened_sections_in_stem": len(INLINE_SEC.findall(q.text or ""))}


# ---------------------------------------------------------------- source structure evidence
_SEC_MARK = re.compile(r"(?:^|\s)(?:[אבגדהו]\.|\.[אבגדהו])(?=\s|$)")
_SUB_MARK = re.compile(r"\(\s*\d{1,2}\s*\)")


def source_structure(text_layer: str) -> dict:
    """Section / subsection markers and commas of an INDEPENDENT source text (PDF text layer or OCR)."""
    t = text_layer or ""
    secs = sorted(set(m.group(0).strip().strip(".") for m in _SEC_MARK.finditer(t)))
    return {"sections": len(secs), "section_labels": secs, "subsections": len(set(_SUB_MARK.findall(t))),
            "subsection_marks": len(_SUB_MARK.findall(t)), "commas": punctuation_commas(t)}


def fidelity_issues(q, source_text: str | None, reliable_commas: bool) -> list[str]:
    """TEXT_STRUCTURE_MISMATCH candidates (teacher review, never auto-export)."""
    out = []
    mine = structure_summary(q)
    if mine["flattened_sections_in_stem"]:
        out.append("TEXT_STRUCTURE_MISMATCH: סעיפים מופיעים בתוך נוסח הגזע (המבנה שוטח) — יש לבדוק.")
    for s in q.sections:
        if INLINE_SEC.search(s.text or ""):
            out.append(f"TEXT_STRUCTURE_MISMATCH: סעיף {s.section_id} מכיל סעיף נוסף בתוכו — יש לבדוק.")
    if not source_text:
        return out
    src = source_structure(source_text)
    if src["sections"] >= 2 and mine["sections"] and src["sections"] != mine["sections"]:
        out.append(f"TEXT_STRUCTURE_MISMATCH: במקור {src['sections']} סעיפים, בשחזור {mine['sections']}.")
    if src["subsections"] >= 2 and src["subsections"] > mine["subsections"]:
        out.append(f"TEXT_STRUCTURE_MISMATCH: במקור {src['subsections']} תת-סעיפים, בשחזור {mine['subsections']}.")
    if reliable_commas and src["commas"] - mine["commas"] >= 2:
        out.append(f"TEXT_STRUCTURE_MISMATCH: במקור {src['commas']} פסיקים, בשחזור {mine['commas']} — ייתכן שפיסוק אבד.")
    return out


HEB_K = {1: "אחד", 2: "שניים", 3: "שלושה", 4: "ארבעה", 5: "חמישה", 6: "שישה", 7: "שבעה", 8: "שמונה"}
HEB_OF_N = {2: "משני", 3: "משלושת", 4: "מארבעת", 5: "מחמשת", 6: "משישת", 7: "משבעת", 8: "משמונת", 9: "מתשעת", 10: "מעשרת"}


def choice_sentence(k: int, n: int, first: str, last: str, members: list[str] | None = None) -> str:
    """Student wording: 'ענו על שלושה מארבעת הסעיפים א–ד.' (no internal points); a non-contiguous group lists its members."""
    kk, nn = HEB_K.get(k, str(k)), HEB_OF_N.get(n, f"מתוך {n}")
    if members:
        span = ", ".join(members[:-1]) + " ו־" + members[-1] if len(members) > 1 else members[0]
    else:
        span = f"{first}–{last}"
    return f"ענו על {kk} {nn} הסעיפים {span}."


def signature(q) -> str:
    """Structure part of the teacher-verification fingerprint (section ids, subsection counts, punctuation commas)."""
    parts = [f"{s.section_id}:{sum(1 for b in blocks(s.text) if b.block_type == 'SUBSECTION')}" for s in q.sections]
    return "|".join(parts) + f"#c{structure_summary(q)['commas']}"


def ocr_marker_text(img_pil) -> str:
    """Hebrew OCR with WORD BOXES: the right-most token of every line is its start (RTL); a lone letter there, with or
    without '.', ')' or '(' around it, is a subpart marker. Returns text with normalised 'א.' markers."""
    import pytesseract
    d = pytesseract.image_to_data(img_pil, lang="heb+eng", config="--psm 4", output_type=pytesseract.Output.DICT, timeout=30)
    lines: dict = {}
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        if t and float(d["conf"][i]) >= 20:
            lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append((d["left"][i] + d["width"][i], t))
    out = []
    for toks in lines.values():
        toks.sort(reverse=True)                                           # right -> left
        first = toks[0][1]
        m = re.fullmatch(r"[.(]?([אבגדהוזח])[.)]?", first) or re.fullmatch(r"([אבגדהוזח])[.)].*", first)
        words = " ".join(w for _, w in toks)
        out.append((f"{m.group(1)}. " + words) if m else words)
    return "\n".join(out)


# ---------------------------------------------------------------- source line-break transfer
_HEB_WORD = re.compile(r"[\u05D0-\u05EA][\u05D0-\u05EA\u05F3\u05F4\"'־\-]*")
_MATH_SEG = re.compile(r"\$\$.*?\$\$|\$[^$]*\$", re.S)


def _norm(w: str) -> str:
    return re.sub(r"[\"'״׳־\-]", "", w)


def transfer_line_breaks(text: str, source_lines: list[str], min_coverage: float = 0.6) -> str:
    """Insert a line break wherever the SOURCE broke the line: the Hebrew words of the reconstruction are aligned with the
    words of the source's visual lines (PDF text layer / OCR); a break goes between two consecutive words that the source
    placed on different lines. Math never provides alignment evidence. Low coverage -> text unchanged (never guessed)."""
    import difflib
    if not text or not source_lines:
        return text
    masked = _MATH_SEG.sub(lambda m: "\x00" * len(m.group(0)), text)
    tw = [(_norm(m.group(0)), m.start(), m.end()) for m in _HEB_WORD.finditer(masked)]
    tw = [t for t in tw if t[0]]
    if len(tw) < 3:
        return text

    def stream(lines):
        out, head = [], []
        for li, line in enumerate(lines):
            toks = line.split()
            hw = [(_norm(x), li) for x in toks if _HEB_WORD.fullmatch(x.strip(".,:;()")) and _norm(x.strip(".,:;()"))]
            out += [(w.strip(".,:;()"), li) for w, li in hw]
            first_heb = next((k for k, x in enumerate(toks) if _HEB_WORD.fullmatch(x.strip(".,:;()"))), None)
            head.append(bool(first_heb) and first_heb > 0 and not re.fullmatch(r"[א-ת][.)]|\(\d+\)|\d+\.", toks[0]))
        return out, head
    best = None
    for lines in (source_lines, [" ".join(reversed(l.split())) for l in source_lines]):     # RTL text layers may be reversed
        sw, head = stream(lines)
        sm = difflib.SequenceMatcher(None, [t[0] for t in tw], [w for w, _ in sw], autojunk=False)
        pairs = [(a + k, b + k) for a, b, n in sm.get_matching_blocks() for k in range(n)]
        if best is None or len(pairs) > len(best[0]):
            best = (pairs, sw, head)
    pairs, sw, head = best
    if len(pairs) < min_coverage * len(tw):
        return text
    cuts = []
    for (i, j), (i2, j2) in zip(pairs, pairs[1:]):
        li, li2 = sw[j][1], sw[j2][1]
        if li2 <= li or i2 != i + 1 or (j2 > 0 and sw[j2 - 1][1] == li2):
            continue                                                      # same line / not the first word of the new line
        gap_start, pos = tw[i][2], tw[i2][1]
        gap = text[gap_start:pos]
        if "\n" in gap:
            continue
        maths = list(_MATH_SEG.finditer(gap))
        if head[li2] and maths:
            pos = gap_start + maths[-1].start()                           # the new source line starts with that formula
            while pos > gap_start and text[pos - 1] in "(־ ":
                pos -= 1 if text[pos - 1] != " " else 0
                if text[pos - 1] == " ":
                    break
        cuts.append(pos)
    out = text
    for pos in sorted(set(cuts), reverse=True):
        a = pos
        while a > 0 and out[a - 1] == " ":
            a -= 1
        out = out[:a] + "\n" + out[pos:].lstrip(" ")
    return out
