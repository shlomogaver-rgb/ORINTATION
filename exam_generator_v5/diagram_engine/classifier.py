"""Two-stage classification sanity layer: family (stage 1) + subtype (stage 2). Never invents content."""
from __future__ import annotations

from .graph.formula_parser import functions_from_text
from .schemas import SUBTYPES, DiagramSpec


def default_subtype(spec: DiagramSpec) -> str | None:
    t = spec.diagram_type
    if t == "graph":
        if spec.multi_graph is not None:
            return "multi_choice_graphs"
        if spec.graph_topology is not None and spec.graph is None:
            return "qualitative_graph"
        return "formula_graph"
    if t == "geometry":
        g = spec.geometry
        if g and g.coordinate_axes:
            return "analytic_geometry"
        if g and g.circles:
            return "circle_geometry"
        return "triangle_geometry" if g and len(g.points) <= 3 else "polygon_geometry"
    if t == "mixed_graph_geometry":
        return "coordinate_circle" if spec.mixed and spec.mixed.geometry.circles else "graph_with_geometry"
    if t == "chart":
        if spec.scatter is not None:
            return "scatter_plot"
        if spec.normal is not None:
            return "normal_distribution_schematic"
        return {"bar": "bar_chart", "histogram": "histogram", "pie": "pie_chart", "line": "line_chart"}.get(
            spec.chart.kind if spec.chart else "", "bar_chart")
    if t == "table":
        return "numeric_table"
    if t == "spatial":
        sp = spec.spatial
        if sp and sp.voxel is not None:
            return "voxel_structure"
        kinds = {s.kind for s in (sp.solids if sp else [])}
        if {"cuboid", "cylinder"} <= kinds:
            return "cylinder_in_box"
        if sp and sp.vectors:
            return "vector_box"
        return "cylinder" if kinds == {"cylinder"} else "cuboid"
    if t == "generic":
        return "schematic"
    return None


def classify(spec: DiagramSpec, question_text: str) -> tuple[str, float, list[str]]:
    t, conf = spec.diagram_type, max(0.0, min(1.0, float(spec.confidence)))
    if not spec.subtype or spec.subtype not in SUBTYPES.get(t, []):
        spec.subtype = default_subtype(spec)
    st = spec.subtype
    reasons: list[str] = []
    missing = {
        ("graph", "formula_graph"): spec.graph is None or (not spec.graph.curves and not spec.graph.points and not functions_from_text(question_text)),
        ("graph", "qualitative_graph"): spec.graph_topology is None or not spec.graph_topology.branches,
        ("graph", "multi_choice_graphs"): spec.multi_graph is None or not spec.multi_graph.options,
        ("mixed_graph_geometry", st): spec.mixed is None,
        ("chart", "scatter_plot"): spec.scatter is None,
        ("chart", "normal_distribution_schematic"): spec.normal is None,
        ("table", st): spec.table is None or not spec.table.rows,
        ("spatial", st): spec.spatial is None,
    }
    if missing.get((t, st)):
        return "unknown", 0.0, [f"סווג כ-{t}/{st} אך חסרים הנתונים המתאימים"]
    if t == "geometry" and (spec.geometry is None or len(spec.geometry.points) < 2):
        return "unknown", 0.0, ["סווג כגאומטריה אך זוהו פחות משתי נקודות"]
    if t == "chart" and st not in ("scatter_plot", "normal_distribution_schematic"):
        c = spec.chart
        if c is None or (not c.values and not c.table):
            return "unknown", 0.0, ["סווג כתרשים נתונים אך אין ערכים"]
    if t == "generic" and (spec.generic is None or not (spec.generic.shapes or spec.generic.arrows or spec.generic.polygons)):
        return "unknown", 0.0, ["תרשים כללי ללא צורות"]
    if t == "unknown":
        return "unknown", 0.0, ["סוג התרשים לא זוהה"]
    if t == "graph" and functions_from_text(question_text):
        reasons.append("בשאלה מופיעה פונקציה מפורשת")
    return t, conf, reasons
