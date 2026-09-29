# TEST REPORT — 5.7.1

| File | Passed | Failed | Skipped |
|---|---|---|---|
| tests/diagram_engine/test_v571_regressions.py | 68 | 0 | 0 |
| tests/diagram_engine/test_v571_fuzz_stability.py (60 fuzz + determinism) | 61 | 0 | 0 |
| tests/diagram_engine/test_master_pipeline.py | 6 | 0 | 0 |
| tests/diagram_engine/test_v57_regressions.py | 45 | 0 | 0 |
| tests/diagram_engine/test_v56_regressions.py | 41 | 0 | 0 |
| tests/diagram_engine/acceptance/test_acceptance.py | 42 | 0 | 0 |
| other tests/diagram_engine files | 90 | 0 | 0 |
| tests/acceptance_real/test_real_acceptance.py | 28 | 0 | 0 |
| tests/test_core.py | 88 | 0 | 0 |
| tests/test_app.py | 6 | 0 | 0 |
| tests/test_diagram_engine.py | 77 | 0 | 0 |
| **Total** | **552** | **0** | **0** |

Browser E2E (Playwright, mock Gemini): PASSED — upload, crop, crop→erase, erase pixel check, straighten, crop, undo, analysis on edited
bytes, approve, explicit raster override (checkbox), **real mouse drag inside the SVG component** (A moved, right angle kept,
approval invalidated), **LaTeX formula edit**, re-approve, Word/PDF/ZIP downloads. DOCX XSD valid ×3; PDFs contain no raster image
except the school logo. compileall OK; ruff (E9,F,B) clean; mypy on new modules: verification.py 0 errors (others: typing-only notes).

## Pagination report
| Question | Fits a page? | Moved to next page? | Split? | Split location | Result |
|---|---|---|---|---|---|
| 1 short | yes | no | no | — | PASS |
| 2 medium | yes | no | no | — | PASS |
| 3 with graph | yes | yes (whole) | no | — | PASS |
| 4 six subparts | yes | no | no | — | PASS |
| 5 longer than a page | no | fresh page | yes | between subparts only | PASS |

## Vector export report
DOCX: `word/media/vector*.svg` + `a:extLst/asvg:svgBlip` per approved figure (test_v571: approved diagram / svg parts).
PDF (LibreOffice): `pdfimages -list` shows only the logo; figures sharp at 800 % zoom (inspected).
Word Desktop / Word Web: NOT TESTED (not available).

## Localization report
| Output | Profile | Semantic | Rendered | Consistent | Result |
|---|---|---|---|---|---|
| generated solution | ISRAEL_HIGH_SCHOOL | MEAN / STANDARD_DEVIATION | \bar{x} / S | yes (gate) | PASS |
| source text μ/σ | SOURCE_FAITHFUL | MEAN / SD | μ / σ kept | yes | PASS |
| mixed \bar{x} + σ | ISRAEL_HIGH_SCHOOL | — | NOTATION_INCONSISTENCY | blocked | PASS |

## Analytic graph sampling
| Function | Branches | Discontinuities | Strategy | Clipping | Cross-branch | Result |
|---|---|---|---|---|---|---|
| 1/(x−1) | 2 | pole 1 | per-branch adaptive | ±5 % margin | no | PASS |
| (x²+1)/(x²−4) | 3 | poles ±2 | per-branch adaptive | yes | no | PASS |
| ln(x−1) | 1 | domain edge 1 | adaptive | yes | no | PASS |
| tan x | 3 | ±π/2 | adaptive | yes | no | PASS |

## Schematic integrity: A01/A02/A03/A10 topologies — no new extrema, no new roots/sign changes (test); inflections NOT guaranteed.
## Full-resolution pipeline: synthetic 5200×3900 photo → master kept, crop replayed at 3800×2800, ROI from master > 1.9× preview (test).
## OCR / CV scale invariance: real crops at 0.5×/1×/2×/4×: never a wrong number (0.5× partially unread → unconfirmed).
## Bar charts: synthetic vertical/horizontal/values-between-ticks PASS; negative values implemented, not separately tested;
real scanned bar chart NOT TESTED (none in the supplied material).

NOT TESTED: real Gemini (PASS 1/2), 14-image real-vision E2E, five-run stability on the real model, holdout set (no images),
Word Desktop/Web, Streamlit Cloud, reload persistence of the drag state (Streamlit sessions are per page load).
