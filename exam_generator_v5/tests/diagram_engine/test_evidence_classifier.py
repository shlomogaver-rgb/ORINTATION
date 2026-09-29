from helpers import de, geo, run  # noqa: F401

from diagram_engine.classifier import classify
from diagram_engine.evidence import ev, may_create_relation, resolve
from diagram_engine.schemas import DiagramSpec


def test_evidence_hierarchy_teacher_beats_text_beats_vision():
    a = ev("image", "length", 5, 0.99)
    b = ev("text", "length", 6, 0.9)
    c = ev("teacher", "length", 7, 0.5)
    assert resolve([a, b]).value == 6 and resolve([a, b, c]).value == 7


def test_ambiguous_never_wins_and_vision_cannot_create_relations():
    amb = ev("text", "label", "B", 0.99, ambiguous=True, alternatives=["8"])
    ok = ev("vision", "label", "8", 0.6)
    assert resolve([amb, ok]).value == "8"
    assert not may_create_relation(ev("image", "equal_length", ["AC", "BC"]))
    assert may_create_relation(ev("mark", "equal_length", ["AC", "BC"])) and may_create_relation(ev("text", "equal_length", ["AC", "BC"]))


def test_evidence_recorded_in_spec():
    r = run(geo({"A": (0, 0), "B": (4, 0), "C": (2, 3)}), "נתון AC=BC")
    kinds = {e.source for e in r.spec.evidence}
    assert {"ocr", "question_text"} <= kinds


def test_two_stage_classification_subtypes():
    s = DiagramSpec.model_validate(geo({"O": (0, 0), "A": (1, 0)}, segs=("OA",), extra={"circles": [{"center": "O", "through": "A"}]}))
    t, _, _ = classify(s, "")
    assert t == "geometry" and s.subtype == "circle_geometry"
    s2 = DiagramSpec.model_validate({"diagram_type": "graph", "confidence": 0.9, "multi_graph": {"options": [{"label": "I"}]}})
    classify(s2, "")
    assert s2.subtype == "multi_choice_graphs"
    s3 = DiagramSpec.model_validate({"diagram_type": "spatial", "confidence": 0.9, "spatial": {"voxel": {"columns": [{"x": 0, "y": 0, "height": 1}]}}})
    classify(s3, "")
    assert s3.subtype == "voxel_structure"


def test_missing_family_data_is_unknown():
    for spec in ({"diagram_type": "table", "confidence": 0.9}, {"diagram_type": "chart", "subtype": "scatter_plot", "confidence": 0.9},
                 {"diagram_type": "spatial", "confidence": 0.9}):
        r = run(spec)
        assert r.decision.action == "original"
