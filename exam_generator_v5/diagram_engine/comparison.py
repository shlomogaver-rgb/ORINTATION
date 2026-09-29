"""Comparison Engine v2.

1. Anti-hallucination: the renderer's manifest must equal exactly what the spec contains (family specific).
2. Source signature: spec vs facts observed in the SOURCE (counts, labels, orders, landmarks, cells, dimensions, ...),
   plus deterministic detection where available (scatter dots).
3. Seven scores (structure, topology, constraint, label, math, layout, visual). A critical mismatch ALWAYS blocks."""
from __future__ import annotations

import io
import re

import numpy as np
from PIL import Image

from .charts import scatter as scatter_mod
from .charts import table as table_mod
from .generic import comparator as generic_cmp
from .geometry.incidence import point_order_holds
from .graph import comparator as graph_cmp
from .mixed import comparator as mixed_cmp
from .ocr_labels import display
from .preprocess import ink_mask
from .schemas import ComparisonResult, DiagramSpec
from .spatial import comparator as spatial_cmp

CATEGORIES = ("structure", "topology", "constraint", "label", "math", "layout")


def _geometry_manifest(spec: DiagramSpec, g) -> dict:
    labels = [display(p.id if p.label is None else p.label, spec) for p in g.points
              if not p.hidden and (p.id if p.label is None else p.label)]
    return {
        "points": sorted(p.id for p in g.points if not p.hidden), "labels": sorted(labels),
        "segments": sorted("".join(sorted((s.a, s.b))) for s in g.segments),
        "lines": sorted("".join(sorted((s.a, s.b))) for s in g.lines),
        "rays": [s.a + s.b for s in g.rays], "circles": len(g.circles), "arcs": len(g.arcs),
        "angle_marks": sum(1 for m in g.angle_marks if m.kind == "arc"),
        "right_angle_marks": sum(1 for m in g.angle_marks if m.kind == "right"),
        "angle_values": [display(m.value, spec) for m in g.angle_marks if m.value],
        "equal_mark_groups": len(g.equal_marks), "parallel_mark_groups": len(g.parallel_marks),
        "length_labels": [display(l.text, spec) for l in g.length_labels],
        "equal_angle_groups": len(g.equal_angle_marks), "polygons": len(g.polygons),
    }


def expected_manifest(spec: DiagramSpec) -> dict:
    """Exactly what the renderer must draw for this spec - nothing more, nothing less."""
    t, st = spec.diagram_type, spec.subtype
    if t == "geometry":
        return _geometry_manifest(spec, spec.geometry)
    if t == "mixed_graph_geometry":
        return {"curves": [c.id for c in spec.mixed.graph.curves]}
    if t == "graph" and st == "qualitative_graph":
        tp = spec.graph_topology
        return {"branches": len(tp.branches), "asymptotes": [[s.kind, s.value] for s in tp.asymptotes],
                "landmarks": [[l.kind, l.style, display(l.label, spec)] for l in tp.landmarks]}
    if t == "graph" and st == "multi_choice_graphs":
        return {"options": [o.label for o in spec.multi_graph.options]}
    if t == "graph":
        g = spec.graph
        return {"curves": [c.id for c in g.curves],
                "points": [[display(p.name, spec), round(p.x, 9), round(p.y, 9), p.style] for p in g.points],
                "asymptotes": [[s.kind, s.value] for s in g.asymptotes]}
    if t == "chart" and st == "scatter_plot":
        return {"points": sorted([round(p[0], 6), round(p[1], 6)] for p in spec.scatter.points)}
    if t == "chart" and st == "normal_distribution_schematic":
        n = spec.normal
        return {"regions": len(n.percentages), "labels": list(n.percentages), "boxes": n.answer_boxes}
    if t == "chart":
        c = spec.chart
        return {"kind": c.kind, "categories": list(c.categories), "values": list(c.values)}
    if t == "table":
        return {"cells": table_mod.cells(spec.table)}
    if t == "generic":
        g = spec.generic
        return {"shapes": len(g.shapes), "polygons": len(g.polygons), "arrows": len(g.arrows), "lines": len(g.lines),
                "labels": sorted(l.text for l in g.labels)}
    if t == "spatial" and st == "voxel_structure":
        return {"columns": sorted([c.x, c.y, c.height] for c in spec.spatial.voxel.columns)}
    if t == "spatial":
        return {"solids": [[s.id, s.kind] for s in spec.spatial.solids],
                "construction": [[k, c.a, c.b] for k, items in (("segment", spec.spatial.construction_segments),
                                 ("line", spec.spatial.construction_lines), ("ray", spec.spatial.construction_rays)) for c in items],
                "vectors": [[v.a, v.b, v.label] for v in spec.spatial.vectors],
                "dimensions": [[d.solid, d.measure, d.text] for d in spec.spatial.dimensions]}
    return {}


def _visual_score(source_png: bytes | None, render_png: bytes | None) -> float | None:
    if not source_png or not render_png:
        return None
    try:
        with Image.open(io.BytesIO(source_png)) as a, Image.open(io.BytesIO(render_png)) as b:
            ma, mb = ink_mask(a), ink_mask(b)
    except Exception:
        return None
    if not ma.any() or not mb.any():
        return 0.0

    def dil(m: np.ndarray, k: int = 3) -> np.ndarray:
        out = m.copy()
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
        return out

    precision = (mb & dil(ma)).sum() / mb.sum()
    recall = (ma & dil(mb)).sum() / ma.sum()
    return float(2 * precision * recall / max(1e-9, precision + recall))


def compare(spec: DiagramSpec, manifest: dict, source_png: bytes | None, render_png: bytes | None,
            question_text: str = "", graph_features: dict | None = None) -> ComparisonResult:
    r = ComparisonResult()
    results: dict[str, list[bool]] = {c: [] for c in CATEGORIES}
    cat = ["structure"]

    def check(ok: bool, critical_msg: str) -> None:
        results[cat[0]].append(ok)
        if not ok:
            r.critical.append(critical_msg)

    # 1) anti-hallucination
    exp = expected_manifest(spec)
    for key, val in exp.items():
        got = manifest.get(key)
        if isinstance(val, list) and key in ("angle_values", "length_labels"):
            val, got = sorted(val), sorted(got or [])
        check(got == val, f"השחזור אינו תואם את המפרט ({key}: {got} ≠ {val}).")
    base_checks = len(results["structure"])
    o = spec.observed
    t, st = spec.diagram_type, spec.subtype
    # 2) source signature per family
    if t == "geometry":
        g = spec.geometry
        if o.num_points is not None:
            check(len([p for p in g.points if not p.hidden]) == o.num_points, f"במקור {o.num_points} נקודות, בשחזור {len(manifest.get('points', []))}.")
        if o.num_segments is not None:
            check(len(g.segments) == o.num_segments, f"במקור {o.num_segments} קטעים, בשחזור {len(g.segments)}.")
        if o.num_circles is not None:
            check(len(g.circles) == o.num_circles, f"במקור {o.num_circles} מעגלים, בשחזור {len(g.circles)}.")
        cat[0] = "label"
        if o.point_labels is not None:
            src, drawn = sorted(o.point_labels), sorted(manifest.get("labels", []))
            check(src == drawn, f"תוויות הנקודות שונות מהמקור (מקור: {', '.join(src)}; שחזור: {', '.join(drawn)}).")
        if o.angle_values is not None:
            check(sorted(o.angle_values) == sorted(manifest.get("angle_values", [])), "ערכי הזוויות שונים מהמקור.")
        cat[0] = "constraint"
        if o.right_angle_marks is not None:
            check(manifest.get("right_angle_marks") == o.right_angle_marks, "סימון זווית ישרה חסר או מיותר ביחס למקור.")
        if o.equal_mark_groups is not None:
            check(manifest.get("equal_mark_groups") == o.equal_mark_groups, "סימוני שוויון קטעים חסרים או מיותרים ביחס למקור.")
        if o.parallel_mark_groups is not None:
            check(manifest.get("parallel_mark_groups") == o.parallel_mark_groups, "סימוני מקבילות חסרים או מיותרים ביחס למקור.")
        cat[0] = "topology"
        for order in o.point_orders or []:
            check(point_order_holds(g, order), f"סדר הנקודות {'-'.join(order)} לא נשמר.")
        if o.tangent_points is not None:
            have = sorted(c.points[0] for c in g.constraints if c.type == "tangent")
            check(sorted(o.tangent_points) == have, "המשיק שבמקור לא נשמר כמשיק בשחזור.")
    elif t == "mixed_graph_geometry":
        cat[0] = "topology"
        mixed_cmp.check(spec, manifest, check)
        cat[0] = "math"
        if o.tangent_points is not None:
            have = sorted(c.points[0] for c in spec.mixed.geometry.constraints if c.type == "tangent")
            check(sorted(o.tangent_points) == have, "המשיק שבמקור לא נשמר כמשיק בשחזור.")
    elif t == "graph" and st == "qualitative_graph":
        cat[0] = "topology"
        graph_cmp.check_topology(spec.graph_topology, o, check)
    elif t == "graph" and st == "multi_choice_graphs":
        cat[0] = "topology"
        opts = spec.multi_graph.options
        if o.num_options is not None:
            check(len(opts) == o.num_options, f"במקור {o.num_options} אפשרויות, בשחזור {len(opts)}.")
        if o.option_labels is not None:
            check([x.label for x in opts] == list(o.option_labels), "תוויות האפשרויות I–IV שונות מהמקור או שסדרן השתנה.")
    elif t == "graph":
        cat[0] = "math"
        graph_cmp.check_formula(spec, manifest, graph_features, check)
    elif t == "chart" and st == "scatter_plot":
        cat[0] = "math"
        if o.num_scatter_points is not None:
            check(len(spec.scatter.points) == o.num_scatter_points,
                  f"במקור {o.num_scatter_points} נקודות, בשחזור {len(spec.scatter.points)}.")
        if source_png:
            det = scatter_mod.detect(source_png, spec.scatter.axes)
            r.notes.append("זיהוי נקודות דטרמיניסטי: " + ("יציב" if det["stable"] else det["reason"]))
            if det["stable"]:
                for msg in scatter_mod.match(spec.scatter.points, det["points"], spec.scatter.axes):
                    check(False, msg)
                results["math"].append(True)
            else:
                check(False, "מיפוי הפיקסלים לקואורדינטות אינו יציב — לא ניתן לאמת את הנקודות.")
    elif t == "chart" and st == "normal_distribution_schematic":
        cat[0] = "label"
        if o.num_regions is not None:
            check(len(spec.normal.percentages) == o.num_regions, "מספר האזורים שונה מהמקור.")
        if o.region_labels is not None:
            check(list(o.region_labels) == list(spec.normal.percentages), "האחוזים באזורים שונים מהמקור.")
        if o.num_answer_boxes is not None:
            check(spec.normal.answer_boxes == o.num_answer_boxes, "מספר תיבות התשובה שונה מהמקור.")
        cat[0] = "topology"
        check(manifest.get("symmetric_labels", False) == (spec.normal.percentages == list(reversed(spec.normal.percentages))),
              "הסימטריה של התרשים לא נשמרה.")
    elif t == "chart":
        if o.num_bars is not None:
            check(len(spec.chart.values) == o.num_bars, f"במקור {o.num_bars} עמודות/פלחים, בשחזור {len(spec.chart.values)}.")
    elif t == "table":
        cat[0] = "math"
        if o.table_shape is not None:
            check([len(spec.table.rows), len(spec.table.rows[0]) if spec.table.rows else 0] == list(o.table_shape), "מבנה הטבלה שונה מהמקור.")
        if o.table_cells is not None:
            for msg in table_mod.compare_cells(spec.table, o.table_cells):
                check(False, msg)
            results["math"].append(True)
    elif t == "generic":
        cat[0] = "layout"
        generic_cmp.check(spec, manifest, check)
    elif t == "spatial":
        cat[0] = "topology"
        spatial_cmp.check(spec, manifest, check)
    signature_checks = sum(len(v) for v in results.values()) - base_checks
    if signature_checks == 0:
        r.notes.append("לא התקבלו נתוני השוואה מהמקור (observed) — ההשוואה חלקית.")
    # 3) labels: nothing drawn that the source/question does not contain
    drawn_labels = set(manifest.get("labels", [])) | set(manifest.get("length_labels", [])) | set(manifest.get("angle_values", []))
    drawn_labels |= set(manifest.get("geometry", {}).get("labels", []))
    axis_labels = set(manifest.get("axis_labels", [])) | set(manifest.get("geometry", {}).get("axis_labels", []))
    drawn_labels |= axis_labels
    drawn_labels.discard("?")
    if t == "table" and o.table_cells is not None:
        r.label_match_score = 1.0 if not table_mod.compare_cells(spec.table, o.table_cells) else 0.0   # every cell verified
    elif spec.labels:
        known = {l.text for l in spec.labels} | axis_labels     # axis names are structural, never "invented"
        confident = {l.text for l in spec.labels if not l.ambiguous and not re.fullmatch(r"-?\d+(?:\.\d+)?", l.text)}
        tokens = set(re.findall(r"[A-Za-z0-9.]+", question_text or ""))
        invented = sorted(x for x in drawn_labels if x not in known and x not in tokens and x.strip("()") not in tokens)
        if invented:
            r.critical.append(f"בשחזור מופיעות תוויות שאינן במקור: {', '.join(invented)}.")
        r.label_match_score = 0.0 if invented else ((len(confident & drawn_labels) / len(confident)) if confident and drawn_labels else 1.0)
    elif drawn_labels:
        r.label_match_score = 0.5
        r.notes.append("לא התקבלו תוויות OCR מהמקור.")
    else:
        r.label_match_score = 1.0          # nothing textual drawn, nothing to verify
    # scores
    def score(c: str, empty: float) -> float:
        v = results[c]
        return (sum(v) / len(v)) if v else empty
    partial = 0.5 if signature_checks == 0 else 1.0
    r.structure_match_score = min(score("structure", 1.0), partial)
    r.topology_score = score("topology", partial)
    r.constraint_score = score("constraint", partial)
    r.math_score = score("math", partial)
    r.layout_score = score("layout", partial)
    if results["label"]:
        r.label_match_score = min(r.label_match_score, score("label", 1.0))
    vis = _visual_score(source_png, render_png)
    r.visual_match_score = 0.0 if vis is None else round(vis, 3)
    if vis is not None and vis < 0.25:
        r.notes.append("הדמיון החזותי למקור נמוך — מומלץ להשוות בעין (השרטוט אינו חייב להיות לפי קנה מידה).")
    core = [r.structure_match_score, r.topology_score, r.constraint_score, r.label_match_score, r.math_score, r.layout_score]
    r.overall_score = round(min(core), 3)   # visual similarity is informative only (drawings are not to scale)
    return r
