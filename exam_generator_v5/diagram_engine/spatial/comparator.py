"""Spatial checks: cube counts / hidden tops, solid count, labels, dimension texts AND their meaning (radius vs diameter)."""
from __future__ import annotations


def check(spec, manifest: dict, check) -> None:
    o, sp = spec.observed, spec.spatial
    if sp.voxel is not None and spec.subtype == "voxel_structure":
        if o.visible_cubes is not None:
            check(manifest.get("visible_cubes") == o.visible_cubes,
                  f"מספר הקוביות הנראות השתנה (מקור {o.visible_cubes}, שחזור {manifest.get('visible_cubes')}).")
        if manifest.get("hidden_tops"):
            check(False, f"בעמודות {manifest['hidden_tops']} ראש העמודה אינו נראה — גובהן אינו ניתן לקביעה מהתמונה (לא ממציאים קוביות).")
        return
    if o.num_solids is not None:
        check(len(sp.solids) == o.num_solids, f"במקור {o.num_solids} גופים, בשחזור {len(sp.solids)}.")
    if o.point_labels is not None:
        got = sorted(set(manifest.get("vertices", [])) | {p[0] for p in manifest.get("points_on_edges", [])})
        check(sorted(o.point_labels) == got, f"תוויות הקודקודים שונות מהמקור ({', '.join(got)}).")
    if o.dimension_texts is not None:
        check(sorted(o.dimension_texts) == sorted(d[2] for d in manifest.get("dimensions", [])), "המידות שונות מהמקור.")
    if o.num_segments is not None:
        check(manifest.get("edges") == o.num_segments, f"במקור {o.num_segments} מקצועות, בשחזור {manifest.get('edges')}.")
