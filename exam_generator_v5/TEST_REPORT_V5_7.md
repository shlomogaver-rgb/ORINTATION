# TEST REPORT — 5.7.0

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| tests/acceptance_real/test_real_acceptance.py (16 real images + 12 adversarial) | 28 | 0 | 0 |
| tests/diagram_engine/test_v57_regressions.py | 45 | 0 | 0 |
| tests/diagram_engine/test_v56_regressions.py | 41 | 0 | 0 |
| tests/diagram_engine/acceptance/test_acceptance.py | 42 | 0 | 0 |
| tests/diagram_engine/test_crop_erase_regression.py | 9 | 0 | 0 |
| tests/diagram_engine/test_decision_export_hallucination.py | 28 | 0 | 0 |
| tests/diagram_engine/test_evidence_classifier.py | 5 | 0 | 0 |
| tests/diagram_engine/test_geometry_v2.py | 15 | 0 | 0 |
| tests/diagram_engine/test_graph_engine.py | 24 | 0 | 0 |
| tests/diagram_engine/test_mixed_charts_spatial.py | 9 | 0 | 0 |
| tests/test_diagram_engine.py | 77 | 0 | 0 |
| tests/test_core.py | 88 | 0 | 0 |
| tests/test_app.py (AppTest) | 6 | 0 | 0 |
| **Total** | **417** | **0** | **0** |

OCR tests run with Tesseract 5.3.4 + heb/eng models (they skip automatically when Tesseract is absent).

Other checks: compileall OK · ruff (E9, F) clean · browser E2E (Playwright, mock Gemini) PASSED: upload, crop, crop→erase, erase
(pixel check), straighten, crop, undo, analysis on the edited bytes, approve Q1, **explicit raster override of Q2 (checkbox required)**,
Word/PDF/ZIP downloads · XSD validation of 3 .docx PASSED · captions verified ("שוחזר ואושר", "סריקה מקורית — אישור חריג").

Performance (mock Gemini, sandbox): 1 question — analysis 2.4 s, 2 API calls, Word ×3 0.3 s, peak Python memory 45 MB;
8 questions — analysis 3.2 s, 16 API calls (analysis + verification per question, no duplicates), Word ×3 1.0 s, peak 49 MB,
OCR 0.23 s. Real Gemini latency NOT MEASURED.

NOT TESTED
- REAL VISION EXTRACTION and the 5-run stability test (no Gemini credentials/network).
- 8-question browser E2E (8-question flow measured at core level only).
- mypy (not installed); Microsoft Word rendering; drag editor interaction; Streamlit Cloud with the new packages.txt.
