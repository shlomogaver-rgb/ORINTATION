# DELIVERY REPORT — 5.7.9 (cube structures read from the drawing, inserted without the teacher)

Status: **PRE-RC**.

## What changed
| Part | Change |
|---|---|
| diagram_engine/spatial/voxel_fit.py (new) | analysis-by-synthesis reader: face classification from the image histogram; projection calibrated from the drawing (plate corners, top-face width, front-face height; cube edges equal); painter's-order rendering of candidates; coordinate-ascent search of the heights; calibration refinement; UNIQUENESS check (any single-cell change that leaves the drawing unchanged = not determined); refuses cut drawings |
| pipeline.py | every cube structure with a source is read from the drawing (the model's reading is only the start); proven -> heights replaced, confidence/coverage from the proof, heuristic hidden-top estimate superseded; not proven -> VOXEL_NOT_DETERMINED (teacher) |
| review_state.py | auto_approve_if_proven (approved_by = system:voxelfit/…); the export gate accepts ONLY this proven approval besides the teacher's |
| exam_core.py | padded crop for cube drawings (plate corners never cut); auto-approval after processing |
| spatial/renderer.py | Bagrut-style cube drawing (front-right view, 32°, light plate with cell lines, arrow, title), inventory kept for the comparator |
| schemas.VoxelSpec.title | structure name above the drawing ("מבנה II") |
| earlier in this round | measurement givens bound to the object that shows them; "אורך רדיוס" = radius; normal-curve axis label reported |

## Results on 35372 (question 5)
All three structures read from the drawings starting from a WRONG reading, corrected, proven unique (agreement 97.2% / 98.3% /
97.9%) and inserted automatically with titles. The 35372 student exam: 9 SVG figures, nothing pending, OOXML PASS.

## Safety
16 random structures: 0 wrong accepted (hidden cubes are refused); a hidden cube behind a wall is refused; a cut drawing is refused.
Limitation: acceptance on random structures is conservative (occlusion slivers) - such cases go to the teacher.

## Tests (exactly as executed)
| Suite | PASS | FAIL | SKIPPED | NOT RUN |
|---|---|---|---|---|
| diagram_engine (incl. 10 new cube tests) | 469 | 0 | 0 | 0 |
| acceptance + acceptance_real + full-document + new-exam findings | 121 | 0 | 0 | 0 |
| core + app + legacy + 5.7.5–5.7.8 regressions + fuzz | 340 | 0 | 0 | 0 |
| full-document dev + Mode-B UI flows | 14 | 0 | 0 | 0 |
| PDF → DOCX structural E2E | 1 | 0 | 0 | 0 |
| **Total** | **945** | **0** | **0** | **0** |
compileall PASS, ruff PASS. Browser E2E: NOT RUN in this release (no UI change). Real Gemini: NOT EXECUTED.

## Still open (35372)
Figure-to-subpart binding by position (Q3, Q6); II/III detected as a graph option group; duplicated answer boxes in Q3;
4×4 template wide and after the stem; roller-coaster illustration simplified.
