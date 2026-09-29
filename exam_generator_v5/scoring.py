"""ONE canonical scoring model (validator, rebalance / UI auto-balance, rubric, DOCX and the PASS-1 prompt all use it).

A question has MANDATORY sections and optional SELECTION GROUPS ("answer K of these N"). A section's stored points are its
points_if_answered. The ANSWERED total = sum(mandatory) + sum_over_groups(K x option points) and must equal the question total.
Rubric percentages are relative to the question total, so over ALL options they sum to 100 x sum(points)/total (> 100 with
choices) - that is not an error."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TOL = Decimal("0.02")
Q2 = Decimal("0.01")


def _d(x) -> Decimal:
    return Decimal(str(x or 0))


VIRTUAL = "__all__"


def groups(q) -> dict[str, int]:
    g = {sg.group_id: int(sg.choose_k) for sg in getattr(q, "selection_groups", []) or []}
    g = {k: v for k, v in g.items() if k and v > 0}
    k_all = int(getattr(q, "required_sections", 0) or 0)
    if not g and 0 < k_all < len(q.sections):
        g = {VIRTUAL: k_all}                         # legacy shorthand: answer K of ALL subparts
    return g


def members(q, gid: str) -> list:
    if gid == VIRTUAL:
        return list(q.sections)
    return [s for s in q.sections if getattr(s, "selection_group", "") == gid]


def is_optional(q, s) -> bool:
    gs = groups(q)
    sg = getattr(s, "selection_group", "")
    return VIRTUAL in gs or (bool(sg) and sg in gs)


def points_if_answered(q, sid: str) -> float:
    return next(float(s.points) for s in q.sections if s.section_id == sid)


def answered_total(q) -> float:
    tot = sum(_d(s.points) for s in q.sections if not is_optional(q, s))
    for gid, k in groups(q).items():
        opts = members(q, gid)
        if opts:
            tot += k * max(_d(s.points) for s in opts)
    return float(tot)


def _general_share(q) -> Decimal:
    ids = {s.section_id for s in q.sections}
    return sum((_d(r.percentage) for r in q.rubric_steps if r.section_id not in ids), Decimal("0"))


def rubric_target(q) -> Decimal:
    """100 per ANSWERED path: general stages G + (100 - G) x sum(points_if_answered) / total over all options."""
    total = _d(q.points)
    if total <= 0 or not groups(q):
        return Decimal("100")
    g = _general_share(q)
    return g + (Decimal("100") - g) * sum(_d(s.points) for s in q.sections) / total


def check(q) -> list[str]:
    """Human-readable errors (empty list = consistent)."""
    out = []
    total = _d(q.points)
    gs = groups(q)
    for gid, k in gs.items():
        opts = members(q, gid)
        if k >= len(opts):
            out.append(f"קבוצת בחירה {gid}: יש לבחור {k} מתוך {len(opts)} — אין בחירה.")
            continue
        per = {(_d(s.points)).quantize(Q2) for s in opts}
        if len(per) > 1 and max(per) - min(per) > TOL:
            out.append(f"בקבוצת הבחירה ({k} מתוך {len(opts)}) לכל הסעיפים צריך להיות אותו ניקוד.")
    if q.sections and abs(_d(answered_total(q)) - total) > TOL * max(1, sum(gs.values())):
        if gs:
            k, n = next(iter(gs.values())), len(members(q, next(iter(gs))))
            out.append(f"ניקוד הסעיפים אינו תואם את כלל הבחירה: בשאלת 'ענו על {k} מתוך {n}' סכום הסעיפים הנענים "
                       f"צריך להיות {total} (כעת {answered_total(q):g}).")
        else:
            out.append(f"סכום ניקוד הסעיפים הוא {answered_total(q):g}, אך ניקוד השאלה הוא {total}.")
    if q.rubric_steps:
        rs = sum(_d(r.percentage) for r in q.rubric_steps)
        tgt = rubric_target(q)
        if abs(rs - tgt) > Decimal("0.5"):
            out.append(f"סכום אחוזי המחוון הוא {rs}% במקום {tgt:.1f}%.")
    return out


def rebalance(q) -> None:
    """UI 'auto-balance': keep the selection rule. Weights are scaled so the ANSWERED total equals the question total;
    options inside a group get equal points (their mean weight). Rubric steps are scaled per section to its share."""
    total = _d(q.points)
    gs = groups(q)
    if q.sections:
        mand = [s for s in q.sections if not is_optional(q, s)]
        wsum = sum(_d(s.points) for s in mand)
        means = {}
        for gid, k in gs.items():
            opts = members(q, gid)
            m = sum(_d(s.points) for s in opts) / len(opts) if opts else Decimal("0")
            means[gid] = m if m > 0 else Decimal("1")
            wsum += k * means[gid]
        if wsum <= 0:
            wsum = Decimal(len(mand) + sum(gs.values())) or Decimal("1")
            for s in mand:
                s.points = 1.0
        f = total / wsum
        new_mand = [(_d(s.points) * f).quantize(Q2, rounding=ROUND_HALF_UP) for s in mand]
        if mand and not gs:
            new_mand[-1] += total - sum(new_mand, Decimal("0"))          # exact total when there is no choice
        for s, v in zip(mand, new_mand):
            s.points = float(v)
        for gid in gs:
            per = (means[gid] * f).quantize(Q2, rounding=ROUND_HALF_UP)
            for s in members(q, gid):
                s.points = float(per)
    if q.rubric_steps:
        pts = {s.section_id: _d(s.points) for s in q.sections}
        by_sec: dict[str, list] = {}
        for r in q.rubric_steps:
            by_sec.setdefault(r.section_id if r.section_id in pts else "", []).append(r)
        if not gs or "" in by_sec and len(by_sec) == 1:
            raw = [_d(r.percentage) for r in q.rubric_steps]
            ssum = sum(raw, Decimal("0"))
            if ssum > 0:
                new = [(r_ * Decimal("100") / ssum).quantize(Q2, rounding=ROUND_HALF_UP) for r_ in raw]
                new[-1] += Decimal("100") - sum(new, Decimal("0"))
                for r_, v in zip(q.rubric_steps, new):
                    r_.percentage = float(v)
        else:
            general = min(sum((_d(r_.percentage) for r_ in by_sec.get("", [])), Decimal("0")), Decimal("50"))
            for sid, steps in by_sec.items():
                if sid == "":                                                # general stages keep their share
                    continue
                share = (Decimal("100") - general) * pts.get(sid, Decimal("0")) / total if total > 0 else Decimal("0")
                raw = [_d(r_.percentage) for r_ in steps]
                ssum = sum(raw, Decimal("0")) or Decimal(len(steps))
                for r_, w in zip(steps, raw or [Decimal("1")] * len(steps)):
                    r_.percentage = float((share * (w if ssum != len(steps) or any(raw) else 1) / ssum).quantize(Q2, rounding=ROUND_HALF_UP))


def selection_note(q) -> str:
    """DOCX: the answering rule shown to the student."""
    notes = []
    for gid, k in groups(q).items():
        opts = members(q, gid)
        if opts and k < len(opts):
            ids = "–".join([opts[0].section_id, opts[-1].section_id]) if len(opts) > 1 else opts[0].section_id
            notes.append(f"ענו על {k} מתוך {len(opts)} הסעיפים {ids} (לכל סעיף {float(opts[0].points):.2f} נקודות).")
    return " ".join(notes)
