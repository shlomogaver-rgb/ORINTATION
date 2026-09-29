# CHANGELOG — 5.6.0

## Why
In 5.5 the DiagramSpec and the `observed` source signature could come from the same vision answer (correlated failure):
a point omitted by the AI in both passed validation with 0 critical mismatches and comparison 1.00 (reproduced: A14 without E →
validation PASS, critical 0, comparison 1.00, decision "review" 0.93). 5.6 makes the vision model one evidence source among several.

## Files added
- `diagram_engine/fact_graph.py` — Fact / FactGraph, canonical fact keys, verification coverage.
- `diagram_engine/text_facts.py` — Hebrew Mathematical Parser V2 (required facts from the question stem) + text-facts→constraints.
- `diagram_engine/verification.py` — SourceSignature V3: required-fact check on the solved reconstruction, contradictions,
  radius/diameter semantics, coverage, confidence breakdown.
- `diagram_engine/symbols.py` — Dynamic Safe Symbol Table (parameters declared in the question text only).
- `tests/diagram_engine/test_v56_regressions.py` — tests A–J, 23 Hebrew formulation tests, consistency test.
- `tests/acceptance_real/` — hand-authored manifests (16), harness, real-image + adversarial tests, artifacts
  (source / render.svg / render.png / overlay.png).
- `AUDIT_V5_6.md`, `CHANGELOG_V5_6.md`, `TEST_REPORT_V5_6.md`, `REAL_IMAGE_ACCEPTANCE_REPORT_V5_6.md`.

## Files modified
- `diagram_engine/pipeline.py` — symbol context, unknown-key detection (no silent degradation), v3 verification, decision v3,
  `required_text` / `ground_truth_facts` parameters, Hebrew fallback message.
- `diagram_engine/decision.py` — `decide_v3` (final confidence ≤ coverage; high confidence only with ≥90% coverage, no AI-only
  critical fact and no contradiction; unsupported feature → original).
- `diagram_engine/safe_math.py` — symbol context, `numeric`, `semicircle`, parametric `domain`.
- `diagram_engine/schemas.py` — schema 3.0: construction segments/lines/rays, points on segments/diagonals, annotations,
  dimensions with object/dimension_type/value/unit (length/side/distance added), `symbols`, `unsupported_features`,
  record confidence/coverage/facts/missing_required/contradictions, comparison semantic/numeric scores.
- `diagram_engine/charts/scatter.py` — V2: axes + tick-mark mapping when the grid is too faint/absent; unstable → original.
- `diagram_engine/spatial/renderer.py` — construction segments/lines/rays, chained points, annotations.
- `diagram_engine/geometry/parser.py` — V2 text facts feed the solver.
- `diagram_engine/constants.py` — versions (schema 3.0, parser diagram-engine/3.0), coverage thresholds, DIAGRAM_TYPES.
- `exam_core.py` — version 5.6.0; prompt lists the 8 diagram types; prompt asks for construction segments, dimension semantics and
  `unsupported_features`; stem passed as required text.
- `diagram_ui.py` — confidence breakdown, coverage, fact sources, missing facts and contradictions.

## Behaviour changes
- A reconstruction with an explicit text fact missing (point, order, circle membership, tangent, diameter, segment, dimension type)
  is blocked (original), even if the AI's own observation agrees with it.
- Nothing reaches high_confidence_preview unless every critical fact is independently verified (≥ 90% coverage, 0 AI-only).
- Tables, normal-distribution labels and qualitative shapes have no independent channel (no OCR engine) → always teacher review.
- Cache keys include parser version 3.0 → 5.5 cached records are recomputed.

## Dependencies
None added.

## Backward compatibility
All 5.5 APIs kept (`process`, `render_spec`, `decide`, shims); 5.5 specs load unchanged.
