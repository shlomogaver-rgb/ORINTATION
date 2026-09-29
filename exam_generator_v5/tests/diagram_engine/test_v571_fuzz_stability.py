"""Independent robustness + stability checks (not tied to a single feature)."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "acceptance_real"))
sys.path.insert(0, str(ROOT / "tests" / "diagram_engine" / "acceptance"))

import diagram_engine as de  # noqa: E402

TYPES = ["graph", "geometry", "mixed_graph_geometry", "chart", "table", "spatial", "generic", "unknown", "bogus", None]


def _junk(rng, depth=0):
    r = rng.random()
    if depth > 3 or r < 0.3:
        return rng.choice([None, 0, -1, 1e308, float("nan"), "", "A", "x^^2", "__import__('os')", [], {}, True])
    if r < 0.6:
        return [_junk(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    keys = ["points", "segments", "circles", "constraints", "curves", "axes", "rows", "solids", "x", "y", "id", "expression", "a", "b"]
    return {rng.choice(keys): _junk(rng, depth + 1) for _ in range(rng.randint(0, 5))}


@pytest.mark.parametrize("seed", range(60))
def test_fuzzed_ai_specs_never_crash_and_never_export(seed):
    rng = random.Random(seed)
    spec = {"diagram_type": rng.choice(TYPES), "confidence": rng.choice([0.99, 1.5, -1, "x", None]),
            rng.choice(["graph", "geometry", "table", "spatial", "chart", "mixed", "generic"]): _junk(rng)}
    try:
        raw = json.dumps(spec, allow_nan=True)
    except Exception:
        raw = "{"
    rec = de.process("fz", raw, rng.choice(["", "ABC הוא משולש שווה צלעות", "R הוא פרמטר חיובי"]), None)
    assert not de.usable_in_document(rec)                                   # nothing reaches the exam without a teacher
    assert rec.decision.action in ("original", "review", "draft", "high_confidence_preview")


def test_pipeline_is_deterministic_across_runs():
    """Stability of the deterministic part: 3 runs of every real-image case give identical decisions / facts / renders."""
    import harness
    first = None
    for _ in range(3):
        rows = [harness.evaluate(p.name.split("_")[0], save=False) for p in harness.MANIFESTS]
        sig = [(r["id"], r["decision"], r["coverage"], r["result"], tuple(r["critical"])) for r in rows]
        assert first is None or sig == first
        first = sig
