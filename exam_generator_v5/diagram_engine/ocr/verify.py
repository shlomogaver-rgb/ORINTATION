"""OCR evidence vs the vision proposal: confirmations become independent facts (source ocr_engine); disagreements become
conflicts resolved by the question text or left UNRESOLVED (teacher must decide). OCR misreads never create facts."""
from __future__ import annotations

import re

from ..fact_graph import Fact
from ..schemas import DiagramSpec
from . import engine

NUMRE = re.compile(r"-?\d+(?:\.\d+)?%?")


def _norm(t: str) -> str:
    return (t or "").replace(",", "").replace(" ", "").strip()


def _loose(a: str, b: str) -> bool:
    """'05%' vs '0.5%': same digits, dot dropped by OCR -> neither confirmation nor conflict."""
    return a.replace(".", "") == b.replace(".", "")


def text_numbers(text: str) -> set[str]:
    return {_norm(n) for n in NUMRE.findall((text or "").replace("−", "-"))}


def run(spec: DiagramSpec, source_png: bytes | None, question_text: str = "") -> dict:
    """{"available", "facts", "conflicts": [{"where","vision","ocr","resolved","message"}], "notes"}"""
    out = {"available": engine.available(), "facts": [], "conflicts": [], "notes": [], "inventory": {}, "status": "SUCCESS"}
    if not out["available"]:
        out["status"] = "ENGINE_UNAVAILABLE"
        out["notes"].append("OCR עצמאי אינו זמין — המספרים והתוויות לא אומתו באופן עצמאי.")
        return out
    if not source_png:
        out["status"] = "INVALID_INPUT"
        return out
    tnums = text_numbers(question_text)
    try:
        if spec.table is not None:
            _table(spec, source_png, out, tnums)
        elif spec.normal is not None:
            _multiset(spec.normal.percentages, [t for t in engine.numbers(source_png) if "%" in t["text"]], "region_label", out, tnums)
        if spec.spatial is not None and spec.spatial.dimensions:
            toks = engine.numbers(source_png)
            got = {_norm(t["text"]).rstrip("%") for t in toks}
            for d in spec.spatial.dimensions:
                if d.value is not None and f"{d.value:g}" in got:
                    out["facts"].append(Fact(fact_type="dimension_value", entities=[f"{d.value:g}"], source="ocr_engine"))
        geo = spec.geometry or (spec.mixed.geometry if spec.mixed else None)
        if geo is not None:
            _geometry_numbers(geo, source_png, out, tnums)
        names = set()
        if geo is not None:
            names = {p.id for p in geo.points if not p.hidden}
        elif spec.generic is not None:
            names = {l.text for l in spec.generic.labels}
        elif spec.spatial is not None:
            sp_ = spec.spatial
            names = {v for s in sp_.solids for v in s.vertices}
            names |= {p.id for p in sp_.points_on_edges + sp_.points_on_diagonals + sp_.points_on_segments}
        if names or spec.diagram_type in ("geometry", "mixed_graph_geometry", "generic", "spatial"):
            toks = engine.labels(source_png)
            found = {t["text"] for t in toks if t["conf"] >= 0.75}
            axis_letters = {"x", "y", "z", "X", "Y", "Z", "O"}            # axis names / origin are not scene entities
            found -= axis_letters
            for tok in toks:
                if tok["text"] in names:
                    out["facts"].append(Fact(fact_type="point", entities=[tok["text"]], source="ocr_engine", confidence=tok["conf"]))
            base = {n.split("'")[0].split("_")[0] for n in names}       # A' in the spec explains an OCR 'A'
            out["inventory"] = {"source_label_inventory": sorted(found), "scene_graph_label_inventory": sorted(names),
                                "missing_from_spec": [f"MISSING_FROM_SPEC:{l}" for l in sorted(found - names - base)],
                                "unverified_render_labels": sorted(names - found)}
    except Exception as exc:  # OCR failure = no evidence (NOT "no text"), never a crash
        out["status"] = "TIMEOUT" if "timeout" in type(exc).__name__.lower() or "Timeout" in str(exc) else "FAILED"
        out["facts"], out["inventory"] = [], {}
        out["notes"].append(f"OCR נכשל ({type(exc).__name__}) — אין אימות OCR (כשל אינו ראיה להיעדר תווית).")
        return out
    if out["status"] == "SUCCESS" and not out["facts"] and not out["conflicts"] and not out["inventory"].get("source_label_inventory"):
        out["status"] = "SUCCESS_NO_TEXT"
    return out


def _conflict(out: dict, where: str, vision: str, ocr: str, tnums: set[str]) -> None:
    if ocr in tnums and vision not in tnums:
        resolved, msg = "text+ocr", (f"{where}: בשחזור {vision}, אך גם OCR וגם נוסח השאלה מראים {ocr} — השחזור שגוי.")
    elif vision in tnums and ocr not in tnums:
        out["notes"].append(f"{where}: OCR קרא {ocr}, אך נוסח השאלה מאשר {vision} (שגיאת OCR).")
        return
    else:
        resolved, msg = "unresolved", (f"לא ניתן לקבוע בוודאות אם הערך ב{where} הוא {vision} או {ocr}. "
                                       f"OCR זיהה {ocr} וניתוח התמונה זיהה {vision}. אנא אשר את הערך הנכון.")
    out["conflicts"].append({"where": where, "vision": vision, "ocr": ocr, "resolved": resolved, "message": msg})


def _table(spec: DiagramSpec, png: bytes, out: dict, tnums: set[str]) -> None:
    res = engine.table_cells(png, rtl=spec.table.rtl)
    rows = spec.table.rows
    if not res["ok"] or len(res["rows"]) != len(rows) or any(len(a) != len(b) for a, b in zip(res["rows"], rows)):
        out["notes"].append("OCR לא הצליח לקרוא את מבנה הטבלה — התאים לא אומתו באופן עצמאי.")
        return
    for r, (orow, srow) in enumerate(zip(res["rows"], rows)):
        for c, (oc, sc) in enumerate(zip(orow, srow)):
            sv = _norm(sc.text)
            if not NUMRE.fullmatch(sv):
                continue
            ov = _norm(oc["numeric"] or (oc["text"] if NUMRE.fullmatch(_norm(oc["text"])) else ""))
            if ov == sv:
                out["facts"].append(Fact(fact_type="table_cell", entities=[f"{r},{c}"], value=sv, source="ocr_engine"))
            elif ov and oc["conf"] >= 0.75 and not _loose(ov, sv):
                from ..charts.table import semantic_cells
                sem = next((x for x in semantic_cells(spec.table) if x["row"] == r and x["col"] == c), None)
                where = (f"התא '{sem['row_header']}' / '{sem['column_header']}'" if sem and (sem["row_header"] or sem["column_header"])
                         else f"תא ({r + 1},{c + 1})")
                _conflict(out, where, sv, ov, tnums)


def _multiset(labels: list[str], toks: list[dict], fact_type: str, out: dict, tnums: set[str]) -> None:
    pool = [_norm(t["text"]) for t in toks]
    for i, lab in enumerate(labels):
        v = _norm(lab)
        if v in pool:
            pool.remove(v)
            out["facts"].append(Fact(fact_type=fact_type, entities=[str(i)], value=lab, source="ocr_engine"))
    for t in toks:
        v = _norm(t["text"])
        if v in pool and t["conf"] >= 0.85 and not any(_loose(v, _norm(l)) for l in labels):
            pool.remove(v)
            _conflict(out, "תווית בתרשים", "(אין)", v, tnums)


def _num_of(text: str) -> str | None:
    m = NUMRE.search((text or "").replace(",", "."))
    return m.group(0).rstrip("%") if m else None


def _geometry_numbers(geo, png: bytes, out: dict, tnums: set[str]) -> None:
    """Independent verification of LENGTH labels / DIMENSIONS and ANGLE values. OCR discovers every number in the ROI;
    each spec value is CONFIRMED, CONFLICT (OCR reads a different value where the counts line up) or OCR_UNRESOLVED."""
    lengths = [(f"{l.a}{l.b}", _num_of(l.text)) for l in geo.length_labels] + [(d.text, _num_of(d.text)) for d in geo.dimensions]
    lengths = [(w, v) for w, v in lengths if v]
    angles = [(f"∠{m.a}{m.vertex}{m.b}", _num_of(m.value)) for m in geo.angle_marks if m.kind == "arc" and _num_of(m.value)]
    if not lengths and not angles:
        return
    ntok = [t for t in engine.numbers(png) if "%" not in t["text"]]
    atok = engine.angle_numbers(png) if angles else []
    res = out.setdefault("geometry_numbers", {"confirmed": [], "conflicts": [], "unresolved": [], "binding": "none"})
    # ---- entity binding: spec coordinates -> source pixels through the OCR'd point labels (affine least squares)
    import numpy as np
    P = {p.id: (p.x, p.y) for p in geo.points}
    labs = {}
    for t in engine.labels(png):
        if t["text"] in P and t["text"] not in labs:
            labs[t["text"]] = (t["cx"], t["cy"])
    if len(labs) >= 3:
        S = np.array([[P[k][0], P[k][1], 1.0] for k in labs])
        D = np.array([labs[k] for k in labs])
        M, *_ = np.linalg.lstsq(S, D, rcond=None)
        if np.linalg.matrix_rank(S) == 3:
            to_px = lambda x, y: np.array([x, y, 1.0]) @ M  # noqa: E731
            segs = {f"{l.a}{l.b}": (_num_of(l.text), to_px(*((np.array(P[l.a]) + np.array(P[l.b])) / 2)))
                    for l in geo.length_labels if l.a in P and l.b in P and _num_of(l.text)}
            if segs:
                res["binding"] = "affine"
                owner = {}
                for t in ntok:                              # every OCR number belongs to the NEAREST labelled segment
                    c = np.array([t["cx"], t["cy"]])
                    w = min(segs, key=lambda k: float(np.linalg.norm(segs[k][1] - c)))
                    d = float(np.linalg.norm(segs[w][1] - c))
                    if w not in owner or d < owner[w][1]:
                        owner[w] = (_norm(t["text"]), d, t["conf"])
                for w, (v, _) in segs.items():
                    got = owner.get(w)
                    if got is None:
                        res["unresolved"].append(w)
                    elif got[0] == v:
                        res["confirmed"].append(w)
                        out["facts"].append(Fact(fact_type="length_value", entities=[w], value=v, source="ocr_engine"))
                    elif got[2] >= 0.75:
                        _conflict(out, f"אורך {w}", v, got[0], tnums)
                        out["conflicts"][-1]["kind"] = "LENGTH_VALUE_CONFLICT"
                        out["conflicts"][-1]["message"] = "LENGTH_VALUE_CONFLICT (שיוך לפי מיקום): " + out["conflicts"][-1]["message"]
                        res["conflicts"].append(w)
                lengths = [(w_, v_) for w_, v_ in lengths if w_ not in segs]          # the rest (dimensions) below
    elif lengths:
        res["binding"] = "unverified: fewer than 3 point labels read - values are NOT bound to entities"
    pool = [_norm(t["text"]) for t in ntok]
    apool = [t for t in atok]
    for where, v in angles:
        hit = next((t for t in apool if v in t["alternatives"]), None)
        if hit:
            apool.remove(hit)
            res["confirmed"].append(where)
            out["facts"].append(Fact(fact_type="angle_value", entities=[where], value=v, source="ocr_engine"))
            if v in pool:
                pool.remove(v)
        else:
            res["unresolved"].append(where)
    for where, v in lengths:
        if v in pool and res["binding"] != "affine" and not res["binding"].startswith("unverified"):
            pool.remove(v)
            res["confirmed"].append(where)
            out["facts"].append(Fact(fact_type="length_value", entities=[where], value=v, source="ocr_engine"))
        elif v in pool:
            pool.remove(v)
            res.setdefault("value_only", []).append(where)                 # seen, but not bound: not a confirmation
        else:
            res["unresolved"].append(where)
    # a conflict only when the numbers line up one-to-one (no guessing about which label an OCR token belongs to)
    un_len = [w for w, v in lengths if w in res["unresolved"]]
    un_ang = [w for w, v in angles if w in res["unresolved"]]
    left_len = [t for t in ntok if _norm(t["text"]) in pool and t["conf"] >= 0.85]
    left_ang = [t for t in apool if t["degree"] and t["conf"] >= 0.85]
    if len(un_ang) == 1 and len(left_ang) == 1:
        v = dict(angles)[un_ang[0]]
        _conflict(out, f"זווית {un_ang[0]}", v + "°", left_ang[0]["alternatives"][0] + "°", tnums)
        out["conflicts"][-1]["kind"] = "ANGLE_VALUE_CONFLICT"
        out["conflicts"][-1]["message"] = "ANGLE_VALUE_CONFLICT: " + out["conflicts"][-1]["message"]
        res["conflicts"].append(un_ang[0])
    if len(un_len) == 1 and len(left_len) == 1:
        v = dict(lengths)[un_len[0]]
        _conflict(out, f"אורך {un_len[0]}", v, _norm(left_len[0]["text"]), tnums)
        out["conflicts"][-1]["kind"] = "LENGTH_VALUE_CONFLICT"
        out["conflicts"][-1]["message"] = "LENGTH_VALUE_CONFLICT: " + out["conflicts"][-1]["message"]
        res["conflicts"].append(un_len[0])
