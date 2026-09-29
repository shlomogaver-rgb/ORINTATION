"""V5.7.9: cube structures are READ FROM THE DRAWING (analysis-by-synthesis) and proven unique -> automatic insertion;
a hidden or cut structure is never guessed."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import diagram_engine as de  # noqa: E402
from diagram_engine.spatial import voxel_fit as V  # noqa: E402

CUBES = ROOT / "tests" / "acceptance_real" / "cubes_35372"
pytest.importorskip("cv2")


def _spec(rows_front_to_back, ambiguous=True, title=""):
    cols = [{"x": k, "y": r, "height": h} for r, row in enumerate(rows_front_to_back) for k, h in enumerate(row) if h]
    return {"diagram_type": "spatial", "subtype": "voxel", "confidence": 0.6, "labels": [],
            "spatial": {"voxel": {"title": title, "columns": cols, "ambiguous": ambiguous, "arrow": None, "plate": [len(rows_front_to_back[0]), len(rows_front_to_back)]}}}


def _draw(rows):
    return de.render_spec(de.process("s", json.dumps(_spec(rows, ambiguous=False)), "", None).spec)[1]


@pytest.mark.parametrize("rows", [[[1, 0, 1, 0], [2, 0, 1, 0], [2, 3, 2, 1], [3, 3, 3, 3]],
                                  [[1, 1, 1, 1], [2, 2, 2, 2], [3, 3, 3, 3]],
                                  [[1, 0, 2], [1, 2, 2], [2, 3, 3]]])
def test_round_trip_a_fully_visible_structure_is_read_back_exactly(rows):
    r = V.fit(_draw(rows))
    assert r["ok"] and r["heights"] == rows, r


def test_safety_never_accepts_a_wrong_structure():
    """WRONG_ACCEPTED = 0 on random structures: either the exact structure, or a refusal (hidden cubes)."""
    rng = np.random.default_rng(579)
    accepted = 0
    for _ in range(16):
        nr, nk = rng.integers(3, 5, size=2)
        rows = rng.integers(0, 4, size=(nr, nk)).tolist()
        if not any(any(r) for r in rows):
            continue
        r = V.fit(_draw(rows))
        assert not (r["ok"] and r["heights"] != rows), (rows, r["heights"])
        accepted += bool(r["ok"])
    # acceptance of random structures is conservative (occlusions); determined structures are covered by the
    # round-trip and real-questionnaire tests. This test guards SAFETY only.


def test_a_hidden_cube_makes_the_structure_undetermined():
    rows = [[3, 3, 3, 3], [3, 3, 3, 3], [0, 0, 0, 0], [1, 0, 0, 0]]        # the back-left cube sits behind a 3-high wall
    r = V.fit(_draw(rows))
    assert not r["ok"] and r["ambiguous_cells"]


def test_a_cut_drawing_is_refused():
    from PIL import Image
    im = Image.open(io.BytesIO(_draw([[1, 1], [2, 1]])))
    b = io.BytesIO()
    im.crop((int(im.width * 0.25), 0, im.width, im.height)).save(b, format="PNG")
    assert not V.fit(b.getvalue())["ok"]


@pytest.mark.parametrize("name,expected", [("I", [[1, 0, 1, 0], [2, 0, 1, 0], [2, 3, 2, 1], [3, 3, 3, 3]]),
                                           ("II", [[1, 0, 0, 0], [1, 0, 2, 0], [1, 3, 2, 1], [3, 3, 2, 2]]),
                                           ("III", [[2, 0, 1, 0], [2, 0, 1, 0], [3, 1, 1, 1], [3, 3, 3, 3]])])
def test_real_bagrut_structures_are_read_and_inserted_automatically(name, expected):
    src = (CUBES / f"structure_{name}.png").read_bytes()
    wrong_reading = [[0, 1, 1, 1], [2, 1, 2, 2], [2, 3, 3, 2], [3, 3, 3, 2]]      # a wrong model reading as the start
    r = de.process("q5" + name, json.dumps(_spec(wrong_reading, title="מבנה " + name)), "", src)
    assert r.audit["voxel_fit"]["ok"] and r.audit["voxel_fit"]["heights"] == expected
    assert de.auto_approve_if_proven(r) and de.usable_in_document(r)
    assert r.review.approved_by.startswith("system:voxelfit")
