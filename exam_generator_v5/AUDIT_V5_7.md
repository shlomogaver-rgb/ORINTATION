# AUDIT & FINAL REPORT — 5.7.0

## A. Problems found
| Severity | File | Function/Class | Problem | Impact | Fix |
|---|---|---|---|---|---|
| P0 | diagram_engine/review_state.py | initial_review / usable_in_document | Approval bound only to the spec hash; survived crop/erase changes | Approved figure of a different source could be exported | Fingerprint of source, edits, spec, required facts, versions |
| P0 | exam_core.py | add_figures | `data is None → continue` | Figure silently missing from the exam | Visible placeholder + blocking validation error |
| P0 | exam_core.py | figure_bytes_for_document | Automatic raster fallback | Unreviewed scans in the exam | EXAM_QUALITY: explicit, audited override only |
| P0 | diagram_engine | (no OCR) | Numbers verified only by the same AI | Correlated wrong numbers undetected | Independent Tesseract channel + conflict resolver |
| P1 | exam_core.py | attach_diagrams | No check that the analysed image = current edited image | Figure built from other bytes than analysed | Input hashes + PIPELINE_INTEGRITY_ERROR |
| P1 | geometry/parser.py | merge_text | Constraint dedupe by sorted points | Parallelogram/rhombus half-enforced | Structure-aware `same_constraint` |
| P1 | fact_graph.py | Fact.key | All dimensions shared one key | Coverage over-counted | Type+value in key |
| P1 | text_facts.py | extract | Dimension bound to the object of the previous sentence | Correct figure blocked / wrong binding | Same sentence, nearest object |
| P1 | safe_math.py | parse_expression | `2ax`, `3xy`, `2πr` rejected | Formula questions unusable | Whitelist-only implicit multiplication |
| P1 | text_facts.py | extract | Morphology/units/semantic polygons/sections missed | Required facts not extracted | Parser extensions (tests in Hebrew) |
| P1 | exam_core.py | image_to_png_bytes | No size/pixel limits; raw exceptions | DoS / confusing errors | Limits + Hebrew ImageInputError |
| P2 | exam_core.py | GeminiService.generate | No total-time limit | Very long waits | max_total_time |
| P2 | safe_math.py | ContextVar default | Mutable default | Possible state leak | default=None |
| P2 | app.py | step5 | Word/PDF blobs in session_state | Memory per user | SessionWorkspaceManager files |

## B. Changes made — see CHANGELOG_V5_7.md.

## C. Tests — 417 total, 417 passed, 0 failed, 0 skipped (details: TEST_REPORT_V5_7.md).

## D. 14-image acceptance (16 figures incl. A07b, A09b)
| Image | Diagram type | Text extraction | OCR | Vision | RequiredFacts | Scene | Solver | Render | Validation | Decision | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A01 q14p2 | graph/qualitative | real | real (no labels read) | SIMULATED | 2 verified | OK | — | OK | PASS | review | coverage 50% |
| A02 q16p7 | graph/multi I–IV | real | — | SIMULATED | options from text | OK | — | OK | PASS | review | 50% |
| A03 q14p3 | graph/multi | real | — | SIMULATED | options | OK | — | OK | PASS | review | 50% |
| A04 q14p7 | graph/formula | real | — | SIMULATED | formula | OK | — | OK | PASS | review | 100% |
| A05 q16p3 | scatter | real | axis numbers | SIMULATED | CV points | OK | — | OK | PASS | review | 100% (CV) |
| A06 q16p8 | generic | real | 9/9 labels | SIMULATED | labels | OK | — | OK | PASS | review | 100% |
| A07 q18p12 | table | — | 8/8 numbers | SIMULATED | cells | OK | — | OK | PASS | review | 53% (Hebrew headers AI-only) |
| A07b q19p4 | table | — | 6/6 numbers | SIMULATED | cells | OK | — | OK | PASS | review | 50% |
| A08 q16p5 | analytic geometry | real | 5 labels | SIMULATED | 9 critical | OK | OK | OK | PASS | review | 85% |
| A09 q15p2 | box | real | partial | SIMULATED | vertices | OK | — | OK | PASS | review | 40% |
| A09b q17p3 | pyramid+vectors | real | — | SIMULATED | E, F | OK | — | OK | PASS | review | 39% |
| A10 q15p5 | graph/multi | real | — | SIMULATED | options | OK | — | OK | PASS | review | 50% |
| A11 q19p8 | normal | — | 11/12 % | SIMULATED | labels | OK | — | OK | PASS | review | 83% |
| A12 q19p12 | voxel | — | — | SIMULATED | — | — | — | — | blocked | teacher decision | SAFE (hidden cubes) |
| A13 q19p14 | solids | real | dims | SIMULATED | 3 dims bound | OK | — | OK | PASS | review | 43% |
| A14 q14p5 | circle geometry | real | 5 labels | SIMULATED | 7 critical | OK | OK | OK | PASS | review | 80% |
"SIMULATED" = hand-written proposal (no Gemini). Adversarial: 12 correlated-failure tests, all blocked (incl. E missing in proposal AND
observation; wrong table number caught by OCR).

## E. Performance — see TEST_REPORT_V5_7.md (8 questions: 3.2 s analysis with mock, 16 API calls, peak 49 MB).

## F. Remaining risks (not hidden)
1. **Real Vision never tested** (no credentials): prompt quality for all families, multi-run stability, real latency — unknown.
2. Three-pass recognition (separate diagram-extraction call on the crop) NOT implemented; one structured call per question.
3. DiagramSpec is still delivered as a JSON string inside the structured response (schema-validated, fails closed).
4. Word embeds 300-dpi PNG, not SVG; labels are vector paths in the SVG (no bidi corruption) but PDF figures are raster.
5. CV topology/keypoint comparison (Hough/corners) and OCR-before/after-render NOT implemented; letter OCR is weak (confirmations only).
6. No independent channel for qualitative graph shapes and Hebrew table headers → always teacher review.
7. Architecture folders (editor/, llm/, …) not reorganised (no functional reason; risk to the working editor).
8. mypy not run; drag editor not automated; 8-question browser E2E not run.

## G. Release decision
**NOT READY – BLOCKERS REMAIN** — P0 "Real Vision extraction was not tested" and "real 14-image E2E with real vision was not executed"
cannot be closed in this environment. All other P0 items listed in the spec are closed and covered by tests.
