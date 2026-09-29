"""Human-readable (Hebrew) list of the facts the system extracted and verified - for the teacher's check panel."""
from __future__ import annotations

from .geometry.constraints import residuals, size_of
from .geometry.incidence import point_order_holds
from .schemas import DiagramRecord

TYPE_HE = {"graph": "גרף", "geometry": "גאומטריה", "mixed_graph_geometry": "גרף וגאומטריה", "chart": "תרשים נתונים",
           "table": "טבלה", "spatial": "מרחב / תלת-ממד", "generic": "תרשים כללי", "unknown": "לא זוהה"}
SUBTYPE_HE = {"formula_graph": "גרף לפי נוסחה", "qualitative_graph": "גרף איכותני (ללא נוסחה)", "multi_choice_graphs": "בחירה בין גרפים",
              "triangle_geometry": "משולש", "circle_geometry": "גאומטריה במעגל", "polygon_geometry": "מצולעים",
              "analytic_geometry": "גאומטריה אנליטית", "coordinate_circle": "מעגל במערכת צירים", "graph_with_geometry": "גרף עם בנייה",
              "scatter_plot": "דיאגרמת פיזור", "normal_distribution_schematic": "התפלגות נורמלית", "numeric_table": "טבלה מספרית",
              "voxel_structure": "מבנה קוביות", "cuboid": "תיבה", "cylinder": "גליל", "cylinder_in_box": "גוף בתוך גוף",
              "vector_box": "גוף עם וקטורים", "bar_chart": "דיאגרמת עמודות", "histogram": "היסטוגרמה", "pie_chart": "דיאגרמת עוגה",
              "schematic": "תרשים סכמטי"}
REL_HE = {"equal_length": "{0}{1} = {2}{3}", "parallel": "{0}{1} ∥ {2}{3}", "perpendicular": "{0}{1} ⟂ {2}{3}",
          "right_angle": "∢{0}{1}{2} = 90°", "midpoint": "{0} אמצע {1}{2}", "diameter": "{0}{1} קוטר", "tangent": "משיק בנקודה {0}",
          "on_circle": "{0} על המעגל", "point_order": "סדר הנקודות {all}", "intersection": "{0} = {1}{2} ∩ {3}{4}",
          "on_x_axis": "{0} על ציר x", "on_y_axis": "{0} על ציר y", "on_segment": "{0} על הקטע {1}{2}", "equilateral": "{0}{1}{2} שווה צלעות",
          "isosceles": "{0}{1} = {0}{2}", "on_curve": "{0} על העקומה", "equal_angle": "∢{0}{1}{2} = ∢{3}{4}{5}"}


def facts(rec: DiagramRecord) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    spec = rec.spec
    if spec is None:
        return out
    geo = spec.geometry or (spec.mixed.geometry if spec.mixed else None)
    if geo is not None:
        import numpy as np

        P = {p.id: np.array([p.x, p.y]) for p in geo.points}
        S = size_of(geo)
        for c in geo.constraints:
            if not all(k in P for k in c.points):
                continue
            tpl = REL_HE.get(c.type)
            if not tpl:
                continue
            try:
                ok = max(abs(v) for v in residuals(c, P, geo, S)) < 1e-6
            except Exception:
                ok = False
            src = {"text": "מהשאלה", "mark": "מסימון", "teacher": "מורה", "image": "מהשרטוט"}.get(c.source, c.source)
            text = tpl.format(*c.points, all="-".join(c.points)) if "{all}" in tpl or len(c.points) >= tpl.count("{") else c.type
            out.append((ok, f"{text} ({src})"))
        for order in spec.observed.point_orders or []:
            out.append((point_order_holds(geo, order), f"סדר הנקודות {'-'.join(order)} נשמר"))
        fixed = [p.id for p in geo.points if p.fixed]
        if fixed:
            out.append((True, "קואורדינטות מדויקות מהשאלה: " + ", ".join(fixed)))
    feats = rec.validation.info.get("graph_features", {})
    for cid, f in feats.items():
        nums = lambda vs: "\u2066" + ", ".join(f"{round(v, 3):g}" for v in vs) + "\u2069"  # noqa: E731  (LTR isolate)
        roots = nums(f["roots"]) if f["roots"] else "אין"
        out.append((True, f"עקומה {cid}: חיתוך עם ציר x ב- {roots}; מספר ענפים: {f['branches']}"))
        if f.get("vertical_asymptotes"):
            out.append((True, f"אסימפטוטות אנכיות: x = {nums(f['vertical_asymptotes'])}"))
    det = rec.validation.info.get("scatter_detection")
    if det:
        out.append((det["stable"], f"זיהוי נקודות דטרמיניסטי מהמקור: {len(det['points'])} נקודות" if det["stable"] else det["reason"]))
    if spec.table is not None and spec.observed.table_cells is not None:
        out.append((not any("תא" in c for c in rec.comparison.critical), "כל תאי הטבלה זהים למקור"))
    for l in spec.labels:
        if l.ambiguous:
            alts = f" (אולי: {', '.join(l.alternatives)})" if l.alternatives else ""
            out.append((False, f"התווית {l.text} זוהתה בביטחון {l.confidence:.0%}{alts}"))
    for m in rec.missing_required:
        out.append((False, "חסר בשחזור: " + m))
    for c in rec.contradictions:
        out.append((False, c))
    for k in (rec.coverage or {}).get("ai_only_facts", [])[:6]:
        out.append((False, f"נתמך רק על-ידי ה-AI: {k}"))
    for c in rec.comparison.critical:
        out.append((False, c))
    return out
