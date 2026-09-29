"""Dependency-aware collection: a test module whose optional dependency is missing is reported as
NOT RUN - dependency unavailable (never counted as PASS, never hidden as FAIL)."""
from __future__ import annotations

import importlib.util
import shutil

DEPENDENCIES = {
    "streamlit": ["test_app.py", "test_mode_b_state.py"],
    "google.genai": ["test_core.py", "test_app.py", "test_mode_b_state.py", "test_full_document_dev.py"],
    "latex2mathml": ["test_core.py"],
    "pymupdf": ["test_full_document.py", "test_full_document_dev.py", "test_full_document_ex_holdout.py", "test_mode_b_state.py"],
}
NOT_RUN: list[str] = []


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


collect_ignore = []
for _mod, _files in DEPENDENCIES.items():
    if not _have(_mod):
        for _f in _files:
            if _f not in collect_ignore:
                collect_ignore.append(_f)
                NOT_RUN.append(f"{_f}: NOT RUN — dependency unavailable ({_mod})")
if not shutil.which("tesseract"):
    NOT_RUN.append("OCR-dependent tests: SKIPPED — tesseract binary unavailable (they skip themselves)")


def pytest_terminal_summary(terminalreporter):
    if NOT_RUN:
        terminalreporter.section("NOT RUN (dependencies)")
        for line in NOT_RUN:
            terminalreporter.write_line(line)
