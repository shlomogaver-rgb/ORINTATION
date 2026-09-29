"""Run the real app.py with Gemini replaced by the offline mock (for E2E tests / demos without an API key)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import mock_gemini  # noqa: E402

mock_gemini.install(disagree=os.environ.get("MOCK_DISAGREE") == "1")
if os.environ.get("MOCK_FREE_TIER") == "1":  # real-time simulation of Google's free tier (5 requests / minute)
    import threading
    import time

    import exam_core
    import free_tier_sim

    class _RealClock:
        lock = threading.Lock()
        monotonic = staticmethod(time.monotonic)
        sleep = staticmethod(time.sleep)

    exam_core.make_client = lambda api_key: free_tier_sim.FreeTierClient(_RealClock(), rpm=int(os.environ.get("MOCK_FREE_TIER_RPM", "5")))
exec(compile((ROOT / "app.py").read_text(encoding="utf-8"), str(ROOT / "app.py"), "exec"))

# Test-only hook: import a whole PDF through the REAL import_full_document() of the running app (MODE B state path).
import streamlit as _st_hook  # noqa: E402
if _st_hook.session_state.get("_test_import_pdf") and not _st_hook.session_state.get("_test_import_done"):
    _st_hook.session_state["_test_import_done"] = True
    import_full_document(Path(_st_hook.session_state["_test_import_pdf"]).read_bytes())  # noqa: F821
    _st_hook.rerun()
if _st_hook.session_state.get("_test_pick_pdf") and not _st_hook.session_state.get("_test_pick_done"):
    _st_hook.session_state["_test_pick_done"] = True
    _path, _sel = _st_hook.session_state["_test_pick_pdf"]
    import_pdf_questions(Path(_path).read_bytes(), list(_sel))  # noqa: F821
    _st_hook.rerun()

# Test-only: dump image-store facts so the browser test can verify pixel-level results.
_state_file = os.environ.get("E2E_STATE_FILE")
if _state_file:
    import json as _json

    import numpy as _np
    import streamlit as _st

    import exam_core as _core

    _out = {"step": _st.session_state.get("step"), "images": {}}
    for _q, _items in _st.session_state.get("image_store", {}).items():
        _rows = []
        for _it in _items:
            _img = _core.png_bytes_to_pil(_it["current"])
            _row = {"id": _it["id"], "size": list(_img.size), "edited": _it["current"] != _it["original"]}
            _orig = _np.asarray(_core.png_bytes_to_pil(_it["original"]))
            if _img.size == (_orig.shape[1], _orig.shape[0]):
                _cur = _np.asarray(_img)
                _row["blot_mean"] = float(_cur[905:955, 305:355].mean())
                _row["blot_mean_orig"] = float(_orig[905:955, 305:355].mean())
                _row["pixels_changed_pct"] = float((_np.abs(_cur.astype(int) - _orig.astype(int)).sum(axis=2) > 30).mean() * 100)
            _row["digest"] = _core.image_digest(_it["current"])
            _row["history"] = len(_it["history"])
            _rows.append(_row)
        _out["images"][str(_q)] = _rows
    _out["sent_for_analysis"] = {str(q["question_number"]): [_core.image_digest(b) for b in q["images"]]
                                 for q in _st.session_state.get("questions_data", [])}
    _exam = _st.session_state.get("processed_exam")
    if _exam is not None:
        _out["diagrams"] = {fid: r.review.status for q in _exam.questions for fid, r in q.diagrams.items()}
        _out["diagram_details"] = {}
        for _q in _exam.questions:
            for _fid, _r in _q.diagrams.items():
                _d = {"edits": len(_r.review.teacher_edits), "valid": _r.validation.ok}
                if _r.spec is not None and _r.spec.geometry is not None:
                    _P = {p.id: (p.x, p.y) for p in _r.spec.geometry.points}
                    _d["points"] = _P
                    if all(k in _P for k in "ABC"):
                        _ba = (_P["A"][0] - _P["B"][0], _P["A"][1] - _P["B"][1])
                        _bc = (_P["C"][0] - _P["B"][0], _P["C"][1] - _P["B"][1])
                        _d["right_angle_B_dot"] = _ba[0] * _bc[0] + _ba[1] * _bc[1]
                if _r.spec is not None and _r.spec.graph is not None and _r.spec.graph.curves:
                    _d["expression"] = _r.spec.graph.curves[0].expression
                _out["diagram_details"][_fid] = _d
    Path(_state_file).write_text(_json.dumps(_out))
    import time as _time
    with open("/tmp/e2e_runs.log", "a") as _fh:
        _fh.write(f"{_time.time():.2f} step={_out['step']} " + " ".join(
            f"q{k}:{[r['edited'] for r in v]}" for k, v in _out["images"].items()) + "\n")
