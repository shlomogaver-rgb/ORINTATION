"""FactGraph: every parser (question text, CV, OCR, vision, math, teacher, acceptance ground truth) adds Facts to ONE graph.

A fact is *independently verified* only when a source OTHER than the vision proposal supports it.
The vision model is one evidence source; it is never the ground truth and never verifies itself."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .constants import INDEPENDENT_SOURCES, SOURCE_RANK

FactSource = Literal["question_text", "diagram_symbol", "deterministic_detection", "derived_math", "ocr_engine", "vision",
                     "teacher", "ground_truth", "visual_appearance"]
CRITICAL_TYPES = {"point", "segment", "point_order", "on_circle", "concyclic", "tangent", "diameter", "radius", "chord",
                  "point_on_line", "point_on_segment", "intersection", "equilateral", "isosceles", "equal_length", "parallel",
                  "perpendicular", "right_angle", "midpoint", "ratio_on_segment", "parallel_to_x_axis", "parallel_to_y_axis",
                  "perpendicular_to_x_axis", "perpendicular_to_y_axis", "collinear", "on_x_axis", "on_y_axis", "coordinate",
                  "dimension", "table_cell", "asymptote", "endpoint", "scatter_point", "voxel_column", "construction_segment",
                  "formula", "region_label", "vertex", "vector", "label", "option", "option_topology", "dimension_value", "rectangle", "square", "parallelogram", "rhombus", "vector_label", "extent", "length_value", "angle_value"}
RANK = dict(SOURCE_RANK, ground_truth=8, ocr_engine=3)
# independence is by PROVIDER + PASS: two facts from the same AI call are ONE source
PROVIDERS = {"question_text": ("Gemini/Text/Pass1+HebrewParser", "pass1"), "vision": ("Gemini/Diagram/Pass2", "pass2"),
             "diagram_symbol": ("Gemini/Diagram/Pass2", "pass2"), "ocr_engine": ("Tesseract/OCR", "pass3"),
             "deterministic_detection": ("OpenCV/CV", "pass3"), "derived_math": ("SymPy/Mathematics+GeometryValidator", "pass3"),
             "teacher": ("Teacher", "review"), "ground_truth": ("Manifest", "test"), "visual_appearance": ("Gemini/Diagram/Pass2", "pass2")}


def canonical(fact_type: str, entities: list[str]) -> str:
    """Order-insensitive key where the relation is symmetric."""
    e = list(entities)
    if fact_type in ("segment", "construction_segment", "collinear", "concyclic", "equilateral", "parallel_pair"):
        e = sorted(e)
    elif fact_type in ("point_order",) and e and e[0] > e[-1]:
        e = list(reversed(e))
    elif fact_type == "equal_length" and len(e) == 4:
        a, b = sorted(e[:2]), sorted(e[2:])
        e = a + b if a <= b else b + a
    elif fact_type in ("parallel", "perpendicular") and len(e) == 4:
        a, b = sorted(e[:2]), sorted(e[2:])
        e = a + b if a <= b else b + a
    elif fact_type in ("diameter", "chord", "point_on_line", "point_on_segment") and len(e) >= 2:
        e = e[:1] + sorted(e[1:]) if fact_type in ("point_on_line", "point_on_segment") else sorted(e)
    return fact_type + "(" + ",".join(e) + ")"


class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    fact_type: str
    entities: list[str] = Field(default_factory=list)
    value: Any = None
    source: FactSource
    confidence: float = 1.0
    critical: bool = True
    required: bool = False           # explicit in the question text -> must be represented in the spec
    ambiguous: bool = False
    alternatives: list[str] = Field(default_factory=list)
    raw_text: str = ""
    provider: str = ""              # e.g. Gemini/Text/Pass1, Gemini/Diagram/Pass2, Tesseract/OCR, OpenCV/Topology, SymPy/Mathematics
    pass_id: str = ""
    criticality: Literal["REQUIRED_FOR_RECONSTRUCTION", "REQUIRED_FOR_SOLUTION", "CONTEXT_ONLY", ""] = ""

    def model_post_init(self, _ctx: Any) -> None:
        if not self.provider:
            self.provider, self.pass_id = PROVIDERS.get(self.source, (self.source, ""))
        if not self.criticality:
            self.criticality = "REQUIRED_FOR_RECONSTRUCTION" if self.required else (
                "REQUIRED_FOR_SOLUTION" if self.source == "question_text" and self.fact_type in CRITICAL_TYPES else "CONTEXT_ONLY")
        if not self.id:
            self.id = hashlib.sha1((self.key + json.dumps(self.value, default=str) + self.source).encode()).hexdigest()[:10]
        if self.fact_type not in CRITICAL_TYPES:
            self.critical = False

    @property
    def key(self) -> str:
        if self.fact_type == "asymptote" and self.value is not None:
            return canonical(self.fact_type, self.entities + [f"{float(self.value):g}"])
        if self.fact_type == "extent":
            return canonical(self.fact_type, sorted(self.entities) + [str(self.value)])
        if self.fact_type == "dimension" and isinstance(self.value, dict):
            return canonical(self.fact_type, [str(self.value.get("dimension_type")), f"{float(self.value.get('value') or 0):g}"])
        return canonical(self.fact_type, self.entities)


class FactGraph(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)

    def add(self, fact: Fact) -> Fact:
        self.facts.append(fact)
        return fact

    def by_key(self) -> dict[str, list[Fact]]:
        out: dict[str, list[Fact]] = {}
        for f in self.facts:
            out.setdefault(f.key, []).append(f)
        return out

    def keys_from(self, *sources: str) -> set[str]:
        return {f.key for f in self.facts if f.source in sources}

    def required(self) -> list[Fact]:
        seen, out = set(), []
        for f in self.facts:
            if f.required and f.key not in seen:
                seen.add(f.key)
                out.append(f)
        return out

    def independently_supported(self, key: str) -> bool:
        return any(f.source in INDEPENDENT_SOURCES and not f.ambiguous for f in self.by_key().get(key, []))

    def reconciliation(self, spec_keys: set[str], missing: list[str], conflicts: list[str]) -> list[dict[str, Any]]:
        """Per-fact status: CONFIRMED / UNCONFIRMED / CONFLICT / MISSING_FROM_SPEC / UNEXPECTED_IN_IMAGE."""
        idx = self.by_key()
        out = []
        for k in sorted(spec_keys):
            facts = idx.get(k, [])
            providers = sorted({f.provider for f in facts})
            indep = any(f.source in INDEPENDENT_SOURCES and not f.ambiguous for f in facts)
            out.append({"fact": k, "status": "CONFIRMED" if indep else "UNCONFIRMED", "providers": providers,
                        "criticality": next((f.criticality for f in facts if f.criticality), "CONTEXT_ONLY")})
        out += [{"fact": m, "status": "MISSING_FROM_SPEC", "providers": [], "criticality": "REQUIRED_FOR_RECONSTRUCTION"} for m in missing]
        out += [{"fact": c, "status": "CONFLICT", "providers": [], "criticality": "REQUIRED_FOR_RECONSTRUCTION"} for c in conflicts]
        return out

    def coverage(self, spec_keys: set[str]) -> dict[str, Any]:
        """Verification coverage of the CRITICAL facts the reconstruction asserts (spec_keys)."""
        idx = self.by_key()
        critical = sorted(k for k in spec_keys if k.split("(")[0] in CRITICAL_TYPES)
        verified = [k for k in critical if any(f.source in INDEPENDENT_SOURCES and not f.ambiguous for f in idx.get(k, []))]
        text_ok = [k for k in critical if any(f.source == "question_text" for f in idx.get(k, []))]
        cv_ok = [k for k in critical if any(f.source in ("deterministic_detection", "derived_math") for f in idx.get(k, []))]
        ai_only = [k for k in critical if k not in verified]
        amb = sorted({f.key for f in self.facts if f.ambiguous})
        req = self.required()
        return {"critical_fact_count": len(critical), "independently_verified_fact_count": len(verified),
                "supported_by_text": len(text_ok), "supported_by_cv": len(cv_ok), "ai_only_fact_count": len(ai_only),
                "ai_only_facts": ai_only, "ambiguous_fact_count": len(amb), "ambiguous_facts": amb,
                "required_fact_count": len(req), "critical_required_fact_count": sum(1 for f in req if f.critical),
                "contradiction_count": len(self.contradictions),
                "verification_coverage": round(len(verified) / len(critical), 3) if critical else 0.0}
