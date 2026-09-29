# AUDIT — 5.7.1: status of the 120 items

Legend: DONE (implemented + tested) · PARTIAL (implemented, limitation stated) · NOT DONE · NOT TESTABLE here.

| # | Item | Status | Evidence / note |
|---|---|---|---|
| 1 | audit before change, no broad refactor, preserve features | DONE | every change preceded by a regression test; 548→552 tests green |
| 2 | principles | DONE | see items below |
| 3 | target pipeline | PARTIAL | all stages implemented; real model never run |
| 4 | full-resolution master | DONE | test_upload_keeps_full_resolution_master |
| 5 | derived images only | DONE | working / preview / OCR derivative from master |
| 6 | no early destruction | DONE | MAX_IMAGE_SIDE applies to the working derivative only |
| 7 | ROI from master | DONE | test_edit_chain_replayed_on_master... |
| 8 | edit transform mapping | DONE | normalized crop, erase masks, rotations replayed |
| 9 | image provenance | PARTIAL | master/derivative/ops/preprocess version; resize params implicit (MAX_IMAGE_SIDE) |
| 10 | PASS 1 text | DONE | prompt: locate figures only, spec_json empty |
| 11 | PASS 2 high-res diagram | DONE | extract_diagrams_pass2, typed AIDiagramSpec |
| 12 | PASS 3 verification | DONE | OCR, CV, SymPy, geometry, topology |
| 13 | fact status | DONE | record.reconciliation |
| 14 | RequiredFacts whole question | DONE | stem + sections (section facts required when about figure points) |
| 15 | fact criticality | DONE | Fact.criticality |
| 16 | evidence independence | DONE | provider + pass_id |
| 17 | independent OCR discovery | PARTIAL | labels, numbers, cells, %, ticks, dims; geometry length/angle numbers not compared |
| 18 | independent numeric verification | PARTIAL | tables, %, dims, bars, scatter; geometry length/angle labels not |
| 19 | semantics vs notation | DONE | notation.py |
| 20 | LocalizationProfile | DONE | ISRAEL_HIGH_SCHOOL / SOURCE_FAITHFUL / GENERIC_MATH |
| 21 | SOURCE_FAITHFUL | DONE | test |
| 22 | x̄ / S | DONE | test |
| 23 | multiple notations parsed | DONE | semantic_of |
| 24 | notation quality gate | DONE | validate_exam error NOTATION_INCONSISTENCY |
| 25 | all outputs | PARTIAL | solutions + rubric + Word (same text); diagrams contain no statistical symbols |
| 26 | OCR states | DONE | SUCCESS/SUCCESS_NO_TEXT/TIMEOUT/ENGINE_UNAVAILABLE/INVALID_INPUT/FAILED |
| 27 | independent inventories | PARTIAL | labels, numbers, circles; segment/dot counts measured unreliable → not gating |
| 28 | multi-signal quality gate | DONE | similarity informative only |
| 29 | native structured output | DONE | legacy spec_json path kept only for old data |
| 30 | no automatic raster fallback | DONE | test_approved_diagram_renderer_exception... |
| 31 | SVG in DOCX/PDF | DONE / NOT TESTABLE | LibreOffice PDF vector verified; Word Desktop/Web not available |
| 32 | Hebrew semantic parser | DONE | text_facts |
| 33 | Hebrew geometry regression | DONE | inscribed, rectangle, isosceles→review, tangent+axis |
| 34 | prime-safe entities | DONE | A, A', A′, A’, A'', A_1 |
| 35 | Hebrew dimension morphology + units | DONE | incl. אורכה, גובהה, רדיוס בסיסו, ס''מ, cm |
| 36 | DimensionFact | DONE | entity + type + value + unit (+ ordinal) |
| 37-39 | SEGMENT/RAY/LINE semantics | DONE | extent facts + spec lists |
| 40 | tangent extent not auto-upgraded | DONE | test |
| 41 | extent resolver | PARTIAL | text + vision; CV extent not measured |
| 42 | extent validator | DONE | test_linear_extent_validator |
| 43 | geometry integrity layer | DONE | satisfied() for all listed relations; kite/trapezoid via explicit relations or review flag |
| 44 | analytic constructions | PARTIAL | all except line/circle and circle/circle intersections (numeric, residual-checked) |
| 45 | exact intersection + degeneracy | DONE | DEGENERATE_GEOMETRY |
| 46 | single coordinate source | DONE | one position per point; pins are layout-only and cleared |
| 47 | parametric geometry | PARTIAL | constructions exact; other incidences via residuals |
| 48 | semantic vs visible | PARTIAL | hidden helper points; full visibility enum not modelled |
| 49-51 | graph anchors, hard vs soft | PARTIAL | formula anchors + schematic landmarks; anchor detection from pixels NOT DONE |
| 52 | analytic function model | PARTIAL | domain, zeros, extrema, asymptotes, holes, monotonicity; inflection/concavity not |
| 53 | graph modes | PARTIAL | field + behaviour by data |
| 54-56 | branch-aware adaptive sampling, clipping | DONE | tests |
| 57-58 | constrained schematic curves, no high-degree Bézier | DONE | monotone cubic |
| 59 | schematic guarantees | PARTIAL | extrema/roots/sign/asymptotes guaranteed; inflections not |
| 60 | visual ↔ analytic reconciliation | PARTIAL | formula vs observed/marked points; pixel curve comparison not |
| 61 | multiple-choice independence + transformations | DONE | option_transformations (evidence only) |
| 62-65 | bar chart CV | DONE / NOT TESTABLE | synthetic charts; no real scanned bar chart supplied |
| 66-67 | scatter real image + fail-closed | DONE | real PDF crop + blur/JPEG/noise/rotation |
| 68-69 | tables preserved + header mapping | DONE | semantic_cells |
| 70 | normal distribution preserved | DONE | renderer untouched; OCR % verification |
| 71-72 | 3D scene + projection engine | DONE | camera.py |
| 73-74 | hidden lines + partial occlusion | DONE (convex) | cylinders approximated / not occluders |
| 75 | label placement solver | PARTIAL | spatial labels; plane geometry uses outward normalized offsets |
| 76-82 | voxel generalisation | DONE | VoxelGrid, views, delta, impact, camera depth order |
| 83-84 | scale-invariant coordinates / resolution | PARTIAL | normalized bbox/crop/OCR; not a formal layered framework |
| 85 | DPI / output size independence | PARTIAL | 0.5×–4× OCR/scatter; output-size render test not |
| 86 | magic-number audit | DONE | MAGIC_NUMBER_AUDIT section below |
| 87 | numerical safety | DONE | constants + NaN/Inf guards + DEGENERATE_GEOMETRY |
| 88 | OCR performance | DONE | budget/regions/PSM, cache by config |
| 89 | safe caching | PARTIAL | approval fingerprint has all versions; render cache keyed by spec + parser version (style/localization not in render key) |
| 90 | memory | DONE | image_store |
| 91 | teacher review | DONE | source, extracted text, facts with status/provider, concrete reasons |
| 92-93 | real drag + UI test | DONE | custom component; E2E drag; reload persistence NOT TESTABLE (per-page Streamlit session) |
| 94 | pagination | DONE | real PDF test |
| 95-97 | real eval harness, raw outputs, manifests | DONE (not run) | eval/real_eval.py |
| 98 | recognition metrics | PARTIAL | label recall, unexpected labels, wrong-accepted, stability |
| 99 | fixed regression set | DONE | 16 figures |
| 100 | holdout set | NOT DONE | no unseen real images available |
| 101 | five-run stability | NOT TESTABLE | harness ready; deterministic part stable over 3 runs |
| 102 | acceptance rule | DONE (simulated vision) | 15 PASS + 1 SAFE FALLBACK |
| 103-111 | regressions | DONE | except 108 real scanned chart (not supplied) |
| 112 | GeoGebra scope | DONE | commands never executed; shown only as teacher reference text |
| 113 | release blockers | see below | |
| 114 | delivery report | DONE | this file + TEST_REPORT_V5_7_1 + CHANGELOG_V5_7_1 |
| 115 | work order | DONE (items above) | |
| 116 | principles | DONE except "real E2E" | |
| 117-119 | localization / analytic / schematic principles | DONE | |
| 120 | final instruction | PARTIAL | real image E2E with the real model not possible here |

## Remaining release blockers (item 113)
- Real model recognition not tested; 14-image real-vision E2E not executed; no holdout set; five-run stability not measured.
- Pixel-level graph anchor detection not implemented; SCHEMATIC inflections not guaranteed; line/circle intersections numeric.
- Word Desktop/Web rendering of the SVG not verified.
All other listed blockers are closed and covered by tests.

## Bugs found and fixed in 5.7.1
Raster fallback on approved render failure (P0) · destructive upload downsampling (P0) · legacy session items crashing the editor ·
OCR misreads at 4× resolution · A''/A_1 collisions · dimension bound to the wrong object · approval could survive component-version
changes · schematic curves could invent a root · drag moved an untouched point instead of the dragged one · audit trail dropped
diagnostics · np.cross deprecation silently disabling topology · bare exception chaining (B904) · unit ס''מ unparsed.

## Magic-number audit (item 86)
192 numeric literals scanned in renderers, OCR, scatter and topology. Classified:
MATHEMATICAL_CONSTANT (π, tolerances → constants.py) · STYLE_CONSTANT (line widths, font sizes, figure inches — renderer style) ·
RESOLUTION_LIMIT (MAX_IMAGE_SIDE, OCR_NORMALIZED_MAX_SIDE, budgets — constants) · PIXEL_SPECIFIC values that were converted to
relative/normalized ones in this release: OCR upscale factors (now target glyph/cell height), topology thresholds (fraction of image
size), label offsets (fraction of drawing size). Remaining pixel-relative thresholds: scatter tick-mark search window (7 px at the
normalized resolution) and scatter dark threshold 110/215 (grey levels, not pixels).

## RELEASE DECISION
**NOT READY – BLOCKERS REMAIN** (real-model evaluation, holdout, five-run stability cannot be executed in this environment).
