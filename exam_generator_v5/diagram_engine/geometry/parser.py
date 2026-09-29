"""Geometry: relations come ONLY from the question text or explicit marks (drawings are often not to scale).
Equality/parallelism is never inferred from how the picture looks."""
from __future__ import annotations

import re

from ..schemas import GConstraint, GeometrySpec
from ..text_utils import normalize_math_text
from .constraints import METRIC

SEG = r"([A-Z][A-Z]?'?)"  # used only in combined patterns below


def _segments_of(token: str) -> list[str] | None:
    token = token.strip()
    return [token[0], token[1]] if re.fullmatch(r"[A-Z]{2}", token) else None


def relations_from_text(text: str) -> tuple[list[GConstraint], list[str]]:
    """Extract geometric relations from Hebrew/English question text. Returns (constraints, triangle_names)."""
    s = normalize_math_text(text)
    out: list[GConstraint] = []
    # equalities between segments, including chains AB=BC=CA (numbers are lengths, not relations)
    for chain in re.findall(r"(?<![A-Za-z])([A-Z]{2}(?:\s*=\s*[A-Z]{2}(?![A-Za-z]))+)", s):
        segs = [t.strip() for t in chain.split("=")]
        for a, b in zip(segs, segs[1:]):
            out.append(GConstraint(type="equal_length", points=[a[0], a[1], b[0], b[1]], source="text"))
    for a, b in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*∥\s*([A-Z]{2})(?![A-Za-z])", s):
        out.append(GConstraint(type="parallel", points=[a[0], a[1], b[0], b[1]], source="text"))
    for a, b in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*⊥\s*([A-Z]{2})(?![A-Za-z])", s):
        out.append(GConstraint(type="perpendicular", points=[a[0], a[1], b[0], b[1]], source="text"))
    triangles = re.findall(r"(?:משולש|triangle)\s*(?:ישר[- ]זווית|שווה[- ]שוקיים|שווה[- ]צלעות)?\s*([A-Z]{3})(?![A-Za-z])", s)
    for name, deg in re.findall(r"∠\s*([A-Z]{3}|[A-Z])\s*=\s*(\d+(?:\.\d+)?)\s*°?", s):
        if len(name) == 1:
            tri = next((t for t in triangles if name in t), None)
            if not tri:
                continue
            others = [c for c in tri if c != name]
            name = others[0] + name + others[1]
        if abs(float(deg) - 90) < 1e-9:
            out.append(GConstraint(type="right_angle", points=list(name), source="text"))
        else:
            out.append(GConstraint(type="angle_value", points=list(name), value=float(deg), source="text"))
    for v in re.findall(r"(?:הזווית|זווית)\s+([A-Z])\s+(?:היא\s+)?ישרה", s):
        tri = next((t for t in triangles if v in t), None)
        if tri:
            o = [c for c in tri if c != v]
            out.append(GConstraint(type="right_angle", points=[o[0], v, o[1]], source="text"))
    for m, seg in re.findall(r"(?<![A-Za-z])([A-Z])\s*(?:היא|הוא)?\s*(?:נקודת\s+)?(?:אמצע|האמצע של|midpoint of)\s*(?:הצלע|הקטע|של)?\s*([A-Z]{2})(?![A-Za-z])", s):
        out.append(GConstraint(type="midpoint", points=[m, seg[0], seg[1]], source="text"))
    for t in re.findall(r"(?:שווה[- ]צלעות|equilateral)\s*([A-Z]{3})", s):
        out.append(GConstraint(type="equal_length", points=[t[0], t[1], t[1], t[2]], source="text"))
        out.append(GConstraint(type="equal_length", points=[t[1], t[2], t[2], t[0]], source="text"))
    for p, seg in re.findall(r"(?<![A-Za-z])([A-Z])\s*(?:נמצאת|נמצא|מונחת|מונח)\s*על\s*(?:הצלע|הקטע)\s*([A-Z]{2})(?![A-Za-z])", s):
        out.append(GConstraint(type="on_segment", points=[p, seg[0], seg[1]], source="text"))
    for seg, t in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*(?:משיק|משיקה)\s*(?:למעגל)?[^.]*?בנקודה\s*([A-Z])", s):
        other = seg[0] if seg[1] == t else seg[1]
        out.append(GConstraint(type="tangent", points=[t, other], source="text"))
    for t, other in re.findall(r"דרך\s*הנקודה\s*([A-Z])\s*(?:מעבירים|העבירו|עובר)\s*משיק[^.]*?בנקודה\s*([A-Z])", s):
        out.append(GConstraint(type="tangent", points=[t, other], source="text"))
    for seg in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*(?:הוא|היא)\s*קוטר", s):
        out.append(GConstraint(type="diameter", points=[seg[0], seg[1]], source="text"))
    for seg in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*(?:הוא|היא)\s*מיתר", s):
        out.append(GConstraint(type="chord", points=[seg[0], seg[1]], source="text"))
    for p in re.findall(r"(?<![A-Za-z])([A-Z])\s*(?:נמצאת|נמצא)\s*על\s*המעגל", s):
        out.append(GConstraint(type="on_circle", points=[p], source="text"))
    for a, b, p in re.findall(r"(?<![A-Za-z])([A-Z]{2})\s*חותך\s*את\s*(?:הקטע|הצלע|הישר)?\s*([A-Z]{2})\s*בנקודה\s*([A-Z])", s):
        out.append(GConstraint(type="intersection", points=[p, a[0], a[1], b[0], b[1]], source="text"))
    for seg, p in re.findall(r"המשך\s*(?:הקטע|הצלע)\s*([A-Z]{2})[^.]*?בנקודה\s*([A-Z])", s):
        out.append(GConstraint(type="point_order", points=[seg[0], seg[1], p], source="text"))
    for p in re.findall(r"(?<![A-Za-z])([A-Z])\s*(?:נמצאת|נמצא)\s*על\s*ציר\s*ה?[־-]?\s*x", s):
        out.append(GConstraint(type="on_x_axis", points=[p], source="text"))
    for p in re.findall(r"(?<![A-Za-z])([A-Z])\s*(?:נמצאת|נמצא)\s*על\s*ציר\s*ה?[־-]?\s*y", s):
        out.append(GConstraint(type="on_y_axis", points=[p], source="text"))
    # de-duplicate
    uniq: list[GConstraint] = []
    for c in out:
        if not any(u.type == c.type and u.points == c.points and u.value == c.value for u in uniq):
            uniq.append(c)
    return uniq, triangles


def coordinates_from_text(text: str) -> dict[str, tuple[float, float]]:
    """Exact coordinates stated in the question, e.g. B(0,18), A(-16 , 6)."""
    s = normalize_math_text(text).replace("−", "-")
    out = {}
    for name, x, y in re.findall(r"(?<![A-Za-z])([A-Z])\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", s):
        out[name] = (float(x), float(y))
    return out


def marks_to_constraints(geo: GeometrySpec) -> list[GConstraint]:
    """Explicit marks in the drawing ARE evidence: tick marks => equal, arrows => parallel, square => right angle."""
    out: list[GConstraint] = []
    for m in geo.equal_marks:
        segs = [s for s in m.segments if len(s) == 2]
        for s1, s2 in zip(segs, segs[1:]):
            out.append(GConstraint(type="equal_length", points=[s1[0], s1[1], s2[0], s2[1]], source="mark"))
    for m in geo.parallel_marks:
        segs = [s for s in m.segments if len(s) == 2]
        for s1, s2 in zip(segs, segs[1:]):
            out.append(GConstraint(type="parallel", points=[s1[0], s1[1], s2[0], s2[1]], source="mark"))
    for a in geo.angle_marks:
        if a.kind == "right":
            out.append(GConstraint(type="right_angle", points=[a.a, a.vertex, a.b], source="mark"))
    for m in geo.equal_angle_marks:
        angs = [x for x in m.angles if len(x) == 3]
        for a1, a2 in zip(angs, angs[1:]):
            out.append(GConstraint(type="equal_angle", points=[*a1, *a2], source="mark"))
    return out


def same_constraint(u: GConstraint, c: GConstraint) -> bool:
    """Duplicate detection that respects structure: AB∥DC and BC∥AD are DIFFERENT constraints on the same 4 points."""
    if u.type != c.type or u.value != c.value:
        return False
    if c.type in ("parallel", "perpendicular", "equal_length") and len(c.points) == 4:
        pair = lambda p: sorted([tuple(sorted(p[:2])), tuple(sorted(p[2:]))])  # noqa: E731
        return pair(u.points) == pair(c.points)
    if c.type in ("point_order", "ratio_on_segment", "midpoint", "angle_value", "right_angle", "tangent", "intersection"):
        return u.points == c.points or (c.type == "point_order" and u.points == list(reversed(c.points)))
    return sorted(u.points) == sorted(c.points)


def merge_text(geo: GeometrySpec, text: str) -> list[str]:
    """Text relations + mark relations -> constraints; exact text coordinates -> fixed points.
    Metric relations proposed only by vision are removed (drawings are not to scale). Returns Hebrew warnings."""
    warnings: list[str] = []
    kept = []
    for c in geo.constraints:
        if c.source == "image" and c.type in METRIC:
            warnings.append(f"היחס {c.type} ({''.join(c.points)}) הוסק רק ממראה השרטוט ולכן לא נאכף.")
        else:
            kept.append(c)
    geo.constraints = kept
    ids = {p.id for p in geo.points}
    for name, (x, y) in coordinates_from_text(text).items():
        pt = next((p for p in geo.points if p.id == name), None)
        if pt is not None:
            pt.x, pt.y, pt.fixed, pt.source = x, y, True, "text"
            geo.coordinate_axes = True
    from .. import text_facts

    text = text_facts.given_text(text)            # goals / claims-to-prove are never imposed on the drawing
    single = geo.circles[0] if len(geo.circles) == 1 else None
    if single is not None and not single.id:
        single.id = "circle_1"
    rels, _ = relations_from_text(text)
    rels += text_facts.constraints_from_facts(text_facts.extract(text), single.id if single else None,
                                              single.center if single else None)
    for c in rels + marks_to_constraints(geo):
        if c.type in ("tangent", "diameter", "chord", "on_circle") and not c.circle:
            if single is None:
                warnings.append(f"נתון {c.type} מהשאלה, אך לא זוהה מעגל יחיד — הנתון לא נאכף.")
                continue
            if not single.id:
                single.id = "circle_1"
            c.circle = single.id
            if c.type == "on_circle":
                c.points = [c.points[0], single.center or f"__c_{single.id}"]
        missing = [p for p in c.points if p not in ids and not p.startswith("__c_")]
        if missing:
            if c.source == "text":
                warnings.append(f"נתון מהשאלה ({c.type}: {''.join(c.points)}) מתייחס לנקודות שאינן בשרטוט: {', '.join(missing)}.")
            continue
        if not any(same_constraint(u, c) for u in geo.constraints):
            if c.type == "on_circle" and any(k.type == "on_circle" and k.points[0] == c.points[0] for k in geo.constraints):
                continue
            geo.constraints.append(c)
    return warnings
