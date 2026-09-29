"""Audit trail of one figure (what, from where, by whom, when)."""
from __future__ import annotations

from typing import Any

from .constants import PARSER_VERSION, SCHEMA_VERSION
from .review_state import now, spec_hash


def build(rec, ai_model: str, cleaned_hash: str = "") -> dict[str, Any]:
    spec = rec.spec
    return {
        "source_image_hash": spec.source_image_hash if spec else "", "cleaned_image_hash": cleaned_hash,
        "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION, "ai_model": ai_model,
        "diagram_type": rec.classifier_type, "subtype": rec.classifier_subtype,
        "classifier_confidence": rec.classifier_confidence, "parser_confidence": rec.parser_confidence,
        "comparison_score": rec.comparison.overall_score, "critical_mismatches": list(rec.comparison.critical),
        "validation_ok": rec.validation.ok, "decision": rec.decision.action,
        "teacher_approved": rec.review.status == "approved" and rec.review.approved_by == "teacher",
        "review_status": rec.review.status, "teacher_edits": [e.model_dump() for e in rec.review.teacher_edits],
        "evidence_count": len(spec.evidence) if spec else 0, "spec_hash": spec_hash(spec), "processed_at": now(),
        "confidence": dict(rec.confidence), "verification_coverage": dict(rec.coverage),
        "missing_required_facts": list(rec.missing_required), "contradictions": list(rec.contradictions),
        "unsupported_features": list(spec.unsupported_features) if spec else [],
    }
