# DELIVERY REPORT — 5.7.6 (text fidelity + graph fidelity + student presentation)

Status: **PRE-RC** (real-model E2E, 5-run stability, new holdout and Word Desktop/Web QA not executed).

| Requirement | Files changed | Regression test | Result | Status |
|---|---|---|---|---|
| 1. No section/subsection points in the student exam | exam_core.py (render_profile, STUDENT/TEACHER profiles, question_heading, exam loop, student_choice_note) | test_v576_presentation (student vs rubric, template opt-in), test_v575_closure (k-of-n rule without points) | PASS | **FIXED** |
| 2/3/4. Paragraph / ENTER / subsection structure | text_structure.py (new TextBlock model: SOFT_WRAP / HARD / SUBSECTION / DISPLAY), exam_core.add_structured_block | tests A, C, D (incl. flattened input), E, F, G + 5 line-break variants; 0 w:br in student exams | PASS | **FIXED** |
| 5. Punctuation fidelity | text_structure (never adds/removes characters), PASS-1 prompt TEXT FIDELITY rules | tests A, B + punctuation invariance on every block split | PASS | **FIXED** (recognition side relies on the prompt + gate) |
| 6. TEXT_STRUCTURE fidelity gate | text_structure.fidelity_issues, exam_core.check_text_structure / validate_exam | lost section / subsection / commas (PDF layer), OCR commas not trusted, flattened stem | PASS | **FIXED** (commas checked only against PDF text layers) |
| 7-10. Graph source fidelity (post-render) | diagram_engine/graph/fidelity.py (panels in RTL order, per-panel inventory), pipeline gate | real A04 / A01 crops PASS; teacher I–IV per-option PASS; 4 plausible-but-different graphs → MISMATCH (blocked) | PASS | **PARTIALLY FIXED** — option-group panel detection fails on some Bagrut layouts (A10/A02/A03, H3) → LOW_CONFIDENCE → teacher review (never a silent pass) |
| 11. Option binding I–IV | fidelity (option i ↔ source panel i) + pipeline labels the failing option | swapped I↔II → exactly I and II flagged | PASS | **FIXED** (where panels are detected) |
| 12. Readability spacing | question heading / blocks spacing | visual check | — | **FIXED** (modest spacing increase) |
| 13. Figure placement | (5.7.4/5.7.5) figure after its subpart | test_v575_closure DOCX placement | PASS | **FIXED** |
| 14. k-of-n prompt contradiction | QUESTION_SYSTEM_PROMPT rubric rule qualified | prompt assertion | PASS | **FIXED** |

## Evidence
- Student exams generated now: parenthesised point values `(N נקודות)` → 0 in 035571, 0 in the 5-question exam; the
  remaining occurrences of the word are mathematical content (5 / 3 × "נקודות הקיצון/החיתוך/הפיתול"). The
  rubric keeps scoring (5 parenthesised values). k-of-n student wording: "ענו על שלושה מארבעת הסעיפים א–ד." (no 6.67).
- Structure: "(1) … (2) …" arriving on one line is split into two Word paragraphs; soft wraps joined; `w:br` count in student exams: 0.
- Graph fidelity caught a REAL error of the earlier 035571 demonstration: option א of Q1ב lost its left branch (formula values above
  the y-window) — "plausible but different". The option spec was corrected (content, not code); both 035571 files were regenerated.
- Robustness bug found: question objects saved by an older version lacked the new fields and crashed validation → migrated.

## Five-image acceptance (teacher images, regression set)
All 5 reconstructions approvable; graph fidelity: Q2 option group 4/4 PASS per option, Q3 option group LOW_CONFIDENCE (panel detection
fails with the open circle at the origin → teacher review), non-graph families n/a; student exam: no point values, 0 w:br, 5 SVG.

## Regression (exactly as executed)
| Suite | PASS | FAIL | SKIPPED | NOT RUN |
|---|---|---|---|---|
| diagram_engine (incl. 9 graph-fidelity tests) | 460 | 0 | 0 | 0 |
| core + app + legacy + 5.7.5 closure + 5.7.6 presentation (17) + fuzz | 295 | 0 | 0 | 0 |
| acceptance + acceptance_real (035571, teacher 5) + full-document | 103 | 0 | 0 | 0 |
| full-document dev + Mode-B UI flows | 14 | 0 | 0 | 0 |
| PDF → DOCX structural E2E | 1 | 0 | 0 | 0 |
| **Total** | **873** | **0** | **0** | **0** |
compileall PASS, ruff PASS, OOXML validation of the regenerated Word files PASS. Browser E2E: NOT RUN in this release (no UI change
beyond the verification checkbox of 5.7.5). Real Gemini PASS 1/2, 5-run stability, new holdout, Word Desktop/Web: NOT EXECUTED.

## Remaining limitations
- Punctuation loss inside the model's transcription is detected reliably only for PDF sources (image OCR commas are not trusted).
- Option-group panel detection is layout-sensitive; undetected layouts go to teacher review.
- The solutions document (teacher-facing) still uses line breaks inside solution steps.
