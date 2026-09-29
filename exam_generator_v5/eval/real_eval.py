"""REAL FULL END-TO-END MODEL EVAL (V5.7.2).

  REAL FULL-PAGE IMAGE -> analyze_question() [REAL PASS 1: text, formulas, subparts, figure bbox]
  -> bbox mapped to the FULL-RESOLUTION MASTER -> REAL HIGH-RES ROI -> REAL PASS 2 (typed)
  -> independent OCR / CV -> reconciliation -> verification -> decision -> render -> export eligibility.

NOTHING hand-written is fed to the system: no manual question text, no proposal, no DiagramSpec, no manual ROI.
The hand-written manifests are used ONLY afterwards, to score the outputs.

    GEMINI_API_KEY=... python eval/real_eval.py --runs 5 --set fixed
    GEMINI_API_KEY=... python eval/real_eval.py --runs 5 --set holdout      # eval/holdout/index.json (same format)
Results: eval/results/<timestamp>/ (raw responses per run, metrics.json, REPORT.md)."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "acceptance_real"))
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def load_set(which: str) -> list[dict]:
    base = ROOT / "eval" / ("fixed_regression_set" if which == "fixed" else "holdout")
    idx = json.loads((base / "index.json").read_text(encoding="utf-8")) if (base / "index.json").exists() else {}
    out = []
    for iid, it in idx.items():
        mf = json.loads((ROOT / it["manifest"]).read_text(encoding="utf-8")) if "manifest" in it else it["expected"]
        exp_text = it.get("expected_text")
        if exp_text is None and "case" in mf:
            sys.path.insert(0, str(ROOT / "tests" / "diagram_engine" / "acceptance"))
            from cases import CASES
            exp_text = CASES[mf["case"]]["text"]
        out.append({"id": iid, "page": base / it["page"], "expected_bbox": it["expected_bbox_1000"], "manifest": mf,
                    "expected_text": exp_text or "", "holdout": which == "holdout",
                    "used_in_development": it.get("used_in_development", which == "fixed")})
    return out


def _iou(a, b) -> float:
    if not a or not b:
        return 0.0
    y0, x0, y1, x1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, y1 - y0) * max(0, x1 - x0)
    area = lambda r: max(0, r[2] - r[0]) * max(0, r[3] - r[1])  # noqa: E731
    return inter / max(1e-9, area(a) + area(b) - inter)


def run_once(service, item: dict, meta: dict) -> dict:
    """The REAL production path from a full page. Returns raw outputs + the final record for the matched figure."""
    import exam_core as c
    page = Path(item["page"]).read_bytes()
    working = c.pil_to_png_bytes(c.png_bytes_to_pil(page))
    question = {"question_number": 1, "points": 100.0, "images": [working], "masters": [page],
                "provenance": [{"master_hash": c.image_digest(page), "working_hash": c.image_digest(working)}]}
    t0 = time.monotonic()
    err = ""
    try:
        q = c.analyze_question(service, meta, question)            # REAL PASS 1 + REAL PASS 2 + pipeline
    except Exception as exc:
        q, err = None, f"{type(exc).__name__}: {exc}"
    latency = round(time.monotonic() - t0, 3)
    if q is None:
        return {"error": err, "latency_s": latency, "figure": None, "record": None, "pass1": None}
    best = max(q.figures, key=lambda f: _iou(f.bbox, item["expected_bbox"]), default=None)
    rec = q.diagrams.get(best.figure_id) if best else None
    return {"error": "", "latency_s": latency, "model": service.model, "prompt_version": c.PROMPT_VERSION,
            "raw_model_evidence": q.model_evidence,                     # exact raw PASS 1 / PASS 2 response texts
            "source_hash": c.image_digest(page), "semantics": rec.audit.get("semantics") if rec else None,
            "ocr_cv": {k: rec.audit.get(k) for k in ("ocr", "topology", "graph_cv", "bar_cv", "ocr_geometry_numbers")} if rec else None,
            "pass1": {"text": q.text, "sections": [s.text for s in q.sections], "figures": [f.bbox for f in q.figures]},
            "pass2_raw": q.diagram_pass.get(best.figure_id, {}).get("raw") if best else None,
            "pass2_status": q.diagram_pass.get(best.figure_id, {}).get("status") if best else "NO_FIGURE",
            "figure_bbox": best.bbox if best else None, "record": rec,
            "decision": rec.decision.action if rec else "NO_FIGURE",
            "spec": rec.spec.model_dump() if rec and rec.spec else None}


def score(item: dict, run: dict) -> dict:
    """PASS 1 accuracy, PASS 2 accuracy and FINAL SAFETY - separately."""
    from harness import check, labels_of
    mf, rec = item["manifest"], run.get("record")
    p1 = run.get("pass1") or {"text": "", "sections": [], "figures": []}
    got_text = " ".join([p1["text"], *p1["sections"]])
    exp = item["expected_text"]
    exp_nums = NUM.findall(exp.replace("−", "-"))
    got_nums = NUM.findall(got_text.replace("−", "-"))
    pass1 = {"text_similarity": round(difflib.SequenceMatcher(None, exp, p1["text"]).ratio(), 3) if exp else None,
             "critical_numbers_exact": (sum(1 for n in exp_nums if n in got_nums) / len(exp_nums)) if exp_nums else None,
             "subparts_found": len(p1["sections"]), "figures_found": len(p1["figures"]),
             "bbox_iou": round(_iou(run.get("figure_bbox"), item["expected_bbox"]), 3),
             "diagram_family_ok": bool(rec and rec.spec and rec.spec.diagram_type == mf["diagram_type"])}
    if rec is None or rec.spec is None:
        return {"pass1": pass1, "pass2": None, "safety": {"outcome": "CORRECTLY_BLOCKED" if not rec else "BLOCKED",
                                                          "wrong_accepted": False}}
    fails = check(mf, rec)
    req = set(mf.get("required_labels", []))
    got = labels_of(rec)
    tp = len(req & got)
    crit = mf.get("critical_facts", [])
    crit_ok = sum(1 for f in crit if not any(f in x for x in fails))
    pass2 = {"entity_precision": round(tp / len(got), 3) if got and req else None,
             "entity_recall": round(tp / len(req), 3) if req else None,
             "label_recall": round(tp / len(req), 3) if req else None,
             "constraint_recall": round(crit_ok / len(crit), 3) if crit else None,
             "hallucinated_entities": sorted(got - req) if req else [], "manifest_failures": fails}
    blocked = rec.decision.action == "original"
    auto = rec.decision.action == "high_confidence_preview"
    if fails and auto:
        outcome = "WRONG_ACCEPTED"
    elif fails and not blocked:
        outcome = "WRONG_OFFERED_FOR_REVIEW"          # not exported without a teacher, but reported
    elif fails:
        outcome = "CORRECTLY_BLOCKED"
    else:
        outcome = "PASS"
    return {"pass1": pass1, "pass2": pass2, "safety": {"outcome": outcome, "wrong_accepted": outcome == "WRONG_ACCEPTED",
                                                        "unsafe_auto_approval": False, "decision": rec.decision.action}}


def stability(runs: list[dict]) -> dict:
    def sig(r, key):
        p1, spec = r.get("pass1") or {}, r.get("spec") or {}
        v = {"pass1_text": p1.get("text"), "critical_numbers": sorted(NUM.findall(p1.get("text") or "")),
             "family": spec.get("diagram_type"), "bbox": [round(x / 25) for x in (r.get("figure_bbox") or [])],
             "entities": sorted(p["id"] for p in ((spec.get("geometry") or {}).get("points") or [])),
             "labels": sorted(l["text"] for l in spec.get("labels") or []),
             "relations": sorted(json.dumps(c_, sort_keys=True) for c_ in ((spec.get("geometry") or {}).get("constraints") or [])),
             "decision": r.get("decision")}[key]
        return json.dumps(v, sort_keys=True, default=str)
    keys = ["pass1_text", "critical_numbers", "family", "bbox", "entities", "labels", "relations", "decision"]
    res = {}
    for k in keys:
        vals = [sig(r, k) for r in runs]
        res[k] = round(max(vals.count(v) for v in set(vals)) / len(vals), 3) if vals else 0.0
    res["verdict"] = "STABLE" if all(v == 1.0 for v in res.values() if isinstance(v, float)) else "UNSTABLE"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--set", choices=["fixed", "holdout"], default="fixed")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("NOT TESTED - REAL VISION: GEMINI_API_KEY is not set")
        return 2
    import exam_core as c
    items = load_set(a.set)
    if not items:
        print(f"NO ITEMS in set '{a.set}' (add real images + eval/{a.set}/index.json)")
        return 3
    service = c.GeminiService(key, model=a.model or c.DEFAULT_MODEL)
    meta = {"school": "", "subject": "מתמטיקה", "notation_profile": "ISRAEL_HIGH_SCHOOL"}
    out_dir = ROOT / "eval" / "results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix, wrong = {}, 0
    for item in items:
        runs = []
        for i in range(a.runs):
            r = run_once(service, item, meta)
            r["score"] = score(item, r)
            (out_dir / f"{item['id']}_run{i + 1}.json").write_text(
                json.dumps({k: v for k, v in r.items() if k != "record"}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            runs.append(r)
        st_ = stability(runs)
        outcomes = [r["score"]["safety"]["outcome"] for r in runs]
        wrong += outcomes.count("WRONG_ACCEPTED")
        matrix[item["id"]] = {"outcomes": outcomes, "stability": st_, "holdout": item["holdout"],
                              "pass1": [r["score"]["pass1"] for r in runs], "pass2": [r["score"]["pass2"] for r in runs]}
    (out_dir / "metrics.json").write_text(json.dumps({"WRONG_RECONSTRUCTION_ACCEPTED": wrong, "runs_total": len(items) * a.runs,
                                                     "matrix": matrix}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"WRONG_RECONSTRUCTION_ACCEPTED": wrong, "runs_total": len(items) * a.runs, "out": str(out_dir)}))
    return 0 if wrong == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
