"""Shared builders for the diagram-engine unit tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import diagram_engine as de  # noqa: E402


def run(spec: dict, text: str = "", source: bytes | None = None):
    return de.process("fig", json.dumps(spec, ensure_ascii=False), text, source)


def geo(points: dict, segs=("AB", "BC", "CA"), extra=None, conf=0.95, observed=None, labels=None, subtype=None):
    g = {"points": [{"id": k, "x": v[0], "y": v[1]} for k, v in points.items()], "segments": [{"a": s[0], "b": s[1]} for s in segs]}
    g.update(extra or {})
    spec = {"diagram_type": "geometry", "confidence": conf, "geometry": g,
            "labels": labels if labels is not None else [{"text": k, "confidence": 0.99} for k in points],
            "observed": observed if observed is not None else {"num_points": len(points), "point_labels": sorted(points), "num_segments": len(segs)}}
    if subtype:
        spec["subtype"] = subtype
    return spec


def pts(r) -> dict:
    import numpy as np

    g = r.spec.geometry or r.spec.mixed.geometry
    return {p.id: np.array([p.x, p.y]) for p in g.points}
