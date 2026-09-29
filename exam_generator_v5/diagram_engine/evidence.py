"""Evidence layer: every fact knows where it came from. Conflicts are resolved by the reliability hierarchy."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .constants import RELATION_SOURCES, SOURCE_RANK

EvidenceSource = Literal["question_text", "diagram_symbol", "ocr", "vision", "deterministic_detection", "derived_math",
                         "teacher", "visual_appearance"]

# engine-internal source names (schemas.Source) -> evidence source
SOURCE_MAP = {"text": "question_text", "mark": "diagram_symbol", "image": "vision", "teacher": "teacher",
              "computed": "derived_math", "detected": "deterministic_detection", "ocr": "ocr"}


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    source: EvidenceSource
    fact_type: str
    value: Any = None
    confidence: float = 1.0
    bbox: list[float] | None = None
    raw_text: str | None = None
    ambiguous: bool = False
    alternatives: list[str] = Field(default_factory=list)

    def model_post_init(self, _ctx: Any) -> None:
        if not self.id:
            raw = json.dumps([self.source, self.fact_type, self.value], sort_keys=True, default=str)
            self.id = "ev_" + hashlib.sha1(raw.encode()).hexdigest()[:10]

    @property
    def rank(self) -> int:
        return SOURCE_RANK.get(self.source, 0)


def ev(source: str, fact_type: str, value: Any, confidence: float = 1.0, **kw: Any) -> EvidenceItem:
    return EvidenceItem(source=SOURCE_MAP.get(source, source), fact_type=fact_type, value=value, confidence=confidence, **kw)


def may_create_relation(item: EvidenceItem) -> bool:
    """'Not to scale' rule: equal/parallel/perpendicular may only come from text, explicit symbols or deterministic proof."""
    return item.source in RELATION_SOURCES and not item.ambiguous


def resolve(items: list[EvidenceItem]) -> EvidenceItem | None:
    """Pick the most reliable item (rank, then confidence). Ambiguous items never beat unambiguous ones."""
    if not items:
        return None
    return sorted(items, key=lambda e: (not e.ambiguous, e.rank, e.confidence), reverse=True)[0]


def conflicts(items: list[EvidenceItem]) -> list[tuple[EvidenceItem, EvidenceItem]]:
    """Pairs of items about the same fact_type+key with different values (used for warnings)."""
    out = []
    by_key: dict[str, list[EvidenceItem]] = {}
    for it in items:
        key = it.fact_type + ":" + json.dumps(it.value.get("key") if isinstance(it.value, dict) else None, default=str)
        by_key.setdefault(key, []).append(it)
    for group in by_key.values():
        vals = {json.dumps(g.value, sort_keys=True, default=str) for g in group}
        if len(vals) > 1:
            best = resolve(group)
            out += [(best, g) for g in group if g is not best and json.dumps(g.value, sort_keys=True, default=str) != json.dumps(best.value, sort_keys=True, default=str)]
    return out
