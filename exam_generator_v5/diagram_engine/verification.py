"""Independent verification (v3).

SourceSignature V3 = FactGraph built from INDEPENDENT channels (question text, deterministic CV, derived math, teacher,
acceptance ground truth) + the vision proposal tagged as 'vision'. The vision `observed` block is NOT a verifier: it is
recorded as vision evidence only.

Outputs: required-fact critical mismatches, contradictions, verification coverage and the confidence breakdown."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import symbols as symtab
from . import text_facts
from .constants import HIGH_COVERAGE
from .fact_graph import Fact, FactGraph, canonical
from .schemas import DiagramSpec, GConstraint

CONSTRAINT_TO_FACT = {"on_segment": "point_on_segment", "on_circle": "on_circle", "radius": "on_circle", "chord": "chord",
                      "secant": "chord", "point_on_ray": "point_on_line", "collinear": "collinear"}


# ------------------------------------------------------------------ what the reconstruction asserts
def _geo(spec: DiagramSpec):
    return spec.geometry or (spec.mixed.geometry if spec.mixed else None)


def spec_facts(spec: DiagramSpec) -> list[Fact]:
    """Facts ASSERTED by the reconstruction (source = vision unless the spec element says otherwise)."""
    out: list[Fact] = []
    src_map = {"text": "question_text", "mark": "diagram_symbol", "image": "vision", "teacher": "teacher", "computed": "derived_math",
               "detected": "deterministic_detection"}

    def add(t, ents, value=None, src="vision"):
        out.append(Fact(fact_type=t, entities=list(ents), value=value, source=src_map.get(src, src)))

    g = _geo(spec)
    if g is not None:
        for p in g.points:
            if not p.hidden:
                add("point", [p.id], src=p.source)
                if p.fixed:
                    add("coordinate", [p.id], [p.x, p.y], src=p.source)
        for s in g.segments + g.lines:
            add("segment", [s.a, s.b])
        for l in g.length_labels:
            add("length_value", [f"{l.a}{l.b}"])
        for m in g.angle_marks:
            if m.kind == "arc" and m.value:
                add("angle_value", [f"∠{m.a}{m.vertex}{m.b}"])
        for kind, items in (("SEGMENT", g.segments), ("LINE", g.lines), ("RAY", g.rays)):
            for s in items:
                add("extent", [s.a, s.b], kind)
        for c in g.constraints:
            t = CONSTRAINT_TO_FACT.get(c.type, c.type)
            ents = list(c.points)
            if t == "on_circle":
                ents = ents[:1]
            elif t == "tangent":
                ents = ents[:2]
            add(t, ents, c.value if c.type in ("ratio_on_segment", "angle_value") else None, c.source)
        for ci in g.circles:
            for k in ci.through_points + ([ci.through] if ci.through else []):
                add("on_circle", [k])
    sp = spec.spatial
    if sp is not None:
        for s in sp.solids:
            for v in s.vertices:
                add("point", [v])
        for pe in sp.points_on_edges:
            add("point", [pe.id])
            add("ratio_on_segment", [pe.id, pe.a, pe.b], round(pe.ratio, 9))
            if abs(pe.ratio - 0.5) < 1e-9:
                add("midpoint", [pe.id, pe.a, pe.b])
            add("point_on_segment", [pe.id, pe.a, pe.b])
        for cs in sp.construction_segments:
            add("segment", [cs.a, cs.b])
            add("construction_segment", [cs.a, cs.b])
        from .spatial.solids import box_edges
        for s in sp.solids:
            for e in (s.edges or (box_edges() if s.kind == "cuboid" and s.vertices else [])):
                add("segment", e)
        for d in sp.dimensions:
            add("dimension", [], {"dimension_type": d.measure, "value": d.value, "unit": d.unit or ""})
            if d.value is not None:
                add("dimension_value", [f"{d.value:g}"])
        for vec in sp.vectors:
            add("vector", [vec.a, vec.b], vec.label)
            add("vector_label", [vec.label])
    if spec.generic is not None:
        for l in spec.generic.labels:
            add("point", [l.text])
    gr = spec.graph or (spec.mixed.graph if spec.mixed else None)
    if gr is not None:
        for c in gr.curves:
            if c.expression:
                add("formula", [c.id], c.expression, c.source)
        for a in gr.asymptotes:
            add("asymptote", [a.kind], a.value, a.source)
    if spec.graph_topology is not None:
        for lm in spec.graph_topology.landmarks:
            if lm.label:
                add("label", [text_facts.label_key(lm.label)])
        for a in spec.graph_topology.asymptotes:
            add("asymptote", [a.kind], a.value, a.source)
    if spec.multi_graph is not None:
        for o in spec.multi_graph.options:
            add("option", [o.label])
            t = o.topology
            if t is not None:
                add("option_topology", [o.label], {"branches": len(t.branches), "asymptotes": len(t.asymptotes)})
    if spec.scatter is not None:
        for p in spec.scatter.points:
            add("scatter_point", [f"{p[0]:g},{p[1]:g}"], src=spec.scatter.points_source)
    if spec.table is not None:
        for r, row in enumerate(spec.table.rows):
            for c, cell in enumerate(row):
                add("table_cell", [f"{r},{c}"], cell.text.strip().replace(",", "").replace(" ", ""), src=spec.table.cells_source)
    if spec.normal is not None:
        for i, lab in enumerate(spec.normal.percentages):
            add("region_label", [str(i)], lab)
    return out


# edge lengths of a solid are one semantic family; radius, diameter and height are each their own
DIM_FAMILY = {"width": "edge", "depth": "edge", "length": "edge", "side": "edge", "edge": "edge",
              "radius": "radius", "diameter": "diameter", "height": "height", "distance": "distance"}


def target_entity_ids(spec: DiagramSpec, v: dict) -> set[str] | None:
    """Exact binding: which solid ids the text dimension may belong to. An ordinal ('הגליל השני') selects ONE id
    (solids of that kind in spec order); otherwise every solid of the kind (ambiguity is flagged separately)."""
    kind = v.get("entity_kind")
    if kind not in ("cylinder", "cuboid", "polyhedron") or spec.spatial is None:
        return None
    ids = [s.id for s in spec.spatial.solids if s.kind == kind]
    idx = v.get("entity_index")
    if idx:
        return {ids[idx - 1]} if 0 < idx <= len(ids) else set()
    return set(ids)


def same_meaning(a: str, b: str) -> bool:
    return DIM_FAMILY.get(a, a) == DIM_FAMILY.get(b, b)


def text_facts_critical() -> set[str]:
    from .fact_graph import CRITICAL_TYPES
    return CRITICAL_TYPES


def spec_keys(spec: DiagramSpec) -> set[str]:
    return {f.key for f in spec_facts(spec)}


# ------------------------------------------------------------------ does the (solved) spec satisfy a text fact?
def _P(spec: DiagramSpec) -> dict[str, np.ndarray]:
    g = _geo(spec)
    return {p.id: np.array([p.x, p.y], float) for p in g.points} if g else {}


def _on_line(P, p, a, b, tol=1e-5) -> bool:
    ab, ap = P[b] - P[a], P[p] - P[a]
    n = float(np.hypot(*ab)) or 1.0
    return abs(ab[0] * ap[1] - ab[1] * ap[0]) / (n * n) < tol


def _between(P, p, a, b) -> bool:
    ab = P[b] - P[a]
    t = float((P[p] - P[a]) @ ab) / max(1e-12, float(ab @ ab))
    return _on_line(P, p, a, b) and -1e-6 <= t <= 1 + 1e-6


def _segment_drawn(spec: DiagramSpec, a: str, b: str) -> bool:
    """AB is represented if drawn directly or contained in a drawn segment/line/edge (e.g. MK inside AM)."""
    g = _geo(spec)
    if g is not None:
        P = _P(spec)
        if a not in P or b not in P:
            return False
        for s in g.segments + g.lines:
            if {s.a, s.b} == {a, b}:
                return True
            if s.a in P and s.b in P and _between(P, a, s.a, s.b) and _between(P, b, s.a, s.b):
                return True
        return False
    sp = spec.spatial
    if sp is not None:
        from .spatial.solids import box_edges
        pairs = {frozenset(e) for s in sp.solids for e in (s.edges or (box_edges() if s.kind == "cuboid" else []))}
        pairs |= {frozenset((c.a, c.b)) for c in sp.construction_segments + sp.construction_lines + sp.construction_rays}
        if frozenset((a, b)) in pairs:
            return True
        # contained: A'E is drawn when E lies on the drawn segment A'C'
        on = {p.id: (p.a, p.b) for p in sp.points_on_edges}
        for x, y in ((a, b), (b, a)):
            if y in on and frozenset(on[y]) in pairs and x in on[y]:
                return True
        return False
    return False


def _contained(spec: DiagramSpec, e: list[str], s) -> bool:
    P = _P(spec)
    return all(k in P for k in (*e, s.a, s.b)) and _between(P, e[0], s.a, s.b) and _between(P, e[1], s.a, s.b)


def _circle_ok(spec: DiagramSpec, p: str) -> bool:
    g = _geo(spec)
    if g is None or not g.circles:
        return False
    P = _P(spec)
    if p not in P:
        return False
    for c in g.circles:
        ctr = P.get(c.center or f"__c_{c.id}")
        ref = c.through or (c.through_points[0] if c.through_points else None)
        if ctr is None:
            continue
        r = float(np.hypot(*(P[ref] - ctr))) if ref and ref in P else float(c.radius or 0)
        if r > 0 and abs(float(np.hypot(*(P[p] - ctr))) - r) < 1e-5 * max(1.0, r):
            return True
    return False


def satisfied(spec: DiagramSpec, f: Fact) -> bool | None:
    """True/False = checked on the reconstruction; None = this family can not check the fact."""
    t, e = f.fact_type, f.entities
    g = _geo(spec)
    if t == "point":
        names = set()
        if g is not None:
            names |= {p.id for p in g.points if not p.hidden}
        if spec.spatial is not None:
            names |= {v for s in spec.spatial.solids for v in s.vertices} | {p.id for p in spec.spatial.points_on_edges}
        if spec.generic is not None:
            names |= {l.text for l in spec.generic.labels}
        return e[0] in names if (g is not None or spec.spatial is not None or spec.generic is not None) else None
    if t in ("segment", "construction_segment"):
        return _segment_drawn(spec, e[0], e[1]) if (g is not None or spec.spatial is not None) else None
    if t == "extent" and g is not None:
        pair = set(e)
        drawn = {"SEGMENT": [s for s in g.segments if {s.a, s.b} == pair or (_contained(spec, e, s))],
                 "LINE": [s for s in g.lines if {s.a, s.b} == pair or _contained(spec, e, s)],
                 "RAY": [s for s in g.rays if {s.a, s.b} == pair]}
        if f.value == "SEGMENT":                   # a segment may be drawn as part of a longer segment/line
            return bool(drawn["SEGMENT"] or drawn["LINE"] or drawn["RAY"])
        return bool(drawn[f.value]) or (f.value == "RAY" and bool(drawn["LINE"]) is False and False)
    if t == "vector_label":
        return e[0] in {v.label for v in spec.spatial.vectors} if spec.spatial is not None else None
    if t == "dimension" and e and g is not None:          # a length written on a segment: bound to that segment
        vtxt = f"{f.value['value']:g}"
        return any({l.a, l.b} == set(e) and vtxt in l.text for l in g.length_labels) or \
            any({d.a, d.b} == set(e) and vtxt in d.text for d in g.dimensions)
    if t == "dimension":
        if spec.spatial is None:
            return None
        v = f.value
        target = target_entity_ids(spec, v)
        same_val = [d for d in spec.spatial.dimensions if d.value is not None and abs(d.value - v["value"]) < 1e-9
                    and (target is None or d.solid in target)]
        return any(same_meaning(d.measure, v["dimension_type"]) for d in same_val) if same_val else False
    if t in ("ratio_on_segment", "midpoint", "point_on_segment") and spec.spatial is not None and g is None:
        ratio = f.value if t == "ratio_on_segment" else (0.5 if t == "midpoint" else None)
        for pe in spec.spatial.points_on_edges:
            if pe.id == e[0] and {pe.a, pe.b} == set(e[1:3]):
                r = pe.ratio if pe.a == e[1] else 1 - pe.ratio
                return ratio is None or abs(r - ratio) < 1e-9
        return False
    if g is None:
        return None
    P = _P(spec)
    if any(k not in P for k in e):
        return False
    if t in ("point_order",):
        a, b = P[e[0]], P[e[-1]]
        ab = b - a
        n2 = max(1e-12, float(ab @ ab))
        ts = [float((P[k] - a) @ ab) / n2 for k in e]
        return all(_on_line(P, k, e[0], e[-1]) for k in e) and all(t2 > t1 + 1e-6 for t1, t2 in zip(ts, ts[1:]))
    if t == "collinear":
        return all(_on_line(P, k, e[0], e[1]) for k in e[2:])
    if t == "point_on_line":
        return _on_line(P, e[0], e[1], e[2])
    if t == "point_on_segment":
        return _between(P, e[0], e[1], e[2])
    if t == "on_circle":
        return _circle_ok(spec, e[0])
    if t == "concyclic":
        return all(_circle_ok(spec, k) for k in e)
    if t == "on_x_axis":
        return abs(P[e[0]][1]) < 1e-6
    if t == "on_y_axis":
        return abs(P[e[0]][0]) < 1e-6
    if t == "coordinate":
        return bool(np.allclose(P[e[0]], f.value, atol=1e-6))
    L = lambda a, b: float(np.hypot(*(P[b] - P[a])))  # noqa: E731
    if t == "equilateral":
        return math.isclose(L(e[0], e[1]), L(e[1], e[2]), rel_tol=1e-6) and math.isclose(L(e[1], e[2]), L(e[2], e[0]), rel_tol=1e-6)
    if t == "equal_length":
        return math.isclose(L(e[0], e[1]), L(e[2], e[3]), rel_tol=1e-6)
    if t in ("rectangle", "square", "parallelogram", "rhombus") and len(e) == 4:
        A, B_, C, D = (P[k] for k in e)
        par = lambda u, v: abs(u[0] * v[1] - u[1] * v[0]) < 1e-6 * max(1.0, np.hypot(*u) * np.hypot(*v))  # noqa: E731
        ok = par(B_ - A, C - D) and par(C - B_, D - A)
        if t in ("rectangle", "square"):
            ok = ok and abs(float((B_ - A) @ (C - B_))) < 1e-6 * max(1.0, np.hypot(*(B_ - A)) * np.hypot(*(C - B_)))
        if t in ("square", "rhombus"):
            ok = ok and math.isclose(L(e[0], e[1]), L(e[1], e[2]), rel_tol=1e-6)
        return ok
    if t in ("parallel", "perpendicular"):
        u, v = P[e[1]] - P[e[0]], P[e[3]] - P[e[2]]
        u, v = u / (np.hypot(*u) or 1), v / (np.hypot(*v) or 1)
        return abs(u[0] * v[1] - u[1] * v[0]) < 1e-6 if t == "parallel" else abs(float(u @ v)) < 1e-6
    if t == "parallel_to_x_axis":
        return abs(P[e[0]][1] - P[e[1]][1]) < 1e-6
    if t == "parallel_to_y_axis":
        return abs(P[e[0]][0] - P[e[1]][0]) < 1e-6
    if t == "right_angle":
        u, v = P[e[0]] - P[e[1]], P[e[2]] - P[e[1]]
        return abs(float(u @ v)) / max(1e-12, np.hypot(*u) * np.hypot(*v)) < 1e-6
    if t == "midpoint":
        return bool(np.allclose(P[e[0]], (P[e[1]] + P[e[2]]) / 2, atol=1e-6))
    if t == "ratio_on_segment":
        return bool(np.allclose(P[e[0]], P[e[1]] + f.value * (P[e[2]] - P[e[1]]), atol=1e-6))
    if t == "diameter" and not g.circles:
        # the source may not DRAW the circle ("ABCD is cyclic, AD a diameter"): the fact is metric - Thales' theorem
        others = [k for k in P if k not in e[:2] and not k.startswith("__")]
        seen = [k for k in others if abs(float((P[e[0]] - P[k]) @ (P[e[1]] - P[k]))) <= 1e-6 * max(1.0, float(np.linalg.norm(P[e[0]] - P[e[1]]) ** 2))]
        return len(seen) >= 2
    if t in ("diameter", "chord"):
        if not (_circle_ok(spec, e[0]) and _circle_ok(spec, e[1])):
            return False
        if t == "chord":
            return True
        return any(np.allclose(P.get(c.center or f"__c_{c.id}", np.array([np.inf, np.inf])), (P[e[0]] + P[e[1]]) / 2, atol=1e-6) for c in g.circles)
    if t == "tangent":
        if not _circle_ok(spec, e[0]):
            return False
        if len(e) < 2:
            return any(c.type == "tangent" and c.points[0] == e[0] for c in g.constraints)
        for c in g.circles:
            ctr = P.get(c.center or f"__c_{c.id}")
            if ctr is not None and abs(float((P[e[0]] - ctr) @ (P[e[1]] - P[e[0]]))) < 1e-6 * max(1.0, L(e[0], e[1]) ** 2):
                return True
        return False
    if t == "intersection":
        return _on_line(P, e[0], e[1], e[2]) and _on_line(P, e[0], e[3], e[4])
    return None


# ------------------------------------------------------------------ the whole v3 verification
APPLIES = {"geometry": {"extent", "rectangle", "square", "parallelogram", "rhombus", "dimension", "point", "segment", "point_order", "collinear", "point_on_line", "point_on_segment", "on_circle", "concyclic",
                        "on_x_axis", "on_y_axis", "coordinate", "equilateral", "equal_length", "parallel", "perpendicular",
                        "parallel_to_x_axis", "parallel_to_y_axis", "right_angle", "midpoint", "ratio_on_segment", "diameter",
                        "chord", "tangent", "intersection"},
           "spatial": {"point", "segment", "construction_segment", "dimension", "midpoint", "ratio_on_segment", "point_on_segment",
                       "vector_label"},
           "generic": {"point"}}
APPLIES["mixed_graph_geometry"] = APPLIES["geometry"]


def verify(spec: DiagramSpec, required_text: str, full_text: str, solved: dict | None = None, raw_points: dict | None = None,
           cv_facts: list[Fact] | None = None, extra_facts: list[Fact] | None = None) -> dict[str, Any]:
    fg = FactGraph()
    for f in text_facts.extract(text_facts.given_text(required_text), required=True):
        fg.add(f)
    for kind, c in text_facts.clauses(full_text or required_text):
        if kind == "CLAIM":
            for f in text_facts.extract(c, required=False):
                if f.fact_type != "point":
                    f.criticality = "CONTEXT_ONLY"
                    f.raw_text = "CLAIM: " + c
                    fg.add(f)
    if full_text and full_text != required_text:
        # everything else in the question: REQUIRED_FOR_SOLUTION / CONTEXT_ONLY - recorded, never blocking
        for f in text_facts.extract(full_text, required=False):
            if not any(g.key == f.key and g.required for g in fg.facts):
                f.criticality = "REQUIRED_FOR_SOLUTION" if f.fact_type in text_facts_critical() else "CONTEXT_ONLY"
                fg.add(f)
    review_flags = [f for f in fg.facts if f.fact_type == "needs_review"]
    for f in [f for f in fg.facts if f.fact_type == "dimension" and f.source == "question_text"]:
        tgt = target_entity_ids(spec, f.value) if isinstance(f.value, dict) else None
        if tgt is not None and len(tgt) > 1:
            review_flags.append(Fact(fact_type="needs_review", entities=[], source="question_text", required=False,
                                     value=f"המידה {f.value['value']:g} עמומה בין {' ל-'.join(sorted(tgt))} — יש לאשר לאיזה אובייקט היא שייכת"))
    for f in cv_facts or []:
        fg.add(f)
    for f in extra_facts or []:
        fg.add(f)
    asserted = spec_facts(spec)
    for f in asserted:
        fg.add(f)
    critical: list[str] = []
    missing_required: list[str] = []
    applies = APPLIES.get(spec.diagram_type, set())
    checked = represented = 0
    review_extent: list[str] = []
    for f in fg.required():
        if f.fact_type not in applies:
            continue
        ok = satisfied(spec, f)
        if ok is None:
            continue
        checked += 1
        if ok:
            represented += 1
            fg.add(Fact(fact_type=f.fact_type, entities=f.entities, value=f.value, source="derived_math", required=False))
        elif f.fact_type == "extent":
            # Hebrew exam wording often says "הישר AD" for a drawn segment: text vs drawing extent -> teacher review, not a block
            review_extent.append(f"LINEAR_EXTENT_REVIEW: בנוסח {f.value} ({''.join(f.entities)}), בשרטוט אחרת — יש לאשר את היקף הקו.")
        else:
            tag = f"missing_required_{f.fact_type}_{'_'.join(f.entities)}" if f.fact_type == "point" else f"required_fact_not_represented:{f.key}"
            missing_required.append(tag)
            critical.append(f"עובדה מפורשת מנוסח השאלה חסרה או לא מתקיימת בשחזור: {f.key}" +
                            (f" ({tag})" if f.fact_type == "point" else ""))
    # contradictions: mutually exclusive text vs vision assertions + text relations badly violated by the raw proposal
    contradictions = _contradictions(fg, spec, raw_points or {}) + review_extent
    fg.contradictions = contradictions
    # dimension semantics: same value, different meaning (radius vs diameter) -> critical
    for f in fg.facts:
        if f.fact_type == "dimension" and f.source == "question_text" and spec.spatial is not None:
            for d in spec.spatial.dimensions:
                if d.value is not None and abs(d.value - f.value["value"]) < 1e-9 and d.measure != f.value["dimension_type"] \
                        and {d.measure, f.value["dimension_type"]} <= {"radius", "diameter"}:
                    critical.append(f"בלבול רדיוס/קוטר: בשאלה {f.value['dimension_type']} = {f.value['value']:g}, בשחזור {d.measure}.")
    # coverage of what the reconstruction asserts
    asserted_keys = {f.key for f in asserted}
    cov = fg.coverage(asserted_keys)
    semantic = (represented / checked) if checked else 1.0
    semantic = max(0.0, semantic - 0.1 * len(contradictions))
    if review_flags:
        cov["ambiguous_fact_count"] += len(review_flags)
        cov["ambiguous_facts"] = cov.get("ambiguous_facts", []) + [str(f.value) for f in review_flags]
    return {"fact_graph": fg, "review_flags": [str(f.value) for f in review_flags], "critical": critical, "missing_required": missing_required, "contradictions": contradictions,
            "coverage": cov, "semantic_confidence": round(semantic, 3), "required_checked": checked, "required_represented": represented}


EXCLUSIVE = [("parallel_to_x_axis", "parallel_to_y_axis")]


def _contradictions(fg: FactGraph, spec: DiagramSpec, raw_points: dict) -> list[str]:
    out = []
    by_ent: dict[tuple, dict[str, set]] = {}
    for f in fg.facts:
        by_ent.setdefault(tuple(sorted(f.entities)), {}).setdefault(f.fact_type, set()).add(f.source)
    for ents, types in by_ent.items():
        for a, b in EXCLUSIVE:
            if a in types and b in types:
                out.append(f"סתירה בין מקורות: {a} מול {b} עבור {''.join(ents)} (הטקסט גובר).")
    # the vision's raw layout vs explicit text axis relations
    for f in fg.facts:
        if f.source != "question_text" or f.fact_type not in ("parallel_to_x_axis", "parallel_to_y_axis") or not raw_points:
            continue
        pa, pb = (raw_points.get(k) for k in f.entities[:2])
        if pa is None or pb is None:
            continue
        dx, dy = abs(float(pb[0]) - float(pa[0])), abs(float(pb[1]) - float(pa[1]))
        ang = math.degrees(math.atan2(dy, dx))
        bad = ang > 30 if f.fact_type == "parallel_to_x_axis" else ang < 60
        if bad:
            out.append(f"סתירה: בנוסח השאלה {f.key}, אך בהצעת ה-AI הקטע {''.join(f.entities)} בזווית {ang:.0f}° (הטקסט גובר).")
    return out


def confidence(model_conf: float, deterministic: float, semantic: float, coverage: float) -> dict[str, float]:
    final = min(model_conf, deterministic, semantic, coverage)
    return {"model_confidence": round(model_conf, 3), "verification_coverage": round(coverage, 3),
            "deterministic_confidence": round(deterministic, 3), "semantic_confidence": round(semantic, 3),
            "final_confidence": round(final, 3)}


def symbol_table(text: str) -> dict[str, dict]:
    return symtab.extract(text)


_unused = (canonical, GConstraint, HIGH_COVERAGE)
