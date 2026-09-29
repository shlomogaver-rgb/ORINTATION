# BASELINE TEST REPORT — V5.6 (before any 5.7 change)

- `python -m compileall` — OK
- `python -m pytest -q tests` — **370 passed, 0 failed, 0 skipped** (75 s)
- Tools found in the environment: Tesseract 5.3.4 (**eng only**; Hebrew model later installed from the official tessdata_fast
  repository), pytesseract 0.3.13, OpenCV 4.13.0. ruff/mypy not installed (ruff installed for the audit; mypy NOT RUN).
- Missing for real E2E: Gemini credentials / network access to Google → REAL VISION NOT TESTABLE here.

Reproduced defects in V5.6 before fixing (each now has a regression test):
1. Approval survives a crop change with the same AI spec (status "approved", usable in document: True). **P0**
2. A figure without image bytes is silently skipped in the Word export (`if data is None: continue`).
3. No independent OCR: a number wrong in both the proposal and its observation passes to teacher review unnoticed.
4. Parallelogram/rhombus: the second parallel constraint was dropped as a "duplicate" (same 4 points).
5. Dimension facts shared one key → coverage over-counted.
6. `2ax`, `3xy`, `2πr` could not be parsed.
7. No upload size / pixel limits; malformed file shows a raw exception.
8. No total-time limit on retries; mutable ContextVar default.
