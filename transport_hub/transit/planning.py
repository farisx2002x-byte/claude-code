"""تخطيط النقل العام: اقتراح محطات جديدة، اقتراح خط، وتقييم السيناريوهات (محطات مضافة/تغيير التردد)."""
import math

import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.siting import coverage as SC
from transport_hub.siting import mcda
from transport_hub.transit import coverage as COV


def suggest_stops(pop, existing_xy, cand, radius_m=400, k=10, poi=None, poi_weight=0.0, proj=None):
    """أفضل k محطة جديدة تعظم السكان المغطين الجدد (مع مكافأة اختيارية لقرب نقاط الجذب).
    radius_m مسافة مشي فعلية؛ نحولها لنصف قطر مستقيم بقسمة معامل التعرج."""
    r = radius_m / geo.DETOUR
    cxy = cand[["x", "y"]].to_numpy()
    bonus = None
    if poi is not None and len(poi) and poi_weight > 0:
        b = mcda.poi_within(cxy, poi, r)
        bonus = poi_weight * pop["pop"].sum() * 0.001 * (b / b.max()) if b.max() > 0 else None
    sel, (before, after) = SC.max_coverage(pop[["x", "y"]].to_numpy(), pop["pop"].to_numpy(float), cxy, r, k, existing_xy=existing_xy, bonus=bonus)
    if proj is not None and len(sel):
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
    return sel, (before, after)


def suggest_line(pop, existing_xy, hubs_xy, cand, n_stops=10, radius_m=400, headway_min=10, speed_kmh=20, dwell_s=30, layover=0.15, proj=None):
    """يقترح خطاً جديداً: n محطة تخدم أكبر سكان غير مخدومين، مرتبة كسلسلة تبدأ من أقرب محور تبديل.
    يرجع (جدول المحطات مرتبة، ملخص الخط)."""
    sel, (before, after) = suggest_stops(pop, existing_xy, cand, radius_m, n_stops, proj=proj)
    if sel.empty:
        return sel, {}
    pts = sel[["x", "y"]].to_numpy()
    if hubs_xy is not None and len(hubs_xy):
        d, hi = geo.nearest(pts, np.asarray(hubs_xy))
        start = int(np.argmin(d))
    else:
        start = int(np.argmax(pts[:, 0]))
    order, left = [start], set(range(len(pts))) - {start}
    while left:
        last = pts[order[-1]]
        nxt = min(left, key=lambda j: np.hypot(*(pts[j] - last)))
        order.append(nxt)
        left.remove(nxt)
    line = sel.iloc[order].reset_index(drop=True)
    line["order"] = np.arange(1, len(line) + 1)
    seg = np.hypot(np.diff(line["x"].values), np.diff(line["y"].values)) * geo.DETOUR
    length_km = seg.sum() / 1000
    run_min = length_km / speed_kmh * 60 + len(line) * dwell_s / 60
    cycle = run_min * 2 * (1 + layover)
    return line, dict(stops=len(line), length_km=round(length_km, 1), run_time_min=round(run_min, 1), headway_min=headway_min,
                      fleet=math.ceil(cycle / headway_min), pop_covered_new=int(line["gain"].sum()),
                      coverage_before=round(before, 1), coverage_after=round(after, 1))


def scenario_kpis(pop, stops, stop_route, add_stops=None, headway_factor=None, radii=(400, 800)):
    """مؤشرات الشبكة بعد تعديلات. stops: stop_id,x,y. stop_route: stop_id,route_id,headway_min.
    add_stops: قائمة dict(x,y,route_id,headway_min) محطات مضافة على خط. headway_factor: dict route_id→معامل ضرب التردد (0.5 = ضعف الخدمة)."""
    st, sr = stops[["stop_id", "x", "y"]].copy(), stop_route.copy()
    if headway_factor:
        sr["headway_min"] = sr["headway_min"] * sr["route_id"].map(headway_factor).fillna(1.0)
    if add_stops:
        new = pd.DataFrame(add_stops)
        new["stop_id"] = [f"NEW_{i}" for i in range(len(new))]
        st = pd.concat([st, new[["stop_id", "x", "y"]]], ignore_index=True)
        sr = pd.concat([sr, new[["stop_id", "route_id", "headway_min"]]], ignore_index=True)
    cov = COV.coverage(pop, st[["x", "y"]].to_numpy(), radii)
    cov = COV.accessibility_index(cov, st, sr)
    p = cov["pop"]
    out = {f"covered_{r}_pct": round(100 * p[cov[f"covered_{r}"]].sum() / p.sum(), 2) for r in radii}
    out["avg_access_index"] = round(float(np.average(cov["access_index"], weights=p)), 2)
    out["pop_no_service"] = int(p[cov["access_index"] == 0].sum())
    return out, cov
