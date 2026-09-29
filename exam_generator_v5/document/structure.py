"""Deterministic document structure from a PDF: running headers, page roles, question/subpart markers, cross-page continuity,
visual objects with roles and question/subpart binding. The PDF text layer is EVIDENCE only (never mathematical truth)."""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from .model import FullDocumentModel, PageModel, PageRole, QuestionModel, Subpart, VisualObject, VisualRole

HEB = re.compile(r"[\u0590-\u05FF]")
ARAB = re.compile(r"[\u0600-\u06FF]")
ADMIN = re.compile(r"מחברת\s+בחינה|מדבק|תעודת\s+זהות|לנבחנים\s+ולנבחנות|אגף\s+בכיר\s+בחינות|دفتر\s+امتحان")
INSTR = re.compile(r"הוראות\s+לנבחן|משך\s+הבחינה|מבנה\s+השאלון|בשאלון\s+זה|ענו\s+על")
DRAFT = re.compile(r"טיוטה|טיוטא")
HEB_NUM = {"אחת": 1, "שתיים": 2, "שתי": 2, "שלוש": 3, "ארבע": 4, "חמש": 5, "שש": 6, "שבע": 7, "שמונה": 8, "תשע": 9, "עשר": 10,
           "שתים": 2, "שלושה": 3, "ארבעה": 4}
QMARK = re.compile(r"^\.?(\d{1,2})\.?$")
SUBMARK = re.compile(r"^(?:([אבגדהוזח])\.|\.([אבגדהוזח]))$")     # 'א.' or '.א' (visual order in RTL text layers)


SCAN_TEXT_THRESHOLD = 40
OCR_DPI = 200


def is_scanned(page) -> bool:
    return len(page.get_text().strip()) < SCAN_TEXT_THRESHOLD and bool(page.get_image_info())


def _render(page, dpi: int = OCR_DPI):
    import io

    from PIL import Image
    pix = page.get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")


def _ocr_lines(page) -> list[dict]:
    """Scanned page: Tesseract words -> the same {text, bbox, spans} structure as the PDF text layer (PDF points)."""
    try:
        import pytesseract
    except Exception:
        return []
    img = _render(page)
    k = page.rect.width / img.width
    d = pytesseract.image_to_data(img, lang="heb+eng", config="--psm 4", output_type=pytesseract.Output.DICT, timeout=60)
    groups: dict = {}
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        if not t or float(d["conf"][i]) < 30:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        bb = [d["left"][i] * k, d["top"][i] * k, (d["left"][i] + d["width"][i]) * k, (d["top"][i] + d["height"][i]) * k]
        groups.setdefault(key, []).append({"text": t, "bbox": bb, "size": (bb[3] - bb[1]) * 1.1})
    out = []
    for spans in groups.values():
        xs0, ys0 = min(s_["bbox"][0] for s_ in spans), min(s_["bbox"][1] for s_ in spans)
        xs1, ys1 = max(s_["bbox"][2] for s_ in spans), max(s_["bbox"][3] for s_ in spans)
        out.append({"text": " ".join(s_["text"] for s_ in spans), "bbox": [xs0, ys0, xs1, ys1], "spans": spans, "ocr": True})
    return out


def _ocr_margin_numbers(page, body: list[dict] | None = None) -> list[dict]:
    """Scanned page: question numbers sit in a column RIGHT of the (right-aligned) text block. The block's right edge is
    measured from the OCR'd lines; only ink right of it is read (each blob separately, digits only, 300 dpi)."""
    try:
        import cv2
        import numpy as np
        import pytesseract
    except Exception:
        return []
    img = _render(page, 300)
    W, H = img.size
    k = page.rect.width / W
    rights = sorted(l["bbox"][2] for l in (body or []) if len(l["text"]) > 12)
    if not rights:
        return []
    edge = rights[int(0.8 * (len(rights) - 1))] / k                       # most lines end here (right-aligned Hebrew)
    x0 = int(edge + 0.006 * W)
    zone = np.asarray(img)[:, x0:int(0.985 * W)]
    bw = (zone < 140).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(bw, np.ones((5, 9), np.uint8)), connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h < 0.006 * H or h > 0.03 * H or w > 0.06 * W or y < 0.05 * H or y > 0.95 * H:
            continue
        crop = img.crop((x0 + x - 6, y - 6, x0 + x + w + 6, y + h + 6))
        crop = crop.resize((crop.width * 2, crop.height * 2))
        t = pytesseract.image_to_string(crop, lang="eng", config="--psm 7 -c tessedit_char_whitelist=0123456789.", timeout=20)
        t = t.strip().strip(".")
        bb = [(x0 + x) * k, y * k, (x0 + x + w) * k, (y + h) * k]
        # ink that belongs to an OCR'd text span on the same row is text, not a number column mark
        if any(sp["bbox"][2] >= bb[0] + 0.5 * (bb[2] - bb[0]) and sp["bbox"][1] < bb[3] and sp["bbox"][3] > bb[1]
               for l in (body or []) for sp in l["spans"] if not l.get("margin_number")):
            continue
        # the POSITION is the evidence of a new question; the digit reading is only a cross-check (blurry scans misread)
        out.append({"text": "#.", "read": t if re.fullmatch(r"\d{1,2}", t) else "", "bbox": bb,
                    "spans": [{"text": "#.", "bbox": bb, "size": 12.0}], "ocr": True, "margin_number": True})
    return out


def _raster_visuals(page, pno: int) -> list[VisualObject]:
    """Scanned page: figures = clusters of LARGE ink components (glyphs are small); evidence only, refined by PASS 2."""
    import numpy as np
    try:
        import cv2
    except Exception:
        return []
    img = np.asarray(_render(page, 150))
    H, W = img.shape
    k = page.rect.width / W
    otsu, _ = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = (img < max(150, min(225, otsu + 10))).astype(np.uint8)          # page-adaptive: thin grey scanned lines count
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    big = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if (w > 0.07 * W or h > 0.07 * H) and not (h < 0.006 * H and w < 0.5 * W) and a < 0.2 * W * H:
            big.append([x, y, x + w, y + h, a])
    clusters: list[list] = []
    for b in sorted(big, key=lambda b: (b[1], b[0])):
        c = next((c for c in clusters if b[0] <= c[2] + 0.02 * W and b[2] >= c[0] - 0.02 * W and b[1] <= c[3] + 0.02 * H and b[3] >= c[1] - 0.02 * H), None)
        if c is None:
            clusters.append(b[:4] + [1])
        else:
            c[0], c[1], c[2], c[3], c[4] = min(c[0], b[0]), min(c[1], b[1]), max(c[2], b[2]), max(c[3], b[3]), c[4] + 1
    out = []
    for x0, y0, x1, y1, cnt in clusters:
        if (x1 - x0) < 0.12 * W or (y1 - y0) < 0.06 * H or (y1 < 0.06 * H) or (y0 > 0.95 * H):
            continue
        vid = hashlib.sha1(f"{pno}:scan:{x0}:{y0}".encode()).hexdigest()[:10]
        out.append(VisualObject(visual_id=vid, visual_role=VisualRole.SOURCE_DIAGRAM, page=pno,
                                bbox=[round(v * k, 1) for v in (x0, y0, x1, y1)],
                                source_evidence={"why": "large ink components on a scanned page", "components": cnt, "scanned": True}))
    return out


def _lines(page) -> list[dict]:
    if is_scanned(page):
        body = _ocr_lines(page)
        W = page.rect.width
        for l in body:                              # body OCR digits in the margin are superseded by the dedicated read
            l["spans"] = [s_ for s_ in l["spans"] if not (s_["bbox"][2] > 0.86 * W and
                                                          re.fullmatch(r"[\W_]*\d{1,2}[\W_]*", s_["text"].replace("\u200f", "").replace("\u200e", "")))]
        return body + _ocr_margin_numbers(page, body)
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if txt:
                out.append({"text": txt, "bbox": l["bbox"], "spans": l["spans"]})
    return out


MARGIN_TOP, MARGIN_BOTTOM = 0.09, 0.92


def _in_margin(l: dict, H: float) -> bool:
    return l["bbox"][3] < MARGIN_TOP * H or l["bbox"][1] > MARGIN_BOTTOM * H


def _running(pages_lines: list[list[dict]], heights: list[float]) -> set[str]:
    """Running headers/footers: MARGIN lines repeated on at least half of the pages (body lines are never noise)."""
    cnt = Counter()
    for lines, H in zip(pages_lines, heights):
        cnt.update({re.sub(r"\d+", "#", l["text"]) for l in lines if _in_margin(l, H)})
    n = max(1, len(pages_lines))
    return {k for k, v in cnt.items() if v >= max(2, 0.5 * n)}


def declared_count(texts: list[str]) -> int | None:
    """'בשאלון זה שש שאלות' / 'ענו על ... 8–1' -> declared number of questions (evidence for segmentation)."""
    for t in texts:
        m = (re.search(r"בשאלון\s+זה\s+(\S+)\s+שאלות", t) or re.search(r"ובהם\s+(\S+)\s+שאלות", t)
             or re.search(r"שאלות\.?\s+(\S+)\s+ובהם", t) or re.search(r"שאלות\.?\s+(\S+)\s+זה\s+בשאלון", t))   # both logical and visual RTL word order
        if m and m.group(1) in HEB_NUM:
            return HEB_NUM[m.group(1)]
        m = re.search(r"(\d{1,2})\s*[–-]\s*1\s+ענו|ענו\s+על[^.\n]{0,40}?(\d{1,2})\s*[–-]\s*1(?!\d)", t)
        if m:
            return int(m.group(1) or m.group(2))
    return None


def classify_page(lines: list[dict], running: set[str], drawings: int, has_qmark: bool, has_sub: bool,
                  H: float = 842.0) -> tuple[PageRole, list[str]]:
    body = [l["text"] for l in lines if not (_in_margin(l, H) and re.sub(r"\d+", "#", l["text"]) in running)]
    text = "\n".join(body)
    heb = len(HEB.findall(text))
    arab = len(ARAB.findall(text))
    ev = [f"hebrew_chars={heb}", f"arabic_chars={arab}", f"vector_drawings={drawings}"]
    if ADMIN.search(text) and not has_qmark:
        return PageRole.ADMINISTRATIVE, ev + ["administrative wording"]
    if arab > heb and not has_qmark:
        return PageRole.ADMINISTRATIVE, ev + ["Arabic administrative page"]
    if has_qmark:
        return PageRole.QUESTION, ev + ["question-number marker"]
    if INSTR.search(text) and heb > 150 and not has_sub:
        return PageRole.INSTRUCTIONS, ev + ["instruction wording"]
    if DRAFT.search(text) and heb < 120:
        return PageRole.DRAFT, ev + ["draft title"]
    if has_sub or heb > 150:
        return PageRole.QUESTION_CONTINUATION, ev + ["question text without a new number"]
    if drawings > 1500 and heb < 120:
        return PageRole.RESPONSE_WORKSPACE, ev + ["dense ruled/grid drawing, no question text"]
    if heb < 120:
        return PageRole.DECORATIVE, ev + ["little content"]
    return PageRole.UNKNOWN, ev


def _visuals(page, pno: int, running_boxes: list) -> list[VisualObject]:
    """Cluster vector drawings + raster images into visual objects and give each a role from its own evidence."""
    W, H = page.rect.width, page.rect.height
    drs = page.get_drawings()
    # background lattice (graph-paper printed under the page): many thin short strokes of ONE repeated length
    thin = [d for d in drs if min(d["rect"].width, d["rect"].height) < 1.5]
    lens = Counter(round(max(d["rect"].width, d["rect"].height)) for d in thin)
    lattice_len = {L for L, n in lens.items() if n >= 150 and L > 3}
    lattice_len |= {L + 1 for L in lattice_len} | {L - 1 for L in lattice_len}
    rects = []
    for d in drs:
        r = d["rect"]
        if r.width * r.height > 0.9 * W * H or r.y1 < 0.06 * H or r.y0 > 0.94 * H:
            continue                                    # page frame / running header rules
        if min(r.width, r.height) < 1.5 and round(max(r.width, r.height)) in lattice_len:
            continue                                    # graph-paper background, not a diagram
        if d.get("fill") in ((1.0, 1.0, 1.0),) and d.get("color") in (None, (1.0, 1.0, 1.0)):
            continue                                    # white masks
        rects.append([r.x0, r.y0, r.x1, r.y1, d])
    for img in page.get_image_info():
        b = img["bbox"]
        if (b[2] - b[0]) * (b[3] - b[1]) > 0.002 * W * H:
            rects.append([b[0], b[1], b[2], b[3], None])
    clusters: list[list] = []
    for r in sorted(rects, key=lambda r: (r[1], r[0])):
        c = next((c for c in clusters if r[0] <= c[2] + 8 and r[2] >= c[0] - 8 and r[1] <= c[3] + 8 and r[3] >= c[1] - 8), None)
        if c is None:
            clusters.append([r[0], r[1], r[2], r[3], [r]])
        else:
            c[0], c[1], c[2], c[3] = min(c[0], r[0]), min(c[1], r[1]), max(c[2], r[2]), max(c[3], r[3])
            c[4].append(r)
    # transitive merge until stable (a later stroke may bridge two earlier clusters, e.g. axes + curve of one graph)
    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
                if a[0] <= b[2] + 8 and a[2] >= b[0] - 8 and a[1] <= b[3] + 8 and a[3] >= b[1] - 8:
                    clusters[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                    del clusters[j]
                    changed = True
                    break
            if changed:
                break
    words = page.get_text("words")
    out = []
    extra_boxes: list = []
    for c in clusters:
        rects_ = [m for m in c[4] if m[4] is not None and any(it[0] == "re" for it in m[4].get("items", []))
                  and 0.02 * W < m[2] - m[0] < 0.12 * W and 0.01 * H < m[3] - m[1] < 0.06 * H
                  and not any(m[0] <= (wd[0] + wd[2]) / 2 <= m[2] and m[1] <= (wd[1] + wd[3]) / 2 <= m[3] for wd in words)]
        rows_: dict = {}
        for m in rects_:
            rows_.setdefault(round(m[1] / 4), []).append(m)
        row = max(rows_.values(), key=len) if rows_ else []
        if len(row) >= 3 and len(row) < len(c[4]):             # a row of empty boxes inside a drawing = response template
            ids = {id(m) for m in row}
            c[4] = [m for m in c[4] if id(m) not in ids]
            c[0], c[1] = min(m[0] for m in c[4]), min(m[1] for m in c[4])
            c[2], c[3] = max(m[2] for m in c[4]), max(m[3] for m in c[4])
            extra_boxes += row
    for m in extra_boxes:
        vid = hashlib.sha1(f"{pno}:box:{m[0]:.0f}:{m[1]:.0f}".encode()).hexdigest()[:10]
        out.append(VisualObject(visual_id=vid, visual_role=VisualRole.ANSWER_BOX, page=pno, bbox=[round(v, 1) for v in m[:4]],
                                source_evidence={"why": "empty box in a row of boxes (split from a drawing)", "grid": [1, 1]}))
    for i, (x0, y0, x1, y1, members) in enumerate(clusters):
        w, h = x1 - x0, y1 - y0
        if w < 0.05 * W or h < 0.02 * H:
            continue
        inside = [wd for wd in words if x0 <= (wd[0] + wd[2]) / 2 <= x1 and y0 <= (wd[1] + wd[3]) / 2 <= y1]
        n = len(members)
        thin = sum(1 for m in members if m[4] is not None and (m[2] - m[0] < 1.5 or m[3] - m[1] < 1.5))
        # content strokes: curves or oblique lines. An empty grid / answer box has only axis-aligned rules.
        curvy = 0
        for m in members:
            if m[4] is None:
                curvy += 1                                   # raster image = content
                continue
            for it in m[4].get("items", []):
                if it[0] == "c":
                    curvy += 1
                elif it[0] == "l":
                    (a, b) = it[1], it[2]
                    if abs(a.x - b.x) > 1.0 and abs(a.y - b.y) > 1.0:
                        curvy += 1
        if (x0 < 0.06 * W or x1 > 0.94 * W) and h > 0.7 * H and w < 0.2 * W:
            role, why = VisualRole.DECORATIVE, "tall strip on the page edge (booklet border)"
        elif curvy >= 3:
            role, why = VisualRole.SOURCE_DIAGRAM, f"content strokes (curves/oblique lines: {curvy})"
        elif n > 400 and thin > 0.8 * n and w * h > 0.15 * W * H:
            role, why = VisualRole.GRAPH_PAPER, "dense regular thin lines over a large area"
        elif (n > 60 and thin > 0.7 * n and len(inside) <= 3) or (n >= 6 and thin >= 0.9 * n and not inside):
            role, why = VisualRole.RESPONSE_TEMPLATE, "axis-aligned grid without content"
        elif n <= 6 and not inside and all(m[4] is not None for m in members):
            role, why = VisualRole.ANSWER_BOX, "empty rectangle"
        else:
            role, why = VisualRole.SOURCE_DIAGRAM, "drawing with content (refined by PASS 2)"
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(W, x1), min(H, y1)      # clip to the page
        vid = hashlib.sha1(f"{pno}:{x0:.0f}:{y0:.0f}:{x1:.0f}:{y1:.0f}".encode()).hexdigest()[:10]
        grid = None
        if role == VisualRole.RESPONSE_TEMPLATE:            # rows x cols of an empty grid, from its own rules
            xs_ = sorted({round((m[0] + m[2]) / 2) for m in members if m[4] is not None and m[2] - m[0] < 1.5})
            ys_ = sorted({round((m[1] + m[3]) / 2) for m in members if m[4] is not None and m[3] - m[1] < 1.5})
            dedup = lambda v: [a for i, a in enumerate(v) if i == 0 or a - v[i - 1] > 2]  # noqa: E731
            grid = [max(1, len(dedup(ys_)) - 1), max(1, len(dedup(xs_)) - 1)]
        out.append(VisualObject(visual_id=vid, visual_role=role, page=pno, bbox=[round(v, 1) for v in (x0, y0, x1, y1)],
                                source_evidence={"primitives": n, "thin": thin, "words_inside": len(inside), "why": why, "grid": grid}))
    return out


def build_document(pdf_bytes: bytes) -> FullDocumentModel:
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_lines = [_lines(p) for p in doc]
    heights = [p.rect.height for p in doc]
    running = _running(pages_lines, heights)
    model = FullDocumentModel(metadata={"pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "page_count": len(doc)})
    model.declared_question_count = declared_count(["\n".join(l["text"] for l in ls) for ls in pages_lines])
    # markers (right margin, not running headers)
    markers = []
    for pi, (page, lines) in enumerate(zip(doc, pages_lines)):
        W, H = page.rect.width, page.rect.height
        for l in lines:
            if _in_margin(l, H) and not (l.get("margin_number") and l["bbox"][1] > 0.05 * H):
                continue                                # headers, footers and page numbers are never markers
            for s in l["spans"]:
                t = s["text"].strip()
                if t == "#." and l.get("margin_number"):
                    markers.append(("Q", -1, pi, s["bbox"][1]))
                    continue
                m = QMARK.fullmatch(t)
                if m and s["bbox"][2] > 0.86 * W and s["size"] >= 9:
                    markers.append(("Q", int(m.group(1)), pi, s["bbox"][1]))
                m2 = SUBMARK.fullmatch(t)
                if m2 and s["bbox"][2] > 0.8 * W:
                    markers.append(("S", m2.group(1) or m2.group(2), pi, s["bbox"][1]))
    # the question sequence must increase 1, 2, 3 ... (instruction lists and page numbers are rejected by the sequence)
    blind = [(pi, y) for (kind, val, pi, y) in markers if kind == "Q" and val == -1]
    if blind:                                               # scanned pages: number column marks without a reliable digit
        instr_pages = {pi for pi, ls in enumerate(pages_lines) if INSTR.search("\n".join(l["text"] for l in ls))
                       and re.search(r"הוראות|משך\s+הבחינה", "\n".join(l["text"] for l in ls))}
        blind = sorted(b for b in blind if b[0] not in instr_pages)
        markers = [m for m in markers if not (m[0] == "Q" and m[1] == -1)] + \
                  [("Q", i + 1, pi, y) for i, (pi, y) in enumerate(blind)]
        model.metadata["scanned_numbering"] = "positional (number column), validated against the declared count"
    qmarks = sorted([m for m in markers if m[0] == "Q"], key=lambda m: (m[2], m[3]))
    listy = {pg for pg, n in Counter(m[2] for m in qmarks).items() if n > 3}      # numbered lists (instructions), not questions
    qmarks = [m for m in qmarks if m[2] not in listy]
    seq, expect = [], 1
    candidates_by_page = {}
    for m in qmarks:
        candidates_by_page.setdefault(m[2], []).append(m)
    best = []
    for start_page in sorted(candidates_by_page):
        seq, expect = [], 1
        for m in qmarks:
            if m[2] < start_page:
                continue
            if m[1] == expect:
                seq.append(m)
                expect += 1
        if len(seq) > len(best):
            best = seq
    qpages = {m[2] for m in best}
    first_q = min(qpages) if qpages else None
    drawings = [len(p.get_drawings()) for p in doc]
    for pi, (page, lines) in enumerate(zip(doc, pages_lines)):
        has_sub = any(m[0] == "S" and m[2] == pi for m in markers)
        role, ev = classify_page(lines, running, drawings[pi], pi in qpages, has_sub, page.rect.height)
        if first_q is not None and pi < first_q and role == PageRole.QUESTION_CONTINUATION:
            role, ev = PageRole.INSTRUCTIONS, ev + ["before the first question: cannot continue a question"]
        model.pages.append(PageModel(index=pi + 1, width=page.rect.width, height=page.rect.height, role=role, role_evidence=ev,
                                     text_layer_chars=sum(len(l["text"]) for l in lines), vector_drawings=drawings[pi]))
    # questions + continuity
    for k, m in enumerate(best):
        nxt = best[k + 1] if k + 1 < len(best) else None
        q = QuestionModel(number=m[1], start={"page": m[2] + 1, "y": m[3]})
        end_page = (nxt[2] if nxt else len(doc) - 1)
        for pi in range(m[2], end_page + 1):
            role = model.pages[pi].role
            if pi == m[2] or (nxt and pi == nxt[2] and nxt[3] > 0.25 * doc[pi].rect.height) or role == PageRole.QUESTION_CONTINUATION:
                q.pages.append(pi + 1)
            elif role != PageRole.QUESTION:
                if role in (PageRole.RESPONSE_WORKSPACE,):
                    q.continuation_metadata.setdefault("response_pages", []).append(pi + 1)
                break
        q.pages = sorted(set(q.pages))
        q.end = {"page": q.pages[-1], "y": (nxt[3] if nxt and nxt[2] + 1 == q.pages[-1] else doc[q.pages[-1] - 1].rect.height)}
        q.continuation_metadata["spans_pages"] = len(q.pages) > 1
        model.questions.append(q)
    # subparts -> the question whose region contains them
    def owner(pi, y):
        for q in model.questions:
            if (q.start["page"] - 1, q.start["y"]) <= (pi, y) and (pi, y) < (q.end["page"] - 1, q.end["y"] + 1e-6) and (pi + 1) in q.pages:
                return q
        return None
    for m in markers:
        if m[0] == "S":
            q = owner(m[2], m[3])
            if q is not None and not any(s.label == m[1] and s.page == m[2] + 1 for s in q.subparts):
                q.subparts.append(Subpart(label=m[1], page=m[2] + 1, y=m[3]))
    # visuals -> question + subpart (the last subpart marker above the visual on the same question)
    for pi, page in enumerate(doc):
        if model.pages[pi].role in (PageRole.ADMINISTRATIVE, PageRole.INSTRUCTIONS, PageRole.DECORATIVE):
            continue
        for v in (_raster_visuals(page, pi + 1) if is_scanned(page) else _visuals(page, pi + 1, [])):
            if v.visual_role == VisualRole.DECORATIVE:
                continue                                    # booklet borders / ornaments are not content
            q = owner(pi, v.bbox[1]) or owner(pi, v.bbox[3])
            if model.pages[pi].role in (PageRole.RESPONSE_WORKSPACE, PageRole.DRAFT):
                # nothing on a workspace/draft page is source content: it is where the student writes
                v.visual_role = VisualRole.ANSWER_WORKSPACE if v.visual_role in (VisualRole.GRAPH_PAPER, VisualRole.SOURCE_DIAGRAM,
                                                                                 VisualRole.UNKNOWN) else v.visual_role
                prev = next((qq for qq in model.questions if (pi + 1) in qq.continuation_metadata.get("response_pages", [])), None)
                if prev is not None:
                    v.associated_question = prev.number
                    prev.response_regions.append(v)
                continue
            if q is None:
                continue
            v.associated_question = q.number
            above = [s for s in q.subparts if (s.page, s.y) <= (pi + 1, v.bbox[1] + 2)]
            v.associated_subpart = above[-1].label if above else None
            (q.response_regions if v.visual_role in (VisualRole.RESPONSE_TEMPLATE, VisualRole.ANSWER_BOX, VisualRole.GRAPH_PAPER,
                                                     VisualRole.ANSWER_WORKSPACE) else q.visual_objects).append(v)
    for q in model.questions:
        q.visual_objects = group_options(q.visual_objects, doc)
    if model.declared_question_count and model.declared_question_count != len(model.questions):
        model.warnings.append(f"QUESTION_COUNT_MISMATCH: השאלון מצהיר על {model.declared_question_count} שאלות, זוהו {len(model.questions)}.")
    return model


OPTION_LABEL = re.compile(r"^(IV|I{1,3}|V|[אבגד])\.?$")


def group_options(visuals: list[VisualObject], doc) -> list[VisualObject]:
    """Several same-size source visuals of one question/subpart laid out side by side = ONE GraphOptionGroup
    (options kept separate, in order, with the label printed next to each)."""
    src = [v for v in visuals if v.visual_role == VisualRole.SOURCE_DIAGRAM]
    rest = [v for v in visuals if v.visual_role != VisualRole.SOURCE_DIAGRAM]
    used, out = set(), []
    for i, v in enumerate(src):
        if i in used:
            continue
        w, h = v.bbox[2] - v.bbox[0], v.bbox[3] - v.bbox[1]
        grp = [i] + [j for j in range(i + 1, len(src)) if j not in used and src[j].page == v.page
                     and src[j].associated_subpart == v.associated_subpart
                     and abs((src[j].bbox[2] - src[j].bbox[0]) - w) < 0.3 * w and abs((src[j].bbox[3] - src[j].bbox[1]) - h) < 0.6 * h]
        if len(grp) < 2:
            out.append(v)
            continue
        used.update(grp)
        members = [src[j] for j in grp]
        page = doc[v.page - 1]
        words = page.get_text("words") if page.get_text().strip() else []
        opts = []
        for m in sorted(members, key=lambda m: (round(m.bbox[1] / 40), -m.bbox[0])):     # rows top->bottom, right->left (RTL)
            x0, y0, x1, y1 = m.bbox
            near = [wd for wd in words if OPTION_LABEL.fullmatch(wd[4].strip()) and x0 - 15 <= (wd[0] + wd[2]) / 2 <= x1 + 15
                    and y0 - 25 <= (wd[1] + wd[3]) / 2 <= y1 + 30]
            label = min(near, key=lambda wd: abs((wd[1] + wd[3]) / 2 - y1))[4].strip(". ") if near else ""
            opts.append({"option_id": m.visual_id, "label": label, "bbox": m.bbox})
        box = [min(m.bbox[0] for m in members), min(m.bbox[1] for m in members), max(m.bbox[2] for m in members), max(m.bbox[3] for m in members)]
        out.append(VisualObject(visual_id="grp_" + v.visual_id, visual_role=VisualRole.SOURCE_GRAPH, page=v.page, bbox=box,
                                associated_question=v.associated_question, associated_subpart=v.associated_subpart,
                                semantic_model={"type": "GraphOptionGroup", "options": opts},
                                source_evidence={"why": f"{len(members)} same-size visuals side by side"}))
    return out + rest
