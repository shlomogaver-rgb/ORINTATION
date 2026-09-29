"""Canonical FullDocumentModel. One question may span pages, have several subparts and several unrelated visuals."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PageRole(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    INSTRUCTIONS = "INSTRUCTIONS"
    QUESTION = "QUESTION"
    QUESTION_CONTINUATION = "QUESTION_CONTINUATION"
    RESPONSE_WORKSPACE = "RESPONSE_WORKSPACE"
    DRAFT = "DRAFT"
    FORMULA_SHEET = "FORMULA_SHEET"
    DECORATIVE = "DECORATIVE"
    UNKNOWN = "UNKNOWN"


class VisualRole(str, Enum):
    SOURCE_DIAGRAM = "SOURCE_DIAGRAM"
    SOURCE_GRAPH = "SOURCE_GRAPH"
    SOURCE_TABLE = "SOURCE_TABLE"
    SOURCE_CHART = "SOURCE_CHART"
    SOURCE_3D_DIAGRAM = "SOURCE_3D_DIAGRAM"
    RESPONSE_TEMPLATE = "RESPONSE_TEMPLATE"
    ANSWER_BOX = "ANSWER_BOX"
    ANSWER_WORKSPACE = "ANSWER_WORKSPACE"
    GRAPH_PAPER = "GRAPH_PAPER"
    ILLUSTRATION = "ILLUSTRATION"
    ADMINISTRATIVE_GRAPHIC = "ADMINISTRATIVE_GRAPHIC"
    DECORATIVE = "DECORATIVE"
    UNKNOWN = "UNKNOWN"


class VisualObject(BaseModel):
    visual_id: str
    visual_role: VisualRole = VisualRole.UNKNOWN
    page: int
    bbox: list[float]                       # PDF points [x0, y0, x1, y1]
    associated_question: int | None = None
    associated_subpart: str | None = None
    semantic_model: dict = Field(default_factory=dict)
    source_evidence: dict = Field(default_factory=dict)


class Subpart(BaseModel):
    label: str
    page: int
    y: float


class QuestionModel(BaseModel):
    number: int
    pages: list[int] = Field(default_factory=list)          # every page the question occupies (continuations included)
    start: dict = Field(default_factory=dict)               # {"page", "y"}
    end: dict = Field(default_factory=dict)
    subparts: list[Subpart] = Field(default_factory=list)
    visual_objects: list[VisualObject] = Field(default_factory=list)
    response_regions: list[VisualObject] = Field(default_factory=list)
    continuation_metadata: dict = Field(default_factory=dict)


class PageModel(BaseModel):
    index: int
    width: float
    height: float
    role: PageRole = PageRole.UNKNOWN
    role_evidence: list[str] = Field(default_factory=list)
    text_layer_chars: int = 0
    vector_drawings: int = 0


class FullDocumentModel(BaseModel):
    metadata: dict = Field(default_factory=dict)
    pages: list[PageModel] = Field(default_factory=list)
    questions: list[QuestionModel] = Field(default_factory=list)
    declared_question_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
