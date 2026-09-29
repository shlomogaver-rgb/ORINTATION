"""Central constants of the diagram engine (versions, policy thresholds, concurrency)."""
from __future__ import annotations

SCHEMA_VERSION = "3.1"
PARSER_VERSION = "diagram-engine/3.1"
RENDERER_VERSION = "renderers/3.1"
VALIDATOR_VERSION = "validator/3.1"
VISION_VERSION = "vision-prompt/5.7"
OCR_ENGINE_VERSION = "ocr/1.0"


class ReconstructionStrictness:
    """EXAM_QUALITY (default): no automatic raster fallback - an unresolved figure blocks export until the teacher approves
    a reconstruction or explicitly chooses the original raster (audited). LEGACY: 5.6 behaviour (source crop)."""
    EXAM_QUALITY = "EXAM_QUALITY"
    LEGACY = "LEGACY"


DEFAULT_STRICTNESS = ReconstructionStrictness.EXAM_QUALITY
SOLVER_TIMEOUT_SIMPLE_S = 1.5
SOLVER_TIMEOUT_COMPLEX_S = 3.0
SOLVER_COMPLEX_CONSTRAINTS = 8

# Confidence policy (decision.py). Nothing is ever exported automatically: HIGH_CONFIDENCE_PREVIEW still needs a teacher.
HIGH_CONFIDENCE = 0.94
REVIEW_CONFIDENCE = 0.85
DRAFT_CONFIDENCE = 0.70
IMAGE_ONLY_CAP = 0.90          # facts read only from pixels can never reach HIGH_CONFIDENCE
QUALITATIVE_CAP = 0.93         # topology sketches (no equation) never reach HIGH_CONFIDENCE

MAX_DIAGRAM_WORKERS = 3
RENDER_CACHE_SIZE = 128

# Reliability hierarchy of evidence sources (higher wins in a conflict).
SOURCE_RANK = {
    "teacher": 7,
    "question_text": 6,
    "diagram_symbol": 5,
    "deterministic_detection": 4,
    "derived_math": 4,
    "ocr": 3,
    "vision": 2,
    "visual_appearance": 1,
}
# Sources allowed to create a geometric RELATION (drawings are often not to scale).
RELATION_SOURCES = {"teacher", "question_text", "diagram_symbol", "deterministic_detection", "derived_math"}

# v3: the final confidence may never exceed independent verification of critical facts
HIGH_COVERAGE = 0.90           # independent verification coverage needed for high_confidence_preview
REVIEW_COVERAGE = 0.50         # below this the reconstruction is at most a draft
DIAGRAM_TYPES = ("graph", "geometry", "mixed_graph_geometry", "chart", "table", "spatial", "generic", "unknown")
INDEPENDENT_SOURCES = {"question_text", "deterministic_detection", "derived_math", "teacher", "ground_truth", "ocr_engine"}

# OCR performance budget (per image; results cached by image hash + OCR config)
OCR_TOTAL_BUDGET_SECONDS = 20.0
OCR_MAX_REGIONS = 80
OCR_MAX_PSM_ATTEMPTS = 2

# numerical safety (tolerance = max(ABS_EPSILON, REL_EPSILON * characteristic_scale))
ABS_EPSILON = 1e-9
REL_EPSILON = 1e-7
MAX_RESIDUAL = 1e-7
MAX_ABS_COORDINATE = 1e6
MAX_CONDITION_NUMBER = 1e12
MAX_SOLVER_ITERATIONS = 60


def tolerance(scale: float) -> float:
    return max(ABS_EPSILON, REL_EPSILON * abs(scale))
