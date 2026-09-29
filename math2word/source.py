"""Load a PDF or image, render pages, and crop figures at high resolution."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


@dataclass
class Page:
    index: int
    width_pt: float          # page size in PDF points (images: pixels * 72/dpi)
    height_pt: float
    image: Image.Image       # rendering sent to the model
    pdf_page: pymupdf.Page | None = None   # vector source when available
    hi_res: Image.Image | None = None      # for image input: the original bitmap
    _drawings: list = field(default=None, repr=False)

    # ---------- figure cropping ----------
    def crop_figure(self, bbox_norm: list[int], dpi: int = 300) -> tuple[Image.Image, tuple[float, float]]:
        """Return (PNG image, (width_pt, height_pt)) for a normalized bbox.

        For vector PDFs the model's bbox is snapped to the actual drawing objects
        (and the short labels around them), so the crop is exact even if the model's
        box is a little off.
        """
        x0, y0, x1, y1 = [v / 1000 for v in bbox_norm]
        rect = pymupdf.Rect(x0 * self.width_pt, y0 * self.height_pt, x1 * self.width_pt, y1 * self.height_pt)
        rect.normalize()
        if self.pdf_page is not None:
            rect = self._snap_to_vectors(rect)
            pad = 4
            clip = pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & self.pdf_page.rect
            pix = self.pdf_page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            return img, (clip.width, clip.height)
        src = self.hi_res or self.image
        sx, sy = src.width / self.width_pt, src.height / self.height_pt
        pad = 0.01 * self.width_pt
        box = (
            max(0, int((rect.x0 - pad) * sx)), max(0, int((rect.y0 - pad) * sy)),
            min(src.width, int((rect.x1 + pad) * sx)), min(src.height, int((rect.y1 + pad) * sy)),
        )
        img = src.crop(box).convert("RGB")
        return img, ((box[2] - box[0]) / sx, (box[3] - box[1]) / sy)

    def _snap_to_vectors(self, rect: pymupdf.Rect) -> pymupdf.Rect:
        page = self.pdf_page
        search = pymupdf.Rect(rect.x0 - 12, rect.y0 - 12, rect.x1 + 12, rect.y1 + 12)
        max_w = 0.9 * page.rect.width
        if self._drawings is None:
            self._drawings = [d["rect"] for d in page.get_drawings()]
        items = [r for r in self._drawings if r.width < max_w and r.intersects(search)
                 and (r & search).get_area() >= 0.5 * max(r.get_area(), 1e-6)]
        for info in page.get_image_info():
            r = pymupdf.Rect(info["bbox"])
            if r.intersects(search) and (r & search).get_area() >= 0.5 * r.get_area():
                items.append(r)
        if not items:
            return rect
        snapped = pymupdf.Rect(items[0])
        for r in items[1:]:
            snapped |= r
        # Short text spans (axis names, point letters, coordinates) near the drawing.
        near = pymupdf.Rect(snapped.x0 - 22, snapped.y0 - 20, snapped.x1 + 22, snapped.y1 + 20)
        search_wide = pymupdf.Rect(search.x0 - 10, search.y0 - 10, search.x1 + 10, search.y1 + 10)
        near &= search_wide
        for block in page.get_text("dict", clip=near)["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    r = pymupdf.Rect(span["bbox"])
                    centre = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                    if span["text"].strip() and len(span["text"].strip()) <= 14 and centre in near:
                        snapped |= r
        return snapped


def load_pages(path: str | Path, render_dpi: int = 200, pages: list[int] | None = None) -> list[Page]:
    path = Path(path)
    out: list[Page] = []
    if path.suffix.lower() in IMAGE_SUFFIXES:
        img = Image.open(path)
        img.load()
        img = img.convert("RGB")
        dpi = img.info.get("dpi", (200, 200))[0] or 200
        w_pt, h_pt = img.width * 72 / dpi, img.height * 72 / dpi
        preview = img.copy()
        preview.thumbnail((2000, 2000))
        out.append(Page(0, w_pt, h_pt, preview, hi_res=img))
        return out

    doc = pymupdf.open(path)
    wanted = pages or list(range(1, len(doc) + 1))
    for n in wanted:
        p = doc[n - 1]
        pix = p.get_pixmap(dpi=render_dpi, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        out.append(Page(n - 1, p.rect.width, p.rect.height, img, pdf_page=p))
    return out
