"""Conservative decision policy (v2).

  I KNOW          -> high_confidence_preview  (still requires teacher approval for export)
  I THINK I KNOW  -> review / draft
  I DO NOT KNOW   -> original
Validation errors or ANY critical mismatch -> original. Nothing is ever exported without a teacher."""
from __future__ import annotations

from dataclasses import dataclass

from .constants import DRAFT_CONFIDENCE, HIGH_CONFIDENCE, IMAGE_ONLY_CAP, QUALITATIVE_CAP, REVIEW_CONFIDENCE
from .schemas import ComparisonResult, Decision, DiagramSpec, ValidationResult


@dataclass(frozen=True)
class Policy:
    high: float = HIGH_CONFIDENCE
    review: float = REVIEW_CONFIDENCE
    draft: float = DRAFT_CONFIDENCE
    image_only_cap: float = IMAGE_ONLY_CAP
    qualitative_cap: float = QUALITATIVE_CAP


DEFAULT_POLICY = Policy()


def parser_confidence(spec: DiagramSpec, solved: dict | None, policy: Policy = DEFAULT_POLICY,
                      detection_confirmed: bool = False) -> float:
    c = max(0.0, min(1.0, spec.confidence))
    t, st = spec.diagram_type, spec.subtype
    if t == "graph" and st == "qualitative_graph":
        return min(c, policy.qualitative_cap)
    if t == "graph" and st == "multi_choice_graphs":
        return min(c, policy.qualitative_cap)
    if t == "graph":
        g = spec.graph
        if g.curves and all(cv.source in ("text", "teacher") for cv in g.curves):
            return max(c, 0.97)
        return min(c, policy.image_only_cap)
    if t == "mixed_graph_geometry":
        curves_ok = spec.mixed.graph.curves and all(cv.source in ("text", "teacher") for cv in spec.mixed.graph.curves)
        base = c if curves_ok else min(c, policy.image_only_cap)
        return min(base, policy.image_only_cap) if solved and solved.get("moved_fraction", 0) > 0.3 else base
    if t == "chart" and st == "scatter_plot":
        return max(c, 0.96) if detection_confirmed else min(c, policy.image_only_cap)
    if t == "chart" and st != "normal_distribution_schematic":
        return max(c, 0.97) if spec.chart.values_source in ("text", "teacher") else min(c, policy.image_only_cap)
    if t in ("generic",):
        return min(c, policy.image_only_cap)
    if t in ("table", "spatial") or st == "normal_distribution_schematic":
        return min(c, policy.qualitative_cap)
    if t == "geometry" and solved is not None and solved.get("moved_fraction", 0) > 0.3:
        return min(c, policy.image_only_cap)
    return c


def decide(parser_conf: float, classifier_conf: float, validation: ValidationResult, comparison: ComparisonResult,
           policy: Policy = DEFAULT_POLICY) -> Decision:
    if not validation.ok:
        return Decision(action="original", confidence=0.0, reasons=["האימות נכשל: " + validation.errors[0]])
    if comparison.critical:
        return Decision(action="original", confidence=0.0, reasons=["אי-התאמה קריטית: " + comparison.critical[0]])
    core = min(comparison.structure_match_score, comparison.topology_score, comparison.constraint_score,
               comparison.label_match_score, comparison.math_score, comparison.layout_score)
    conf = round(min(parser_conf, classifier_conf, core), 3)
    reasons = [f"ביטחון: ניתוח {parser_conf:.2f}, סיווג {classifier_conf:.2f}, השוואה {core:.2f}"]
    if conf >= policy.high and comparison.overall_score >= policy.high:
        action = "high_confidence_preview"
    elif conf >= policy.review:
        action = "review"
    elif conf >= policy.draft:
        action = "draft"
    else:
        action = "original"
        reasons.append("ביטחון נמוך — נעשה שימוש במקור.")
    return Decision(action=action, confidence=conf, reasons=reasons)



def decide_v3(validation: ValidationResult, comparison: ComparisonResult, conf: dict, coverage: dict,
              unsupported: list[str], policy: Policy = DEFAULT_POLICY, unresolved: list[str] | None = None) -> Decision:
    """I KNOW -> high_confidence_preview (still needs the teacher); I THINK I KNOW -> review/draft; I DO NOT KNOW -> original.
    The final confidence can never exceed the independent verification coverage of the critical facts."""
    from .constants import HIGH_COVERAGE

    if unsupported:
        return Decision(action="original", confidence=0.0, reasons=["המשרטט אינו יכול לייצג: " + ", ".join(unsupported[:3])])
    if not validation.ok:
        return Decision(action="original", confidence=0.0, reasons=["האימות נכשל: " + validation.errors[0]])
    if comparison.critical:
        return Decision(action="original", confidence=0.0, reasons=["אי-התאמה קריטית: " + comparison.critical[0]])
    if unresolved:
        return Decision(action="original", confidence=0.0, reasons=["סתירה לא פתורה: " + unresolved[0]])
    final = conf["final_confidence"]
    plaus = min(conf["model_confidence"], conf["deterministic_confidence"], conf["semantic_confidence"])
    cov = coverage.get("verification_coverage", 0.0)
    reasons = [f"ביטחון AI {conf['model_confidence']:.0%} · כיסוי אימות עצמאי {cov:.0%} · דטרמיניסטי {conf['deterministic_confidence']:.0%}"
               f" · סמנטי {conf['semantic_confidence']:.0%} · סופי {final:.0%}"]
    if plaus < policy.draft:
        return Decision(action="original", confidence=final, reasons=reasons + ["ביטחון נמוך — נעשה שימוש במקור."])
    if final >= policy.high and cov >= HIGH_COVERAGE and coverage.get("ai_only_fact_count", 1) == 0 and not coverage.get("contradiction_count") \
            and not coverage.get("ambiguous_fact_count"):
        action = "high_confidence_preview"
    elif plaus >= policy.review:
        action = "review"
        if cov < HIGH_COVERAGE:
            reasons.append("חלק מהעובדות הקריטיות נתמכות רק על-ידי ה-AI — נדרשת בדיקת מורה.")
    else:
        action = "draft"
    return Decision(action=action, confidence=final, reasons=reasons)
