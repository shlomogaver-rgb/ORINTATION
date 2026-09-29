"""3D semantic scene: camera + projection (ISOMETRIC / ORTHOGRAPHIC / OBLIQUE / PERSPECTIVE), convex-hull faces,
hidden-line removal with PARTIAL occlusion, and a collision-aware label placer. Vertices (x,y,z) are the source of
truth; nothing about visibility is hard-coded."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

PROJECTION_VERSION = "projection/1.0"


from .projection import OBL_A as _OBL_A, OBL_K as _OBL_K


@dataclass(frozen=True)
class Camera:
    mode: str = "OBLIQUE"                         # ISOMETRIC | ORTHOGRAPHIC | OBLIQUE | PERSPECTIVE
    position: tuple = (6.0, -10.0, 7.0)
    target: tuple = (0.0, 0.0, 0.0)
    up: tuple = (0.0, 0.0, 1.0)
    fov_deg: float = 35.0
    near: float = 0.1
    far: float = 1000.0
    oblique_k: float = _OBL_K                     # identical to projection.oblique (one definition)
    oblique_deg: float = math.degrees(_OBL_A)

    def view_dir(self) -> np.ndarray:
        if self.mode == "OBLIQUE":               # receding axis y goes up-right: viewer looks from -y, slightly right/up
            a = math.radians(self.oblique_deg)
            d = np.array([-self.oblique_k * math.cos(a), 1.0, -self.oblique_k * math.sin(a)])
            return d / np.linalg.norm(d)
        d = np.array(self.target, float) - np.array(self.position, float)
        return d / np.linalg.norm(d)

    def project(self, p) -> tuple[float, float, float]:
        """-> (u, v, depth). Larger depth = farther from the viewer."""
        p = np.asarray(p, float)
        if self.mode == "OBLIQUE":
            a = math.radians(self.oblique_deg)
            return (p[0] + self.oblique_k * p[1] * math.cos(a), p[2] + self.oblique_k * p[1] * math.sin(a),
                    float(p @ self.view_dir()))
        f = self.view_dir()
        r = np.cross(f, np.array(self.up, float))
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        rel = p - np.array(self.position, float)
        x, y, z = float(rel @ r), float(rel @ u), float(rel @ f)
        if self.mode == "PERSPECTIVE":
            s = 1.0 / (math.tan(math.radians(self.fov_deg) / 2) * max(z, self.near))
            return x * s, y * s, z
        return x, y, z


def isometric() -> Camera:
    return Camera(mode="ISOMETRIC", position=(10.0, -10.0, 10.0))


PRESETS = {"OBLIQUE_RIGHT": Camera(), "OBLIQUE_LEFT": Camera(oblique_deg=145.0), "ISOMETRIC": isometric(),
           "ORTHO_FRONT": Camera(mode="ORTHOGRAPHIC", position=(0.3, -10.0, 1.0))}


def hull_faces(verts: dict[str, np.ndarray]) -> list[tuple[list[str], np.ndarray]]:
    """Faces of a convex polyhedron (small n): planes through vertex triples with all vertices on one side;
    coplanar triples are merged. Returns [(vertex ids, outward normal)]."""
    ids = list(verts)
    P = np.array([verts[k] for k in ids], float)
    c = P.mean(axis=0)
    faces: dict[tuple, list] = {}
    for i, j, k in itertools.combinations(range(len(ids)), 3):
        n = np.cross(P[j] - P[i], P[k] - P[i])
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            continue
        n /= nn
        d = P @ n - P[i] @ n
        scale = max(1e-9, np.ptp(P))
        if np.all(d <= 1e-7 * scale) or np.all(d >= -1e-7 * scale):
            if (c - P[i]) @ n > 0:
                n = -n
            on = tuple(sorted(ids[m] for m in range(len(ids)) if abs((P[m] - P[i]) @ n) < 1e-7 * scale))
            faces.setdefault(on, n)
    return [(list(k), n) for k, n in faces.items()]


def _edges_of(face_ids, verts) -> set:
    return {frozenset(e) for e in itertools.combinations(face_ids, 2)}


def edge_visibility(verts: dict[str, np.ndarray], edges: list[list[str]], cam: Camera,
                    occluders: list[list[tuple[list[str], np.ndarray, dict]]] | None = None, samples: int = 24) -> dict:
    """{edge: [(t0, t1, 'VISIBLE'|'HIDDEN'), ...]} - self-occlusion by back-faces + PARTIAL occlusion by other solids."""
    faces = hull_faces(verts)
    front = [f for f, n in faces if _faces_viewer(cam, n, np.mean([verts[k] for k in f], axis=0))]
    out = {}
    for e in edges:
        key = frozenset(e)
        on_front = any(set(e) <= set(f) for f in front)
        state = "VISIBLE" if on_front else "HIDDEN"
        a, b = np.asarray(verts[e[0]], float), np.asarray(verts[e[1]], float)
        states = []
        for t in np.linspace(0, 1, samples + 1):
            p = a + t * (b - a)
            s = state
            if s == "VISIBLE" and occluders:
                for solid_faces in occluders:
                    if _occluded(p, solid_faces, cam):
                        s = "HIDDEN"
                        break
            states.append((t, s))
        intervals, start = [], 0
        for i in range(1, len(states) + 1):
            if i == len(states) or states[i][1] != states[start][1]:
                intervals.append((round(states[start][0], 4), round(states[min(i, len(states) - 1)][0], 4), states[start][1]))
                start = i
        out[key] = intervals
    return out


def _faces_viewer(cam: Camera, normal, centre) -> bool:
    """Back-face test with the SAME camera: per-face view vector for PERSPECTIVE, constant direction otherwise."""
    if cam.mode == "PERSPECTIVE":
        v = np.asarray(centre, float) - np.asarray(cam.position, float)
    else:
        v = cam.view_dir()
    return float(np.asarray(normal) @ v) < 0


def _occluded(p, solid_faces, cam: Camera) -> bool:
    """Point p hidden behind a FRONT face of another convex solid (projected point-in-polygon + depth)."""
    pu, pv, pd = cam.project(p)
    for ids, n, verts in solid_faces:
        if not _faces_viewer(cam, n, np.mean([verts[k] for k in ids], axis=0)):
            continue
        poly = [cam.project(verts[k]) for k in ids]
        c = np.mean([[q[0], q[1]] for q in poly], axis=0)
        poly = sorted(poly, key=lambda q: math.atan2(q[1] - c[1], q[0] - c[0]))
        inside = True
        sign = 0
        for (x1, y1, _), (x2, y2, _) in zip(poly, poly[1:] + poly[:1]):
            cr = (x2 - x1) * (pv - y1) - (y2 - y1) * (pu - x1)
            if abs(cr) < 1e-12:
                continue
            if sign == 0:
                sign = 1 if cr > 0 else -1
            elif (cr > 0) != (sign > 0):
                inside = False
                break
        if inside and min(q[2] for q in poly) < pd - 1e-9:
            return True
    return False


def choose_camera(verts, edges, source_hidden: list[list[str]]) -> tuple[str | None, Camera | None]:
    """The camera whose COMPUTED hidden edges equal the edges drawn dashed in the source (None -> conflict)."""
    want = {frozenset(e) for e in source_hidden}
    for name, cam in PRESETS.items():
        vis = edge_visibility(verts, edges, cam)
        hidden = {k for k, iv in vis.items() if all(s == "HIDDEN" for *_, s in iv)}
        if hidden == want:
            return name, cam
    return None, None


@dataclass
class LabelPlacer:
    """Collision-aware placement in NORMALIZED units (fraction of the drawing size); no fixed pixel offsets."""
    size: float
    segments: list = field(default_factory=list)
    placed: list = field(default_factory=list)

    def place(self, anchor, outward) -> np.ndarray:
        anchor, outward = np.asarray(anchor, float), np.asarray(outward, float)
        n = np.linalg.norm(outward)
        base = outward / n if n > 1e-12 else np.array([0.0, 1.0])
        best, best_cost = None, math.inf
        for r in (0.05, 0.075, 0.1):
            for da in (0, 25, -25, 50, -50, 90, -90, 180):
                a = math.radians(da)
                d = np.array([base[0] * math.cos(a) - base[1] * math.sin(a), base[0] * math.sin(a) + base[1] * math.cos(a)])
                cand = anchor + d * r * self.size
                cost = r + 0.002 * abs(da)
                for p, q in self.segments:
                    dist = _dist_seg(cand, np.asarray(p, float), np.asarray(q, float))
                    if dist < 0.03 * self.size:
                        cost += 5
                for other in self.placed:
                    if np.linalg.norm(cand - other) < 0.05 * self.size:
                        cost += 10
                if cost < best_cost:
                    best, best_cost = cand, cost
        self.placed.append(best)
        return best


def _dist_seg(p, a, b) -> float:
    ab = b - a
    t = 0.0 if float(ab @ ab) < 1e-18 else max(0.0, min(1.0, float((p - a) @ ab) / float(ab @ ab)))
    return float(np.linalg.norm(p - (a + t * ab)))


def scene_camera(solids, box_vertices, box_edges, preferred: str = "") -> tuple[str, Camera, list[str]]:
    """ONE camera for the whole scene: the preset whose computed hidden edges match the source's dashed edges for EVERY
    polyhedron that declares them. None fits -> OBLIQUE_RIGHT + conflict list (never a silent hard-coded choice)."""
    polys = [s for s in solids if s.kind in ("cuboid", "polyhedron") and s.hidden_edges]
    order = ([preferred] if preferred in PRESETS else []) + [n for n in PRESETS if n != preferred]
    for name in order:
        cam = PRESETS[name]
        ok = True
        for s in polys:
            V3 = {k: np.asarray(v, float) for k, v in box_vertices(s).items()}
            edges = s.edges or (box_edges() if s.kind == "cuboid" else [])
            vis = edge_visibility(V3, edges, cam)
            hidden = {k for k, iv in vis.items() if all(st == "HIDDEN" for *_, st in iv)}
            if hidden != {frozenset(e) for e in s.hidden_edges}:
                ok = False
                break
        if ok:
            return name, cam, []
    return "OBLIQUE_RIGHT", PRESETS["OBLIQUE_RIGHT"], [s.id for s in polys]
