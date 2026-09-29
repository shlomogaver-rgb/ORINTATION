"""Performance benchmark (mock Gemini): 1-question and 8-question exams. Prints JSON."""
from __future__ import annotations

import json
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import mock_gemini  # noqa: E402

import diagram_engine as de  # noqa: E402
import exam_core as c  # noqa: E402
from diagram_engine import cache  # noqa: E402
from diagram_engine.ocr import engine as ocr_engine  # noqa: E402
from diagram_engine.geometry import solver as solver_mod  # noqa: E402
from test_app import page_image  # noqa: E402
from test_core import meta  # noqa: E402

timers = {"ocr_s": 0.0, "solver_s": 0.0, "render_s": 0.0}


def timed(mod, name, key):
    orig = getattr(mod, name)

    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            timers[key] += time.perf_counter() - t
    setattr(mod, name, wrap)


timed(ocr_engine, "_read_regions", "ocr_s")
timed(ocr_engine, "_table_cells", "ocr_s")
timed(solver_mod, "solve", "solver_s")
import diagram_engine.pipeline as pl  # noqa: E402
timed(pl, "_renderer", "render_s")
_orig_render = pl.render_spec


def run(n: int) -> dict:
    mock_gemini.install()
    calls = {"n": 0}
    orig = c.GeminiService.generate

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)
    c.GeminiService.generate = counting
    for k in timers:
        timers[k] = 0.0
    cache.RENDER.clear()
    cache.OCR.clear()
    qd = [{"question_number": i, "points": round(100 / n, 2), "images": [page_image()]} for i in range(1, n + 1)]
    tracemalloc.start()
    t = time.perf_counter()
    exam, _ = c.run_full_analysis(c.GeminiService("k"), meta(), qd, verify=True)
    analysis = time.perf_counter() - t
    for q in exam.questions:
        for f in q.figures:
            de.approve(q.diagrams[f.figure_id])
    t = time.perf_counter()
    docs = {k: c.create_word_document(exam, meta(), qd, k)[0] for k in ("exam", "solution", "rubric")}
    word = time.perf_counter() - t
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    c.GeminiService.generate = orig
    return {"questions": n, "analysis_s": round(analysis, 2), "word_s": round(word, 2), "api_calls": calls["n"],
            "peak_python_mb": round(peak / 1e6, 1), "ocr_s": round(timers["ocr_s"], 2), "solver_s": round(timers["solver_s"], 3),
            "render_dispatch_s": round(timers["render_s"], 3), "docx_kb": {k: len(v) // 1024 for k, v in docs.items()}}


if __name__ == "__main__":
    print(json.dumps([run(1), run(8)], ensure_ascii=False, indent=1))
