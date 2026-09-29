# AUDIT — 5.7.2
Scope: only the remaining verified gaps of 5.7.1. Every item was reproduced (or found missing) before a fix and has a regression test —
see CHANGELOG_V5_7_2.md (issue / confirmed / fix / test / status) and TEST_REPORT_V5_7_2.md (all required reports).

## Additional bugs found during 5.7.2
1. Perspective hidden-line removal used a constant view direction (wrong for close cameras) — fixed, ray-cast tested.
2. Horizontal bar order was read top→bottom (against the axis) — fixed.
3. "AD מאונך ל-BC" (hyphenated preposition) not parsed — fixed.
4. Graph CV split a curve that runs along an axis — axes are now removed only as thin lines.

## Remaining risks (not hidden)
- Real Gemini PASS 1 / PASS 2 never executed; 80-run stability and holdout NOT done (no credentials, no unseen images).
- Topology and graph pixel evidence are gating only in families where they were measured reliable; elsewhere report-only.
- Letter OCR is weak (confirmations and review flags only). Cylinders are drawn only under the oblique camera.
- Word Desktop / Word Web rendering of svgBlip not verified here.

## Release decision
**NOT READY – BLOCKERS REMAIN**: real-model E2E on the 14 images, five-run real stability, an unseen holdout set and Word QA are required.
