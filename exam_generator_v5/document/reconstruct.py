"""MODE B: full document -> per-question source regions (cropped from the FULL-RESOLUTION page render) that enter the normal
question pipeline (PASS 1 -> PASS 2 -> verification -> teacher review -> DOCX). Response templates are carried as EMPTY
templates; they are never solved or filled."""
from __future__ import annotations

import io

from PIL import Image

from .model import FullDocumentModel, QuestionModel, VisualRole

PREVIEW_DPI = 150            # working / preview derivative only
ROI_DPI = 450                # vector PDFs: question regions are re-rendered from the ORIGINAL PDF at recognition resolution
RESPONSE_KINDS = (VisualRole.RESPONSE_TEMPLATE, VisualRole.ANSWER_BOX)


def render_pages(pdf_bytes: bytes, dpi: int = PREVIEW_DPI) -> list[bytes]:
    """Page PREVIEWS (never the master evidence)."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    return [p.get_pixmap(dpi=dpi).tobytes("png") for p in doc]


def page_master_region(pdf_bytes: bytes, page_no: int, y0: float, y1: float) -> tuple[bytes, dict]:
    """HIGH-RESOLUTION source evidence for a page region (PDF points):
    - scanned page (one embedded raster): the ORIGINAL embedded image is cropped at its native resolution (no re-sampling);
    - vector/text page: the region is rendered from the original PDF at ROI_DPI (small labels, primes, ticks survive)."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_no - 1]
    W = page.rect.width
    imgs = page.get_images(full=True)
    if len(page.get_text().strip()) < 40 and len(imgs) == 1:
        info = page.get_image_info(xrefs=True)[0]
        bx0, by0, bx1, by1 = info["bbox"]
        raw = doc.extract_image(imgs[0][0])
        with Image.open(io.BytesIO(raw["image"])) as im:
            im = im.convert("RGB")
            ky = im.height / max(1e-6, by1 - by0)
            box = (0, max(0, int((y0 - by0) * ky)), im.width, min(im.height, int((y1 - by0) * ky)))
            out = io.BytesIO()
            im.crop(box).save(out, format="PNG")
        return out.getvalue(), {"source": "embedded_raster", "native_px": [im.width, im.height], "dpi_equiv": round(im.width / (W / 72), 1)}
    clip = pymupdf.Rect(0, y0, W, y1)
    pix = page.get_pixmap(dpi=ROI_DPI, clip=clip)
    return pix.tobytes("png"), {"source": "vector_pdf_render", "dpi": ROI_DPI}


def question_regions(model: FullDocumentModel, q: QuestionModel) -> list[tuple[int, float, float]]:
    """[(page, y0, y1)] in PDF points: from the question marker to the next marker, across continuation pages."""
    regs = []
    for pno in q.pages:
        H = model.pages[pno - 1].height
        y0 = max(0.0, q.start["y"] - 12) if pno == q.start["page"] else 0.07 * H
        y1 = (q.end["y"] - 4) if pno == q.end["page"] and q.end["y"] < H else 0.95 * H
        regs.append((pno, y0, max(y0 + 20, y1)))
    return regs


def crop_region(page_png: bytes, page_w: float, page_h: float, y0: float, y1: float) -> bytes:
    with Image.open(io.BytesIO(page_png)) as im:
        k = im.height / page_h
        box = (0, int(y0 * k), im.width, int(y1 * k))
        out = io.BytesIO()
        im.convert("RGB").crop(box).save(out, format="PNG")
        return out.getvalue()


def region_lines(page, y0: float, y1: float, exclude: list | None = None) -> list[str]:
    """VISUAL lines of a page region: words grouped by their vertical centre and ordered right -> left (Hebrew reading
    order). Words inside figure boxes (axis labels, point names) and in the page margins (running headers) are excluded."""
    H = page.rect.height
    words = [w for w in page.get_text("words") if y0 <= (w[1] + w[3]) / 2 <= y1 and 0.06 * H < (w[1] + w[3]) / 2 < 0.94 * H]
    ex = exclude or []
    words = [w for w in words if not any(b[0] - 2 <= (w[0] + w[2]) / 2 <= b[2] + 2 and b[1] - 2 <= (w[1] + w[3]) / 2 <= b[3] + 2 for b in ex)]
    if not words:
        return []
    hts = sorted(w[3] - w[1] for w in words)
    tol = 0.55 * hts[len(hts) // 2]
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - yc) <= tol:
            lines[-1][1].append(w)
            lines[-1][0] = (lines[-1][0] * (len(lines[-1][1]) - 1) + yc) / len(lines[-1][1])
        else:
            lines.append([yc, [w]])
    return [" ".join(x[4] for x in sorted(ws, key=lambda w: -w[2])) for _, ws in lines]


def questions_data(pdf_bytes: bytes, model: FullDocumentModel, total_points: float = 100.0) -> list[dict]:
    """Input for exam_core.run_full_analysis: one entry per LOGICAL question (continuations merged)."""
    n = max(1, len(model.questions))
    out = []
    for q in model.questions:
        masters, evidence, text_layer, src_lines = [], [], [], []
        import pymupdf
        _doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        for p, y0, y1 in question_regions(model, q):
            m, ev = page_master_region(pdf_bytes, p, y0, y1)
            masters.append(m)
            evidence.append({"page": p, "y0": y0, "y1": y1, **ev})
            text_layer.append(_doc[p - 1].get_text(clip=pymupdf.Rect(0, y0, _doc[p - 1].rect.width, y1)))
            src_lines += region_lines(_doc[p - 1], y0, y1, [v.bbox for v in q.visual_objects if v.page == p])
        crops = masters                                      # the editor derives its own working copy from the master
        templates = merge_box_rows([{"role": v.visual_role.value, "page": v.page, "bbox": v.bbox, "subpart": v.associated_subpart,
                                     "grid": v.source_evidence.get("grid") or [1, 1]}
                                    for v in q.response_regions if v.visual_role in RESPONSE_KINDS])
        out.append({"question_number": q.number, "points": round(total_points / n, 2), "images": crops, "masters": masters,
                    "source_evidence": evidence,
                    "document": {"text_layer": "\n".join(text_layer), "source_lines": src_lines, "pages": q.pages, "subparts": [s.label for s in q.subparts],
                                 "visuals": [v.model_dump() for v in q.visual_objects], "response_templates": templates}})
    return out


def merge_box_rows(templates: list[dict]) -> list[dict]:
    """A row of same-size empty answer boxes (e.g. under a normal curve) is ONE 1 x N template."""
    boxes = sorted([t for t in templates if t["role"] == "ANSWER_BOX"], key=lambda t: (t["page"], round(t["bbox"][1] / 6), t["bbox"][0]))
    rest = [t for t in templates if t["role"] != "ANSWER_BOX"]
    rows: list[list[dict]] = []
    for b in boxes:
        h = b["bbox"][3] - b["bbox"][1]
        if rows and rows[-1][0]["page"] == b["page"] and abs(rows[-1][0]["bbox"][1] - b["bbox"][1]) < 0.3 * h:
            rows[-1].append(b)
        else:
            rows.append([b])
    for r in rows:
        if len(r) == 1:
            rest.append(r[0])
        else:
            rest.append({"role": "RESPONSE_TEMPLATE", "page": r[0]["page"], "subpart": r[0]["subpart"], "grid": [1, len(r)],
                         "bbox": [min(x["bbox"][0] for x in r), min(x["bbox"][1] for x in r), max(x["bbox"][2] for x in r), max(x["bbox"][3] for x in r)],
                         "kind": "box_row"})
    return rest


def templates_by_question(data: list[dict]) -> dict:
    return {str(d["question_number"]): d.get("document", {}).get("response_templates", []) for d in data}


def text_layers_by_question(data: list[dict]) -> dict:
    return {str(d["question_number"]): d.get("document", {}).get("text_layer", "") for d in data}
