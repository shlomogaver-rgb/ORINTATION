"""Deterministic 3D drawings: isometric cube structures and oblique solids with dimensions, vectors, points on edges."""
from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Ellipse, FancyArrowPatch
from matplotlib.patches import Polygon as MplPolygon

from ..render_base import INK, export, new_figure
from ..schemas import DiagramSpec
from ..text_utils import visual
from . import solids as S
from . import voxel as V
from .projection import iso, oblique

SHADE = {"top": "#e6e6e6", "left": "#bdbdbd", "front": "#8f8f8f"}


def render(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    sp = spec.spatial
    if sp.voxel is not None:
        return _render_voxel_bagrut(sp.voxel)
    return _render_solids(spec)


# Bagrut cube drawings: viewer at the FRONT-RIGHT, parallel projection measured on real questionnaires
# (front edge 32 deg below the horizontal, depth edge 32 deg above, cube height 0.945 x edge)
BAGRUT_THETA, BAGRUT_HEIGHT, BAGRUT_MARGIN = math.radians(32), 0.945, 0.42
BAGRUT_SHADE = {"top": "#ffffff", "front": "#b3b3b3", "right": "#8b8b8b", "plate": "#f2f2f2"}


def voxel_heights(v) -> np.ndarray:
    """heights[r][k]: r = 0 the FRONT row (facing the arrow), k = 0 the viewer's left. VoxelColumn: x = k, y = r."""
    nk, nr = (v.plate or [max((c.x for c in v.columns), default=0) + 1, max((c.y for c in v.columns), default=0) + 1])[:2]
    H = np.zeros((nr, nk), int)
    for c in v.columns:
        if 0 <= c.y < nr and 0 <= c.x < nk:
            H[c.y, c.x] = max(H[c.y, c.x], c.height)
    return H


def _render_voxel_bagrut(v) -> tuple[str, bytes, dict]:
    H = voxel_heights(v)
    nr, nk = H.shape
    u = np.array([math.cos(BAGRUT_THETA), -math.sin(BAGRUT_THETA)])        # matplotlib y points UP
    dv = np.array([math.cos(BAGRUT_THETA), math.sin(BAGRUT_THETA)])
    w = np.array([0.0, BAGRUT_HEIGHT])
    P = lambda k, r, z: k * u + r * dv + z * w  # noqa: E731
    fig, ax = new_figure(4.6, 4.2)
    ax.set_aspect("equal")
    ax.axis("off")
    m = BAGRUT_MARGIN
    plate = [P(-m, -m, 0), P(nk + m, -m, 0), P(nk + m, nr + m, 0), P(-m, nr + m, 0)]
    ax.add_patch(MplPolygon(plate, closed=True, facecolor=BAGRUT_SHADE["plate"], edgecolor=INK, lw=0.8, zorder=1))
    for i in range(nk + 1):                                                  # plate cell lines BELOW the cubes
        a, b = P(i, 0, 0), P(i, nr, 0)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#6b6b6b", lw=0.5, zorder=1.5)
    for j in range(nr + 1):
        a, b = P(0, j, 0), P(nk, j, 0)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#6b6b6b", lw=0.5, zorder=1.5)
    cubes = [(k, r, z) for r in range(nr) for k in range(nk) for z in range(int(H[r, k]))]
    cubes.sort(key=lambda t: (-t[0] + t[1] - t[2]), reverse=True)            # far (left, back, low) first
    for k, r, z in cubes:
        for name, q in (("front", ((k, r, z), (k + 1, r, z), (k + 1, r, z + 1), (k, r, z + 1))),
                        ("right", ((k + 1, r, z), (k + 1, r + 1, z), (k + 1, r + 1, z + 1), (k + 1, r, z + 1))),
                        ("top", ((k, r, z + 1), (k + 1, r, z + 1), (k + 1, r + 1, z + 1), (k, r + 1, z + 1)))):
            ax.add_patch(MplPolygon([P(*p) for p in q], closed=True, facecolor=BAGRUT_SHADE[name], edgecolor=INK, lw=0.9,
                                    joinstyle="round", zorder=2))
    a0, a1 = P(0.9, -1.55, 0), P(0.9, -0.75, 0)                              # the "view from the front" arrow
    ax.add_patch(FancyArrowPatch(a0, a1, arrowstyle="-|>", mutation_scale=14, color=INK, lw=1.4, zorder=3))
    ax.autoscale_view()
    if getattr(v, "title", ""):
        top = max(P(nk + m, nr + m, 0)[1], max((P(k + 1, r + 1, int(H[r, k]))[1] for r in range(nr) for k in range(nk)), default=0))
        cx = (P(-m, -m, 0)[0] + P(nk + m, nr + m, 0)[0]) / 2
        ax.text(cx, top + 0.55, visual(v.title), ha="center", va="bottom", fontsize=11, fontweight="bold", color=INK)
        ax.set_ylim(top=top + 1.3)
    vis = V.visibility(v)                                                    # same inventory the spatial comparator uses
    man = {"total_cubes": V.total(v), "visible_cubes": len(vis["visible"]), "hidden_tops": vis["hidden_tops"],
           "columns": sorted([c.x, c.y, c.height] for c in v.columns), "arrow": v.arrow is not None or True,
           "style": "bagrut", "grid": [nr, nk], "labels": [v.title] if getattr(v, "title", "") else []}
    svg, png = export(fig)
    return svg, png, man


def _render_voxel(v) -> tuple[str, bytes, dict]:
    fig, ax = new_figure(4.8, 4.4)
    ax.set_aspect("equal")
    ax.axis("off")
    if v.plate:
        nx, ny = v.plate
        plate = [iso(-0.3, -0.3, 0), iso(nx + 0.3, -0.3, 0), iso(nx + 0.3, ny + 0.3, 0), iso(-0.3, ny + 0.3, 0)]
        ax.add_patch(MplPolygon(plate, closed=True, facecolor="#9e9e9e", edgecolor=INK, lw=0.8))
    from .camera import Camera
    from .voxel_scene import VoxelGrid
    iso_cam = Camera(mode="ORTHOGRAPHIC", position=(-10.0, -10.0, 10.0))   # the viewer of the isometric drawing
    for c in VoxelGrid.from_spec(v).depth_order(iso_cam):                  # generic camera-depth painter order
        for name, poly in V._faces(*c):
            ax.add_patch(MplPolygon(poly, closed=True, facecolor=SHADE[name], edgecolor=INK, lw=0.8))
    if v.arrow:
        x, y, dx, dy = v.arrow
        ax.add_patch(FancyArrowPatch(iso(x, y, 0), iso(x + dx, y + dy, 0), arrowstyle="-|>", mutation_scale=16, color=INK, lw=2))
    ax.autoscale_view()
    vis = V.visibility(v)
    man = {"total_cubes": V.total(v), "visible_cubes": len(vis["visible"]), "hidden_tops": vis["hidden_tops"],
           "columns": sorted([c.x, c.y, c.height] for c in v.columns), "arrow": v.arrow is not None}
    svg, png = export(fig)
    return svg, png, man


_PROJ = lambda p: np.array(oblique(*p))  # noqa: E731   replaced per scene by the scene camera (render lock held)


def _render_solids(spec: DiagramSpec) -> tuple[str, bytes, dict]:
    sp = spec.spatial
    fig, ax = new_figure(5.2, 5.0)
    ax.set_aspect("equal")
    ax.axis("off")
    man: dict = {"solids": [], "vertices": [], "edges": 0, "hidden_edges": 0, "dimensions": [], "vectors": [],
                 "points_on_edges": [], "relations": [[r.type, r.a, r.b] for r in sp.relations]}
    all_pts: dict[str, np.ndarray] = {}
    from .camera import edge_visibility, scene_camera
    cam_name, cam, conflict = scene_camera(sp.solids, S.box_vertices, S.box_edges, sp.camera)      # ONE camera for the scene
    if conflict:
        man["hidden_edge_conflict"] = conflict
    proj = lambda p: np.array(cam.project(p)[:2])  # noqa: E731   the single projection used for EVERYTHING drawn
    man["projection_source"] = man["visibility_camera"] = cam_name
    man["screen"] = {}
    global _PROJ
    _PROJ = proj
    for s in sp.solids:
        man["solids"].append([s.id, s.kind])
        if s.kind in ("cuboid", "polyhedron"):
            verts = S.box_vertices(s)
            P = {k: proj(v) for k, v in verts.items()}
            all_pts.update(P)
            man["screen"].update({k: [round(float(v[0]), 6), round(float(v[1]), 6)] for k, v in P.items()})
            edges = s.edges or (S.box_edges() if s.kind == "cuboid" else [])
            V3 = {k: np.asarray(v, float) for k, v in verts.items()}
            man.setdefault("camera", {})[s.id] = cam_name
            occluders = []
            from .camera import hull_faces
            for other in sp.solids:
                if other.id != s.id and other.kind in ("cuboid", "polyhedron"):
                    ov = {k: np.asarray(v, float) for k, v in S.box_vertices(other).items()}
                    occluders.append([(ids, n, ov) for ids, n in hull_faces(ov)])
            vis = edge_visibility(V3, edges, cam, occluders)
            for e in edges:
                a3, b3 = V3[e[0]], V3[e[1]]
                ivs = vis[frozenset(e)]
                for t0, t1, state in ivs:            # partial occlusion: visible / hidden intervals
                    pa, pb = proj(a3 + t0 * (b3 - a3)), proj(a3 + t1 * (b3 - a3))
                    ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=INK, lw=1.1, linestyle=(0, (4, 3)) if state == "HIDDEN" else "-")
                man["edges"] += 1
                man["hidden_edges"] += int(all(st_ == "HIDDEN" for *_, st_ in ivs))
                man["partially_hidden_edges"] = man.get("partially_hidden_edges", 0) + int(len({st_ for *_, st_ in ivs}) > 1)
            if s.vertices:
                from .camera import LabelPlacer
                cen = np.mean(list(P.values()), axis=0)
                span = max(np.ptp([p[0] for p in P.values()]), np.ptp([p[1] for p in P.values()]), 1e-6)
                placer = LabelPlacer(size=span, segments=[(P[e[0]], P[e[1]]) for e in edges])
                for k, p in P.items():
                    ax.plot([p[0]], [p[1]], "o", color=INK, markersize=2.5)
                    ax.text(*placer.place(p, p - cen), k, ha="center", va="center", fontsize=11)   # normalized, collision-aware
                    man["vertices"].append(k)
            if s.face_text:
                front = [P[k] for k in ("D", "C", "C'", "D'") if k in P]
                if len(front) == 4:
                    c = np.mean(front, axis=0)
                    ax.text(c[0], c[1] + 0.15 * (front[2][1] - front[1][1]), visual(s.face_text), ha="center", fontsize=10,
                            bbox=dict(boxstyle="square,pad=0.2", fc="white", ec=INK, lw=0.7))
        elif s.kind == "cylinder":
            r, h = s.dims.get("radius", 1.0), s.dims.get("height", 2.0)
            ox, oy, oz = s.origin
            if cam.mode != "OBLIQUE":             # the base-ellipse drawing is only valid for the oblique projection
                man.setdefault("unsupported", []).append(f"CYLINDER_GENERIC_CAMERA_UNSUPPORTED:{s.id}")
            cx, cy = proj((ox, oy, oz))
            ry = r * 0.35
            ax.add_patch(Ellipse((cx, cy + h), 2 * r, 2 * ry, fill=False, edgecolor=INK, lw=1.1))
            t = np.linspace(np.pi, 2 * np.pi, 80)
            ax.plot(cx + r * np.cos(t), cy + ry * np.sin(t), color=INK, lw=1.1)
            t2 = np.linspace(0, np.pi, 80)
            ax.plot(cx + r * np.cos(t2), cy + ry * np.sin(t2), color=INK, lw=0.9, linestyle=(0, (4, 3)))
            ax.plot([cx - r, cx - r], [cy, cy + h], color=INK, lw=1.1)
            ax.plot([cx + r, cx + r], [cy, cy + h], color=INK, lw=1.1)
            all_pts[s.id + ".center"] = np.array([cx, cy])
            all_pts[s.id + ".rim"] = np.array([cx + r, cy])
            all_pts[s.id + ".top"] = np.array([cx, cy + h])
            all_pts[s.id + ".left"] = np.array([cx - r, cy])
    for d in sp.dimensions:
        sol = next((s for s in sp.solids if s.id == d.solid), None)
        if sol is None:
            continue
        a, b = _dimension_endpoints(sol, d)
        if a is None:
            continue
        if d.measure == "radius":
            ax.plot(*zip(a, b), color=INK, lw=0.9)
            ax.plot([a[0]], [a[1]], "o", color=INK, markersize=2.5)
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 0.08 * max(1.0, sol.dims.get("radius", 1)), visual(d.text), ha="center", va="top", fontsize=10)
        else:
            ax.add_patch(FancyArrowPatch(tuple(a), tuple(b), arrowstyle="<|-|>", mutation_scale=10, color=INK, lw=0.9))
            v = b - a
            n = np.array([v[1], -v[0]]) / max(1e-9, np.hypot(*v))
            ax.text(*((a + b) / 2 + n * 0.08 * max(np.hypot(*v), 1)), visual(d.text), ha="center", va="center", fontsize=10,
                    rotation=math.degrees(math.atan2(v[1], v[0])) if abs(v[0]) > 1e-9 and abs(v[1]) > 1e-9 else (90 if abs(v[0]) < 1e-9 else 0))
        man["dimensions"].append([d.solid, d.measure, d.text])
    man["construction"] = []
    pending = list(sp.points_on_edges)
    for _ in range(3):                                    # points may sit on segments between other points (resolved in passes)
        for pe in list(pending):
            if pe.a in all_pts and pe.b in all_pts:
                all_pts[pe.id] = all_pts[pe.a] + pe.ratio * (all_pts[pe.b] - all_pts[pe.a])
                pending.remove(pe)
    for kind, items in (("segment", sp.construction_segments), ("line", sp.construction_lines), ("ray", sp.construction_rays)):
        for cs in items:
            if cs.a not in all_pts or cs.b not in all_pts:
                continue
            a, b = all_pts[cs.a], all_pts[cs.b]
            if kind == "line":
                a, b = a - 3 * (b - a), b + 3 * (b - a)
            elif kind == "ray":
                b = a + 4 * (b - a)
            ax.plot(*zip(a, b), color=INK, lw=1.0, linestyle=(0, (4, 3)) if cs.style == "dashed" else "-")
            man["construction"].append([kind, cs.a, cs.b])
    for an in sp.annotations:
        if an.at in all_pts:
            p = all_pts[an.at]
            ax.text(p[0] + 0.2, p[1] - 0.3, visual(an.text), fontsize=10)
    for pe in sp.points_on_edges:
        if pe.id in all_pts:
            p = all_pts[pe.id]
            ax.plot([p[0]], [p[1]], "o", color=INK, markersize=3)
            ax.text(p[0] - 0.25, p[1] + 0.15, pe.label if pe.label is not None else pe.id, fontsize=11)
            man["points_on_edges"].append([pe.id, pe.a, pe.b, round(pe.ratio, 9)])
    for vec in sp.vectors:
        if vec.a in all_pts and vec.b in all_pts:
            a, b = all_pts[vec.a], all_pts[vec.b]
            ax.add_patch(FancyArrowPatch(tuple(a), tuple(a + 0.55 * (b - a)), arrowstyle="-|>", mutation_scale=11, color=INK, lw=1.0))
            m = a + 0.55 * (b - a)
            ax.text(m[0] + 0.1, m[1] + 0.12, vec.label, fontsize=11, fontweight="bold")
            man["vectors"].append([vec.a, vec.b, vec.label])
    ax.autoscale_view()
    man["vertices"].sort()
    svg, png = export(fig)
    return svg, png, man


def _dimension_endpoints(sol, d):
    if sol.kind == "cylinder":
        r, h = sol.dims.get("radius", 1.0), sol.dims.get("height", 2.0)
        cx, cy = _PROJ(sol.origin)
        if d.measure == "radius":
            return np.array([cx, cy]), np.array([cx + r, cy])
        if d.measure == "diameter":
            return np.array([cx - r, cy - 0.5 * r]), np.array([cx + r, cy - 0.5 * r])
        if d.measure == "height":
            return np.array([cx + r * 1.3, cy]), np.array([cx + r * 1.3, cy + h])
        return None, None
    verts = S.box_vertices(sol)
    P = {k: _PROJ(v) for k, v in verts.items()}
    if d.edge and all(k in P for k in d.edge):
        a, b = P[d.edge[0]], P[d.edge[1]]
    elif d.measure == "height":
        a, b = P["B"], P["B'"]
        a, b = a + np.array([0.12 * sol.dims.get("width", 1), 0]), b + np.array([0.12 * sol.dims.get("width", 1), 0])
    elif d.measure == "width":
        a, b = P["D"] - np.array([0, 0.1 * sol.dims.get("height", 1) * 0.1]), P["C"] - np.array([0, 0.1 * sol.dims.get("height", 1) * 0.1])
    elif d.measure == "depth":
        shift = np.array([0.1 * sol.dims.get("width", 1), -0.1 * sol.dims.get("width", 1)])
        a, b = P["C"] + shift, P["B"] + shift
    else:
        return None, None
    return a, b
