"""OCR labels: uncertain readings are never treated as facts."""
from __future__ import annotations

from .schemas import DiagramSpec, OCRLabel

AMBIGUOUS_DISPLAY = "?"


def label_index(spec: DiagramSpec) -> dict[str, OCRLabel]:
    return {l.text: l for l in spec.labels}


def ambiguous_labels(spec: DiagramSpec) -> list[OCRLabel]:
    return [l for l in spec.labels if l.ambiguous]


def is_ambiguous(text: str, spec: DiagramSpec) -> bool:
    lab = label_index(spec).get(text)
    return bool(lab and lab.ambiguous)


def display(text: str | None, spec: DiagramSpec) -> str:
    if not text:
        return ""
    return AMBIGUOUS_DISPLAY if is_ambiguous(text, spec) else text
