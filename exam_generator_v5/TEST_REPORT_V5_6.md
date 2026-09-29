# TEST REPORT — 5.6.0

Environment: Linux sandbox, Python 3.12, Streamlit 1.64.0, LibreOffice. Gemini **mocked** (no network to Google).

| Suite | Passed | Failed |
|---|---|---|
| tests/acceptance_real/test_real_acceptance.py — 16 real images + 12 adversarial/correlated-failure tests | 28 | 0 |
| tests/diagram_engine/test_v56_regressions.py — tests A–J, 23 Hebrew formulations, consistency | 41 | 0 |
| tests/diagram_engine/acceptance/test_acceptance.py (5.5 suite) | 42 | 0 |
| tests/diagram_engine/test_crop_erase_regression.py | 9 | 0 |
| tests/diagram_engine/test_decision_export_hallucination.py | 28 | 0 |
| tests/diagram_engine/test_evidence_classifier.py | 5 | 0 |
| tests/diagram_engine/test_geometry_v2.py | 15 | 0 |
| tests/diagram_engine/test_graph_engine.py | 24 | 0 |
| tests/diagram_engine/test_mixed_charts_spatial.py | 9 | 0 |
| tests/test_diagram_engine.py | 77 | 0 |
| tests/test_core.py | 86 | 0 |
| tests/test_app.py (AppTest) | 6 | 0 |
| **Total `python -m pytest -q tests`** | **370** | **0** |

Other checks: `compileall` OK · browser E2E (Playwright, mock Gemini) PASSED — crop, crop→erase, erase (pixel check), straighten, crop,
undo, edited bytes sent, approval, 7 downloads · Word XSD validation of 3 .docx PASSED · review-panel screenshot inspected.

Regression tests for the V5.5 problems: A (E omitted by proposal AND observation) · B (AB ∥ y-axis, contradiction logged) · C (R>0,
semicircle, domain [−R,R]; undeclared R rejected) · D (a>0) · E (faint grid → ticks; no grid/ticks → original) · F (A'C' and FE drawn;
missing either → blocked) · G (radius 6 stays radius; as diameter → blocked) · H (8 types identical in schema/prompt/classifier/renderer)
· I (AI 0.99, coverage 0.60 → final 0.60, review) · J (unknown JSON feature / declared unsupported → original).

NOT TESTED
- **REAL VISION EXTRACTION** — no Gemini credentials/network; acceptance proposals are hand-written simulations.
- Free-tier browser run for 5.6 (5.5 passed; the image editor code is unchanged).
- Microsoft Word rendering (XSD + LibreOffice only); drag-editor interaction; Streamlit Cloud.
