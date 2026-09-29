"""Formal data model of the diagram engine (DiagramSpec and everything around it).

The renderer only ever receives these validated structures - never free text from the AI.
Numeric ranges are validated by validator.py (not here) so that a bad value yields a clear
Hebrew message instead of a pydantic exception.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .constants import PARSER_VERSION, SCHEMA_VERSION
from .evidence import EvidenceItem

DiagramType = Literal["graph", "geometry", "mixed_graph_geometry", "chart", "table", "spatial", "generic", "unknown"]
Source = Literal["text", "image", "mark", "teacher", "computed", "detected"]
SUBTYPES = {
    "graph": ["formula_graph", "qualitative_graph", "multi_choice_graphs"],
    "geometry": ["triangle_geometry", "circle_geometry", "polygon_geometry", "analytic_geometry"],
    "mixed_graph_geometry": ["coordinate_circle", "graph_with_geometry", "coordinate_construction"],
    "chart": ["scatter_plot", "histogram", "bar_chart", "pie_chart", "line_chart", "normal_distribution_schematic"],
    "table": ["numeric_table", "frequency_table", "two_way_table", "grid_view"],
    "spatial": ["voxel_structure", "cuboid", "cylinder", "cylinder_in_box", "vector_box", "polyhedron"],
    "generic": ["schematic", "flow"],
}


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ------------------------------------------------------------------ OCR
class OCRLabel(_M):
    text: str
    bbox: list[float] = Field(default_factory=list)
    confidence: float = 1.0
    alternatives: list[str] = Field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return self.confidence < 0.8 or bool([a for a in self.alternatives if a and a != self.text])


# ------------------------------------------------------------------ graphs
class GraphAxes(_M):
    x_min: float = -10.0
    x_max: float = 10.0
    y_min: float = -10.0
    y_max: float = 10.0
    x_step: float = 1.0
    y_step: float = 1.0
    x_label: str = "x"
    y_label: str = "y"
    show_grid: bool = True
    show_numbers: bool = True


class CurvePiece(_M):
    expression: str
    x_from: float | None = None
    x_to: float | None = None
    left_closed: bool | None = None   # None = no endpoint marker
    right_closed: bool | None = None


class GraphCurve(_M):
    id: str = "f"
    label: str = ""
    expression: str = ""
    pieces: list[CurvePiece] = Field(default_factory=list)
    source: Source = "image"
    confidence: float = 0.0


class GraphPoint(_M):
    name: str = ""
    x: float
    y: float
    on_curve: str = ""
    kind: Literal["marked", "max", "min", "root", "y_intercept", "inflection"] = "marked"   # a claim that SymPy verifies
    style: Literal["closed", "open"] = "closed"
    label_dx: float = 0.0
    label_dy: float = 0.0
    show_coordinates: bool = False
    source: Source = "image"


class Asymptote(_M):
    kind: Literal["vertical", "horizontal"]
    value: float
    label: str = ""
    source: Source = "image"


class Illustration(_M):
    """Illustration layer of a HYBRID diagram (never changes the mathematics): an icon anchored at a math-space point."""
    kind: Literal["person", "ball", "basket", "building", "road", "pot", "fridge", "icon"] = "icon"
    x: float
    y: float
    size: float = 1.0
    label: str = ""


class GraphSpec(_M):
    axes: GraphAxes = Field(default_factory=GraphAxes)
    illustrations: list[Illustration] = Field(default_factory=list)          # HybridDiagram: illustration layer only
    mode: Literal["ANALYTIC", "SCHEMATIC", "HYBRID", "AUTO"] = "AUTO"   # AUTO -> ANALYTIC with a formula, HYBRID when anchors exist
    parameter_values: dict[str, float] = Field(default_factory=dict)   # layout values for declared parameters (drawing only)
    curves: list[GraphCurve] = Field(default_factory=list)
    points: list[GraphPoint] = Field(default_factory=list)
    asymptotes: list[Asymptote] = Field(default_factory=list)


class Landmark(_M):
    """A point of a qualitative graph. (x, y) are LAYOUT coordinates; `label` is shown verbatim (may be symbolic, e.g. "(6 , a)")."""
    x: float
    y: float
    label: str = ""
    kind: Literal["max", "min", "x_intercept", "y_intercept", "marked", "inflection", "endpoint"] = "marked"
    style: Literal["closed", "open", "none"] = "closed"
    source: Source = "image"


class EndBehavior(_M):
    toward: Literal["asymptote", "plus_inf", "minus_inf", "stop"] = "stop"
    value: float | None = None          # asymptote value (horizontal) or vertical asymptote x


class Branch(_M):
    landmarks: list[int] = Field(default_factory=list)   # indices into GraphTopologySpec.landmarks, left->right
    left: EndBehavior = Field(default_factory=EndBehavior)
    right: EndBehavior = Field(default_factory=EndBehavior)
    x_from: float | None = None
    x_to: float | None = None


class GraphTopologySpec(_M):
    """Qualitative graph: NO equation. Only topology (landmarks, monotonic order, asymptotes, branches, end behaviour)."""
    axes: GraphAxes = Field(default_factory=lambda: GraphAxes(show_numbers=False, show_grid=False))
    function_label: str = ""
    landmarks: list[Landmark] = Field(default_factory=list)
    branches: list[Branch] = Field(default_factory=list)
    asymptotes: list["Asymptote"] = Field(default_factory=list)


class GraphOption(_M):
    label: str
    formula: GraphSpec | None = None
    topology: GraphTopologySpec | None = None


class MultiGraphSpec(_M):
    rtl: bool = True                      # Hebrew exams: option I / א is the RIGHTMOST panel
    options: list[GraphOption] = Field(default_factory=list)
    columns: int = 2


# ------------------------------------------------------------------ geometry
def _pair(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class GPoint(_M):
    id: str
    x: float
    y: float
    label: str | None = None      # None -> use id; "" -> no label
    source: Source = "image"
    fixed: bool = False           # exact coordinate stated in the question (analytic geometry)
    pinned: bool = False          # layout-only hold during a teacher drag (NOT a mathematical fact; cleared after solving)
    hidden: bool = False          # solver helper (e.g. unknown circle centre) - never drawn


class GSegment(_M):
    a: str = Field(validation_alias=_pair("a", "from", "p1", "start"))
    b: str = Field(validation_alias=_pair("b", "to", "p2", "end"))
    style: Literal["solid", "dashed"] = "solid"


class GCircle(_M):
    id: str = ""
    center: str = ""              # may be empty: the solver then uses a hidden centre point
    radius: float | None = None
    through: str | None = None
    through_points: list[str] = Field(default_factory=list)
    style: Literal["solid", "dashed"] = "solid"


class GArc(_M):
    center: str
    start: str
    end: str


class GAngleMark(_M):
    vertex: str
    a: str
    b: str
    kind: Literal["arc", "right"] = "arc"
    value: str = ""
    arcs: int = 1


class GEqualMark(_M):
    segments: list[list[str]]
    ticks: int = 1


class GParallelMark(_M):
    segments: list[list[str]]
    arrows: int = 1


class GEqualAngleMark(_M):
    angles: list[list[str]]       # [[A,B,C], [D,E,F]] = angle ABC = angle DEF
    arcs: int = 1


class GPolygon(_M):
    vertices: list[str]
    fill: bool = False            # shaded region (e.g. feasible region)


class GText(_M):
    text: str
    x: float
    y: float


class GDimension(_M):
    a: str
    b: str
    text: str
    offset: float = 0.08          # fraction of diagram size, perpendicular to AB


class GLengthLabel(_M):
    a: str = Field(validation_alias=_pair("a", "from"))
    b: str = Field(validation_alias=_pair("b", "to"))
    text: str


ConstraintType = Literal[
    "equal_length", "parallel", "perpendicular", "right_angle", "midpoint", "collinear",
    "on_segment", "on_circle", "angle_value", "tangent",
    "equal_angle", "point_on_line", "point_on_ray", "concyclic", "point_order", "intersection", "secant", "diameter",
    "radius", "chord", "equilateral", "isosceles", "rectangle", "square", "parallel_to_x_axis", "parallel_to_y_axis",
    "perpendicular_to_x_axis", "perpendicular_to_y_axis", "inside_circle", "outside_circle", "inside_polygon",
    "outside_polygon", "on_curve", "on_x_axis", "on_y_axis", "fixed", "ratio_on_segment",
    "perpendicular_foot", "centroid", "circumcenter", "incenter",
]
CONSTRAINT_ARITY = {  # number of point ids expected in `points` (None = variable, see validator)
    "equal_length": 4, "parallel": 4, "perpendicular": 4, "right_angle": 3, "midpoint": 3,
    "collinear": 3, "on_segment": 3, "on_circle": 2, "angle_value": 3, "tangent": 3,
    "equal_angle": 6, "point_on_line": 3, "point_on_ray": 3, "concyclic": 4, "point_order": 3, "intersection": 5,
    "secant": 2, "diameter": 2, "radius": 1, "chord": 2, "equilateral": 3, "isosceles": 3, "rectangle": 4, "square": 4,
    "parallel_to_x_axis": 2, "parallel_to_y_axis": 2, "perpendicular_to_x_axis": 2, "perpendicular_to_y_axis": 2,
    "inside_circle": 1, "outside_circle": 1, "inside_polygon": 1, "outside_polygon": 1, "on_curve": 1,
    "on_x_axis": 1, "on_y_axis": 1, "fixed": 1, "ratio_on_segment": 3,
    "perpendicular_foot": 4, "centroid": 4, "circumcenter": 4, "incenter": 4,
}
VARIABLE_ARITY = {"collinear", "concyclic", "point_order", "inside_polygon", "outside_polygon"}  # minimum = CONSTRAINT_ARITY


class GConstraint(_M):
    """Point order: equal_length/parallel/perpendicular [A,B,C,D] = AB,CD; right_angle/angle_value [A,B,C] = angle ABC;
    midpoint [M,A,B]; collinear [A,B,C]; on_segment [P,A,B]; on_circle [P,O]; tangent [T,A,O] (line AT tangent at T)."""
    type: ConstraintType
    points: list[str]
    value: float | None = None
    circle: str = ""              # circle id for circle constraints (diameter, chord, tangent, inside_circle, ...)
    curve: str = ""               # curve id for on_curve (mixed diagrams)
    polygon: list[str] = Field(default_factory=list)
    source: Source = "image"


class GeometrySpec(_M):
    points: list[GPoint] = Field(default_factory=list)
    segments: list[GSegment] = Field(default_factory=list)
    lines: list[GSegment] = Field(default_factory=list)
    rays: list[GSegment] = Field(default_factory=list)
    circles: list[GCircle] = Field(default_factory=list)
    arcs: list[GArc] = Field(default_factory=list)
    angle_marks: list[GAngleMark] = Field(default_factory=list)
    equal_marks: list[GEqualMark] = Field(default_factory=list)
    parallel_marks: list[GParallelMark] = Field(default_factory=list)
    length_labels: list[GLengthLabel] = Field(default_factory=list)
    equal_angle_marks: list[GEqualAngleMark] = Field(default_factory=list)
    polygons: list[GPolygon] = Field(default_factory=list)
    texts: list[GText] = Field(default_factory=list)
    dimensions: list[GDimension] = Field(default_factory=list)
    constraints: list[GConstraint] = Field(default_factory=list)
    not_to_scale: bool = True
    coordinate_axes: bool = False   # analytic geometry: draw x/y axes through the origin


class MixedSpec(_M):
    """Graph + geometry in ONE coordinate system: the curves are drawn first, then the construction."""
    graph: GraphSpec = Field(default_factory=GraphSpec)
    geometry: GeometrySpec = Field(default_factory=GeometrySpec)


# ------------------------------------------------------------------ charts / generic
class ChartSpec(_M):
    kind: Literal["bar", "histogram", "pie", "line", "frequency_table", "two_way_table"] = "bar"
    title: str = ""
    categories: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    bins: list[float] = Field(default_factory=list)
    x_label: str = ""
    y_label: str = ""
    show_percentages: bool = False
    row_labels: list[str] = Field(default_factory=list)
    col_labels: list[str] = Field(default_factory=list)
    table: list[list[str]] = Field(default_factory=list)
    values_source: Source = "image"


class ScatterSpec(_M):
    axes: GraphAxes = Field(default_factory=GraphAxes)
    points: list[list[float]] = Field(default_factory=list)
    regression: list[float] | None = None      # [slope, intercept] only if drawn in the source
    title: str = ""
    points_source: Source = "image"


class NormalDistSpec(_M):
    """Schematic normal curve: k+1 regions separated by k vertical lines, a label per region, answer boxes."""
    percentages: list[str] = Field(default_factory=list)   # one per region, verbatim ("0.5%", "19%")
    boxed_regions: list[int] = Field(default_factory=list)  # regions whose label is drawn in a callout (tails)
    answer_boxes: int = 0
    axis_label: str = "x"
    box_labels: list[str] = Field(default_factory=list)


class TableCell(_M):
    text: str = ""
    value: float | None = None
    confidence: float = 1.0
    fill: bool = False


class TableSpec(_M):
    rows: list[list[TableCell]] = Field(default_factory=list)
    header_rows: int = 1
    header_columns: int = 0
    merged: list[list[int]] = Field(default_factory=list)   # [r0, c0, r1, c1]
    rtl: bool = True
    title: str = ""
    cells_source: Source = "image"


class GShape(_M):
    kind: Literal["rect", "ellipse"] = "rect"
    x: float
    y: float
    w: float
    h: float
    text: str = ""


class GArrow(_M):
    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""


class GPolyShape(_M):
    id: str = ""
    points: list[list[float]]
    text: str = ""


class GDimLine(_M):
    x1: float
    y1: float
    x2: float
    y2: float
    text: str
    attach: list[str] = Field(default_factory=list)   # labels of the endpoints it measures, e.g. ["A", "G"]


class GLabel(_M):
    text: str
    x: float
    y: float


class GenericSpec(_M):
    """y grows DOWN (page coordinates)."""
    width: float = 100.0
    height: float = 60.0
    shapes: list[GShape] = Field(default_factory=list)
    polygons: list[GPolyShape] = Field(default_factory=list)
    arrows: list[GArrow] = Field(default_factory=list)
    lines: list[GArrow] = Field(default_factory=list)
    dimensions: list[GDimLine] = Field(default_factory=list)
    labels: list[GLabel] = Field(default_factory=list)


# ------------------------------------------------------------------ spatial / 3D
class VoxelColumn(_M):
    x: int
    y: int
    height: int


class VoxelSpec(_M):
    title: str = ""                         # the structure's name shown above it in the source ("מבנה II")
    columns: list[VoxelColumn] = Field(default_factory=list)
    ambiguous: bool = False                   # hidden cubes cannot be determined from the image
    arrow: list[float] | None = None          # [x, y, dx, dy] on the base plate (viewing direction)
    plate: list[int] | None = None            # [nx, ny] base plate size


class Solid(_M):
    id: str
    kind: Literal["cuboid", "cylinder", "polyhedron"]
    dims: dict[str, float] = Field(default_factory=dict)          # cuboid: width/depth/height; cylinder: radius/height
    origin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    vertices: dict[str, list[float]] = Field(default_factory=dict)  # polyhedron / labelled box vertices (x, y, z)
    edges: list[list[str]] = Field(default_factory=list)
    hidden_edges: list[list[str]] = Field(default_factory=list)
    face_text: str = ""


class SpatialDimension(_M):
    """object + dimension_type + value + unit: '6 cm' alone is never enough (radius != diameter)."""
    solid: str = Field(validation_alias=AliasChoices("solid", "object"))
    measure: Literal["width", "depth", "height", "radius", "diameter", "edge", "length", "side", "distance"] = Field(
        validation_alias=AliasChoices("measure", "dimension_type"))
    text: str = ""
    value: float | None = None
    unit: str = ""
    edge: list[str] = Field(default_factory=list)


class SpatialRelation(_M):
    type: Literal["inside", "touching_base", "touching_side", "separate"]
    a: str
    b: str


class SpatialVector(_M):
    a: str = Field(validation_alias=AliasChoices("a", "from"))
    b: str = Field(validation_alias=AliasChoices("b", "to"))
    label: str


class PointOnEdge(_M):
    id: str
    a: str
    b: str
    ratio: float      # position from a (0..1)
    label: str | None = None


class SpatialSegment(_M):
    a: str = Field(validation_alias=AliasChoices("a", "from"))
    b: str = Field(validation_alias=AliasChoices("b", "to"))
    style: Literal["solid", "dashed"] = "solid"


class SpatialAnnotation(_M):
    text: str
    at: str = ""          # a vertex / point id


class SpatialSpec(_M):
    voxel: VoxelSpec | None = None
    camera: Literal["", "OBLIQUE_RIGHT", "OBLIQUE_LEFT", "ISOMETRIC", "ORTHO_FRONT"] = ""   # preferred view (checked vs dashed edges)
    construction_segments: list[SpatialSegment] = Field(default_factory=list)
    construction_lines: list[SpatialSegment] = Field(default_factory=list)
    construction_rays: list[SpatialSegment] = Field(default_factory=list)
    points_on_segments: list["PointOnEdge"] = Field(default_factory=list)
    points_on_diagonals: list["PointOnEdge"] = Field(default_factory=list)
    annotations: list[SpatialAnnotation] = Field(default_factory=list)
    solids: list[Solid] = Field(default_factory=list)
    dimensions: list[SpatialDimension] = Field(default_factory=list)
    relations: list[SpatialRelation] = Field(default_factory=list)
    vectors: list[SpatialVector] = Field(default_factory=list)
    points_on_edges: list[PointOnEdge] = Field(default_factory=list)

    def model_post_init(self, _ctx) -> None:
        # one list for the engine: points on edges, on segments and on diagonals are the same kind of fact
        for extra in (self.points_on_segments, self.points_on_diagonals):
            for p in extra:
                if not any(q.id == p.id for q in self.points_on_edges):
                    self.points_on_edges.append(p)
        self.points_on_segments, self.points_on_diagonals = [], []


# ------------------------------------------------------------------ what the vision model observed (evidence)
class Observed(_M):
    """Counts / facts reported about the SOURCE image. Used only for comparison (never rendered)."""
    point_labels: list[str] | None = None
    num_points: int | None = None
    num_segments: int | None = None
    num_circles: int | None = None
    num_curves: int | None = None
    right_angle_marks: int | None = None
    equal_mark_groups: int | None = None
    parallel_mark_groups: int | None = None
    angle_values: list[str] | None = None
    x_intercepts: list[float] | None = None
    y_intercept: float | None = None
    open_endpoints: list[list[float]] | None = None
    closed_endpoints: list[list[float]] | None = None
    num_bars: int | None = None
    has_asymptote_lines: bool | None = None
    # v2 source signature facts
    num_branches: int | None = None
    num_maxima: int | None = None
    num_minima: int | None = None
    vertical_asymptotes: list[float] | None = None
    horizontal_asymptotes: list[float] | None = None
    num_options: int | None = None
    option_labels: list[str] | None = None
    num_scatter_points: int | None = None
    table_shape: list[int] | None = None
    table_cells: list[list[str]] | None = None
    num_regions: int | None = None
    region_labels: list[str] | None = None
    num_answer_boxes: int | None = None
    visible_cubes: int | None = None
    num_solids: int | None = None
    dimension_texts: list[str] | None = None
    num_shapes: int | None = None
    shape_labels: list[str] | None = None
    point_orders: list[list[str]] | None = None
    tangent_points: list[str] | None = None


# ---------------------------------------------------------------- typed mathematical semantics (PASS 2 may return these)
class ComplexItem(_M):
    label: str
    value: str = ""                    # rectangular literal, e.g. "3+4i"
    polar: str = ""                    # polar form, symbolic allowed: "r(cos(theta)+i sin(theta))"
    r: float | None = None             # or polar form r(cos t + i sin t)
    theta_deg: float | None = None


class ComplexRoots(_M):
    n: int
    w: str                             # z^n = w


class ComplexPlaneSemantics(_M):
    numbers: list[ComplexItem] = Field(default_factory=list)
    roots_of: ComplexRoots | None = None
    polygon: bool = True


class ConicSemantics(_M):
    equation: str                      # canonical equation in x, y, e.g. "x^2/25+y^2/9=1"
    claimed_kind: Literal["", "circle", "ellipse", "parabola", "hyperbola"] = ""
    label: str = ""


class Point3(_M):
    id: str
    x: float
    y: float
    z: float = 0.0


class VectorDef(_M):
    name: str
    from_point: str
    to_point: str


class SemanticClaim(_M):
    kind: Literal["parallel", "perpendicular", "ratio", "combination", "on_plane", "angle_lines", "angle_line_plane",
                  "angle_planes", "intersection", "distance_point_plane", "equal"]
    refs: list[str] = Field(default_factory=list)
    value: float | None = None
    coeffs: list[float] = Field(default_factory=list)


class Line3(_M):
    id: str
    through: list[str] = Field(default_factory=list)     # two point ids


class Plane3(_M):
    id: str
    through: list[str] = Field(default_factory=list)     # three point ids
    equation: str = ""                                   # or "a*x+b*y+c*z=d"


class VectorSemantics(_M):
    points: list[Point3] = Field(default_factory=list)
    vectors: list[VectorDef] = Field(default_factory=list)
    claims: list[SemanticClaim] = Field(default_factory=list)


class Space3DSemantics(_M):
    points: list[Point3] = Field(default_factory=list)
    lines: list[Line3] = Field(default_factory=list)
    planes: list[Plane3] = Field(default_factory=list)
    claims: list[SemanticClaim] = Field(default_factory=list)


class FunctionRelationSpec(_M):
    child: str                         # curve id
    relation: Literal["DERIVATIVE_OF", "ANTIDERIVATIVE_OF", "NEGATIVE_OF", "VERTICAL_SCALE_OF", "TRANSLATION_OF",
                      "MULTIPLICATIVE_TRANSFORM"]
    parent: str
    k: float | None = None
    dx: float | None = None
    dy: float | None = None


class FormulaItem(_M):
    id: str
    latex: str


class SemanticSpec(_M):
    complex_plane: ComplexPlaneSemantics | None = None
    conics: list[ConicSemantics] = Field(default_factory=list)
    vectors: VectorSemantics | None = None
    space3d: Space3DSemantics | None = None
    function_relations: list[FunctionRelationSpec] = Field(default_factory=list)
    formulas: list[FormulaItem] = Field(default_factory=list)


class DiagramSpec(_M):
    schema_version: str = SCHEMA_VERSION
    diagram_type: DiagramType = "unknown"
    subtype: str | None = None
    confidence: float = 0.0                 # vision-model confidence (classifier)
    source_image_hash: str = ""
    parser_version: str = PARSER_VERSION
    graph: GraphSpec | None = None
    graph_topology: GraphTopologySpec | None = None
    multi_graph: MultiGraphSpec | None = None
    geometry: GeometrySpec | None = None
    mixed: MixedSpec | None = None
    chart: ChartSpec | None = None
    scatter: ScatterSpec | None = None
    normal: NormalDistSpec | None = None
    table: TableSpec | None = None
    generic: GenericSpec | None = None
    spatial: SpatialSpec | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    symbols: dict[str, dict] = Field(default_factory=dict)          # declared parameters (filled from the QUESTION TEXT only)
    semantics: SemanticSpec | None = None                           # typed mathematical semantics (engines run in the pipeline)
    unsupported_features: list[str] = Field(default_factory=list)   # anything the engine can not represent -> original
    labels: list[OCRLabel] = Field(default_factory=list)
    observed: Observed = Field(default_factory=Observed)
    warnings: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ results
class ValidationResult(_M):
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    info: dict[str, Any] = Field(default_factory=dict)


class ComparisonResult(_M):
    semantic_score: float = 0.0
    numeric_score: float = 0.0
    structure_match_score: float = 0.0
    topology_score: float = 0.0
    constraint_score: float = 0.0
    label_match_score: float = 0.0
    math_score: float = 0.0
    layout_score: float = 0.0
    visual_match_score: float = 0.0
    overall_score: float = 0.0
    critical: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Decision(_M):
    action: Literal["high_confidence_preview", "review", "draft", "original"] = "original"
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class TeacherEdit(_M):
    at: str
    summary: str
    spec_hash_before: str = ""
    spec_hash_after: str = ""


class ReviewState(_M):
    status: Literal["pending", "approved", "rejected", "original", "raster_override"] = "pending"
    approved_by: Literal["", "teacher"] = ""
    spec_hash: str = ""          # approval is bound to this exact spec
    fingerprint: str = ""        # ... AND to the exact source, crop, edits, required facts and engine versions
    override_reason: str = ""
    teacher_edits: list[TeacherEdit] = Field(default_factory=list)
    updated_at: str = ""


class DiagramRecord(_M):
    figure_id: str
    input_key: str = ""                 # image digest + bbox + spec + versions (set by the caller)
    input_hashes: dict[str, str] = Field(default_factory=dict)   # vision / ocr / diagram / analysis / edited image hashes
    spec: DiagramSpec | None = None
    raw_spec_json: str = ""
    classifier_type: DiagramType = "unknown"
    classifier_subtype: str = ""
    classifier_confidence: float = 0.0
    parser_confidence: float = 0.0
    validation: ValidationResult = Field(default_factory=ValidationResult)
    comparison: ComparisonResult = Field(default_factory=ComparisonResult)
    decision: Decision = Field(default_factory=Decision)
    review: ReviewState = Field(default_factory=ReviewState)
    manifest: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)      # model / coverage / deterministic / semantic / final
    coverage: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict] = Field(default_factory=list)                 # FactGraph (serialised) for audit / UI
    missing_required: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    reconciliation: list[dict] = Field(default_factory=list)       # PASS 3 per-fact status
    render_error: str = ""
    teacher_message: str = ""
    audit: dict[str, Any] = Field(default_factory=dict)
GraphTopologySpec.model_rebuild()
SpatialSpec.model_rebuild()
