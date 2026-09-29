"""Deterministic diagram reconstruction engine (v2).

SOURCE -> structured evidence -> DiagramSpec -> validation -> deterministic renderer -> source comparison ->
decision -> teacher approval -> export. The AI never draws the final figure; nothing is exported without a teacher."""
from .constants import PARSER_VERSION, SCHEMA_VERSION  # noqa: F401
from .pipeline import DiagramResult, apply_teacher_edit, export_bundle, parse_raw, process, process_diagram, render_spec  # noqa: F401
from .review_state import auto_approve_if_proven, approve, can_approve, raster_allowed, raster_override, reject, usable_in_document, use_original  # noqa: F401
from .schemas import DiagramRecord, DiagramSpec  # noqa: F401
