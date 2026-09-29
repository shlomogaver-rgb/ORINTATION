"""Independent reading of the source (photo OR PDF) and the READING_CONFLICT export gate.

    photo  -> rectified image -> text lines -> reader B reads every line alone -> compare with the reconstruction
              + figure labels read again from each figure crop -> compare with the PASS 2 labels
    PDF    -> the text layer lines of the question region are reader B (Hebrew words and numbers; its formulas are
              typographically broken, so formulas are not compared)

Reader B's raw readings are stored on the question; the comparison itself is recomputed from them after every edit,
so fixing a word in the editor clears its conflict without another API call."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from typing import Any

from . import consensus
from .consensus import compare

READING_VERSION = "reading/1.0"
_CONFIG: dict[str, Any] = {}


def configure(secrets: dict[str, Any] | None) -> None:
    """Called once by the app with the relevant secrets (SECOND_READER, ANTHROPIC_API_KEY, SECOND_READER_MODEL)."""
    _CONFIG.clear()
    _CONFIG.update({k: v for k, v in (secrets or {}).items() if v})


def _reader_config() -> dict[str, Any]:
    cfg = {k: os.environ.get(k) for k in ("SECOND_READER", "ANTHROPIC_API_KEY", "SECOND_READER_MODEL") if os.environ.get(k)}
    cfg.update(_CONFIG)
    return cfg


def source_kind(question: dict[str, Any]) -> str:
    doc = question.get("document") or {}
    return "pdf" if (doc.get("text_layer") or question.get("text_layer")) else "photo"


def texts_of(q: Any) -> list[str]:
    return [q.text or ""] + [s.text or "" for s in q.sections]


def _fingerprint(q: Any) -> str:
    labels = {fid: [l.text for l in (spec.labels or [])] for fid, spec in (q.diagram_specs or {}).items()}
    raw = json.dumps([texts_of(q), labels], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------ figure labels
def _norm_label(s: str) -> str:
    s = re.sub(r"\s+", "", s or "").replace("−", "-").strip("$")
    return re.sub(r"\\(mathrm|text)\{([^{}]*)\}", r"\2", s)


def figure_label_conflicts(fid: str, a_labels: list[str], b_labels: list[str]) -> list[dict]:
    a = Counter(_norm_label(x) for x in a_labels if _norm_label(x))
    b = Counter(_norm_label(x) for x in b_labels if _norm_label(x) and "[?]" not in x)
    out = []
    for lab in (a - b):
        out.append({"kind": "figure_label", "a": lab, "b": "", "figure_id": fid,
                    "message": f"READING_CONFLICT: בשרטוט {fid} התווית '{lab}' שבשחזור לא נמצאה בקריאה השנייה של השרטוט"})
    for lab in (b - a):
        out.append({"kind": "figure_label", "a": "", "b": lab, "figure_id": fid,
                    "message": f"READING_CONFLICT: בשרטוט {fid} נקראה התווית '{lab}' שאינה בשחזור"})
    unread = [x for x in b_labels if "[?]" in (x or "")]
    if unread:
        out.append({"kind": "figure_label", "a": "", "b": ", ".join(unread), "figure_id": fid,
                    "message": f"READING_CONFLICT: בשרטוט {fid} יש תוויות שלא נקראו בוודאות: {', '.join(unread)}"})
    return out


# ------------------------------------------------------------------ run / refresh
def run_reading_check(service: Any, q: Any, question: dict[str, Any], reader: Any = None) -> dict[str, Any]:
    """Reader B for one question; stores the raw readings and the report on q.reading_check."""
    from .lines import split_lines
    from .second_reader import make_reader

    kind = source_kind(question)
    check: dict[str, Any] = {"version": READING_VERSION, "mode": kind}
    if kind == "pdf":
        doc = question.get("document") or {}
        lines = doc.get("source_lines") or [l for l in (doc.get("text_layer") or "").split("\n") if l.strip()]
        check.update(reader="pdf-text-layer", b_lines=[{"text": l, "unreadable": False} for l in lines], figure_labels={})
    else:
        reader = reader or make_reader(service, _reader_config())
        images: list[bytes] = question.get("images") or []
        all_lines = []
        for idx, img in enumerate(images, 1):
            boxes = [_padded_box(f.bbox) for f in q.figures if int(f.source_image_index) == idx and f.bbox]
            all_lines += split_lines(img, idx, boxes)
        readings = reader.read_lines([l.crop_png for l in all_lines]) if all_lines else []
        b_lines = [{"text": r.text, "unreadable": bool(r.unreadable), "image_index": l.image_index, "norm_bbox": l.norm_bbox}
                   for l, r in zip(all_lines, readings)]
        fig_labels: dict[str, dict] = {}
        for fig in q.figures:
            spec = (q.diagram_specs or {}).get(fig.figure_id)
            if spec is None:
                continue
            crop = _figure_crop(fig, images)
            if crop:
                fig_labels[fig.figure_id] = {"b": reader.read_figure_labels(crop)}
        check.update(reader=getattr(reader, "name", "reader-b"), b_lines=b_lines, figure_labels=fig_labels)
    q.reading_check = check
    refresh_report(q)
    return q.reading_check


def refresh_report(q: Any) -> dict[str, Any] | None:
    """Recompute the comparison from the stored readings (no API call). Cached by content fingerprint."""
    check = getattr(q, "reading_check", None) or {}
    if not check or check.get("error"):
        return None
    fp = _fingerprint(q)
    if check.get("fp") == fp and check.get("report"):
        return check["report"]
    pdf = check.get("mode") == "pdf"
    report = compare(texts_of(q), check.get("b_lines") or [], reader=check.get("reader", ""), check_formulas=not pdf)
    for fid, fl in (check.get("figure_labels") or {}).items():
        spec = (q.diagram_specs or {}).get(fid)
        a_labels = [l.text for l in (spec.labels if spec else [])]
        report["conflicts"] += figure_label_conflicts(fid, a_labels, fl.get("b") or [])
    if report["conflicts"] and report["status"] == "AGREED":
        report["status"] = "CONFLICTS"
    check["report"], check["fp"] = report, fp
    q.reading_check = check
    return report


def gate_messages(q: Any, limit: int = 6) -> list[str]:
    """Blocking messages for validate_exam (empty = the two readings agree)."""
    check = getattr(q, "reading_check", None) or {}
    if not check:
        return []
    if check.get("error"):
        return [f"READING_CHECK_FAILED: הקריאה העצמאית של המקור נכשלה ({check['error'][:120]}) — יש לבדוק את השאלה ולאשר ידנית."]
    report = refresh_report(q) or {}
    msgs = [c["message"] for c in report.get("conflicts", [])]
    if len(msgs) > limit:
        msgs = msgs[:limit] + [f"READING_CONFLICT: ועוד {len(msgs) - limit} אי-התאמות (ראו בקרת איכות)."]
    return msgs


def _padded_box(b: list[int], pad: int = 30) -> list[int]:
    """Figure box [ymin,xmin,ymax,xmax] (0..1000) grown so labels printed just outside the drawing are blanked too."""
    y0, x0, y1, x1 = b
    return [max(0, y0 - pad), max(0, x0 - pad), min(1000, y1 + pad), min(1000, x1 + pad)]


def _figure_crop(fig: Any, images: list[bytes]) -> bytes | None:
    try:
        import exam_core
        idx = int(fig.source_image_index) - 1
        if not 0 <= idx < len(images):
            return None
        return exam_core.crop_figure_bytes(images[idx], _padded_box(fig.bbox, 15) if fig.bbox else None, max_side=None)
    except Exception:
        return None


__all__ = ["configure", "run_reading_check", "refresh_report", "gate_messages", "source_kind", "consensus"]
