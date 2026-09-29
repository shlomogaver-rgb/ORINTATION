# AUDIT & DELIVERY REPORT — 5.7.3 (generalization + full semantic reconstruction)

## A. Architecture changes
| File | Class/function | Old | New | Why |
|---|---|---|---|---|
| document/model.py, structure.py (new) | FullDocumentModel, build_document | no document understanding | page roles, questions/subparts, cross-page continuity, visuals with roles + question/subpart binding, option groups, response templates; PDF text layer = evidence only | MODE B |
| document/structure.py | _ocr_lines, _ocr_margin_numbers, _raster_visuals | scanned PDFs unsupported | OCR + positional number column + adaptive-threshold figures | scanned exams |
| document/reconstruct.py (new) | questions_data, merge_box_rows | — | per-question full-resolution regions (multi-page), empty response templates | MODE B -> normal pipeline |
| app.py | import_full_document | per-question images only | "ייבוא מבחן שלם (PDF)" | MODE B UI |
| exam_core.py | add_response_templates | — | empty native Word tables (boxes, grids, rows of boxes) | response areas never filled |
| diagram_engine/text_facts.py | clauses, given_text, plural dimensions | whole-sentence roles; claims enforced; plural lists lost | clause-level GIVEN/GOAL/CLAIM; all listed values kept | semantic correctness |
| geometry/parser.py, verification.py | merge_text / verify | "הוכיחו כי AB=CD" imposed on the drawing | only GIVEN clauses constrain; claims recorded as context | BUG (confirmed) |
| ocr/verify.py | _geometry_numbers | multiset confirmation | affine spec->pixel binding through OCR'd labels; swapped values = conflict; <3 labels = unbound (never confirmed) | OCR swap bug (confirmed) |
| graph/graph_cv.py, pipeline.py | analyse, self-check | 8/9 simple correct graphs falsely blocked | generic piece re-join, crossing clustering, symbolic limits, per-graph reliability self-check | false positives (confirmed) |
| charts/bar_cv.py, validator.py | detect / verify | only mid-grey bars; negatives rejected | fill-holes detection (black/dark/light/outline/colour), minus-sign recovery at the zero tick, calibration-resolution tolerance; negatives forbidden only for pie/histogram | bar generalisation |
| diagram_engine/semantic/* (new) | complex, conics, vectors, space3d, expression_ast, functions | — | engines -> existing tested renderers | spec §11–25 |
| graph/renderer.py, schemas.py | draw_illustrations, Illustration | — | hybrid illustration layer (math manifest unchanged) | §34 |

## B. Generalization evidence
| Feature | Original failure | Variants tested |
|---|---|---|
| clause roles | claim enforced as a given | 4 given+goal sentences (other letters/verbs), 5 claim forms (הוכח/הראו/הסבירו/נמקו), 3 claims in a drawing, given+claim in one sentence |
| plural dimensions | 60 & 30 lost | 5 phrasings, 2–3 values, with/without unit per value, other nouns |
| OCR binding | swapped AB/BC confirmed | ABC / PQR / KLM, different layouts; unreadable labels -> unbound (safe) |
| graph CV | y=x etc. blocked | 12 functions (linear, cubic, exp, log, sin, rational, 2^x, −e^−x) |
| bar CV | black/outline bars missed | 6 styles × 3 value sets, 2 negative sets, horizontal |
| document structure | — | 12 real exams (6 + 4 dev incl. 1 scanned + 2 former holdout) + unseen synthetic documents |
| engines | — | 4 root equations, 5 conic types, locus, pyramid vectors, 3D relations, 5 AST forms |

## C. Full document reconstruction (structure; real-model text/formulas NOT tested)
| PDF | Pages | Questions (declared) | Cross-page | Visuals / option groups | Response areas | Result |
|---|---|---|---|---|---|---|
| 14–19 (first batch) | 7/5/8/6/20/20 | 8/5/8/5/6/6 | 14:Q1 p2–3 | 16 known figures bound correctly | workspace pages 18/19 | PASS |
| 20 | 6 | 5 (5) | – | Q1 box, Q4 option group(3) | – | PASS (no code change needed) |
| 21 scanned | 6 | 8 (8) | – | Q1×2, Q4, Q5, Q6 | – | PASS after scan path |
| 22 | 7 | 8 (8) | Q1 p2–3 | option groups Q1(3), Q6(3) | – | PASS (no code change needed) |
| 24 | 5 | 5 (5) | – | Q2 box, Q5 group(4) | – | PASS (declared-count word order fixed) |
| 23 former holdout | 20 | 6 (6) | – | 6 figures | Q3 11 boxes, Q5 grids, 5 workspace pages | blind 16/18 of 18 checks with 25 → fixed → regression |
| 25 former holdout | 5 | 5 (5) | – | Q2–Q4, Q5 group(4) | – | (see above) |
DOCX: MODE B verified end-to-end with the mock model (PDF -> regions -> PASS 1/2 -> approval -> DOCX with SVG; empty template tables).

## D. Formula recognition
NOT TESTED with the real model. The PDF text layer is shown (and kept) as evidence only: it reverses Hebrew and breaks fractions,
powers and radicals (observed in every PDF). ExpressionAST + SymPy validation + OMML path exist and are unit-tested.

## E. Visual reconstruction
All graphs/geometry/charts/solids are re-generated from semantic models as vector SVG; raster only by explicit teacher override.

## F. Exact user regression set
The original problem images mentioned in the spec were not supplied beyond the 12 exam PDFs; all 12 PDFs are regression inputs.

## G. Real model E2E — NOT TESTED (no credentials). Harness: eval/real_eval.py.
## H. Holdout — 23 and 25 were used as holdout (blind: 16/18), then consumed by generic fixes -> regression. **A new unseen holdout
set is needed** (eval/holdout is empty).

## I. Remaining risks
- Real Gemini PASS 1/2, five-run stability: not executed. Hebrew text/formula quality of MODE B depends on it.
- Scanned-PDF numbering is positional (validated against the declared count; mismatch -> teacher).
- Letter OCR is weak (binding falls back to "unverified", never confirms).
- Engines are complete as mathematics but only partially wired into the AI schema (the model must still produce them in PASS 2).
- Word Desktop/Web SVG rendering not verified here.

## Release decision
**NOT READY – BLOCKERS REMAIN** (real-model E2E, stability, new holdout, Word QA).

## Tests
702 passed, 0 failed (diagram_engine 465, core/app/acceptance 199, full-document 38). ruff (E9,F) clean; compileall OK.
