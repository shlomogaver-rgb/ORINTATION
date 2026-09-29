"""Hard validation, run BEFORE rendering. Any error => the reconstruction cannot be used."""
from __future__ import annotations

import math

import numpy as np

from . import safe_math as sm
from .charts import normal_distribution as nd
from .charts import table as tb
from .geometry.constraints import size_of
from .graph import qualitative_parser as qp
from .ocr_labels import ambiguous_labels
from .schemas import CONSTRAINT_ARITY, VARIABLE_ARITY, DiagramSpec, ValidationResult


def _graph(spec: DiagramSpec, r: ValidationResult) -> None:
    g = spec.graph
    if g is None:
        r.errors.append("חסרים נתוני גרף.")
        return
    a = g.axes
    for lo, hi, st, name in ((a.x_min, a.x_max, a.x_step, "x"), (a.y_min, a.y_max, a.y_step, "y")):
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            r.errors.append(f"טווח ציר {name} אינו חוקי ({lo}..{hi}).")
            return
        if not (math.isfinite(st) and st > 0):
            r.errors.append(f"מרווח השנתות בציר {name} אינו חוקי ({st}).")
        elif (hi - lo) / st > 60:
            # too dense for the range (typically the default step 1 on a large range): choose a readable step, not an error
            nice = _nice_step((hi - lo) / 10)
            setattr(a, f"{name}_step", nice)
            r.warnings.append(f"מרווח השנתות בציר {name} הותאם אוטומטית ל־{nice:g}.")
    if not g.curves and not g.points:
        r.errors.append("בגרף אין עקומות ואין נקודות.")
    ids = [c.id for c in g.curves]
    if len(ids) != len(set(ids)):
        r.errors.append("מזהי עקומות כפולים.")
    fns = {}
    for c in g.curves:
        if not c.expression and not c.pieces:
            r.errors.append(f"לעקומה {c.id} אין ביטוי.")
            continue
        exprs = [(p.expression, p.x_from, p.x_to) for p in c.pieces] if c.pieces else [(c.expression, None, None)]
        prev_hi = None
        any_visible = False
        for e, lo, hi in exprs:
            try:
                f = sm.safe_function(e)
            except Exception as exc:
                r.errors.append(f"עקומה {c.id}: ביטוי לא תקין — {exc}")
                continue
            lo2 = a.x_min if lo is None else max(a.x_min, lo)
            hi2 = a.x_max if hi is None else min(a.x_max, hi)
            if lo is not None and hi is not None and lo >= hi:
                r.errors.append(f"עקומה {c.id}: קטע עם תחום ריק ({lo}..{hi}).")
                continue
            if prev_hi is not None and lo is not None and lo < prev_hi - 1e-12:
                r.errors.append(f"עקומה {c.id}: קטעי הפונקציה חופפים.")
            prev_hi = hi if hi is not None else prev_hi
            if hi2 <= lo2:
                continue
            ys = f(np.linspace(lo2, hi2, 801))
            fin = np.isfinite(ys)
            if not fin.any():
                r.errors.append(f"עקומה {c.id}: לביטוי {e} אין ערכים ממשיים בתחום המוצג.")
                continue
            if ((ys[fin] >= a.y_min) & (ys[fin] <= a.y_max)).any():
                any_visible = True
            fns.setdefault(c.id, []).append((f, lo, hi))
        if fns.get(c.id) and not any_visible:
            r.warnings.append(f"עקומה {c.id} אינה נראית בחלון הצירים שנבחר.")
    tol = 1e-6 + 1e-4 * (a.y_max - a.y_min)
    names = [p.name for p in g.points if p.name]
    if len(names) != len(set(names)):
        r.errors.append("שמות נקודות כפולים בגרף.")
    for p in g.points:
        if not (math.isfinite(p.x) and math.isfinite(p.y)):
            r.errors.append(f"נקודה {p.name or '?'} עם קואורדינטות לא חוקיות.")
            continue
        if p.on_curve:
            if p.on_curve not in fns:
                r.errors.append(f"נקודה {p.name}: מוגדרת על עקומה לא קיימת ({p.on_curve}).")
                continue
            val = None
            for f, lo, hi in fns[p.on_curve]:
                if (lo is None or p.x >= lo - 1e-12) and (hi is None or p.x <= hi + 1e-12):
                    v = float(f(np.array([p.x]))[0])
                    if math.isfinite(v):
                        val = v
            if val is None or abs(val - p.y) > tol:
                r.errors.append(f"נקודה {p.name or f'({p.x:g},{p.y:g})'} אינה על העקומה {p.on_curve} (הצבה נותנת {val}).")
    for s in g.asymptotes:
        lo, hi = (a.x_min, a.x_max) if s.kind == "vertical" else (a.y_min, a.y_max)
        if not (lo <= s.value <= hi):
            r.warnings.append(f"אסימפטוטה {s.kind} {s.value:g} מחוץ לחלון הצירים.")


def _geometry(spec: DiagramSpec, r: ValidationResult, solved: dict | None) -> None:
    geo = spec.geometry
    if geo is None:
        r.errors.append("חסרים נתוני שרטוט גאומטרי.")
        return
    ids = [p.id for p in geo.points]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        r.errors.append(f"מזהי נקודות כפולים: {', '.join(dup)}.")
    known = set(ids)
    for p in geo.points:
        if not (math.isfinite(p.x) and math.isfinite(p.y)):
            r.errors.append(f"לנקודה {p.id} קואורדינטות לא חוקיות.")

    def need(pid: str, what: str) -> None:
        if pid not in known:
            r.errors.append(f"{what} מתייחס לנקודה לא קיימת: {pid}.")

    for kind, items in (("קטע", geo.segments), ("ישר", geo.lines), ("קרן", geo.rays)):
        for s in items:
            need(s.a, kind)
            need(s.b, kind)
            if s.a == s.b:
                r.errors.append(f"{kind} {s.a}{s.b} מחבר נקודה לעצמה.")
    for c in geo.circles:
        if c.center:
            need(c.center, "מעגל")
        for q in c.through_points:
            need(q, "מעגל")
        if c.through:
            need(c.through, "מעגל")
        elif not c.through_points and not (c.radius and c.radius > 0):
            r.errors.append(f"למעגל {c.id or c.center} אין רדיוס חוקי.")
        if not c.center and len(c.through_points) < 3 and not c.through:
            r.errors.append(f"למעגל {c.id} אין מרכז ופחות משלוש נקודות עליו — לא ניתן לקבוע אותו.")
    for poly in geo.polygons:
        for q in poly.vertices:
            need(q, "מצולע")
    for d in geo.dimensions:
        need(d.a, "קו מידה")
        need(d.b, "קו מידה")
    for m in geo.equal_angle_marks:
        if len(m.angles) < 2 or any(len(a) != 3 for a in m.angles):
            r.errors.append("סימון זוויות שוות דורש לפחות שתי זוויות בנות 3 נקודות.")
        for a in m.angles:
            for q in a:
                need(q, "סימון זוויות שוות")
    for a in geo.arcs:
        for q in (a.center, a.start, a.end):
            need(q, "קשת")
    for m in geo.angle_marks:
        for q in (m.vertex, m.a, m.b):
            need(q, "סימון זווית")
    drawn = {frozenset((s.a, s.b)) for s in geo.segments + geo.lines + geo.rays}
    for group, name in ((geo.equal_marks, "סימון שוויון"), (geo.parallel_marks, "סימון מקבילות")):
        for m in group:
            if len(m.segments) < 2:
                r.errors.append(f"{name} חייב לכלול לפחות שני קטעים.")
            for sg in m.segments:
                if len(sg) != 2:
                    r.errors.append(f"{name}: קטע לא חוקי {sg}.")
                    continue
                for q in sg:
                    need(q, name)
                if frozenset(sg) not in drawn:
                    r.errors.append(f"{name} על הקטע {''.join(sg)} שאינו משורטט.")
    for l in geo.length_labels:
        need(l.a, "תווית אורך")
        need(l.b, "תווית אורך")
    for c in geo.constraints:
        n = CONSTRAINT_ARITY[c.type]
        if c.type in VARIABLE_ARITY:
            if len(c.points) < n:
                r.errors.append(f"אילוץ {c.type} דורש לפחות {n} נקודות.")
                continue
        elif c.type == "tangent" and len(c.points) in (2, 3):
            pass
        elif c.type == "on_circle" and len(c.points) in (1, 2):
            pass
        elif len(c.points) != n:
            r.errors.append(f"אילוץ {c.type} דורש {n} נקודות.")
            continue
        for q in c.points:
            if not q.startswith("__c_"):
                need(q, f"אילוץ {c.type}")
        if c.type == "angle_value" and not (c.value and 0 < c.value < 180):
            r.errors.append(f"ערך זווית לא חוקי באילוץ {''.join(c.points)}.")
        if c.type == "on_circle" and len(c.points) > 1 and not c.points[1].startswith("__c_") \
                and not any(ci.center == c.points[1] for ci in geo.circles):
            r.errors.append(f"אילוץ 'על מעגל' מתייחס למעגל שמרכזו {c.points[1]} שאינו קיים.")
    if solved is not None and not r.errors:
        if not solved["ok"]:
            worst = max(solved["residuals"].items(), key=lambda kv: kv[1])[0] if solved["residuals"] else ""
            code = solved.get("code") or "SOLVER_CONVERGENCE_ERROR"
            if code == "DRAG_INFEASIBLE":
                r.errors.append("DRAG_INFEASIBLE: לא ניתן להציב את הנקודה במיקום המבוקש תחת האילוצים — הגרירה לא הוחלה.")
            elif code == "DEGENERATE_GEOMETRY":
                r.errors.append(f"DEGENERATE_GEOMETRY: בנייה מנוונת (למשל חיתוך ישרים מקבילים) עבור {', '.join(solved.get('degenerate', []))} — נדרשת בדיקת מורה.")
            elif code == "SOLVER_TIMEOUT":
                r.errors.append("SOLVER_TIMEOUT: הפותר חרג מתקציב הזמן — נדרשת בדיקת מורה.")
            else:
                r.errors.append(f"{code}: האילוצים הגאומטריים סותרים או בלתי אפשריים (לא ניתן לקיים {worst}).")
        S = size_of(geo)
        pts = solved["points"]
        vis_ids = [p.id for p in geo.points if not p.hidden]
        for a, b in [(a, b) for i, a in enumerate(vis_ids) for b in vis_ids[i + 1:]]:
            if a in pts and b in pts and math.dist(pts[a], pts[b]) < 1e-6 * S:
                r.errors.append(f"הנקודות {a} ו-{b} מתלכדות.")
        if solved["moved_fraction"] > 0.3:
            r.warnings.append("כדי לקיים את נתוני השאלה, נקודות הוזזו משמעותית ביחס לצילום (השרטוט המקורי אינו לפי קנה מידה).")


def _chart(spec: DiagramSpec, r: ValidationResult) -> None:
    c = spec.chart
    if c is None:
        r.errors.append("חסרים נתוני תרשים.")
        return
    if c.kind in ("frequency_table", "two_way_table"):
        if not c.table or len({len(row) for row in c.table}) != 1:
            r.errors.append("הטבלה ריקה או שאינה מלבנית.")
        if c.col_labels and c.table and len(c.col_labels) != len(c.table[0]):
            r.errors.append("מספר כותרות העמודות אינו תואם את הטבלה.")
        if c.row_labels and len(c.row_labels) != len(c.table):
            r.errors.append("מספר כותרות השורות אינו תואם את הטבלה.")
        return
    if not c.values:
        r.errors.append("אין ערכים בתרשים.")
    if not all(math.isfinite(v) for v in c.values):
        r.errors.append("ערך לא מספרי בתרשים.")
    if c.kind == "histogram":
        if len(c.bins) != len(c.values) + 1 or any(b2 <= b1 for b1, b2 in zip(c.bins, c.bins[1:])):
            r.errors.append("בהיסטוגרמה נדרשים גבולות מחלקות עולים (אחד יותר ממספר הערכים).")
    elif len(c.categories) != len(c.values):
        r.errors.append(f"מספר הקטגוריות ({len(c.categories)}) שונה ממספר הערכים ({len(c.values)}).")
    if c.kind in ("pie", "histogram") and any(v < 0 for v in c.values):     # a bar value may be negative
        r.errors.append("ערכים שליליים אינם אפשריים בסוג תרשים זה.")
    if c.kind == "pie" and sum(c.values) <= 0:
        r.errors.append("סכום ערכי תרשים העוגה חייב להיות חיובי.")


def _generic(spec: DiagramSpec, r: ValidationResult) -> None:
    g = spec.generic
    if g is None or not (g.shapes or g.arrows):
        r.errors.append("תרשים כללי ללא צורות.")
        return
    for s in g.shapes:
        if s.w <= 0 or s.h <= 0 or s.x < 0 or s.y < 0 or s.x + s.w > g.width + 1e-9 or s.y + s.h > g.height + 1e-9:
            r.errors.append("צורה בתרשים הכללי חורגת מגבולות התרשים.")
    for a in g.arrows:
        if not all(math.isfinite(v) for v in (a.x1, a.y1, a.x2, a.y2)):
            r.errors.append("חץ עם קואורדינטות לא חוקיות.")


def _qualitative(topo, r: ValidationResult) -> None:
    if topo is None:
        r.errors.append("חסרים נתוני הגרף האיכותני.")
        return
    r.errors += qp.validate(topo)


def _multi(spec: DiagramSpec, r: ValidationResult) -> None:
    m = spec.multi_graph
    if m is None or len(m.options) < 2:
        r.errors.append("שאלת בחירה בין גרפים דורשת לפחות שתי אפשרויות.")
        return
    labels = [o.label for o in m.options]
    if len(set(labels)) != len(labels) or not all(labels):
        r.errors.append("תוויות האפשרויות (I, II, ...) חסרות או כפולות.")
    for o in m.options:
        sub = ValidationResult()
        if o.formula is not None:
            _graph(DiagramSpec(diagram_type="graph", graph=o.formula), sub)
        elif o.topology is not None:
            _qualitative(o.topology, sub)
        else:
            sub.errors.append("אפשרות ללא תוכן.")
        r.errors += [f"אפשרות {o.label}: {e}" for e in sub.errors]
        r.warnings += [f"אפשרות {o.label}: {w}" for w in sub.warnings]


def _mixed(spec: DiagramSpec, r: ValidationResult, solved: dict | None) -> None:
    m = spec.mixed
    if m is None:
        r.errors.append("חסרים נתוני השרטוט המשולב.")
        return
    _graph(DiagramSpec(diagram_type="graph", graph=m.graph), r)
    _geometry(DiagramSpec(diagram_type="geometry", geometry=m.geometry), r, solved)
    ids = {c.id for c in m.graph.curves}
    for c in m.geometry.constraints:
        if c.type == "on_curve" and c.curve not in ids:
            r.errors.append(f"אילוץ 'על העקומה' מתייחס לעקומה לא קיימת ({c.curve}).")


def _scatter(spec: DiagramSpec, r: ValidationResult) -> None:
    sc = spec.scatter
    if sc is None or not sc.points:
        r.errors.append("בדיאגרמת הפיזור אין נקודות.")
        return
    a = sc.axes
    if not (a.x_min < a.x_max and a.y_min < a.y_max and a.x_step > 0 and a.y_step > 0):
        r.errors.append("צירי דיאגרמת הפיזור אינם חוקיים.")
    for p in sc.points:
        if len(p) != 2 or not all(math.isfinite(v) for v in p) or not (a.x_min <= p[0] <= a.x_max and a.y_min <= p[1] <= a.y_max):
            r.errors.append(f"נקודה לא חוקית או מחוץ לצירים: {p}.")


def _spatial(spec: DiagramSpec, r: ValidationResult) -> None:
    sp = spec.spatial
    if sp is None:
        r.errors.append("חסרים נתוני השרטוט המרחבי.")
        return
    if spec.subtype == "voxel_structure":
        v = sp.voxel
        if v is None or not v.columns:
            r.errors.append("במבנה הקוביות אין עמודות.")
            return
        cells = [(c.x, c.y) for c in v.columns]
        if len(cells) != len(set(cells)):
            r.errors.append("עמודת קוביות מופיעה פעמיים באותו מקום.")
        if any(c.height < 0 or c.height > 20 for c in v.columns):
            r.errors.append("גובה עמודה לא חוקי.")
        if v.plate and any(not (0 <= c.x < v.plate[0] and 0 <= c.y < v.plate[1]) for c in v.columns):
            r.errors.append("עמודה מחוץ ללוח הבסיס.")
        if v.ambiguous:
            r.errors.append("מבנה הקוביות אינו חד-משמעי מהתמונה (קוביות נסתרות) — לא ממציאים קוביות.")
        return
    ids = {s.id for s in sp.solids}
    if not sp.solids:
        r.errors.append("לא הוגדרו גופים.")
    verts: dict[str, set] = {}
    for s in sp.solids:
        if s.kind == "cylinder" and not (s.dims.get("radius", 0) > 0 and s.dims.get("height", 0) > 0):
            r.errors.append(f"לגליל {s.id} חסרים רדיוס/גובה חיוביים.")
        if s.kind == "cuboid" and not s.vertices and not all(s.dims.get(k, 0) > 0 for k in ("width", "depth", "height")):
            r.errors.append(f"לתיבה {s.id} חסרות מידות חיוביות.")
        names = set(s.vertices)
        if s.kind == "cuboid" and not s.vertices:
            names = {"A", "B", "C", "D", "A'", "B'", "C'", "D'"}
        verts[s.id] = names
        for e in s.edges + s.hidden_edges:
            if len(e) != 2 or not set(e) <= names:
                r.errors.append(f"מקצוע {e} בגוף {s.id} מתייחס לקודקוד לא קיים.")
    for d in sp.dimensions:
        sol = next((s for s in sp.solids if s.id == d.solid), None)
        if sol is None:
            r.errors.append(f"מידה '{d.text}' מתייחסת לגוף לא קיים.")
        elif d.measure in ("radius", "diameter") and sol.kind != "cylinder":
            r.errors.append(f"מידת {d.measure} אפשרית רק בגליל ({d.text}).")
    all_names = set().union(*verts.values()) if verts else set()
    all_names |= {p.id for p in sp.points_on_edges}
    for p in sp.points_on_edges:
        if not (0 < p.ratio < 1):
            r.errors.append(f"הנקודה {p.id} חייבת להיות בין קצות המקצוע (יחס {p.ratio}).")
        if p.a not in all_names or p.b not in all_names:
            r.errors.append(f"הנקודה {p.id} מוגדרת על קטע לא קיים ({p.a}{p.b}).")
    for cs in sp.construction_segments + sp.construction_lines + sp.construction_rays:
        if cs.a not in all_names or cs.b not in all_names:
            r.errors.append(f"קטע בנייה {cs.a}{cs.b} מתייחס לנקודה לא קיימת.")
    for v in sp.vectors:
        if v.a not in all_names or v.b not in all_names:
            r.errors.append(f"הווקטור {v.label} מתייחס לנקודה לא קיימת.")
    for rel in sp.relations:
        if rel.a not in ids or rel.b not in ids:
            r.errors.append(f"היחס {rel.type} מתייחס לגוף לא קיים.")


def _generic_v2(spec: DiagramSpec, r: ValidationResult) -> None:
    g = spec.generic
    if g is None or not (g.shapes or g.arrows or g.polygons or g.lines):
        r.errors.append("תרשים כללי ללא צורות.")
        return
    for s in g.shapes:
        if s.w <= 0 or s.h <= 0 or s.x < 0 or s.y < 0 or s.x + s.w > g.width + 1e-9 or s.y + s.h > g.height + 1e-9:
            r.errors.append("צורה בתרשים הכללי חורגת מגבולות התרשים.")
    for a in g.arrows + g.lines + g.dimensions:
        if not all(math.isfinite(v) for v in (a.x1, a.y1, a.x2, a.y2)):
            r.errors.append("קו/חץ עם קואורדינטות לא חוקיות.")
    labels = {l.text for l in g.labels}
    for d in g.dimensions:
        if not d.attach:
            r.errors.append(f"קו המידה '{d.text}' אינו קשור לאובייקט (יש לציין בין אילו נקודות הוא נמדד).")
        missing = [x for x in d.attach if x not in labels]
        if missing:
            r.errors.append(f"קו המידה '{d.text}' מחובר לנקודות שאינן בתרשים: {', '.join(missing)}.")


def _labels_used(spec: DiagramSpec) -> set[str]:
    used: set[str] = set()
    if spec.geometry:
        for p in spec.geometry.points:
            used.add(p.id if p.label is None else p.label)
        used |= {l.text for l in spec.geometry.length_labels}
        used |= {m.value for m in spec.geometry.angle_marks if m.value}
    if spec.graph:
        used |= {p.name for p in spec.graph.points if p.name}
        used |= {c.label for c in spec.graph.curves if c.label}
    if spec.graph_topology:
        used |= {l.label for l in spec.graph_topology.landmarks}
    if spec.mixed:
        used |= {p.id if p.label is None else p.label for p in spec.mixed.geometry.points if not p.hidden}
    if spec.table:
        used |= {c.text for row in spec.table.rows for c in row}
    if spec.normal:
        used |= set(spec.normal.percentages)
    if spec.spatial:
        used |= {d.text for d in spec.spatial.dimensions} | {v.label for v in spec.spatial.vectors}
    return {u for u in used if u}


def validate(spec: DiagramSpec, solved: dict | None = None) -> ValidationResult:
    r = ValidationResult()
    if not (0.0 <= spec.confidence <= 1.0):
        r.errors.append("ערך ביטחון מחוץ לטווח 0–1.")
    t, st = spec.diagram_type, spec.subtype
    if t == "graph" and st == "qualitative_graph":
        _qualitative(spec.graph_topology, r)
    elif t == "graph" and st == "multi_choice_graphs":
        _multi(spec, r)
    elif t == "graph":
        _graph(spec, r)
    elif t == "geometry":
        _geometry(spec, r, solved)
    elif t == "mixed_graph_geometry":
        _mixed(spec, r, solved)
    elif t == "chart" and st == "scatter_plot":
        _scatter(spec, r)
    elif t == "chart" and st == "normal_distribution_schematic":
        r.errors += nd.validate(spec.normal) if spec.normal else ["חסרים נתוני ההתפלגות."]
    elif t == "chart":
        _chart(spec, r)
    elif t == "table":
        r.errors += tb.validate(spec.table) if spec.table else ["חסרים נתוני הטבלה."]
    elif t == "spatial":
        _spatial(spec, r)
    elif t == "generic":
        _generic_v2(spec, r)
    else:
        r.errors.append("סוג תרשים לא ידוע — לא ניתן לשחזר.")
    amb = [l.text for l in ambiguous_labels(spec) if l.text in _labels_used(spec)]
    for text in amb:
        alts = next((l.alternatives for l in spec.labels if l.text == text), [])
        extra = f" (אפשרויות: {', '.join(alts)})" if alts else ""
        r.errors.append(f"התווית '{text}' אינה קריאה בוודאות{extra} — יש לאשר או לתקן אותה.")
    r.ok = not r.errors
    return r


def _nice_step(raw: float) -> float:
    """1-2-5 x 10^k step closest above raw."""
    k = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * k >= raw:
            return m * k
    return 10 * k
