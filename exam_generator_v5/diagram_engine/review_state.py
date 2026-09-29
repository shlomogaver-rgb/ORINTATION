"""Teacher review state. An approval is bound to the exact spec (hash); any change voids it."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .schemas import DiagramRecord, DiagramSpec, ReviewState, TeacherEdit


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def spec_hash(spec: DiagramSpec | None) -> str:
    if spec is None:
        return ""
    data = spec.model_dump_json(exclude={"warnings", "source_image_hash"})
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def fingerprint(record: DiagramRecord) -> str:
    """Everything an approval depends on. Any change (crop, erase, rotate, new image, edited number/label/relation,
    new required facts, engine version) produces a new fingerprint and INVALIDATES the approval."""
    from .constants import OCR_ENGINE_VERSION, PARSER_VERSION, RENDERER_VERSION, SCHEMA_VERSION, VALIDATOR_VERSION, VISION_VERSION

    spec = record.spec
    req = sorted(f["id"] for f in record.facts if f.get("required")) if record.facts else []
    from .notation import NOTATION_VERSION
    from .spatial.camera import PROJECTION_VERSION
    from .topology_extractor import TOPOLOGY_VERSION
    from .charts.bar_cv import BAR_CV_VERSION
    parts = [NOTATION_VERSION, PROJECTION_VERSION, TOPOLOGY_VERSION, BAR_CV_VERSION,
             spec_hash(spec), spec.source_image_hash if spec else "", record.input_key,
             hashlib.sha256((record.raw_spec_json or "").encode()).hexdigest(), json.dumps(req),
             json.dumps(record.input_hashes, sort_keys=True), SCHEMA_VERSION, PARSER_VERSION, RENDERER_VERSION,
             VALIDATOR_VERSION, VISION_VERSION, OCR_ENGINE_VERSION]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def initial_review(record: DiagramRecord, prior: ReviewState | None, allow_auto: bool = False) -> ReviewState:
    """allow_auto is accepted for v5.4 compatibility and IGNORED: nothing is approved without a teacher.
    A prior decision survives ONLY if the fingerprint is identical."""
    h = spec_hash(record.spec)
    if prior is not None and prior.fingerprint and prior.fingerprint == fingerprint(record) \
            and prior.status in ("approved", "rejected", "original", "raster_override"):
        return prior.model_copy(deep=True)
    review = ReviewState(status="pending", spec_hash=h, updated_at=now(),
                         teacher_edits=list(prior.teacher_edits) if prior else [])
    if record.decision.action == "original":
        review.status = "original"
    return review


def can_approve(record: DiagramRecord) -> bool:
    return record.validation.ok and not record.comparison.critical and record.decision.action != "original" and not record.render_error


def auto_approve_if_proven(record: DiagramRecord) -> bool:
    """AUTOMATIC approval, without the teacher, ONLY for a reconstruction that was proven from the source drawing
    itself (a cube structure read by analysis-by-synthesis: face-by-face agreement AND a unique solution). Recorded
    as approved_by = 'system:<proof>'; the teacher can still reject it."""
    vf = (record.audit or {}).get("voxel_fit") or {}
    if not (vf.get("ok") and not vf.get("ambiguous_cells") and float(vf.get("score", 0)) >= 0.93):
        return False
    if not can_approve(record) or record.decision.action not in ("high_confidence_preview", "review"):
        return False
    record.review.status, record.review.approved_by = "approved", f"system:{vf.get('version', 'voxelfit')}"
    record.review.spec_hash, record.review.updated_at = spec_hash(record.spec), now()
    record.review.fingerprint = fingerprint(record)
    return True


def approve(record: DiagramRecord) -> bool:
    if not can_approve(record):
        return False
    record.review.status, record.review.approved_by = "approved", "teacher"
    record.review.spec_hash, record.review.updated_at = spec_hash(record.spec), now()
    record.review.fingerprint = fingerprint(record)
    return True


def raster_override(record: DiagramRecord, reason: str = "") -> None:
    """EXCEPTIONAL, explicit teacher action: use the original raster for this figure. Audited, never automatic."""
    record.review.status, record.review.approved_by = "raster_override", "teacher"
    record.review.override_reason, record.review.updated_at = reason or "בחירה מפורשת של המורה", now()
    record.review.fingerprint = fingerprint(record)
    record.audit.setdefault("raster_overrides", []).append({"at": now(), "reason": record.review.override_reason,
                                                             "fingerprint": record.review.fingerprint})


def raster_allowed(record: DiagramRecord | None) -> bool:
    return bool(record and record.review.status == "raster_override" and record.review.approved_by == "teacher"
                and record.review.fingerprint == fingerprint(record))


def use_original(record: DiagramRecord) -> None:
    record.review.status, record.review.approved_by, record.review.updated_at = "original", "", now()


def reject(record: DiagramRecord) -> None:
    record.review.status, record.review.approved_by, record.review.updated_at = "rejected", "", now()


def usable_in_document(record: DiagramRecord | None) -> bool:
    """THE export gate: teacher-approved AND bound to this exact spec AND valid AND no critical mismatch."""
    proven = bool(record and record.review.approved_by.startswith("system:voxelfit")
                  and ((record.audit or {}).get("voxel_fit") or {}).get("ok")
                  and not ((record.audit or {}).get("voxel_fit") or {}).get("ambiguous_cells"))
    return bool(record and record.review.status == "approved" and (record.review.approved_by == "teacher" or proven)
                and record.review.spec_hash == spec_hash(record.spec) and record.review.fingerprint == fingerprint(record)
                and can_approve(record) and not record.missing_required)


def add_edit(review: ReviewState, summary: str, before: str, after: str) -> None:
    review.teacher_edits.append(TeacherEdit(at=now(), summary=summary, spec_hash_before=before, spec_hash_after=after))
