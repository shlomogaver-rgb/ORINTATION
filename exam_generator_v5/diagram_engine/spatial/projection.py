"""Fixed deterministic projections."""
from __future__ import annotations

import math

COS30, SIN30 = math.cos(math.radians(30)), 0.5
OBL_K, OBL_A = 0.5, math.radians(35)


def iso(x: float, y: float, z: float) -> tuple[float, float]:
    """Isometric; viewer in front-left (low x+y is near). Visible faces: top, -x, -y."""
    return (x - y) * COS30, z + (x + y) * SIN30


def oblique(x: float, y: float, z: float) -> tuple[float, float]:
    """Cabinet oblique projection: width x to the right, depth y up-right at 35°, height z up."""
    return x + OBL_K * y * math.cos(OBL_A), z + OBL_K * y * math.sin(OBL_A)
