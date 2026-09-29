from __future__ import annotations

from ..geometry.incidence import point_order_holds


def check(spec, manifest: dict, check) -> None:
    geo = spec.mixed.geometry
    o = spec.observed
    g = manifest.get("geometry", {})
    if o.point_labels is not None:
        check(sorted(o.point_labels) == sorted(g.get("labels", [])), "תוויות הנקודות בשחזור שונות מהמקור.")
    if o.num_points is not None:
        check(len(g.get("points", [])) == o.num_points, f"במקור {o.num_points} נקודות, בשחזור {len(g.get('points', []))}.")
    for order in o.point_orders or []:
        check(point_order_holds(geo, order), f"סדר הנקודות {'-'.join(order)} לא נשמר.")
