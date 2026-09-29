# DELIVERY REPORT — 5.7.7 (fixes for the 14 findings of the 5.7.6 deep review)

Status: **PRE-RC** (real Gemini E2E, 5-run stability, a new holdout and Word Desktop/Web QA not executed).
Method: every finding reproduced by a test that FAILED on 5.7.6 (25 of 27 failed initially), then fixed generally.

| # | Finding (severity) | Fix | Status |
|---|---|---|---|
| 1 | Absolute values rendered as "¿…∨¿" in PDF (P0) | lone bars → native Word delimiter m:d; a closing bar carrying an exponent (\|FE\|²) handled; `\mid` (P(A∣B)) excluded; operator-only scripts (0⁺, 0⁻) marked m:nor, schema-ordered | FIXED |
| 2 | Line ending with a formula merged with the next sentence (P0) | a line ending with math is a paragraph boundary; true soft wraps still joined | FIXED |
| 3 | Graph-fidelity gate inactive for axes at the edge (P1) | L/T axes at an end of the x-axis; frames = border-touching lines spanning the image; new TREND feature (growth vs decay) | FIXED |
| 4 | Thousands separators = "lost commas" (P1) | punctuation commas exclude 2,100 / (3,4) / {,} | FIXED |
| 5 | Image OCR found no subpart markers (P1) | word boxes: the right-most token of every line is its start (≥4 of א–ה found on the teacher image) | FIXED |
| 6 | Teacher verification not bound to structure (P1) | verification fingerprint = math + structure signature | FIXED |
| 7 | k-of-n rebalance zeroed general rubric stages (P1) | general stages keep their share; rubric target accounts for them | FIXED |
| 8 | PDF evidence survived teacher crops (P1) | ops hash stored at import; after an edit response templates are dropped, source text kept, flagged | FIXED |
| 9 | Subsection indentation on the wrong RTL side (P2) | start-side indentation | FIXED |
| 10 | "(א)" / "1." subsections not recognised (P2) | grammar extended | FIXED |
| 11 | Non-contiguous choice group "ב–ד" (P2) | members listed ("ב ו־ד") | FIXED |
| 12 | No UI control for question points (P2) | step-1 checkbox → meta.show_question_points | FIXED |
| 13 | Mixed graph+geometry not fidelity-checked (P2) | gate runs for mixed_graph_geometry | FIXED |
| 14 | Line breaks in the solutions document (P3) | stem, steps and final answers use TextBlocks | FIXED |

Found while fixing (all fixed, with tests): superscripted closing bar; `\mid` wrongly treated as a bar (P(A∣B)+P(C∣D) would have become
an absolute value); operator-only superscripts rendered as "¿ ¿+"; the first m:nor fix violated the OOXML schema (nor and sty are
alternatives) - caught by the full validator, fixed, and a schema-order test added.

## Regenerated Word files (validated one by one)
| File | OOXML validation | '¿'/'∨' in the LibreOffice PDF | w:br | "(N נקודות)" | equations (OMML) | SVG figures |
|---|---|---|---|---|---|---|
| מבחן_5_שאלות | PASS | 0 | 0 | 0 | 85 | 5 |
| פתרונות_5_שאלות | PASS | 0 | 0 | 24 | 163 | 5 |
| מחוון_5_שאלות | PASS | 0 | 0 | 5 | 7 | 0 |
| מבחן_035571 | PASS | 0 | 0 | 0 | 157 | 6 |
| פתרונות_035571 | PASS | 0 | 0 | 43 | 286 | 6 |
| מחוון_035571 | PASS | 0 | 0 | 8 | 41 | 0 |
Student exams: 0 point values; solutions and rubrics keep scoring (teacher documents).

## Tests (exactly as executed)
| Suite | PASS | FAIL | SKIPPED | NOT RUN |
|---|---|---|---|---|
| diagram_engine (excl. fuzz/acceptance) | 460 | 0 | 0 | 0 |
| core + app + legacy + 5.7.5/5.7.6/5.7.7 regressions (incl. 35 review fixes) + fuzz | 330 | 0 | 0 | 0 |
| acceptance + acceptance_real (035571, teacher 5) + full-document | 103 | 0 | 0 | 0 |
| full-document dev + Mode-B UI flows | 14 | 0 | 0 | 0 |
| PDF → DOCX structural E2E | 1 | 0 | 0 | 0 |
| **Total** | **908** | **0** | **0** | **0** |
Parts 2 and 3 were re-run after the last change (schema-correct m:nor); parts 1 and 4 were last run after the previous change (they do
not exercise operator-only scripts). compileall PASS, ruff PASS, browser E2E PASS (before the last OMML-only change).
NOT EXECUTED: real Gemini PASS 1/2, 5-run stability, new holdout, Word Desktop / Word Web.

## Remaining limitations
- Word Desktop/Web rendering of the delimiters/accents not verified (LibreOffice PDF + OOXML schema only).
- Graph fidelity: option-group panel detection still layout-sensitive on some Bagrut layouts (→ teacher review).
- Comma fidelity checked only against PDF text layers; image OCR is used for subpart markers only.
