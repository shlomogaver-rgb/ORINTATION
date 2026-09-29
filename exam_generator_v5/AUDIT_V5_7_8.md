# DELIVERY REPORT — 5.7.8 (source line layout + findings of the first unseen full-PDF conversion)

Status: **PRE-RC** (real Gemini E2E, 5-run stability, new holdout, Word Desktop/Web QA not executed).

## A. Source line layout (teacher request: "every line starts and ends as in the source")
| Part | Change |
|---|---|
| document/reconstruct.region_lines | VISUAL source lines of a PDF question region: words grouped by baseline, ordered right→left; figure boxes and page margins excluded (the raw text layer split formulas into 178 fragments for one question) |
| text_structure.transfer_line_breaks | Hebrew words of the reconstruction aligned with the source lines (difflib; reversed RTL layers handled); a break goes where the source broke the line, before a formula when the source line starts with one; only whitespace changes; low coverage → unchanged |
| exam_core.apply_source_line_breaks | runs after PASS 1 (PDF: visual lines; images: OCR lines) |
| text_structure.blocks(preserve_lines) | source line breaks stay INSIDE the paragraph (w:br); paragraphs, subsections and display formulas stay separate w:p |
| exam_core (sections / subsections) | hanging labels: continuation lines align under the text, not under "א." / "(1)" |
| exam_core.fit_scale_for_source_lines + margins | every forced line is measured with the real font metrics; the column is widened to the source column (~18 cm) and the font reduced (never below 10 pt) so Word does not re-wrap a source line and leave an orphan word |
| QUESTION_SYSTEM_PROMPT | PASS 1 keeps every source line break |
| app.py | step-1 option "שמירת שבירות השורה של המקור" (default ON) |
Verified on the unseen 35571 PDF: subpart 1ב — 11/11 lines identical to the source; 1ג and the Q4 stem identical.

## B. Findings of the first unseen full-PDF conversion (35571, summer 2024) — fixed generally
Blind structure detection: 8/8 questions, continuation, 7/7 visuals bound (subparts ב/ג/ד), I–IV group bound to ד.
Fixed: roman claim labels read as points + facts leaking between subparts (required facts per figure); "AD is a diameter" with the
circle not drawn (Thales); tight-crop axes taken as a frame (graph fidelity found 0 graphs); dashed asymptotes as axes (solidity);
subpart-only entities required in a stem figure; math-list / coordinate commas counted as punctuation; short entity formulas
false-flagged; LaTeX thousands separator 44{,}307; choice rule repeated when the stem states it.

## C. Tests (exactly as executed)
| Suite | PASS | FAIL | SKIPPED | NOT RUN |
|---|---|---|---|---|
| diagram_engine (excl. fuzz/acceptance) | 460 | 0 | 0 | 0 |
| core + app + legacy + 5.7.5–5.7.8 regressions + fuzz | 352 | 0 | 0 | 0 |
| acceptance + acceptance_real + full-document | 103 | 0 | 0 | 0 |
| full-document dev + Mode-B UI flows | 14 | 0 | 0 | 0 |
| PDF → DOCX structural E2E | 1 | 0 | 0 | 0 |
| **Total** | **930** | **0** | **0** | **0** |
Browser E2E PASS; compileall (SyntaxWarning = error) PASS; ruff PASS; OOXML validation of the generated exam PASS.

## D. Open (not fixed in this release)
- Q7ד of 35571: graph-fidelity still false-blocks option I on this source (panel binding) → the I–IV figure is not in the Word file.
- Figures are placed below their text; the source places them beside the text (side-by-side layout not implemented).
- Coordinate labels of graph points (show_coordinates) are not rendered in the 1ג graph; projection lines to the axes (1ב) and
  unlabeled points (Q8 centre) are not in the schema.
- Exam-level choice rules ("at least one question from each chapter") are not modelled.
- Word Desktop / Word Web rendering not verified (LibreOffice PDF + OOXML schema only).
