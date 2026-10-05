"""تخطيط النقل العام: اقتراح محطات جديدة، اقتراح خط، وتقييم السيناريوهات (محطات مضافة/تغيير التردد)."""

import math

import numpy as np
import pandas as pd

from transport_hub.core import geo
from transport_hub.core.access import Access
from transport_hub.siting import coverage as SC
from transport_hub.siting import mcda
from transport_hub.transit import coverage as COV


def suggest_stops(pop, existing_xy, cand, radius_m=400, k=10, poi=None, poi_weight=0.0, proj=None, access=None):
    """أفضل k محطة جديدة تعظم السكان المغطين الجدد (مع مكافأة اختيارية لقرب نقاط الجذب).
    radius_m مسافة مشي فعلية: على شبكة الشوارع إن توفرت (access)، وإلا مستقيم ÷ معامل التعرج."""
    access = access or Access()
    r = radius_m / geo.DETOUR
    cxy = cand[["x", "y"]].to_numpy()
    dxy = pop[["x", "y"]].to_numpy()
    bonus = None
    if poi is not None and len(poi) and poi_weight > 0:
        b = mcda.poi_within(cxy, poi, r)
        bonus = poi_weight * pop["pop"].sum() * 0.001 * (b / b.max()) if b.max() > 0 else None
    covered = None
    if existing_xy is not None and len(existing_xy):
        d0, _ = access.walk_nearest(dxy, np.asarray(existing_xy, float), limit=radius_m * 2)
        covered = d0 <= radius_m
    lists = access.cover_lists(cxy, dxy, radius_m)
    sel, (before, after) = SC.max_coverage(dxy, pop["pop"].to_numpy(float), cxy, r, k, bonus=bonus, lists=lists, covered=covered)
    if proj is not None and len(sel):
        sel["lon"], sel["lat"] = proj.lonlat(sel["x"], sel["y"])
    return sel, (before, after)


def suggest_line(
    pop, existing_xy, hubs_xy, cand, n_stops=10, radius_m=400, headway_min=10, speed_kmh=20, dwell_s=30, layover=0.15, proj=None, access=None
):
    """يقترح خطاً جديداً: n محطة تخدم أكبر سكان غير مخدومين، مرتبة كسلسلة تبدأ من أقرب محور تبديل.
    يرجع (جدول المحطات مرتبة، ملخص الخط)."""
    access = access or Access()
    sel, (before, after) = suggest_stops(pop, existing_xy, cand, radius_m, n_stops, proj=proj, access=access)
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
    xy = line[["x", "y"]].to_numpy()
    seg = access.drive_pairs(xy[:-1], xy[1:], "length")  # الحافلة تتبع الشوارع (واتجاهها الواحد)
    length_km = seg.sum() / 1000
    run_min = length_km / speed_kmh * 60 + len(line) * dwell_s / 60
    cycle = run_min * 2 * (1 + layover)
    # زمن الرحلة الواقعي لكل فترة يوم من الشبكة وازدحامها (أو التقدير): الأسطول الفعلي = الأكبر عبر الفترات
    from transport_hub.core.congestion import PERIOD_KEYS

    dwell_min = len(line) * dwell_s / 60
    by_period = {p: round(float(access.with_period(p).drive_pairs(xy[:-1], xy[1:], "time").sum() / 60 + dwell_min), 1) for p in PERIOD_KEYS}
    fleet_p = {p: math.ceil(t * 2 * (1 + layover) / headway_min) for p, t in by_period.items()}
    return line, dict(
        run_time_by_period=by_period,
        fleet_by_period=fleet_p,
        fleet_realistic=max(fleet_p.values()),
        stops=len(line),
        length_km=round(length_km, 1),
        run_time_min=round(run_min, 1),
        headway_min=headway_min,
        fleet=math.ceil(cycle / headway_min),
        pop_covered_new=int(line["gain"].sum()),
        coverage_before=round(before, 1),
        coverage_after=round(after, 1),
    )


def scenario_kpis(pop, stops, stop_route, add_stops=None, headway_factor=None, radii=(400, 800), access=None):
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
    cov = COV.coverage(pop, st[["x", "y"]].to_numpy(), radii, access)
    cov = COV.accessibility_index(cov, st, sr, access=access)
    p = cov["pop"]
    out = {f"covered_{r}_pct": round(100 * p[cov[f"covered_{r}"]].sum() / p.sum(), 2) for r in radii}
    out["avg_access_index"] = round(float(np.average(cov["access_index"], weights=p)), 2)
    out["pop_no_service"] = int(p[cov["access_index"] == 0].sum())
    return out, cov
