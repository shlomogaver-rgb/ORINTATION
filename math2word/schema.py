"""JSON schema for one transcribed page.

The model fills this schema (structured outputs); the DOCX builder consumes it.

Coordinates are normalized to 0..1000 of the page width/height, origin top-left.
"""

SEGMENT = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["text", "math"]},
        "value": {
            "type": "string",
            "description": "Hebrew/plain text for 'text'; LaTeX (no $ delimiters) for 'math'.",
        },
        "bold": {"type": "boolean"},
        "underline": {"type": "boolean"},
    },
    "required": ["type", "value", "bold", "underline"],
    "additionalProperties": False,
}

# One visual line of the source = one array of segments, in LOGICAL (reading) order.
LINE = {"type": "array", "items": SEGMENT}

PARAGRAPH_PROPS = {
    "label": {
        "type": "string",
        "description": "Item label exactly as printed, e.g. '3.', 'א.', '(1)', 'I.'. Empty if none.",
    },
    "level": {
        "type": "integer",
        "description": "Nesting: 0 = question body, 1 = section (א./ב.), 2 = sub-item ((1)/(2)), 3 = deeper (I./II.).",
    },
    "align": {"type": "string", "enum": ["start", "center"]},
    "space_before": {
        "type": "boolean",
        "description": "True when the source shows a clearly larger vertical gap above this paragraph.",
    },
    "lines": {"type": "array", "items": LINE},
}

PARAGRAPH = {
    "type": "object",
    "properties": PARAGRAPH_PROPS,
    "required": list(PARAGRAPH_PROPS),
    "additionalProperties": False,
}

BLOCK = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["heading", "paragraph", "figure", "figure_row", "table", "display_math"],
            "description": (
                "heading/paragraph: text. figure: a figure on its own, centered. "
                "figure_row: paragraphs printed BESIDE a figure (the figure sits in the column given by figure_side). "
                "table: a real table (rows of cells). display_math: a centered stand-alone formula line."
            ),
        },
        **PARAGRAPH_PROPS,
        "figure_id": {"type": "string", "description": "Id from `figures` for figure/figure_row, else ''."},
        "figure_side": {"type": "string", "enum": ["left", "right", "none"]},
        "paragraphs": {
            "type": "array",
            "items": PARAGRAPH,
            "description": "Only for figure_row: the paragraphs that sit beside the figure. Else [].",
        },
        "rows": {
            "type": "array",
            "items": {"type": "array", "items": LINE},
            "description": "Only for table: rows, each row a list of cells (cells listed RIGHT-TO-LEFT). Else [].",
        },
    },
    "required": [
        "kind", *PARAGRAPH_PROPS, "figure_id", "figure_side", "paragraphs", "rows",
    ],
    "additionalProperties": False,
}

FIGURE = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "bbox": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "[x0, y0, x1, y1] normalized 0..1000 (x from left, y from top), tight around the drawing and ALL its labels.",
        },
        "description": {"type": "string", "description": "Short Hebrew description (used as alt text)."},
    },
    "required": ["id", "bbox", "description"],
    "additionalProperties": False,
}

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_type": {
            "type": "string",
            "enum": ["questions", "instructions", "cover", "answer_space", "blank", "formula_sheet", "other"],
        },
        "blocks": {"type": "array", "items": BLOCK},
        "figures": {"type": "array", "items": FIGURE},
    },
    "required": ["page_type", "blocks", "figures"],
    "additionalProperties": False,
}
