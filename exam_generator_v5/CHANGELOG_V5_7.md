# CHANGELOG — 5.7.0

## Added
- `diagram_engine/ocr/` (engine: region-based Tesseract reading of numbers/percentages/letters, grid-detected per-cell table OCR,
  cached by image hash; verify: confirmations → `ocr_engine` facts, disagreements → conflicts resolved by the text or UNRESOLVED).
- `workspace.py` — SessionWorkspaceManager (per-session temp dir, atomic writes, no path traversal, stale cleanup).
- `ReconstructionStrictness` (EXAM_QUALITY default), solver time budget constants, version constants (schema/parser/renderer/
  validator/vision/OCR).
- Tests: `tests/diagram_engine/test_v57_regressions.py` (45), new core tests (approval invalidation, integrity), browser E2E raster
  override path, `tests/benchmark.py`.
- Docs: BASELINE_TEST_REPORT.md, AUDIT_V5_7.md, CHANGELOG_V5_7.md, TEST_REPORT_V5_7.md, REAL_IMAGE_ACCEPTANCE_REPORT_V5_7.md.

## Changed
- Approval / override bound to a fingerprint (spec, source hash, input key incl. crop, raw spec, required facts, input hashes,
  versions). `usable_in_document` additionally requires no missing required fact.
- Export: approved reconstruction → vector render (PNG 300 dpi in Word); explicit override → source crop (captioned, audited);
  otherwise a red placeholder and a blocking validation error. No automatic raster.
- `attach_diagrams`: stem + sections as required text (section facts required when they refer to figure points), input hashes and
  PIPELINE_INTEGRITY_ERROR.
- Hebrew parser: morphology, Unicode gershayim units, nearest-object dimension binding, semantic quadrilaterals, inscribed,
  tangent-meets-axis, "הבע באמצעות … את …", review flags for isosceles/right/trapezoid without explicit data.
- Safe math: implicit multiplication split only into whitelisted names and declared symbols; superscripts; `symbols.classify`.
- Solver: derived construction points (midpoint/ratio) computed directly, time budget, `SOLVER_TIMEOUT` / `SOLVER_CONVERGENCE_ERROR`.
- Pipeline: `SCHEMA_VALIDATION_FAILED` / `PIPELINE_ERROR` codes kept in the audit; Hebrew messages without tracebacks.
- Uploads: 25 MB / 60 MP limits, decompression-bomb and malformed-file handling in Hebrew. Retries: `max_total_time`.
- UI: raster override needs an explicit confirmation checkbox; statuses reworded for EXAM_QUALITY.
- `packages.txt`: tesseract-ocr, tesseract-ocr-heb, tesseract-ocr-eng. `requirements.txt`: pytesseract, opencv-python-headless.

## Fixed
All defects listed in BASELINE_TEST_REPORT.md, plus: dimension bound to an object of the previous sentence; ruff F401/F841/B039.
