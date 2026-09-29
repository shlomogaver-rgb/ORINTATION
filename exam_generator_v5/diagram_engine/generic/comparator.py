"""Generic diagram checks: counts, labels, region texts, dimensions attached to the right endpoints, adjacency."""
from __future__ import annotations


def adjacency(spec) -> list[list[str]]:
    """Pairs of rectangles (by text) that share part of an edge - computed deterministically."""
    out = []
    sh = [s for s in spec.generic.shapes if s.kind == "rect"]
    eps = 1e-6 * max(spec.generic.width, spec.generic.height)
    for i in range(len(sh)):
        for j in range(i + 1, len(sh)):
            a, b = sh[i], sh[j]
            vert = (abs(a.x + a.w - b.x) < eps or abs(b.x + b.w - a.x) < eps) and min(a.y + a.h, b.y + b.h) - max(a.y, b.y) > eps
            horiz = (abs(a.y + a.h - b.y) < eps or abs(b.y + b.h - a.y) < eps) and min(a.x + a.w, b.x + b.w) - max(a.x, b.x) > eps
            if vert or horiz:
                out.append(sorted([a.text, b.text]))
    return sorted(out)


def check(spec, manifest: dict, check) -> None:
    o, g = spec.observed, spec.generic
    if o.num_shapes is not None:
        check(len(g.shapes) + len(g.polygons) == o.num_shapes, f"במקור {o.num_shapes} צורות, בשחזור {len(g.shapes) + len(g.polygons)}.")
    if o.shape_labels is not None:
        check(sorted(o.shape_labels) == sorted(manifest.get("texts", [])), "הכיתובים בתוך האזורים שונים מהמקור.")
    if o.point_labels is not None:
        check(sorted(o.point_labels) == manifest.get("labels", []), "התוויות שונות מהמקור.")
    if o.dimension_texts is not None:
        check(sorted(o.dimension_texts) == sorted(d[0] for d in manifest.get("dimensions", [])), "קווי המידה שונים מהמקור.")
    labels = set(manifest.get("labels", []))
    for text, attach in manifest.get("dimensions", []):
        check(all(a in labels for a in attach), f"קו המידה '{text}' מחובר לנקודות שאינן בשרטוט ({', '.join(attach)}).")
