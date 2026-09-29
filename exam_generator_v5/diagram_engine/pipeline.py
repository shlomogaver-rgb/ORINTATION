"""Diagram pipeline v2 - ONE entry point per figure. Never raises: any failure means 'use the original'.

SOURCE -> preprocess -> structured evidence (vision JSON + question text) -> DiagramSpec -> schema validation ->
text/marks merge -> constraint solving -> deterministic validation -> deterministic renderer -> source comparison ->
decision -> teacher review -> (approved) export."""
from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from . import audit, cache, safe_math as sm
from .charts import parser as chart_parser
from .charts import scatter as scatter_mod
from .classifier import classify
from .comparison import compare
from .decision import DEFAULT_POLICY, Policy, decide_v3, parser_confidence
from . import symbols as symtab
from . import verification
from .fact_graph import Fact
from .evidence import ev
from .geometry import parser as geometry_parser
from .geometry.solver import solve as solve_geometry
from .graph import feature_detector, formula_parser
from .mixed import parser as mixed_parser
from .mixed import solver as mixed_solver
from .preprocess import cleaned_png, image_hash
from .review_state import add_edit, initial_review, spec_hash
from .schemas import PARSER_VERSION, ComparisonResult, Decision, DiagramRecord, DiagramSpec, ReviewState, ValidationResult
from .validator import validate

log = logging.getLogger("diagram_engine")
_RENDER_LOCK = Lock()   # matplotlib rcParams are global: renders from parallel question workers must not interleave
MSG_ORIGINAL = "השחזור נחסם. נדרשת החלטת מורה. ניתן לבחור בסריקה המקורית רק כחריגה מפורשת ומתועדת."


# ------------------------------------------------------------------ parsing (incl. legacy format of 5.x)
def _legacy_to_spec(data: dict, figure_type: str, confidence: float) -> dict:
    if figure_type == "function_graph" or "objects" in data and any(o.get("type") == "function" for o in data.get("objects", [])):
        xr, yr = data.get("x_range", [-10, 10]), data.get("y_range", [-10, 10])
        curves, points = [], []
        for i, o in enumerate(data.get("objects", [])):
            if o.get("type") == "function":
                curves.append({"id": f"c{i}", "label": o.get("label", ""), "expression": o.get("expression", "")})
            elif o.get("type") == "point":
                points.append({"name": o.get("label", ""), "x": o.get("x", 0), "y": o.get("y", 0)})
        return {"diagram_type": "graph", "confidence": confidence,
                "graph": {"axes": {"x_min": xr[0], "x_max": xr[1], "y_min": yr[0], "y_max": yr[1]}, "curves": curves, "points": points}}
    if figure_type == "geometry":
        geo: dict[str, Any] = {"points": [], "segments": [], "circles": [], "angle_marks": [], "length_labels": []}
        for o in data.get("objects", []):
            t = o.get("type")
            if t == "point":
                geo["points"].append({"id": o.get("label", ""), "x": o.get("x", 0), "y": o.get("y", 0)})
            elif t == "segment":
                geo["segments"].append({"a": o.get("from"), "b": o.get("to")})
            elif t == "polygon":
                v = o.get("vertices", [])
                geo["segments"] += [{"a": v[i], "b": v[(i + 1) % len(v)]} for i in range(len(v))]
            elif t == "circle":
                geo["circles"].append({"center": o.get("center"), "radius": o.get("radius")})
            elif t == "length_label":
                geo["length_labels"].append({"a": o.get("from"), "b": o.get("to"), "text": o.get("text", "")})
            elif t == "angle_mark" and len(o.get("arms", [])) == 2:
                val = str(o.get("text", ""))
                kind = "right" if val.strip() in ("90", "90°") else "arc"
                geo["angle_marks"].append({"vertex": o["vertex"], "a": o["arms"][0], "b": o["arms"][1], "kind": kind,
                                           "value": "" if kind == "right" else val})
        return {"diagram_type": "geometry", "confidence": confidence, "geometry": geo}
    if figure_type in ("bar_chart", "line_chart", "pie_chart"):
        kind = {"bar_chart": "bar", "line_chart": "line", "pie_chart": "pie"}[figure_type]
        return {"diagram_type": "chart", "confidence": confidence,
                "chart": {"kind": kind, "categories": data.get("categories") or data.get("labels") or [], "values": data.get("values", []),
                          "title": data.get("title", ""), "show_percentages": bool(data.get("show_percentages"))}}
    return {"diagram_type": "unknown", "confidence": 0.0}


IGNORED_KEYS = {"confidence", "source", "bbox", "notes", "comment", "id"}


def _unknown_keys(data: Any, model: Any, path: str = "") -> list[str]:
    """Keys present in the AI JSON that the schema would silently drop -> reported, never silently lost."""
    from pydantic import BaseModel

    out: list[str] = []
    if isinstance(data, dict) and isinstance(model, BaseModel):
        fields = type(model).model_fields
        aliases = set()
        for name, f in fields.items():
            aliases.add(name)
            va = getattr(f, "validation_alias", None)
            if va is not None and hasattr(va, "choices"):
                aliases |= {c for c in va.choices if isinstance(c, str)}
        for k, v in data.items():
            if k not in aliases:
                if k not in IGNORED_KEYS and v not in (None, [], {}, ""):
                    out.append(f"{path}{k}")
                continue
            sub = getattr(model, k, None)
            if sub is None:
                name = next((n for n, f in fields.items() if getattr(f, "validation_alias", None) is not None
                             and hasattr(f.validation_alias, "choices") and k in f.validation_alias.choices), None)
                sub = getattr(model, name, None) if name else None
            out += _unknown_keys(v, sub, f"{path}{k}.")
    elif isinstance(data, list) and isinstance(model, list):
        for i, (d, m) in enumerate(zip(data, model)):
            out += _unknown_keys(d, m, f"{path}{i}.")
    return out


def parse_raw(raw: str, figure_type: str = "", fallback_confidence: float = 0.0) -> DiagramSpec:
    data = json.loads(raw) if raw and raw.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("ה-JSON של השרטוט אינו אובייקט")
    if "diagram_type" not in data:
        data = _legacy_to_spec(data, figure_type, fallback_confidence)
    spec = DiagramSpec.model_validate(data)
    lost = [k for k in _unknown_keys(data, spec) if not k.startswith(("observed.", "labels.", "evidence."))]
    if lost:
        spec.unsupported_features = list(dict.fromkeys(spec.unsupported_features + lost))
    return spec


# ------------------------------------------------------------------ rendering (cached by spec hash, serialised)
def _renderer(spec: DiagramSpec):
    t, st = spec.diagram_type, spec.subtype
    if t == "graph":
        from .graph.renderer import render
        return render
    if t == "geometry":
        from .geometry.renderer import render
        return render
    if t == "mixed_graph_geometry":
        from .mixed.renderer import render
        return render
    if t == "chart" and st == "scatter_plot":
        from .charts.renderer import render_scatter
        return render_scatter
    if t == "chart" and st == "normal_distribution_schematic":
        from .charts.normal_distribution import render as r
        return lambda sp: r(sp.normal)
    if t == "chart":
        from .charts.renderer import render
        return render
    if t == "table":
        from .charts.table import render as r
        return lambda sp: r(sp.table)
    if t == "generic":
        from .generic.renderer import render
        return render
    if t == "spatial":
        from .spatial.renderer import render
        return render
    raise ValueError("אין מנוע שרטוט לסוג זה")


def _layout_values(spec: DiagramSpec) -> dict[str, float]:
    g = spec.graph or (spec.mixed.graph if spec.mixed else None)
    vals = {k: symtab.layout_value(k, v) for k, v in spec.symbols.items()}
    if g is not None:
        vals.update(g.parameter_values)
    return vals


def render_spec(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    fn = _renderer(spec)

    def run() -> tuple[str, bytes, dict]:
        with _RENDER_LOCK, sm.symbol_context(spec.symbols, _layout_values(spec)):
            return fn(spec)

    return cache.RENDER.get_or_compute(cache.key("render", spec_hash(spec), spec.diagram_type, spec.subtype), run)


# ------------------------------------------------------------------ evidence
def _evidence(spec: DiagramSpec) -> list:
    out = [ev("ocr", "label", l.text, l.confidence, bbox=l.bbox or None, ambiguous=l.ambiguous, alternatives=l.alternatives)
           for l in spec.labels]
    geo = spec.geometry or (spec.mixed.geometry if spec.mixed else None)
    if geo is not None:
        out += [ev(c.source, "relation", {"type": c.type, "points": c.points, "value": c.value}) for c in geo.constraints]
        out += [ev("text", "coordinate", {"key": p.id, "xy": [p.x, p.y]}) for p in geo.points if p.fixed]
    g = spec.graph or (spec.mixed.graph if spec.mixed else None)
    if g is not None:
        out += [ev(c.source, "equation", {"key": c.id, "expr": c.expression}, c.confidence) for c in g.curves if c.expression]
    obs = {k: v for k, v in spec.observed.model_dump().items() if v is not None}
    if obs:
        out.append(ev("vision", "source_signature", obs, spec.confidence))
    return out


# ------------------------------------------------------------------ main entry
def process(figure_id: str, raw_spec_json: str, question_text: str, source_png: bytes | None, *,
            figure_type_hint: str = "", fallback_confidence: float = 0.0, ai_model: str = "",
            prior_review: ReviewState | None = None, allow_auto: bool = False, teacher_spec: DiagramSpec | None = None,
            policy: Policy = DEFAULT_POLICY, required_text: str | None = None,
            ground_truth_facts: list[Fact] | None = None, input_key: str = "",
            input_hashes: dict[str, str] | None = None, ai_spec: DiagramSpec | None = None) -> DiagramRecord:
    """allow_auto is accepted for v5.4 compatibility and ignored (no automatic export exists any more).
    required_text: the question STEM whose explicit facts MUST appear in the figure (default: question_text).
    ground_truth_facts: hand-authored acceptance truth (tests only) - an independent verifier."""
    rec = DiagramRecord(figure_id=figure_id, raw_spec_json=raw_spec_json or "", input_key=input_key,
                        input_hashes=dict(input_hashes or {}))
    rec.input_hashes.setdefault("diagram_input_hash", image_hash(source_png or b""))
    rec.input_hashes.setdefault("ocr_input_hash", image_hash(source_png or b""))
    try:
        if teacher_spec is not None:
            spec = teacher_spec.model_copy(deep=True)
        elif ai_spec is not None:                      # PASS 2 native structured output (typed, no JSON string)
            spec = ai_spec.model_copy(deep=True)
            rec.audit["spec_source"] = "Gemini/Diagram/Pass2 (typed)"
        else:
            spec = parse_raw(raw_spec_json, figure_type_hint, fallback_confidence)
            rec.audit["spec_source"] = "legacy spec_json"
        spec.source_image_hash = image_hash(source_png or b"")
        spec.parser_version = PARSER_VERSION
        spec.symbols = symtab.extract(question_text)          # parameters come from the TEXT, never from the AI
        rec.spec = spec
        with sm.symbol_context(spec.symbols, _layout_values(spec)):
            return _process_body(rec, spec, question_text, source_png, figure_id, ai_model, prior_review, teacher_spec, policy,
                                 required_text if required_text is not None else question_text, ground_truth_facts)
    except Exception as exc:  # one diagram must never break the exam
        log.exception("diagram pipeline failed for %s", figure_id)
        rec.render_error = f"{type(exc).__name__}: {exc}"
        code = "SCHEMA_VALIDATION_FAILED" if isinstance(exc, (json.JSONDecodeError, ValueError)) or "validation error" in str(exc) else "PIPELINE_ERROR"
        rec.audit["error_code"] = code
        rec.decision = Decision(action="original", reasons=[f"{code}: שחזור השרטוט נכשל."])
        rec.review = ReviewState(status="original")
        rec.teacher_message = "לא ניתן היה לשחזר את התרשים באופן אמין. השחזור נחסם. נדרשת החלטת מורה. ניתן לבחור בסריקה המקורית רק כחריגה מפורשת ומתועדת."
    return _finish(rec, ai_model, source_png)


def _process_body(rec, spec, question_text, source_png, figure_id, ai_model, prior_review, teacher_spec, policy,
                  required_text, ground_truth_facts) -> DiagramRecord:
    if True:  # (body kept at its v5.5 indentation)
        # typed mathematical semantics: engines BUILD a missing drawing / VERIFY the proposed one (before classification)
        from .semantic import bridge as sem_bridge
        sem_res = sem_bridge.apply(spec)
        if source_png and spec.spatial is not None and spec.spatial.voxel is not None:
            # CUBE STRUCTURE: read the number diagram FROM THE DRAWING (analysis-by-synthesis) and prove it is unique;
            # the model's reading is only the starting point
            from .spatial import voxel_fit
            vx = spec.spatial.voxel
            init = None
            if vx.columns:
                from .spatial.renderer import voxel_heights
                init = voxel_heights(vx).tolist()
            try:
                vf = voxel_fit.fit(source_png, init)
            except Exception as exc:                                            # never a guess on failure
                vf = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            rec.audit["voxel_fit"] = {k_: v_ for k_, v_ in vf.items() if k_ != "params"}
            if vf.get("ok"):
                from .schemas import VoxelColumn
                Hf = vf["heights"]
                if init is not None and init != Hf:
                    rec.audit["voxel_fit"]["model_reading_corrected"] = True
                vx.columns = [VoxelColumn(x=k_, y=r_, height=int(h_)) for r_, row in enumerate(Hf) for k_, h_ in enumerate(row) if h_]
                vx.plate = [len(Hf[0]), len(Hf)]
                vx.ambiguous = False
                spec.subtype = "voxel_structure"
            else:
                vx.ambiguous = True
                rec.contradictions.append("VOXEL_NOT_DETERMINED: " + (vf.get("reason") or "") +
                                          " — המבנה אינו נקבע באופן יחיד מן הציור; נדרשת קביעת תרשים המספרים.")
        rec.audit["semantics"] = sem_res
        ctype, cconf, creasons = classify(spec, question_text)
        rec.classifier_type, rec.classifier_subtype, rec.classifier_confidence = ctype, spec.subtype or "", cconf
        if ctype == "unknown":
            rec.validation.errors = creasons or ["סוג התרשים לא זוהה"]
            rec.decision = Decision(action="original", reasons=creasons)
            rec.teacher_message = "לא ניתן לשחזר את התרשים באופן אמין. השחזור נחסם. נדרשת החלטת מורה. ניתן לבחור בסריקה המקורית רק כחריגה מפורשת ומתועדת."
            rec.review = initial_review(rec, prior_review)
            return _finish(rec, ai_model, source_png)
        warns: list[str] = []
        solved = None
        feats: dict[str, Any] = {}
        detection_ok = False
        t, st = spec.diagram_type, spec.subtype
        if t == "graph" and st == "formula_graph":
            if teacher_spec is None:
                warns += formula_parser.merge_text(spec.graph, question_text, spec.observed.num_curves)
            from .graph import function_validator as fv
            for c in spec.graph.curves:
                if c.expression and not c.pieces:
                    try:
                        sym = sm.parse_expression(c.expression)
                        pts = [p for p in spec.graph.points if p.on_curve in ("", c.id)]
                        rec.audit.setdefault("math_conflicts", []).extend(fv.check_points(sym, pts if len(spec.graph.curves) == 1
                                                                                        else [p for p in pts if p.on_curve == c.id]))
                        rec.audit.setdefault("source_conflicts", []).extend(fv.text_claims(question_text, sym))
                        a_ = spec.graph.axes
                        rec.audit.setdefault("analytic", {})[c.id] = fv.concavity(sym, a_.x_min, a_.x_max)
                    except Exception:
                        pass
                    try:
                        f = feature_detector.features(sm.parse_expression(c.expression), spec.graph.axes.x_min, spec.graph.axes.x_max,
                                                      spec.graph.axes.y_max - spec.graph.axes.y_min)
                        feats[c.id] = f
                        feature_detector.add_computed_holes(spec.graph, c, f)
                    except Exception:
                        pass
        elif t == "graph" and st == "qualitative_graph" and formula_parser.functions_from_text(question_text):
            warns.append("בשאלה מופיעה נוסחה מפורשת — מומלץ לשחזר כגרף נוסחה (הגרף האיכותני אינו ממציא משוואה).")
        elif t == "geometry":
            if teacher_spec is None:
                warns += geometry_parser.merge_text(spec.geometry, question_text)
            else:
                for c in geometry_parser.marks_to_constraints(spec.geometry):
                    if not any(u.type == c.type and sorted(u.points) == sorted(c.points) for u in spec.geometry.constraints):
                        spec.geometry.constraints.append(c)
            solved = _solve_into(spec.geometry, rec, lambda: solve_geometry(spec.geometry))
        elif t == "mixed_graph_geometry":
            if teacher_spec is None:
                warns += mixed_parser.merge_text(spec.mixed, question_text, spec.observed.num_curves)
            solved = _solve_into(spec.mixed.geometry, rec, lambda: mixed_solver.solve(spec.mixed))
        elif t == "chart" and st == "scatter_plot":
            if source_png:
                det = scatter_mod.detect(source_png, spec.scatter.axes)
                rec.validation.info["scatter_detection"] = {"stable": det["stable"], "points": det["points"], "reason": det["reason"]}
                detection_ok = det["stable"] and not scatter_mod.match(spec.scatter.points, det["points"], spec.scatter.axes)
        elif t == "chart" and st != "normal_distribution_schematic" and teacher_spec is None:
            warns += chart_parser.merge_text(spec.chart, question_text)
        spec.evidence = _evidence(spec)
        spec.warnings = list(dict.fromkeys(spec.warnings + warns))
        info = rec.validation.info
        rec.validation = validate(spec, solved)
        rec.validation.info.update(info)
        rec.validation.warnings = list(dict.fromkeys(warns + rec.validation.warnings))
        if feats:
            rec.validation.info["graph_features"] = feats
        if solved is not None:
            rec.validation.info["constraints"] = {"max_residual": solved["max_residual"], "moved_fraction": solved["moved_fraction"]}
        rec.parser_confidence = parser_confidence(spec, solved, policy, detection_confirmed=detection_ok)
        png = None
        manifest: dict = {}
        if rec.validation.ok:
            try:
                _, png, manifest = render_spec(spec)
            except Exception as exc:
                log.exception("render failed for %s", figure_id)
                rec.render_error = f"{type(exc).__name__}: {exc}"
        rec.manifest = manifest
        if rec.validation.ok and not rec.render_error:
            main_feats = next(iter(feats.values()), None) if feats else None
            rec.comparison = compare(spec, manifest, source_png, png, question_text, main_feats)
            if solved is not None and solved["flips"]:
                rec.comparison.critical += [f"שינוי יחס גאומטרי: {f}" for f in solved["flips"]]
        # ---- v3: independent verification (text facts / CV / derived math / teacher / ground truth vs the AI proposal)
        cv_facts = []
        det = rec.validation.info.get("scatter_detection")
        if det and det.get("stable"):
            cv_facts = [Fact(fact_type="scatter_point", entities=[f"{round(p[0] / spec.scatter.axes.x_step) * spec.scatter.axes.x_step:g},"
                                                                  f"{round(p[1] / spec.scatter.axes.y_step) * spec.scatter.axes.y_step:g}"],
                             source="deterministic_detection") for p in det["points"]]
        for c in (spec.graph.curves if spec.graph else []):
            for va in feats.get(c.id, {}).get("vertical_asymptotes", []) if c.source == "text" else []:
                cv_facts.append(Fact(fact_type="asymptote", entities=["vertical"], value=va, source="derived_math"))
            if c.source == "text":
                cv_facts.append(Fact(fact_type="formula", entities=[c.id], value=c.expression, source="question_text"))
        for u in manifest.get("unsupported", []):
            if u not in spec.unsupported_features:
                spec.unsupported_features.append(u)
        if manifest.get("unsupported"):
            rec.decision = Decision(action="original", confidence=0.0,
                                    reasons=["המשרטט אינו יכול לייצג: " + ", ".join(manifest["unsupported"])])
        if manifest.get("hidden_edge_conflict"):
            rec.contradictions.append("HIDDEN_EDGE_CONFLICT: הקווים המקווקווים במקור אינם מתאימים לאף מצלמה עבור "
                                      + ", ".join(manifest["hidden_edge_conflict"]) + " — נדרשת בדיקת מורה.")
        if spec.chart is not None and spec.chart.kind == "bar" and source_png:
            from .charts import bar_cv
            det: dict = {}
            try:
                det = bar_cv.detect(source_png)
                vals = spec.chart.values
                step = (max(vals) - min(min(vals), 0)) / 5 if vals else 1.0
                bres = bar_cv.verify(spec.chart.categories, vals, det, step)
            except Exception as exc:
                bres = {"status": "BAR_CV_UNAVAILABLE", "conflicts": [], "verified": {}, "reason": type(exc).__name__}
            rec.audit["bar_cv"] = {"status": bres["status"], "orientation": det.get("orientation"),
                                   "calibration": det.get("calibration"),
                                   "bars": [{k: v for k, v in b.items() if k != "bbox"} for b in det.get("bars", [])],
                                   "conflicts": bres["conflicts"], "reason": bres.get("reason", "")}
            for cf in bres["conflicts"]:
                rec.audit.setdefault("unresolved_conflicts", []).append({"message": cf + " — נדרשת החלטת מורה."})
                rec.contradictions.append(cf)
            if bres["status"] == "PARTIAL_BAR_VERIFICATION":
                rec.contradictions.append("PARTIAL_BAR_VERIFICATION: ערכי העמודות אומתו אך שיוך הקטגוריות לא נקרא — נדרשת בדיקת מורה.")
            if bres["status"] == "BAR_CV_UNAVAILABLE":
                rec.audit.setdefault("notes", []).append("BAR_CV_UNAVAILABLE: אין אימות עצמאי לערכי העמודות (אינו אישור).")
            rec.audit["bar_verified"] = dict(bres["verified"])
        from . import topology_extractor as topo
        if source_png and png and topo.available() and spec.diagram_type in topo.RELIABLE:
            try:
                ts, tr = topo.extract(source_png), topo.extract(png)
                rec.audit["topology"] = {"source": ts, "render": tr}
                rec.contradictions += topo.compare(ts, tr, spec.diagram_type)
            except Exception as exc:  # CV failure = no evidence, never a crash
                rec.audit["topology"] = {"error": type(exc).__name__}
        g_ = spec.geometry or (spec.mixed.geometry if spec.mixed else None)
        fam = "generic" if spec.diagram_type == "generic" else ("geometry_no_circles" if spec.diagram_type == "geometry"
                                                                 and g_ is not None and not g_.circles else "")
        if source_png and png and topo.available():
            try:
                js, jr = topo.junctions(source_png), topo.junctions(png)
                rec.audit.setdefault("topology", {})["structure"] = {"source": js, "render": jr, "gating": bool(fam)}
                if fam:
                    rec.contradictions += topo.compare_structure(js, jr, fam)
            except Exception as exc:
                rec.audit.setdefault("topology", {})["structure_error"] = type(exc).__name__
        if source_png and png and spec.diagram_type in ("graph", "mixed_graph_geometry"):
            # SOURCE FIDELITY: the vector graph must correspond to the SOURCE graph (per option for option groups)
            from .graph import fidelity as gfid
            try:
                n_exp = len(spec.multi_graph.options) if spec.multi_graph is not None else 1
                fres = gfid.check(source_png, png, n_exp)
            except Exception as exc:
                fres = {"decision": "LOW_CONFIDENCE", "reasons": [type(exc).__name__]}
            rec.audit["graph_fidelity"] = fres
            if fres["decision"] == "MISMATCH":
                bad = [o for o in fres.get("per_option", []) if o["decision"] == "MISMATCH"]
                for o in bad:
                    label = spec.multi_graph.options[o["index"]].label if spec.multi_graph is not None else ""
                    rec.comparison.critical.append(f"GRAPH_SOURCE_MISMATCH{(' (אפשרות ' + label + ')') if label else ''}: "
                                                   + "; ".join(o["reasons"][:2]))
            elif fres["decision"] == "LOW_CONFIDENCE":
                rec.contradictions.append("GRAPH_SOURCE_FIDELITY_LOW_CONFIDENCE: לא ניתן לאמת שהגרף המשוחזר תואם למקור "
                                          f"({'; '.join(fres.get('reasons', [])[:1])}) — נדרשת בדיקת מורה.")
        if source_png and spec.diagram_type == "graph" and spec.subtype != "multi_choice_graphs":
            from .graph import graph_cv
            try:
                gcv = graph_cv.analyse(source_png)
                eb, ec = graph_cv.expected_from_spec(spec, rec.validation.info.get("graph_features"))
                gating = spec.graph is not None and bool(spec.graph.curves)   # formula graphs only
                # per-graph reliability: the CV must reproduce the model on OUR correct render before it may judge the source
                self_check = graph_cv.analyse(png) if png else {"ok": False}
                reliable = {"branches": self_check.get("ok") and eb is not None and self_check.get("branches") == eb,
                            "contacts": self_check.get("ok") and ec is not None and self_check.get("x_axis_contacts") == ec}
                rec.audit["graph_cv"] = {"cv": gcv, "self_check": self_check, "expected_branches": eb, "expected_contacts": ec,
                                         "reliable": reliable, "gating": gating}
                if gating:
                    rec.contradictions += graph_cv.compare(gcv, eb if reliable["branches"] else None,
                                                           ec if reliable["contacts"] else None)
            except Exception as exc:
                rec.audit["graph_cv"] = {"error": type(exc).__name__}
        if spec.table is not None:
            from .charts.table import semantic_model
            try:
                rec.audit["table_semantic"] = {k: v for k, v in semantic_model(spec.table).items() if k != "cells"}
                rec.audit["table_semantic"]["cells"] = semantic_model(spec.table)["cells"]
            except Exception as exc:
                rec.audit["table_semantic"] = {"table_type": "unknown", "error": type(exc).__name__}
        from .ocr import verify as ocr_verify
        ocr_res = ocr_verify.run(spec, source_png, question_text)
        rec.audit["ocr_geometry_numbers"] = ocr_res.get("geometry_numbers", {})
        rec.audit["ocr"] = {"available": ocr_res["available"], "status": ocr_res["status"], "confirmed": len(ocr_res["facts"]),
                            "notes": ocr_res["notes"], "conflicts": ocr_res["conflicts"]}
        cv_facts += ocr_res["facts"]
        ver = verification.verify(spec, required_text, question_text, solved, rec.audit.get("raw_points"), cv_facts, ground_truth_facts)
        rec.comparison.critical += [m for m in rec.audit.get("math_conflicts", []) if m not in rec.comparison.critical]
        rec.contradictions += rec.audit.get("source_conflicts", [])
        inv = ocr_res.get("inventory", {})
        rec.audit["inventory"] = inv
        rec.contradictions += [f"OCR מצא את התווית {m.split(':')[1]} בתמונת המקור, אך היא חסרה בשחזור ({m}) — נדרשת בדיקת מורה."
                               for m in inv.get("missing_from_spec", [])]
        for cf in ocr_res["conflicts"]:
            (rec.comparison.critical if cf["resolved"] == "text+ocr" else rec.contradictions).append(cf["message"])
        rec.audit["unresolved_conflicts"] = rec.audit.get("unresolved_conflicts", []) + \
            [c for c in ocr_res["conflicts"] if c["resolved"] == "unresolved"]
        rec.comparison.critical += [c for c in ver["critical"] if c not in rec.comparison.critical]
        rec.missing_required = ver["missing_required"]
        rec.contradictions = rec.contradictions + ver["contradictions"]
        rec.validation.warnings += ver["contradictions"]
        rec.coverage = {k: v for k, v in ver["coverage"].items()}
        rec.coverage["contradiction_count"] = rec.coverage.get("contradiction_count", 0) + len(rec.contradictions)
        rec.reconciliation = ver["fact_graph"].reconciliation(verification.spec_keys(spec),
                                                              rec.missing_required + inv.get("missing_from_spec", []),
                                                              rec.contradictions)
        rec.facts = [f.model_dump() for f in ver["fact_graph"].facts]
        core = min(rec.comparison.structure_match_score, rec.comparison.topology_score, rec.comparison.constraint_score,
                   rec.comparison.label_match_score, rec.comparison.math_score, rec.comparison.layout_score) if rec.validation.ok else 0.0
        rec.comparison.semantic_score = ver["semantic_confidence"]
        rec.comparison.numeric_score = rec.comparison.math_score
        rec.comparison.overall_score = round(min(rec.comparison.overall_score, ver["semantic_confidence"]), 3)
        model_conf = min(rec.parser_confidence, rec.classifier_confidence)
        rec.confidence = verification.confidence(model_conf, core, ver["semantic_confidence"], ver["coverage"]["verification_coverage"])
        # typed-semantics results take part in EVERY decision (with or without a source image)
        sem_res = rec.audit.get("semantics", {})
        rec.comparison.critical += [m for m in sem_res.get("conflicts", []) if m not in rec.comparison.critical]
        rec.contradictions += [x for x in [f"SEMANTIC_UNSUPPORTED: {u} — נדרשת בדיקת מורה." for u in sem_res.get("unsupported", [])]
                               + [f"FORMULA_UNPARSED: {f['id']}" for f in sem_res.get("formulas", []) if f["status"] != "OK"]
                               if x not in rec.contradictions]
        vf_ = rec.audit.get("voxel_fit") or {}
        if vf_.get("ok"):
            # the structure was READ FROM THE DRAWING and proven (face-by-face agreement + uniqueness): the model's own
            # reading no longer carries the geometry - the deterministic proof does
            sc_ = float(vf_.get("score", 0.0))
            for key_ in ("model_confidence", "deterministic_confidence", "final_confidence"):
                rec.confidence[key_] = max(rec.confidence.get(key_, 0.0), sc_)
            rec.coverage["verification_coverage"] = max(rec.coverage.get("verification_coverage", 0.0), sc_)
            rec.coverage["ai_only_fact_count"] = 0
            # the proof (face-by-face agreement + uniqueness in the DRAWING's own view) supersedes the heuristic
            # hidden-top estimate, which assumes a fixed viewpoint
            superseded = [c_ for c_ in rec.comparison.critical if "ראש העמודה אינו נראה" in c_]
            if superseded:
                rec.comparison.critical = [c_ for c_ in rec.comparison.critical if c_ not in superseded]
                rec.audit["voxel_fit"]["superseded_hidden_top_estimate"] = superseded
        rec.decision = decide_v3(rec.validation, rec.comparison, rec.confidence, rec.coverage, spec.unsupported_features, policy,
                                 unresolved=[c["message"] for c in rec.audit.get("unresolved_conflicts", [])])
        if rec.render_error:
            rec.decision.action = "original"
            rec.decision.reasons.insert(0, "יצירת השרטוט נכשלה.")
        rec.review = initial_review(rec, prior_review)
        rec.teacher_message = _message(rec)
    return _finish(rec, ai_model, source_png)


def _solve_into(geo, rec: DiagramRecord, fn) -> dict | None:
    rec.audit["raw_points"] = {p.id: [p.x, p.y] for p in geo.points}
    ids = [p.id for p in geo.points]
    if len(ids) != len(set(ids)):
        return None
    solved = fn()
    if solved["ok"]:
        for p in geo.points:
            if p.id in solved["points"]:
                p.x, p.y = solved["points"][p.id]
    elif any(p.pinned for p in geo.points):
        solved["code"] = "DRAG_INFEASIBLE"
    for p in geo.points:
        p.pinned = False                          # layout holds never persist as facts
    return solved


def _message(rec: DiagramRecord) -> str:
    a = rec.decision.action
    if a == "original":
        return "לא ניתן היה לשחזר את התרשים באופן אמין — נדרשת החלטת מורה (תיקון השחזור או שימוש חריג בסריקה)." + (
            " " + rec.decision.reasons[0] if rec.decision.reasons else "")
    if a == "draft":
        return "טיוטת שחזור בביטחון בינוני — נדרשת בדיקה ואישור מורה. עד להחלטת המורה התרשים לא ייוצא."
    if a == "review":
        return "השחזור עבר את הבדיקות — נדרש אישור מורה. עד להחלטת המורה התרשים לא ייוצא."
    return "השחזור עבר את כל הבדיקות בביטחון גבוה — עדיין נדרש אישור מורה לפני שילוב במסמך."


def _finish(rec: DiagramRecord, ai_model: str, source_png: bytes | None = None) -> DiagramRecord:
    cleaned_hash = ""
    if source_png:
        try:
            cleaned_hash = cache.PREPROCESS.get_or_compute(cache.key("clean-hash", image_hash(source_png)),
                                                          lambda: image_hash(cleaned_png(source_png)))
        except Exception:
            cleaned_hash = ""
    # typed-semantics results take part in EVERY exit path (early exits included) - never silently dropped
    sem_res = rec.audit.get("semantics") or {}
    crit = [m for m in sem_res.get("conflicts", []) if m not in rec.comparison.critical]
    rec.comparison.critical += crit
    rev = [f"SEMANTIC_UNSUPPORTED: {u} — נדרשת בדיקת מורה." for u in sem_res.get("unsupported", [])] + \
          [f"FORMULA_UNPARSED: {f['id']}" for f in sem_res.get("formulas", []) if f["status"] != "OK"]
    rec.contradictions += [x for x in rev if x not in rec.contradictions]
    if sem_res.get("conflicts") and rec.decision.action != "original":
        rec.decision = Decision(action="original", confidence=0.0, reasons=["אי-התאמה סמנטית: " + sem_res["conflicts"][0]])
    elif rev and rec.decision.action == "high_confidence_preview":
        rec.decision = Decision(action="review", confidence=rec.decision.confidence, reasons=rev[:1])
    # keep EVERY pipeline audit entry (a fixed allow-list silently dropped new diagnostics twice)
    rec.audit = {**rec.audit, **audit.build(rec, ai_model, cleaned_hash)}
    return rec


def apply_teacher_edit(rec: DiagramRecord, new_spec: DiagramSpec, summary: str, question_text: str,
                       source_png: bytes | None, ai_model: str = "") -> DiagramRecord:
    before = spec_hash(rec.spec)
    review = rec.review.model_copy(deep=True)
    new = process(rec.figure_id, rec.raw_spec_json, question_text, source_png, teacher_spec=new_spec, ai_model=ai_model,
                  input_key=rec.input_key, input_hashes=rec.input_hashes)
    for k in ("raw_points", "input_key", "question_text"):
        if k in rec.audit:
            new.audit[k] = rec.audit[k]
    new.review.teacher_edits = review.teacher_edits
    add_edit(new.review, summary, before, spec_hash(new.spec))
    return _finish(new, ai_model, source_png)


# ------------------------------------------------------------------ public single-call API
@dataclass
class DiagramResult:
    source_image: bytes
    cleaned_image: bytes
    spec: DiagramSpec | None
    validation: ValidationResult
    comparison: ComparisonResult | None
    decision: Decision
    preview_svg: str | None
    preview_png: bytes | None
    diagnostics: list[str] = field(default_factory=list)
    record: DiagramRecord | None = None


def process_diagram(edited_image: bytes, question_text: str, bbox: list[int] | None = None, question_id: str | int | None = None,
                    figure_id: str | None = None, raw_spec_json: str = "", teacher_context: dict | None = None,
                    ai_model: str = "") -> DiagramResult:
    """The edited (cropped/erased) image is the ONLY image used. bbox = [ymin,xmin,ymax,xmax] in 0..1000."""
    from PIL import Image

    diagnostics: list[str] = []
    source = edited_image
    if bbox and len(bbox) == 4:
        try:
            with Image.open(io.BytesIO(edited_image)) as im:
                W, H = im.size
                y0, x0, y1, x1 = bbox
                buf = io.BytesIO()
                im.convert("RGB").crop((int(x0 * W / 1000), int(y0 * H / 1000), int(x1 * W / 1000), int(y1 * H / 1000))).save(buf, format="PNG")
                source = buf.getvalue()
        except Exception as exc:
            diagnostics.append(f"crop failed: {exc}")
    fid = figure_id or f"q{question_id or 0}f1"
    teacher_spec = (teacher_context or {}).get("spec")
    rec = process(fid, raw_spec_json, question_text, source, ai_model=ai_model, teacher_spec=teacher_spec)
    svg = png = None
    if rec.validation.ok and not rec.render_error and rec.spec is not None:
        try:
            svg, png, _ = render_spec(rec.spec)
        except Exception as exc:
            diagnostics.append(f"render failed: {exc}")
    try:
        cleaned = cleaned_png(source)
    except Exception:
        cleaned = b""
    diagnostics += rec.validation.errors + rec.comparison.critical + rec.comparison.notes
    return DiagramResult(source, cleaned, rec.spec, rec.validation, rec.comparison, rec.decision, svg, png, diagnostics, rec)


def export_bundle(records: dict[str, DiagramRecord], sources: dict[str, bytes]) -> bytes:
    """ZIP with, per figure: source, cleaned source, spec JSON, SVG, PNG, validation, comparison, decision, review, audit."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fid, rec in records.items():
            base = f"{fid}/"
            src = sources.get(fid)
            if src:
                zf.writestr(base + "source.png", src)
                try:
                    zf.writestr(base + "cleaned.png", cleaned_png(src))
                except Exception:
                    pass
            if rec.spec is not None:
                zf.writestr(base + "spec.json", rec.spec.model_dump_json(indent=2))
                if rec.validation.ok and not rec.render_error:
                    try:
                        svg, png, _ = render_spec(rec.spec)
                        zf.writestr(base + "render.svg", svg)
                        zf.writestr(base + "render.png", png)
                    except Exception:
                        pass
            for name, obj in (("validation", rec.validation), ("comparison", rec.comparison), ("decision", rec.decision), ("review", rec.review)):
                zf.writestr(base + f"{name}.json", obj.model_dump_json(indent=2))
            zf.writestr(base + "audit.json", json.dumps(rec.audit, ensure_ascii=False, indent=2))
    return buf.getvalue()
