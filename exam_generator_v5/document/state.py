"""MODE-B canonical state. The FullDocumentModel imported from a PDF is the source of truth for document semantics; every
later step ENRICHES it and every questions_data rebuild re-attaches it (nothing may silently disappear)."""
from __future__ import annotations

from typing import Any


def question_payload(document_model: dict | None, number: int, templates: dict | None = None,
                     text_layers: dict | None = None) -> dict | None:
    """The per-question document block carried in questions_data["document"] (built from the canonical model)."""
    if not document_model:
        return None
    q = next((x for x in document_model.get("questions", []) if x.get("number") == number), None)
    if q is None:
        return None
    return {"pages": q.get("pages", []), "subparts": [s["label"] for s in q.get("subparts", [])],
            "visuals": q.get("visual_objects", []), "response_regions": q.get("response_regions", []),
            "response_templates": (templates or {}).get(str(number), []), "continuation": q.get("continuation_metadata", {}),
            "text_layer": (text_layers or {}).get(str(number), ""),
            "page_roles": {str(p["index"]): p["role"] for p in document_model.get("pages", [])},
            "document_sha256": document_model.get("metadata", {}).get("pdf_sha256", "")}


def source_hash(item) -> str:
    """IMMUTABLE source identity of an editor item: the digest of its full-resolution master (not the question number)."""
    import exam_core
    try:
        data = item["master"]
    except Exception:
        data = None
    return exam_core.image_digest(data or item["current"])


def item_ops_hash(item) -> str:
    """Hash of the teacher's edit operations on an editor item ('' = unedited)."""
    try:
        if hasattr(item, "provenance"):
            return item.provenance().get("ops_hash", "") if item.provenance().get("ops") else ""
        return item.get("ops_hash", "") or ""
    except Exception:
        return ""


def build_questions_data(store: dict, points: dict, n: int, document_model: dict | None = None,
                         templates: dict | None = None, text_layers: dict | None = None,
                         pdf_questions: dict | None = None, source_evidence: dict | None = None) -> list[dict]:
    """ONE place that builds questions_data from the editor store - used by the app at every rebuild.
    Document semantics are re-attached from the canonical model, so a UI step can never drop them."""
    out = []
    for q in range(1, n + 1):
        items = store.get(q, [])
        entry: dict[str, Any] = {"question_number": q, "points": points[q], "images": [it["current"] for it in items],
                                 "masters": [it.master_current() if hasattr(it, "master_current") else it["current"] for it in items],
                                 "provenance": [it.provenance() if hasattr(it, "provenance") else {} for it in items]}
        if source_evidence is not None:
            # evidence follows the SOURCE: attached only if one of this question's items IS the imported source
            hit = next(((source_evidence[source_hash(it)], it) for it in items if source_hash(it) in source_evidence), None)
            if hit is not None:
                ev, it = hit
                doc = dict(ev)
                if item_ops_hash(it) != (ev.get("import_ops_hash") or ""):
                    # the teacher edited (cropped / erased) the source after import: region-dependent evidence (answer
                    # boxes, grids) may have been cut away -> dropped; the source text layer stays evidence of the SAME source
                    doc["response_templates"] = []
                    doc["edited_after_import"] = True
                entry["document"] = doc
        else:                                                    # legacy callers (number-keyed) - not used by the app
            doc = question_payload(document_model, q, templates, text_layers)
            if doc is not None:
                entry["document"] = doc
            elif pdf_questions and str(q) in pdf_questions:
                entry["document"] = dict(pdf_questions[str(q)])
        out.append(entry)
    return out
