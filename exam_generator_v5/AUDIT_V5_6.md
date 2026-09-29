# AUDIT — 5.6.0

## Phase 1–2: V5.5 audit and known failures (reproduced before changing code)
1. **Correlated failure (BLOCKER).** A14 proposal and `observed` both without E → validation PASS, critical 0, comparison 1.00,
   decision "review" (0.93). Text facts about E only produced warnings.
2. **Prompt/schema mismatch.** The prompt still listed `graph|geometry|chart|generic|unknown`; the schema has 8 types.
3. **Parser gaps.** "ABC הוא משולש שווה צלעות", "הנקודה D נמצאת על המשך BC", "AD חותך את המעגל בנקודה E", "AB מקבילה/מאונכת לציר",
   "דרך C העבירו משיק", "האלכסון A'C'", "A'E = 3/4 A'C'", "על אותו מעגל", points with primes — not recognised.
4. **Symbols.** Only `x`; parameters such as R or a were rejected.
5. **Silent degradation.** Pydantic `extra="ignore"` dropped unknown JSON keys (e.g. a construction segment in an unexpected field).
6. **Spatial.** No construction segments (A'C', FE) and no points on diagonals.
7. **Confidence.** One AI-derived number; nothing measured independent verification.
8. **Scatter.** Grid-only mapping; a faint/absent grid meant total failure.
9. **Solver/verification gap (found during 5.6 work).** Text facts recognised by the new parser were not fed to the solver, so a correct
   proposal could be blocked; fixed by `constraints_from_facts`.
10. **Spatial edges (found during 5.6 work).** A default cuboid (no explicit edge list) was treated as having no edges by the checker.

## Changes (phases 3–16) — see CHANGELOG_V5_6.md
FactGraph · required facts from the stem · Hebrew parser V2 · symbol table · SourceSignature V3 · comparison V3 (semantic/numeric)
· confidence V2 · decision v3 · scatter V2 · spatial V2 · dimension semantics · no silent degradation · UI · export unchanged
(approval + valid + no critical; required facts are part of "no critical").

## Remaining limitations (honest)
| Limitation | Safe behaviour | Future |
|---|---|---|
| Real Gemini extraction NOT TESTED (no credentials/network) | — | run the 16 manifests against the live API |
| No independent OCR engine: table numbers, normal-distribution percentages and topology labels are AI-only | always teacher review; a correlated wrong number can only be caught by the teacher (proven by test) | Tesseract/OCR channel |
| Independent CV exists only for scatter dots (and derived math for text formulas) | coverage < 90% → review | line/circle/label detection |
| Text facts are extracted from the stem; facts written only in later sections are informational | — | per-section figures |
| Required-segment check accepts a segment contained in a drawn segment (e.g. MK inside AM) | — | — |
| Drag editor interaction not automated | table editors tested | Playwright drag test |
| Word embeds 300-dpi PNG (SVG in bundle/artifacts) | — | svgBlip |
