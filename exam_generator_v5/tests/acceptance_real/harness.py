"""Real-image acceptance harness (V5.6).

REAL IMAGE (crop from the supplied PDFs) -> PRODUCTION pipeline (no ground truth given to it) -> produced spec ->
validation -> rendering -> comparison -> decision; THEN the result is checked against the hand-authored manifest.

The structured proposal fed to the pipeline is a SIMULATED vision proposal (tests/diagram_engine/acceptance/cases.py):
real Gemini extraction was not available in this environment -> reported as NOT TESTED – REAL VISION."""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "diagram_engine" / "acceptance"))

import diagram_engine as de  # noqa: E402
from cases import CASES  # noqa: E402
from diagram_engine import safe_math as sm  # noqa: E402
from diagram_engine.fact_graph import Fact  # noqa: E402
from diagram_engine.preprocess import ink_mask  # noqa: E402
from diagram_engine.verification import satisfied  # noqa: E402

FIX = ROOT / "tests" / "diagram_engine" / "acceptance" / "fixtures"
MANIFESTS = sorted((HERE / "manifests").glob("*_expected.json"))


def load(mid: str) -> dict:
    return json.loads((HERE / "manifests" / f"{mid}_expected.json").read_text(encoding="utf-8"))


def parse_fact(s: str) -> Fact:
    m = re.fullmatch(r"(\w+)(?:\(([^)]*)\))?(?:=(.*))?", s)
    t, ents, val = m.group(1), [e.strip() for e in (m.group(2) or "").split(",") if e.strip()], m.group(3)
    value = None
    if val is not None:
        if t == "coordinate":
            value = [float(v) for v in val.split(",")]
        elif t == "ratio_on_segment":
            value = float(val)
        else:
            value = val
    return Fact(fact_type=t, entities=ents, value=value, source="ground_truth")


def run_case(case: dict, spec_override: dict | None = None):
    spec = spec_override if spec_override is not None else case["spec"]
    src = (FIX / case["fixture"]).read_bytes()
    rec = de.process(case["fixture"], json.dumps(spec, ensure_ascii=False), case["text"], src, required_text=case["text"])
    return rec, src


def labels_of(rec) -> set[str]:
    m, s = rec.manifest, rec.spec
    out = set(m.get("labels", [])) | set(m.get("geometry", {}).get("labels", [])) | set(m.get("options", []))
    if s and s.spatial:
        out |= {v for so in s.spatial.solids for v in so.vertices} | {p.id for p in s.spatial.points_on_edges}
    if s and s.generic:
        out |= {l.text for l in s.generic.labels}
    return out


def check(mf: dict, rec) -> list[str]:
    """Compare the PRODUCED record with the hand-authored manifest. Returns failures (empty = all required facts present)."""
    fails: list[str] = []
    spec = rec.spec
    if spec is None:
        return ["no spec produced"]
    if spec.diagram_type != mf["diagram_type"]:
        fails.append(f"diagram_type {spec.diagram_type} != {mf['diagram_type']}")
    if (spec.subtype or "") != mf["subtype"]:
        fails.append(f"subtype {spec.subtype} != {mf['subtype']}")
    missing = [l for l in mf["required_labels"] if l not in labels_of(rec)]
    if missing:
        fails.append(f"missing labels {missing}")
    with sm.symbol_context(spec.symbols, {}):
        for fs in mf["critical_facts"]:
            f = parse_fact(fs)
            if f.fact_type == "formula":
                c = next((c for c in (spec.graph.curves if spec.graph else []) if c.id == f.entities[0]), None)
                ok = c is not None and sm.equivalent(sm.parse_expression(c.expression), sm.parse_expression(f.value))
            elif f.fact_type == "dimension":
                kind, val = f.value.split(":")[:2]
                ok = any(d.measure == kind and d.value is not None and abs(d.value - float(val)) < 1e-9 for d in spec.spatial.dimensions)
            else:
                ok = bool(satisfied(spec, f))
            if not ok:
                fails.append(f"critical fact not satisfied: {fs}")
    rv, man = mf["required_values"], rec.manifest
    if "landmark_kinds" in rv and [l[0] for l in man.get("landmarks", [])] != rv["landmark_kinds"]:
        fails.append("landmark kinds/order differ")
    if "branches" in rv and spec.subtype == "qualitative_graph" and man.get("branches") != rv["branches"]:
        fails.append("branch count differs")
    if "horizontal_asymptotes" in rv and sorted(a[1] for a in man.get("asymptotes", []) if a[0] == "horizontal") != rv["horizontal_asymptotes"]:
        fails.append("horizontal asymptotes differ")
    if "options" in rv and man.get("options") != rv["options"]:
        fails.append(f"options {man.get('options')} != {rv['options']}")
    if "branches_per_option" in rv:
        got = [man.get("option_manifests", {}).get(o, {}).get("branches") for o in rv.get("options", [])]
        if got != rv["branches_per_option"]:
            fails.append(f"branches per option {got} != {rv['branches_per_option']}")
    if "roots" in rv:
        f = rec.validation.info.get("graph_features", {}).get("f", {})
        if not np.allclose(f.get("roots", []), rv["roots"]) or f.get("branches") != rv["branches"]:
            fails.append("roots/branches differ")
    if "scatter_points" in rv and sorted(map(list, spec.scatter.points)) != sorted(rv["scatter_points"]):
        fails.append("scatter points differ")
    if "regions" in rv and sorted(man.get("texts", [])) != sorted(rv["regions"]):
        fails.append("regions differ")
    if "dimension" in rv and rv["dimension"] not in man.get("dimensions", []):
        fails.append("dimension line / attachment differs")
    if "adjacency" in rv:
        from diagram_engine.generic.comparator import adjacency
        if adjacency(spec) != rv["adjacency"]:
            fails.append("adjacency differs")
    if "cells" in rv:
        got = [[c.text for c in row] for row in spec.table.rows]
        if got != rv["cells"]:
            fails.append("table cells differ")
    if "coordinates" in rv:
        P = {p.id: (p.x, p.y) for p in spec.geometry.points}
        for k, v in rv["coordinates"].items():
            if k not in P or not np.allclose(P[k], v, atol=1e-6):
                fails.append(f"coordinate {k} differs")
    if "edges" in rv and man.get("edges") != rv["edges"]:
        fails.append("edge count differs")
    if "hidden_edges" in rv:
        hid = sorted(sorted(e) for s in spec.spatial.solids for e in s.hidden_edges)
        if hid != sorted(sorted(e) for e in rv["hidden_edges"]):
            fails.append("hidden edges differ")
    if "vectors" in rv and sorted(v[2] for v in man.get("vectors", [])) != rv["vectors"]:
        fails.append("vector labels differ")
    if "percentages" in rv and (spec.normal.percentages != rv["percentages"] or spec.normal.answer_boxes != rv["answer_boxes"]):
        fails.append("normal distribution labels/boxes differ")
    if "dimensions" in rv:
        got = sorted([d.solid, d.measure, d.value] for d in spec.spatial.dimensions)
        if got != sorted(rv["dimensions"]):
            fails.append(f"dimensions {got} differ")
    for fo in mf["forbidden_objects"]:
        if fo == "formula" and spec.graph is not None and spec.graph.curves:
            fails.append("forbidden: an equation was produced for a qualitative graph")
        if fo == "merged_options" and len(man.get("options", [])) != 4:
            fails.append("forbidden: options merged/lost")
        if fo.startswith("point:") and any(p[0] == fo[6:] for p in man.get("points", [])):
            fails.append(f"forbidden object drawn: {fo}")
        if fo.startswith("dimension:") and spec.spatial is not None:
            _, sol, kind = fo.split(":")
            if any(d.solid == sol and d.measure == kind for d in spec.spatial.dimensions):
                fails.append(f"forbidden: {fo}")
    return fails


def evaluate(mid: str, spec_override: dict | None = None, save: bool = True) -> dict:
    mf = load(mid)
    case = CASES[mf["case"]]
    rec, src = run_case(case, spec_override)
    fails = check(mf, rec) if mf["expected"] == "reconstruct" else []
    exported_before = de.usable_in_document(rec)
    blocked = rec.decision.action == "original"
    if mf["expected"] == "safe_fallback":
        result = "SAFE FALLBACK PASS" if blocked and not exported_before else "FAIL"
    elif fails or rec.comparison.critical or not rec.validation.ok or exported_before:
        result = "SAFE FALLBACK" if blocked and not exported_before else "FAIL"
    else:
        result = "PASS" if not blocked else "SAFE FALLBACK"
    facts = rec.facts
    row = {"id": mid, "source": mf["source"], "classification": rec.classifier_type, "subtype": rec.classifier_subtype,
           "required_critical_facts": len(mf["critical_facts"]) + len(mf["required_labels"]),
           "facts_from_text": sum(1 for f in facts if f["source"] == "question_text"),
           "facts_from_cv": sum(1 for f in facts if f["source"] in ("deterministic_detection", "derived_math")),
           "vision_only": rec.coverage.get("ai_only_fact_count", 0), "coverage": rec.coverage.get("verification_coverage", 0.0),
           "ambiguous": rec.coverage.get("ambiguous_fact_count", 0), "contradictions": len(rec.contradictions),
           "critical": list(rec.comparison.critical), "manifest_failures": fails, "decision": rec.decision.action,
           "final_confidence": rec.confidence.get("final_confidence"), "export_before_approval": exported_before,
           "export_after_approval": None, "result": result}
    if not blocked:
        import copy
        r2 = copy.deepcopy(rec)
        row["export_after_approval"] = de.approve(r2) and de.usable_in_document(r2)
    if save and spec_override is None:
        art = HERE / "artifacts"
        (art / f"{mid}_source.png").write_bytes(src)
        if rec.validation.ok and not rec.render_error:
            svg, png, _ = de.render_spec(rec.spec)
            (art / f"{mid}_render.svg").write_text(svg, encoding="utf-8")
            (art / f"{mid}_render.png").write_bytes(png)
            with Image.open(io.BytesIO(src)) as a, Image.open(io.BytesIO(png)) as b:
                ma, mb = ink_mask(a, 400), ink_mask(b, 400)
            ov = np.full((400, 400, 3), 255, np.uint8)
            ov[ma] = [210, 40, 40]          # source ink: red
            ov[mb] = [30, 90, 220]          # reconstruction ink: blue
            ov[ma & mb] = [40, 40, 40]      # overlap: dark
            Image.fromarray(ov).save(art / f"{mid}_overlay.png")
    return row


def write_report(rows: list[dict], path: Path) -> None:
    L = ["# REAL IMAGE ACCEPTANCE REPORT — V5.7", "",
         "Source images: figure crops extracted from the six supplied Bagrut questionnaires (vector PDFs, 170 dpi).",
         "Pipeline: the PRODUCTION pipeline (no ground truth passed in). Result checked afterwards against hand-authored manifests",
         "(`tests/acceptance_real/manifests/*_expected.json`).", "",
         "**NOT TESTED – REAL VISION EXTRACTION:** no Gemini credentials/network in this environment. The structured proposal fed",
         "to the pipeline is a SIMULATED vision proposal written by hand (`tests/diagram_engine/acceptance/cases.py`). Text parsing,",
         "deterministic CV (scatter), validation, rendering, comparison, decision and export gating are REAL.", "",
         "| Test | Source | Class / subtype | Req. facts | Text facts | CV/math facts | Vision-only | Indep. coverage | Ambig. | Contradictions | Critical | Decision | Final conf. | Export before / after approval | Result |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        crit = "; ".join(r["critical"] + r["manifest_failures"]) or "0"
        L.append(f"| {r['id']} | {r['source']} | {r['classification']} / {r['subtype']} | {r['required_critical_facts']} | {r['facts_from_text']} | "
                 f"{r['facts_from_cv']} | {r['vision_only']} | {r['coverage']:.0%} | {r['ambiguous']} | {r['contradictions']} | {crit} | "
                 f"{r['decision']} | {r['final_confidence']} | {'yes' if r['export_before_approval'] else 'no'} / "
                 f"{'yes' if r['export_after_approval'] else ('no' if r['export_after_approval'] is False else '—')} | **{r['result']}** |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
